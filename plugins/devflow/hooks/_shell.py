"""Shell-aware command splitting for the devflow guardrail hooks.

Python 3.11, standard library only. Words are split by `shlex` (POSIX rules); this module adds what
shlex does not know: the operators `&&`, `||`, `;`, `|`, `&`, newlines, subshell parentheses,
heredoc bodies, comments, `$(...)`, backticks and `<(...)`, and redirections.

    split_commands("git add . && (cd x; git push -f) # note")  ->  [Command(...), ...]
    candidates(words)  ->  the word lists that may really be executed (wrappers stripped,
                           `bash -c '...'` and `eval` unpacked)

Anything that cannot be tokenised raises ParseError; the destructive hooks treat that as a deny.
Expansions are never evaluated: a substitution becomes the placeholder DYN inside its word.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field

from _ansi import ansi_c_decode
from _wrappers import (ASSIGN, WRAPPER_POSITIONALS, WRAPPER_VALUE_OPTS, WRAPPERS, ParseError,  # noqa: F401
                       script_command, strip_wrapper as _strip_wrapper)

DYN = ""    # a substitution or expansion this module does not evaluate
REDIR = ""  # marks a redirection operator in the intermediate text
MAX_DEPTH = 8


@dataclass
class Command:
    words: list[str]
    redirects: list[tuple[str, str]] = field(default_factory=list)  # (operator, target)


def is_dynamic(word: str) -> bool:
    return DYN in word or "$" in word


# --------------------------------------------------------------------------- scanning

_REDIR_OP = re.compile(r"<<<|<<-|<<|<>|<&|<|>>|>&|>\||>")
_FD_TAIL = re.compile(r"(?<![^\s])\d+$")


def split_commands(text: str, depth: int = 0) -> list[Command]:
    """All simple commands in `text`, including those nested in substitutions, in textual order."""
    if depth > MAX_DEPTH:
        raise ParseError("command nesting is too deep")
    segments: list[str] = []
    _scan(text, 0, segments, depth, inner=False)
    commands = [_to_command(s) for s in segments]
    return [c for c in commands if c.words or c.redirects]


def _to_command(segment: str) -> Command:
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError as exc:
        raise ParseError(str(exc)) from None
    words: list[str] = []
    redirects: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith(REDIR):
            target = ""
            if i + 1 < len(tokens) and not tokens[i + 1].startswith(REDIR):
                target = tokens[i + 1]
                i += 1
            redirects.append((tok[1:], target))
        else:
            words.append(tok)
        i += 1
    return Command(words, redirects)


def _scan(text: str, i: int, out: list[str], depth: int, inner: bool) -> int:
    """Split `text` from `i` into raw segments appended to `out`. In `inner` mode stop after the
    `)` that closes a `$(`; return the index after what was consumed."""
    if depth > MAX_DEPTH:
        raise ParseError("command nesting is too deep")
    n = len(text)
    buf: list[str] = []
    paren = 0
    heredocs: list[tuple[str, bool, bool]] = []  # (delimiter, strip tabs, quoted)

    def flush() -> None:
        s = "".join(buf).strip()
        buf.clear()
        if s:
            out.append(s)

    def prev() -> str:
        return buf[-1][-1:] if buf else ""

    while i < n:
        c = text[i]
        if c == "\\":
            if text[i + 1:i + 2] == "\n":
                i += 2
                continue
            buf.append(text[i:i + 2])
            i += 2
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated single quote")
            buf.append(text[i:j + 1])
            i = j + 1
        elif c == '"':
            body, j = _expand_text(text, i + 1, '"', out, depth)
            if j >= n:
                raise ParseError("unterminated double quote")
            buf.append('"' + body + '"')
            i = j + 1
        elif c == "$":
            nxt = text[i + 1:i + 2]
            if nxt == "(":
                i = _scan(text, i + 2, out, depth + 1, True)
                buf.append(DYN)
            elif nxt == "'":  # ANSI-C quoting: decoded to its literal value
                j = i + 2
                while j < n and text[j] != "'":
                    j += 2 if text[j] == "\\" else 1
                if j >= n:
                    raise ParseError("unterminated $'...' quote")
                buf.append(shlex.quote(ansi_c_decode(text[i + 2:j])))
                i = j + 1
            else:
                buf.append("$")
                i += 1
        elif c == "`":
            j = _backtick_end(text, i)
            _scan(text[i + 1:j].replace("\\`", "`"), 0, out, depth + 1, False)
            buf.append(DYN)
            i = j + 1
        elif c in "<>" or (c == "&" and text[i + 1:i + 2] == ">"):
            if c in "<>" and text[i + 1:i + 2] == "(":  # process substitution
                i = _scan(text, i + 2, out, depth + 1, True)
                buf.append(DYN)
                continue
            if c == "&":
                op = "&>>" if text.startswith("&>>", i) else "&>"
            else:
                op = _REDIR_OP.match(text, i).group(0)
            m = _FD_TAIL.search("".join(buf))  # `2>file`: the 2 is a descriptor, not a word
            if m:
                rest = "".join(buf)[:m.start()]
                buf.clear()
                buf.append(rest)
            buf.append(f" {REDIR}{op} ")
            i += len(op)
            if op in ("<<", "<<-"):
                i = _heredoc_delimiter(text, i, op == "<<-", buf, heredocs)
        elif c == "&":
            flush()
            i += 2 if text.startswith("&&", i) else 1
        elif c in ";|":
            flush()
            i += 2 if text[i:i + 2] in ("||", ";;", "|&", ";&") else 1
        elif c == "\n":
            flush()
            i += 1
            for delim, strip, quoted in heredocs:
                i = _skip_heredoc(text, i, delim, strip, quoted, out, depth)
            heredocs.clear()
        elif c == "(":
            flush()
            paren += 1
            i += 1
        elif c == ")":
            flush()
            i += 1
            if paren > 0:
                paren -= 1
            elif inner:
                return i
        elif c == "#" and prev() in ("", " ", "\t", "\n"):
            while i < n and text[i] != "\n":
                i += 1
        else:
            buf.append(c)
            i += 1
    if inner:
        raise ParseError("unterminated $(")
    flush()
    return i


def _backtick_end(text: str, i: int) -> int:
    j = i + 1
    while j < len(text) and text[j] != "`":
        j += 2 if text[j] == "\\" else 1
    if j >= len(text):
        raise ParseError("unterminated backtick")
    return j


def _expand_text(text: str, i: int, stop: str | None, out: list[str], depth: int) -> tuple[str, int]:
    """Copy text from `i` until the unescaped `stop` character (or the end), replacing command
    substitutions by DYN and scanning them. Returns (copied text, index of the stop character)."""
    n = len(text)
    res: list[str] = []
    while i < n and text[i] != stop:
        c = text[i]
        if c == "\\":
            res.append(text[i:i + 2])
            i += 2
        elif c == "$" and text[i + 1:i + 2] == "(":
            i = _scan(text, i + 2, out, depth + 1, True)
            res.append(DYN)
        elif c == "`":
            j = _backtick_end(text, i)
            _scan(text[i + 1:j].replace("\\`", "`"), 0, out, depth + 1, False)
            res.append(DYN)
            i = j + 1
        else:
            res.append(c)
            i += 1
    return "".join(res), i


def _heredoc_delimiter(text: str, i: int, strip: bool, buf: list[str], heredocs: list) -> int:
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    start = i
    quoted = False
    delim: list[str] = []
    while i < n and text[i] not in " \t\n;|&()<>":
        c = text[i]
        if c in "'\"":
            j = text.find(c, i + 1)
            if j < 0:
                raise ParseError("unterminated heredoc delimiter")
            delim.append(text[i + 1:j])
            quoted = True
            i = j + 1
        elif c == "\\":
            delim.append(text[i + 1:i + 2])
            quoted = True
            i += 2
        else:
            delim.append(c)
            i += 1
    if i == start:
        raise ParseError("heredoc without a delimiter")
    buf.append(" " + shlex.quote("".join(delim)) + " ")
    heredocs.append(("".join(delim), strip, quoted))
    return i


def _skip_heredoc(text: str, i: int, delim: str, strip: bool, quoted: bool, out: list[str], depth: int) -> int:
    n = len(text)
    body: list[str] = []
    while i < n:
        j = text.find("\n", i)
        end = n if j < 0 else j
        line = text[i:end]
        i = end + 1 if j >= 0 else n
        if (line.lstrip("\t") if strip else line) == delim:
            break
        body.append(line)
    if not quoted:  # an unquoted heredoc body still runs $(...) and backticks
        _expand_text("\n".join(body), 0, None, out, depth)
    return min(i, n)


# --------------------------------------------------------------------------- command words

RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "case", "esac",
            "in", "!", "{", "}", "time", "select", "function", "coproc"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash"}
SCANNING = {"xargs", "find", "parallel", "watch", "ssh"}  # run other commands whose words follow


def base(word: str) -> str:
    return os.path.basename(word)


def candidates(words: list[str], redirects: list[tuple[str, str]] | None = None, depth: int = 0) -> list[Command]:
    """Commands that may be executed because of `words`: the command itself without prefixes and
    wrappers, plus whatever a shell `-c` string, `eval`, `xargs`, `find -exec` ... would run."""
    if depth > MAX_DEPTH:
        raise ParseError("command nesting is too deep")
    w = list(words)
    out: list[Command] = []
    while w:
        head = w[0]
        if head in RESERVED or ASSIGN.match(head):
            w = w[1:]
            if head == "time":  # `time -p` / `time --`: the flag is not the command
                while w and w[0] in ("-p", "--"):
                    w = w[1:]
        elif base(head) in WRAPPERS:
            if base(head) == "script":  # `script -c CMD FILE` runs CMD
                cmd_text = script_command(w[1:])
                if cmd_text is not None:
                    for cmd in split_commands(cmd_text, depth + 1):
                        out += candidates(cmd.words, cmd.redirects, depth + 1)
            w = _strip_wrapper(base(head), w[1:])
        else:
            break
    if not w:
        return out + ([Command([], list(redirects or []))] if redirects else [])
    name = base(w[0])
    if name in SHELLS:
        for k, tok in enumerate(w[1:], 1):
            if tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:] and k + 1 < len(w):
                for cmd in split_commands(w[k + 1], depth + 1):
                    out += candidates(cmd.words, cmd.redirects, depth + 1)
                break
    elif name == "eval":
        for cmd in split_commands(" ".join(w[1:]), depth + 1):
            out += candidates(cmd.words, cmd.redirects, depth + 1)
    elif name in SCANNING:
        for k, tok in enumerate(w[1:], 1):
            if base(tok) in ("git", "gh"):
                out += candidates(w[k:], None, depth + 1)
    out.append(Command(w, list(redirects or [])))
    return out


def walk(command: str):
    """Yield (cwd_hint, words, redirects) for every command `command` may run; cwd_hint is the
    directory the last `cd` / `pushd` in front of it named (or None)."""
    cwd: str | None = None
    for cmd in split_commands(command):
        for c in candidates(cmd.words, cmd.redirects):
            if c.words and base(c.words[0]) in ("cd", "pushd") and len(c.words) > 1 and not is_dynamic(c.words[1]):
                cwd = c.words[1] if os.path.isabs(c.words[1]) or cwd is None else os.path.join(cwd, c.words[1])
            yield cwd, c.words, c.redirects
