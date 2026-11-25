#!/usr/bin/env python3
"""Download, check and unpack the pinned Reflektor release for the `reflektor` role.

    tld roles reflektor-prepare --dest DIR --repo CLONE --base BASE
    tld roles reflektor-check --report FILE --root CLONE
    tld roles reflektor-html (--file FILE | --send --answer FILE --dest DIR)

`prepare` refuses a clone whose `.reflektor.json` is not plain (only the keys `base`, `targets` and `generated`,
checked values, no hooks), a branch that changed that file, a missing or old Node and a PATH with an empty or
relative entry. It then downloads `PIN["url"]` (only `https://github.com/`), checks its size and sha256 against
the pin, validates every archive member before writing any, writes the files itself under `DIR/reflektor`
and writes `report-guide.md` (the report rules of SKILL.md). It prints the absolute path of `DIR/reflektor`, then the
absolute path of `node`.

The PATH check comes first, so no program is looked up in the working directory; git is resolved once.
Exit 0 on success; exit 3 when the repository, the branch, Node or the network is not fit (the role then ends `n/a`);
exit 1 when the download or the archive is not the pinned release. A message is `tld roles: reflektor: <reason>`
on stderr. The pin proves the bytes, not the intent of the release. Python 3.11+, standard library.

`reflektor-check` refuses a report whose `path` values leave the clone. `reflektor-html --file` adds the
Content-Security-Policy to build's page and checks it against the pinned viewer; `--send` is the only way the
orchestrator sends a page: it reads the role's saved answer, takes the path of its last `REPORT-HTML` line, opens
it without following links, checks the bytes and writes the text to `DIR/report.html`. The page is written with each
literal allow mark replaced by `[secret-scan mark removed]`, after a scan that ignores the mark. Exit 1 on any refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import unicodedata
import urllib.error
from pathlib import Path

from tld import net
from tld.board import report_check
from tld.guard import secret_scan

PIN = {
    "version": "0.9.1",
    "url": "https://github.com/bashovski/reflektor/releases/download/v0.9.1/reflektor-0.9.1.tar.gz",
    "size": 5581999,
    "sha256": "4a94eda3e8ee4a23b45e940a852ad32d9e3e7abef806655476a836e16c835eb6",
    "manifest_sha256": "9525595339ea7b47a1f50951fa7eea088fa78f8311ba44c10992b5b25a25ddef",
    "signature_sha256": "eefd5e1708e31d89ad6423742806775dcd6f6f9ae7f5c05b89b795c1def085ba",
    "release_key_sha256": "f60a00499bc6b5033de27b63c80b15266d710737e1a173c13029dbd29e191b6e",
    "build_commit": "de70055",
}

DOWNLOAD_SECONDS = 120
CONFIG_MAX = 100000
ALLOWED_KEYS = ("base", "targets", "generated")
TARGET_NAMES = ("backend", "frontend", "database", "infrastructure", "cicd", "misc")
GLOB_RE = re.compile(r"^[A-Za-z0-9._/*?{}-]+$")
MAX_HTML = 64 * 1024 * 1024
REPORT_HTML_RE = re.compile(r"/[A-Za-z0-9._/-]+/out/report\.html")
REQUIRED_FILES = ("scripts/collect.mjs", "scripts/build.mjs", "assets/viewer.html", "SKILL.md")


class PrepareError(Exception):
    """A reason to stop; `code` is the exit code (1 or 3)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _node_major(node) -> int | None:
    """The major version of `node --version`, or None when it cannot be told."""
    try:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0:
        return None
    m = re.match(r"v(\d+)\.", (done.stdout or "").strip())
    return int(m.group(1)) if m else None


