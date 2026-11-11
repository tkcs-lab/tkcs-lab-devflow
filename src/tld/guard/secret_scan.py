#!/usr/bin/env python3
"""PreToolUse hook `secret-scan`: deny Write / Edit / MultiEdit content that looks like a credential.

The message names the pattern and the line, never the secret. A line that ends in
`secret-scan:allow` is skipped (test fixtures, documented examples).
"""
from __future__ import annotations

import math
import re

from tld.guard._common import Ctx
from tld.guard._shell import ParseError, base, walk_commands

NAME = "secret-scan"
ALLOW_MARK = "secret-scan:allow"
WRITE_REDIRS = (">", ">>", ">|", "&>", "&>>", ">&")

# (name, description, regex). No literal secret is stored here; the BEGIN pattern is written so that
# its own source text does not match it.
SPECIFIC = [
    ("private-key", "a private key block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws-access-key-id", "an AWS access key id",
     re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[0-9A-Z]{16}\b")),
    ("aws-secret-key", "an AWS secret access key",
     re.compile(r"(?i)aws.{0,20}secret.{0,20}[:=]\s*[\"']?[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])")),
    ("github-token", "a GitHub token",
     re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b")),
    ("gcp-api-key", "a Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("gcp-oauth-token", "a Google OAuth access token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("slack-token", "a Slack token", re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}")),
    ("gitlab-token", "a GitLab personal access token", re.compile(r"\bglpat-[0-9A-Za-z_\-]{20,}")),
    ("stripe-key", "a Stripe live or restricted key", re.compile(r"\b(?:sk|rk)_live_[0-9a-zA-Z]{20,}")),
    ("anthropic-key", "an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", "an OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("npm-token", "an npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi-token", "a PyPI token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}")),
    ("sendgrid-key", "a SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b")),
    ("azure-storage-key", "an Azure storage account key", re.compile(r"AccountKey=[A-Za-z0-9+/]{60,}={0,2}")),
    ("url-credentials", "credentials in a URL",
     re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s/:@$<>{}%]+:[^\s/@$<>{}%]{3,}@[^\s/]+")),
    ("bearer-token", "a bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}")),
    ("jwt", "a JSON web token", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
]
ASSIGNMENT = re.compile(
    r"""(?<![A-Za-z0-9_.\-])([A-Za-z_][A-Za-z0-9_.\-]{0,63})["']?\s*(?::=|[:=])\s*"""
    r"""(?:(["'])([^"'\s]{12,})\2|([A-Za-z0-9+/=_\-.~]{12,}))""")
PLACEHOLDERS = ("example", "placeholder", "changeme", "change_me", "your", "xxxx", "dummy", "sample",
                "redacted", "replace", "insert", "todo", "fake", "notasecret")
SUFFIXES = ("key", "token", "secret", "password", "passwd", "pwd", "credential", "credentials", "auth")
PASSWORD_SUFFIXES = ("password", "passwd", "pwd")
MAX_LINE_FOR_ASSIGNMENT = 1_000_000
MIN_ENTROPY = 3.5


def entropy(value: str) -> float:
    counts = {c: value.count(c) for c in set(value)}
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def name_tokens(name: str) -> list[str]:
    """The name split on separators and camelCase boundaries, lower-cased: `API_KEY_1` -> [api, key, 1]."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced) if t]


def _suffix_token_hit(name: str, suffixes: tuple[str, ...]) -> bool:
    """A whole token equals a secret word, and it is the last token, or every token after it is a
    number, or the name is an upper-case constant. So `API_KEY_1`, `SECRET_KEY_BASE` and `client_secret`
    match, but `secret_name` (a label) does not, and `monkey` has no such token at all."""
    tokens = name_tokens(name)
    upper = name.upper() == name  # UPPER_SNAKE env-var style (no lower-case letters)
    for i, tok in enumerate(tokens):
        if tok.lower() in suffixes:
            rest = tokens[i + 1:]
            if not rest or all(t.isdigit() for t in rest) or upper:
                return True
    return False


def secret_like_name(name: str) -> bool:
    lower = name.lower()
    if "public" in lower or "pubkey" in lower:
        return False
    if _suffix_token_hit(name, SUFFIXES):
        return True
    for suffix in SUFFIXES:  # a run-on name such as `apikey` or `deploytoken` with no separator
        if lower.endswith(suffix):
            head = name[:-len(suffix)]
            tail = name[-len(suffix):]
            if not head or head[-1] in "_.-" or (tail[0].isupper() and not head[-1].isupper()):
                return True
    return False


def is_password_name(name: str) -> bool:
    return _suffix_token_hit(name, PASSWORD_SUFFIXES) or name.lower().endswith(PASSWORD_SUFFIXES)


def password_literal(value: str) -> bool:
    low = value.lower()
    return (len(value) >= 12 and any(c.isdigit() for c in value) and any(c.isalpha() for c in value)
            and not any(p in low for p in PLACEHOLDERS) and entropy(value) >= 3.0)


def high_entropy_literal(value: str) -> bool:
    low = value.lower()
    return (len(value) >= 20 and any(c.isdigit() for c in value) and any(c.isalpha() for c in value)
            and not any(p in low for p in PLACEHOLDERS) and entropy(value) >= MIN_ENTROPY)


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """(line number, pattern name, description) for every credential-looking line."""
    hits: list[tuple[int, str, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.rstrip().endswith(ALLOW_MARK):
            continue
        for name, desc, rx in SPECIFIC:
            m = rx.search(line)
            if m and not (name == "bearer-token" and any(p in m.group(0).lower() for p in PLACEHOLDERS)):
                hits.append((n, name, desc))
                break
        else:
            if len(line) > MAX_LINE_FOR_ASSIGNMENT:
                continue
            for m in ASSIGNMENT.finditer(line):
                value = m.group(3) or m.group(4)
                is_password = is_password_name(m.group(1))
                if secret_like_name(m.group(1)) and (password_literal(value) if is_password
                                                     else high_entropy_literal(value)):
                    hits.append((n, "high-entropy-assignment",
                                 f"a high-entropy value assigned to `{m.group(1)}`"))
                    break
    return hits


def shell_texts(command: str) -> list[tuple[str, str]]:
    """(where, text) for content a Bash command writes to a file: a heredoc / herestring body, and the
    words of a command that redirects to a file or pipes to tee (`echo ghp_... > f`, `cat <<EOF > .env`)."""
    out: list[tuple[str, str]] = []
    try:
        for _, cmd in walk_commands(command):
            name = base(cmd.words[0]) if cmd.words else ""
            writes = any(op in WRITE_REDIRS for op, _ in cmd.redirects) or name == "tee"
            if cmd.stdin_text and writes:
                out.append(("a heredoc written to a file", cmd.stdin_text))
            if writes and name in ("echo", "printf", "tee", "cat", "head", "sed", "awk") or (writes and cmd.words):
                out.append(("a value written to a file", " ".join(cmd.words)))
    except ParseError:
        return []
    return out


def texts_of(ctx: Ctx) -> list[tuple[str, str]]:
    """(where, text) for the content the action would write."""
    if ctx.action.kind == "write":
        return [(where, text) for where, text in ctx.action.content]
    if ctx.action.kind == "shell" and isinstance(ctx.action.command, str):
        return shell_texts(ctx.action.command)
    return []


def evaluate(ctx: Ctx) -> str | None:
    path = ctx.action.path or "the file"
    if ctx.action.kind == "shell":
        path = "a file"
    for where, text in texts_of(ctx):
        if not isinstance(text, str):
            continue
        hits = scan_text(text)
        if hits:
            n, name, desc = hits[0]
            more = f" ({len(hits)} lines in all)" if len(hits) > 1 else ""
            where_line = f"{where}" if ctx.action.kind == "shell" else f"line {n} of {where} for {path}"
            return (f"blocked: {where_line} looks like {desc} (pattern: {name}){more}. "
                    "The value is not shown. Do not write a credential into a file: read it from the "
                    "environment or a secret store and write only the variable's name. If this is a test "
                    "fixture or a documented example, build the value at runtime, or end the line with "
                    f"`{ALLOW_MARK}`.")
    return None