def _fetch(url: str, limit: int) -> bytes:
    """Download `url` (only https://github.com/), reading at most `limit + 1` bytes within 120 seconds."""
    if not url.startswith("https://github.com/"):
        raise PrepareError(1, "only https://github.com/ URLs are fetched")
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    chunks: list[bytes] = []
    total = 0
    try:
        with net.opener().open(url, timeout=30) as resp:
            while total <= limit:
                if time.monotonic() > deadline:
                    raise PrepareError(3, "download timed out")
                chunk = resp.read(min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
    except PrepareError:
        raise
    except TimeoutError as exc:
        raise PrepareError(3, f"download failed: {exc}") from exc
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        raise PrepareError(3, f"download failed: {exc}") from exc
    return b"".join(chunks)


def _member_name(raw: str, is_dir: bool) -> str:
    """The normalised name of an archive member; PrepareError(1) for a name that is not safe."""
    name = raw
    while name.startswith("./"):
        name = name[2:]
    if name == ".":
        if is_dir:
            return ""
        raise PrepareError(1, f"bad member name {raw!r}")
    if "\\" in name or "\x00" in name:
        raise PrepareError(1, f"bad member name {raw!r}")
    if not name or name.startswith("/"):
        raise PrepareError(1, f"bad member name {raw!r}")
    if is_dir and name.endswith("/"):
        name = name.rstrip("/")
    for seg in name.split("/"):
        if seg in ("", ".", ".."):
            raise PrepareError(1, f"bad member name {raw!r}")
    return name


def _bad_text(value: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Cf") for c in value)


def _check_glob_list(key: str, globs, counter: list[int]) -> None:
    if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
        raise PrepareError(3, f".reflektor.json: '{key}' must be a list of strings")
    for g in globs:
        counter[0] += 1
        if (not GLOB_RE.match(g) or len(g) > 200 or g.count("**") > 2
                or g.replace("**", "").count("*") + g.count("?") > 4):
            raise PrepareError(3, f".reflektor.json: glob {g[:40]!r} in '{key}' is not allowed")


def check_repo(repo) -> None:
    """Refuse a clone whose .reflektor.json is anything but a plain, small, allow-listed file."""
    path = Path(repo) / ".reflektor.json"
    if not path.is_symlink() and not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise PrepareError(3, ".reflektor.json is not a regular file")
    try:
        if path.stat().st_size > CONFIG_MAX:
            raise PrepareError(3, ".reflektor.json is larger than 100000 bytes")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise PrepareError(3, f".reflektor.json cannot be read: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise PrepareError(3, ".reflektor.json is not a JSON object")
    for key in data:
        if key not in ALLOWED_KEYS:
            raise PrepareError(3, f".reflektor.json has the key '{key}' (only base, targets, generated are allowed)")
    if "base" in data:
        b = data["base"]
        if not isinstance(b, str) or len(b) > 200 or _bad_text(b):
            raise PrepareError(3, ".reflektor.json: 'base' must be a plain string of at most 200 characters")
    counter = [0]
    if "targets" in data:
        t = data["targets"]
        if not isinstance(t, dict):
            raise PrepareError(3, ".reflektor.json: 'targets' must be an object")
        for name, globs in t.items():
            if name not in TARGET_NAMES:
                raise PrepareError(3, f".reflektor.json: target '{str(name)[:40]}' is not one of {', '.join(TARGET_NAMES)}")
            _check_glob_list(f"targets.{name}", globs, counter)
    if "generated" in data:
        _check_glob_list("generated", data["generated"], counter)
    if counter[0] > 50:
        raise PrepareError(3, ".reflektor.json has more than 50 globs")


def _git(git=None) -> str:
    """The absolute path of git, resolved through a PATH that _check_path_env accepted."""
    found = git or shutil.which("git")
    if not found:
        raise PrepareError(3, "git was not found on PATH")
    return found


def check_base(repo, base, git=None) -> None:
    """The branch under review must not change .reflektor.json."""
    git = _git(git)
    try:
        done = subprocess.run([git, "-C", str(repo), "diff", "--quiet", str(base), "HEAD", "--", ".reflektor.json"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrepareError(3, f"git failed: {type(exc).__name__}") from exc
    if done.returncode == 0:
        return
    if done.returncode == 1:
        raise PrepareError(3, ".reflektor.json changed in this branch")
    raise PrepareError(3, "git failed")


def _check_path_env() -> None:
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            raise PrepareError(3, "PATH has an empty or relative entry")


def _guide(skill: bytes) -> str:
    lines = skill.decode("utf-8", "replace").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## 5. Write report.json")), None)
    end = None
    if start is not None:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## 6. Build")), None)
    if start is None or end is None:
        raise PrepareError(1, "SKILL.md lacks the report rules section")
    return "".join(lines[start:end])


def prepare(dest, repo, base, pin=None, fetch=None, node_major=None) -> Path:
    """Check, download, verify and unpack; returns `dest/reflektor` (the node path is `shutil.which("node")`)."""
    pin = PIN if pin is None else pin
    fetch = _fetch if fetch is None else fetch
    node_major = _node_major if node_major is None else node_major
    _check_path_env()
    git = _git()
    check_repo(repo)
    check_base(repo, base, git)
    node = shutil.which("node")
    if node is None:
        raise PrepareError(3, "node was not found on PATH")
    major = node_major(node)
    if major is None or major < 18:
        raise PrepareError(3, "node 18 or newer is required")
    data = fetch(pin["url"], pin["size"])
    if len(data) > pin["size"] or len(data) != pin["size"]:
        raise PrepareError(1, "the download does not have the pinned size")
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise PrepareError(1, "the download does not match the pinned sha256")
    files: dict[str, bytes] = {}
    dirs: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            seen: set[str] = set()
            for member in tar:
                if not (member.isreg() or member.isdir()):
                    raise PrepareError(1, f"member {member.name!r} is not a file or directory")
                name = _member_name(member.name, member.isdir())
                if not name:
                    continue
                if name in seen:
                    raise PrepareError(1, f"duplicate member {name!r}")
                seen.add(name)
                if member.isdir():
                    dirs.add(name)
                else:
                    handle = tar.extractfile(member)
                    files[name] = handle.read() if handle else b""
    except PrepareError:
        raise
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        raise PrepareError(1, f"the archive cannot be read: {type(exc).__name__}") from exc
    # a file and a directory (or a file below a file) may not share a path
    for name in files:
        parts = name.split("/")
        for i in range(1, len(parts)):
            if "/".join(parts[:i]) in files:
                raise PrepareError(1, f"member {name!r} lies below a file")
        if name in dirs:
            raise PrepareError(1, f"member {name!r} is both a file and a directory")
    for need in REQUIRED_FILES:
        if need not in files:
            raise PrepareError(1, f"the archive lacks {need}")
    guide = _guide(files["SKILL.md"])
    out = Path(dest).resolve() / "reflektor"
    try:
        out.mkdir(parents=False, exist_ok=False)
        for d in sorted(dirs):
            (out / d).mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (out / "report-guide.md").write_text(guide, encoding="utf-8")
    except OSError as exc:
        raise PrepareError(1, f"cannot write {out}: {type(exc).__name__}") from exc
    return out


def _walk(value):
    """Every (parent key, key, child) of a parsed JSON value, iteratively."""
    stack = [(None, None, value, 0)]
    while stack:
        parent, key, item, depth = stack.pop()
        if depth > report_check.MAX_DEPTH:
            raise ValueError("nested too deeply")
        yield parent, key, item
        if isinstance(item, dict):
            for k, child in item.items():
                stack.append((key, k, child, depth + 1))
        elif isinstance(item, list):
            for child in item:
                stack.append((parent, key, child, depth + 1))


def _bad_path(raw, root_real: str) -> str | None:
    """The reason a report `path` value is not acceptable, or None."""
    if not isinstance(raw, str):
        return "a path is not a string"
    shown = raw[:60]
    if (not raw or raw.startswith("/") or raw.startswith("~") or "\\" in raw or "\x00" in raw
            or any(seg in ("", ".", "..") for seg in raw.split("/"))):
        return f"path {shown!r} is not a plain relative path"
    real = os.path.realpath(os.path.join(root_real, raw))
    if real != root_real and not real.startswith(root_real.rstrip(os.sep) + os.sep):
        return f"path {shown!r} leaves the clone"
    return None


def check_report(report_text, root) -> list[str]:
    """The reasons an agent-written report.json is not acceptable (empty when it is)."""
    if not isinstance(report_text, str):
        return ["the report is not text"]
    body = report_text[:-1] if report_text.endswith("\n") else report_text
    if "\n" in body or "\r" in body:
        return ["the report is not one line of JSON"]
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        return ["the report is not valid JSON"]
    if not isinstance(value, dict):
        return ["the report is not a JSON object"]
    root_real = os.path.realpath(str(root))
    reasons: list[str] = []
    try:
        for _parent, key, child in _walk(value):
            if key == "path":
                why = _bad_path(child, root_real)
                if why and why not in reasons:
                    reasons.append(why)
    except ValueError:
        reasons.append("the report is nested too deeply")
    return reasons


ALLOW_MARK = secret_scan.ALLOW_MARK
REDACTED_MARK = "[secret-scan mark removed]"
REASON_SPLIT = "the data holds a line-splitting character"
REASON_ESCAPED = "the data carries an escaped secret-scan allow mark"
REASON_MARK_RAW = "the page carries a secret-scan allow mark outside its data"
_SPLITTERS = frozenset("\x0b\x0c\x1c\x1d\x1e\x1f\x85")


def _splits_lines(s: str) -> bool:
    """A character the secret scan's line splitting treats as a line break (or a category Zl or Zp)."""
    return any(c in _SPLITTERS or unicodedata.category(c) in ("Zl", "Zp") for c in s)


def verify_html(text) -> list[str]:
    """`report_check.check` plus the secret scan of the raw text and of every decoded string and key of the data.

    The scan ignores the allow mark (the scan option that turns the skip off), so a credential on a line that ends in the mark is found.
    It splits on more characters than a newline, so a line-splitting character in the data is refused. The mark
    itself is dealt with by `prepare_page`, after this check."""
    reasons = report_check.check(text)
    if reasons:
        return reasons
    got = report_check.split(text)
    if _splits_lines(got[1]):
        return [REASON_SPLIT]
    value = report_check.parse_payload(got[1])
    strings = []
    for _parent, key, child in _walk(value):
        for s in (key, child):
            if isinstance(s, str):
                strings.append(s)
    for s in strings:
        if _splits_lines(s):
            return [REASON_SPLIT]
    hits = secret_scan.scan_text(text, skip_marked=False)
    for s in strings:
        if not hits:
            hits = secret_scan.scan_text(s, skip_marked=False)
    if hits:
        names = sorted({name for _n, name, _d in hits})
        return [f"the page holds something that looks like a credential ({', '.join(names)})"]
    return []


def _swap(s: str) -> tuple[str, int]:
    return s.replace(ALLOW_MARK, REDACTED_MARK), s.count(ALLOW_MARK)


def neutralise_page(text: str) -> tuple[str, int]:
    """Replace each literal allow mark in the title and the data; the fixed viewer parts and the CSP stay byte for byte."""
    got = report_check.split(text)
    if isinstance(got, list):
        raise ValueError(got[0])
    title, payload = got
    n1, n2, n3, n4 = (p[0] for p in report_check.VIEWER_PARTS)
    t_start = n1 + len(report_check.CSP_META) + n2 + len(report_check.TITLE_OPEN)
    p_start = t_start + len(title) + len(report_check.TITLE_CLOSE) + n3
    p_end = len(text) - n4
    new_title, c1 = _swap(title)
    new_payload, c2 = _swap(payload)
    return text[:t_start] + new_title + text[t_start + len(title):p_start] + new_payload + text[p_end:], c1 + c2


def marks_left(text: str) -> list[str]:
    """A reason when the page still holds the allow mark, raw or as an escaped form in the decoded data."""
    if ALLOW_MARK in text:
        return [REASON_MARK_RAW]
    got = report_check.split(text)
    if isinstance(got, list):
        return got
    value = report_check.parse_payload(got[1])
    for _parent, key, child in _walk(value):
        for s in (key, child):
            if not isinstance(s, str):
                continue
            if ALLOW_MARK in s:
                return [REASON_ESCAPED]
    return []


def _report_removed(count: int) -> None:
    if count:
        print(f"tld roles: reflektor: removed {count} secret-scan allow marks from the page", file=sys.stderr)


def prepare_page(text: str) -> tuple[str, int]:
    """Check the original page, replace each literal allow mark, check the result in full, and return the neutral page
    with the number of marks replaced. The caller prints the count with `_report_removed` after its write succeeds.

    The swap can create a word boundary (the mark starts and ends with a letter, its replacement with a bracket), so
    a credential glued to the mark is found only in the result: the whole check runs on both."""
    reasons = verify_html(text)
    if reasons:
        raise _refuse(reasons)
    neutral, count = neutralise_page(text)
    reasons = verify_html(neutral) or marks_left(neutral)
    if reasons:
        raise _refuse(reasons)
    return neutral, count


_CHECK_REASONS = (
    r"the page is not text", r"page part [1-4] differs from the pinned viewer",
    r"the Content-Security-Policy meta tag is missing or changed", r"the title tag is missing",
    r"the title tag is not closed", r"the title is not plain one-line text",
    r"already hardened", r"the page must have exactly one <head>", r"the answer has no REPORT-HTML line",
    r"the REPORT-HTML path is not an out/report\.html path",
    r"cannot (?:open|read|write) (?:the page|the answer): [A-Za-z]+",
    r"(?:the page|the answer) is (?:not a regular file|not UTF-8|larger than [0-9]+ bytes)",
)
_INVALID = (r"invalid payload(?: \((?:NaN or Infinity|duplicate key|not one line|contains '<'|not JSON|nested too deeply)\))?")
_LINK = "the data has a link target under '(?:%s)'" % "|".join(
    re.escape(k) for k in (*report_check.NULL_KEYS, "branch.pr", "avatar.image"))
_CRED_NAMES = [name for name, _d, _rx in secret_scan.SPECIFIC] + ["high-entropy-assignment"]
_CRED = r"the page holds something that looks like a credential \((?:%s)(?:, (?:%s))*\)" % (
    "|".join(re.escape(n) for n in _CRED_NAMES), "|".join(re.escape(n) for n in _CRED_NAMES))
_KNOWN = re.compile("|".join(f"(?:{p})" for p in (
    *_CHECK_REASONS, _INVALID, _LINK, _CRED, re.escape(REASON_SPLIT), re.escape(REASON_ESCAPED),
    re.escape(REASON_MARK_RAW))))


def known_reason(reason: str) -> bool:
    """True only when REASON fully matches one of the texts this module and `report_check` can emit."""
    return _KNOWN.fullmatch(reason) is not None


def _read_regular(path, what: str) -> str:
    """Read a regular file (never through a symlink) of at most MAX_HTML bytes as UTF-8, or PrepareError(1)."""
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise PrepareError(1, f"cannot open {what}: {type(exc).__name__}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise PrepareError(1, f"{what} is not a regular file")
        if st.st_size > MAX_HTML:
            raise PrepareError(1, f"{what} is larger than {MAX_HTML} bytes")
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(MAX_HTML + 1)
    except OSError as exc:
        raise PrepareError(1, f"cannot read {what}: {type(exc).__name__}") from exc
    finally:
        os.close(fd)
    if len(data) > MAX_HTML:
        raise PrepareError(1, f"{what} is larger than {MAX_HTML} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PrepareError(1, f"{what} is not UTF-8") from exc


def _refuse(reasons: list[str]) -> PrepareError:
    return PrepareError(1, "\n".join(reasons))


def harden_html(file) -> Path:
    """Add CSP_META directly after the single <head> of build's page, check the result, write it only when clean."""
    text = _read_regular(file, "the page")
    if report_check.CSP_META in text:
        raise PrepareError(1, "already hardened")
    if text.count("<head>") != 1:
        raise PrepareError(1, "the page must have exactly one <head>")
    at = text.index("<head>") + len("<head>")
    hardened = text[:at] + report_check.CSP_META + text[at:]
    neutral, removed = prepare_page(hardened)
    path = Path(file)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(neutral, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise PrepareError(1, f"cannot write the page: {type(exc).__name__}") from exc
    _report_removed(removed)
    return path


def send_copy(answer_file, dest) -> Path:
    """Copy the page named by the last REPORT-HTML line of a saved answer to DEST/report.html after checking it."""
    answer = _read_regular(answer_file, "the answer")
    rest = None
    for line in answer.split("\n"):
        if line.startswith("REPORT-HTML "):
            rest = line[len("REPORT-HTML "):].rstrip("\r")
    if rest is None:
        raise PrepareError(1, "the answer has no REPORT-HTML line")
    if not REPORT_HTML_RE.fullmatch(rest) or ".." in rest.split("/"):
        raise PrepareError(1, "the REPORT-HTML path is not an out/report.html path")
    text, removed = prepare_page(_read_regular(rest, "the page"))
    out = Path(dest)
    try:
        out.mkdir(parents=True, exist_ok=True)
        target = out / "report.html"
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
    except OSError as exc:
        raise PrepareError(1, f"cannot write the page: {type(exc).__name__}") from exc
    _report_removed(removed)
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("prepare", help="download the pinned release, check it and unpack it")
    pp.add_argument("--dest", required=True)
    pp.add_argument("--repo", required=True)
    pp.add_argument("--base", required=True)
    ck = sub.add_parser("check", help="check the paths of an agent-written report")
    ck.add_argument("--report", required=True)
    ck.add_argument("--root", required=True)
    hp = sub.add_parser("html", help="harden build's page, or check and copy a saved answer's page")
    mode = hp.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file")
    mode.add_argument("--send", action="store_true")
    hp.add_argument("--answer")
    hp.add_argument("--dest")
    args = ap.parse_args(argv)
    if args.cmd == "html" and args.send and not (args.answer and args.dest):
        ap.error("--send needs --answer and --dest")
    if args.cmd == "html" and not args.send and (args.answer or args.dest):
        ap.error("--answer and --dest go with --send")
    try:
        if args.cmd == "check":
            text = _read_regular(args.report, "the report")
            reasons = check_report(text, args.root)
            for r in reasons:
                print(f"tld roles: reflektor: {r}", file=sys.stderr)
            return 1 if reasons else 0
        if args.cmd == "html":
            out = send_copy(args.answer, args.dest) if args.send else harden_html(args.file)
            if args.send:
                print(out)
            return 0
        out = prepare(Path(args.dest), Path(args.repo), args.base)
    except PrepareError as exc:
        for line in exc.message.split("\n"):
            print(f"tld roles: reflektor: {line}", file=sys.stderr)
        return exc.code
    print(out)
    print(os.path.abspath(shutil.which("node")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
