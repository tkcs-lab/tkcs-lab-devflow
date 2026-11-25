#!/usr/bin/env python3
"""The org base profile: parse a pin, fetch the file by commit, cache it, check it.

    tld profile base check FILE         check a base file before it is tagged (prints `base: OK`)
    tld profile base fetch [PROFILE]    fill the cache with the base the profile extends (default .tld/toolkit.yaml)
    tld profile base latest SOURCE      print {"sha", "tag"} of the newest tagged commit that has the file

A profile extends a base with `tld.extends: <owner>/<repo>/<path>@<40-hex commit>`. Only a full commit is
accepted (a tag can move). The file is fetched with git over HTTPS into a separate bare repository
`<git common dir>/tld/base/objects.git` (never the project's own object store, so the project never becomes
shallow) and cached as the exact bytes in `<git common dir>/tld/base/<key>.yaml` with `<key>.json` beside it.
A commit never changes, so the cache has no expiry and a base is never fetched twice.

A base is policy for every agent of an organisation, so it is checked before anything reads it: size, UTF-8,
no YAML anchors or aliases, a bounded depth, only the keys in BASE_KEYS, no chaining and no credential. No
message of this module contains the offending value.

Exit 0 ok; 1 on a refusal or an error (`toolkit.yaml: ...` or `base: ...` on stderr). Python 3.11+, stdlib and
PyYAML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from tld.guard import secret_scan
from tld.guard.trust import SAFE_OPTS, _env, _git, _out

DEFAULT_PROFILE = ".tld/toolkit.yaml"
FETCH_TIMEOUT = 20.0
MAX_BYTES = 65536
MAX_DEPTH = 8
MAX_TAGS_TRIED = 20
SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
SOURCE_RE = re.compile(r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<repo>[A-Za-z0-9._-]{1,100})/(?P<path>[A-Za-z0-9._/-]{1,256})$")
TAG_RE = re.compile(r"^v?[0-9]{1,9}(\.[0-9]{1,9}){0,5}$", re.ASCII)

# The keys a base may set, as dotted paths; a path allows everything below it.
BASE_KEYS = ("tld.version", "tld.allow_override", "git.bot_login", "git.codeowners", "git.branch_pattern",
             "roles.posture", "roles.required", "hooks", "models", "runtime.environments", "verify.dod_manual")
BASE_KEYS_TEXT = ", ".join(k if k != "hooks" else "hooks.*" for k in BASE_KEYS)

Runner = Callable[[list, dict, float], "tuple[int, bytes | str, str]"]


class BaseError(Exception):
    """A refusal or failure with the finished message (it starts with `toolkit.yaml: `)."""


@dataclass(frozen=True)
class BaseRef:
    owner: str  # owner and repo are kept lower-case: GitHub names compare case-insensitively
    repo: str
    path: str
    sha: str

    @property
    def source(self) -> str:
        return f"{self.owner}/{self.repo}/{self.path}"

    @property
    def label(self) -> str:
        return f"{self.source}@{self.sha[:7]}"


def _split_source(text: str) -> tuple[str, str, str] | None:
    m = SOURCE_RE.match(text) if isinstance(text, str) else None
    if not m:
        return None
    owner, repo, path = m.group("owner"), m.group("repo"), m.group("path")
    if repo in (".", "..") or repo.endswith(".git"):
        return None
    segments = path.split("/")
    if (any(s in ("", ".", "..") for s in segments) or "\\" in path or not path.isprintable()
            or not path.endswith((".yaml", ".yml"))):
        return None
    return owner.lower(), repo.lower(), path


def parse_source(text: str) -> tuple[str, str, str]:
    """(owner, repo, path) of `<owner>/<repo>/<path>`, or BaseError with the shape message."""
    parts = _split_source(text)
    if parts is None:
        raise BaseError(f"toolkit.yaml: 'tld.extends': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got '{_show(text)}')")
    return parts


def _show(value: object) -> str:
    text = value if isinstance(value, str) else type(value).__name__
    return "".join(c if c.isprintable() else "?" for c in text)[:200]


def parse_extends(value: object) -> BaseRef:
    """`tld.extends` as a BaseRef. A tag or branch is refused: only a full commit cannot move."""
    shape = BaseError(f"toolkit.yaml: 'tld.extends': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got '{_show(value)}')")
    if not isinstance(value, str) or "@" not in value:
        raise shape
    source, _, ref = value.rpartition("@")
    parts = _split_source(source)
    if parts is None or not ref:
        raise shape
    if not SHA40_RE.match(ref):
        raise BaseError(f"toolkit.yaml: 'tld.extends': '@{_show(ref)}' is not a commit SHA; pin the base by its full "
                        f"40-hex commit (a tag can move): run tld profile base latest {parts[0]}/{parts[1]}/{parts[2]}")
    return BaseRef(*parts, ref.lower())


def url_for(ref: BaseRef) -> str:
    return f"https://github.com/{ref.owner}/{ref.repo}.git"


# ---- checking a base file ------------------------------------------------------------------------------------

def _allowed(path: str) -> str:
    """'yes' (the key or something above it is allowed), 'descend' (a key below it is) or 'no'."""
    for allowed in BASE_KEYS:
        if path == allowed or path.startswith(allowed + "."):
            return "yes"
    if any(allowed.startswith(path + ".") for allowed in BASE_KEYS):
        return "descend"
    return "no"


def _key_errors(data: dict, label: str) -> list[str]:
    errors: list[str] = []
    pre = f"toolkit.yaml: base {label}: "
    tld = data.get("tld")
    if isinstance(tld, dict) and "extends" in tld:
        errors.append(f"{pre}'tld.extends': a base cannot extend another profile")

    def walk(node: dict, prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}{key}"
            if path == "tld.extends":
                continue
            verdict = _allowed(path)
            if verdict == "yes":
                continue
            if verdict == "descend" and isinstance(value, dict):
                walk(value, path + ".")
                continue
            errors.append(f"{pre}'{_show(path)}' cannot be set in a base (a base may set: {BASE_KEYS_TEXT})")

    walk(data, "")
    return errors


def _scan_events(text: str, pre: str) -> tuple[list[str], bool]:
    """Errors from the YAML event stream (anchors, aliases, depth, credential-named keys); `parsed` is False
    when the text is not valid YAML. Events are read one at a time, so nothing recursive runs on deep input."""
    errors: list[str] = []
    stack: list[list] = []  # [is_mapping, children seen]
    depth = anchors = 0
    reported: set[str] = set()

    def once(kind: str, message: str) -> None:
        if kind not in reported:
            reported.add(kind)
            errors.append(message)

    try:
        for event in yaml.parse(text):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
                anchors += 1
            is_key = bool(stack) and stack[-1][0] and stack[-1][1] % 2 == 0
            if isinstance(event, yaml.ScalarEvent) and is_key and secret_scan.secret_like_name(event.value):
                errors.append(f"{pre}refused: line {event.start_mark.line + 1} has a key named like a credential "
                              f"(pattern: secret-like-name); the value is not shown. A base never holds a credential.")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                if stack:
                    stack[-1][1] += 1
                stack.append([isinstance(event, yaml.MappingStartEvent), 0])
                depth = max(depth, len(stack))
                if len(stack) > MAX_DEPTH:
                    once("depth", f"{pre}nests deeper than {MAX_DEPTH} levels")
                    break
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                stack.pop()
            elif stack and not isinstance(event, (yaml.StreamStartEvent, yaml.StreamEndEvent,
                                                  yaml.DocumentStartEvent, yaml.DocumentEndEvent)):
                stack[-1][1] += 1
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        errors.append(f"{pre}is not valid YAML{where}")
        return errors, False
    if anchors:
        errors.append(f"{pre}uses YAML anchors or aliases; a base must not")
    return errors, True


def check_base_text(text: str | bytes, label: str) -> tuple[dict | None, list[str]]:
    """(the parsed base, []) or (None, the refusals). `label` is `<source>@<sha7>` (or a file name)."""
    pre = f"toolkit.yaml: base {label}: "
    raw = text if isinstance(text, bytes) else text.encode("utf-8", "surrogatepass")
    if len(raw) > MAX_BYTES:
        return None, [f"{pre}is larger than {MAX_BYTES} bytes"]
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, [f"{pre}is not UTF-8"]
    if decoded.startswith("﻿"):
        return None, [f"{pre}starts with a byte order mark; a base is UTF-8 without BOM"]
    errors, parsed = _scan_events(decoded, pre)
    for line, name, desc in secret_scan.scan_text(decoded, skip_marked=False):
        errors.append(f"{pre}refused: line {line} looks like {desc} (pattern: {name}); the value is not shown. "
                      f"A base never holds a credential.")
    if errors or not parsed:
        return None, errors
    try:
        data = yaml.safe_load(decoded)
    except yaml.YAMLError:
        return None, [f"{pre}is not valid YAML"]
    if not isinstance(data, dict):
        return None, [f"{pre}must be a mapping at the top"]
    errors = _key_errors(data, label)
    return (None, errors) if errors else (data, [])


# ---- cache and fetch -----------------------------------------------------------------------------------------

def common_dir(project: str | Path) -> Path | None:
    """The git common directory (shared by linked worktrees) of `project`, or None outside a repository."""
    out = _out(_git(str(project), "rev-parse", "--git-common-dir"))
    if not out:
        return None
    path = Path(out)
    return path if path.is_absolute() else Path(project) / path


def cache_key(ref: BaseRef) -> str:
    return hashlib.sha256(f"{ref.source}@{ref.sha}".encode()).hexdigest()[:24].lower()


def _base_dir(git_dir: Path) -> Path:
    return git_dir / "tld" / "base"


def cached(git_dir: str | Path, ref: BaseRef) -> str | None:
    """The cached text of `ref`, or None on a miss or when the stored bytes no longer match their hash."""
    key = cache_key(ref)
    folder = _base_dir(Path(git_dir))
    try:
        meta = json.loads((folder / f"{key}.json").read_text())
        data = (folder / f"{key}.yaml").read_bytes()
        if (not isinstance(meta, dict) or meta.get("source") != ref.source or meta.get("sha") != ref.sha
                or meta.get("sha256") != hashlib.sha256(data).hexdigest() or meta.get("size") != len(data)
                or not isinstance(meta.get("blob"), str) or not _blob_matches(data, meta["blob"])):
            return None
        return data.decode("utf-8", "surrogateescape")
    except (OSError, ValueError):
        return None


def _blob_matches(data: bytes, blob: str) -> bool:
    """Does `data` hash to the git blob id `blob` (SHA-1 or SHA-256 object format)?"""
    algo = {40: hashlib.sha1, 64: hashlib.sha256}.get(len(blob))  # noqa: S324 - git's own object id
    return algo is not None and algo(b"blob %d\0" % len(data) + data).hexdigest() == blob.lower()


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _store(git_dir: Path, ref: BaseRef, data: bytes, blob: str) -> None:
    folder = _base_dir(git_dir)
    folder.mkdir(parents=True, exist_ok=True)
    key = cache_key(ref)
    meta = {"source": ref.source, "sha": ref.sha, "blob": blob, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _write_atomic(folder / f"{key}.yaml", data)
    _write_atomic(folder / f"{key}.json", json.dumps(meta).encode())  # last: a half-written entry is a miss


def _default_runner(args: list, env: dict, timeout: float) -> tuple[int, bytes, str]:
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return 124, b"", f"timed out after {timeout:g} s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, b"", f"git could not run: {type(exc).__name__}"
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")


def _bytes(out: bytes | str) -> bytes:
    return out if isinstance(out, bytes) else out.encode("utf-8", "surrogateescape")


def _str(out: bytes | str) -> str:
    return out.decode("utf-8", "replace") if isinstance(out, bytes) else out


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return _show(line.strip())
    return "no output"


class _Git:
    """git calls in one bare repository through the injectable runner, with trust.py's safe options and environment."""

    def __init__(self, repo: Path, runner: Runner | None, timeout: float) -> None:
        self.repo, self.run, self.timeout = repo, runner or _default_runner, timeout

    def __call__(self, *args: str) -> tuple[int, bytes, str]:
        code, out, err = self.run(["git", *SAFE_OPTS, "-C", str(self.repo), *args], _env(), self.timeout)
        return code, _bytes(out), err


def _init_bare(repo: Path, runner: Runner | None, timeout: float) -> None:
    if (repo / "HEAD").is_file():
        return
    repo.parent.mkdir(parents=True, exist_ok=True)
    code, _, err = (runner or _default_runner)(["git", *SAFE_OPTS, "init", "--bare", "-q", str(repo)], _env(), timeout)
    if code != 0:
        raise BaseError(f"toolkit.yaml: 'tld.extends': could not prepare the base cache ({_first_line(err)})")


def _blob_at(git: _Git, ref: BaseRef) -> tuple[str, int]:
    """(blob id, size) of the file at the fetched commit, or BaseError."""
    gone = BaseError(f"toolkit.yaml: 'tld.extends': {ref.path} does not exist at {ref.owner}/{ref.repo}@{ref.sha[:7]}")
    code, out, _ = git("ls-tree", ref.sha, "--", ref.path)
    fields = _str(out).strip().split(None, 3)
    if code != 0 or len(fields) < 4 or fields[3].strip() != ref.path:
        raise gone
    if fields[0] not in ("100644", "100755") or fields[1] != "blob":
        raise BaseError(f"toolkit.yaml: 'tld.extends': {ref.path} at {ref.owner}/{ref.repo}@{ref.sha[:7]} "
                        f"is not a regular file")
    code, size, _ = git("cat-file", "-s", fields[2])
    if code != 0 or not _str(size).strip().isdigit():
        raise gone
    return fields[2], int(_str(size))


def _fetch_commit(git: _Git, ref: BaseRef) -> None:
    code, _, err = git("fetch", "--quiet", "--depth=1", "--no-tags", "--no-write-fetch-head", url_for(ref), ref.sha)
    if code != 0:
        raise BaseError(f"toolkit.yaml: 'tld.extends': the base {ref.label} is not cached and could not be fetched "
                        f"({_first_line(err)[:200]}); run again with network access")


def _remote_tags(out: str) -> dict[str, str]:
    """version tag -> commit from `git ls-remote --tags` output (the peeled line, the commit of an annotated tag, wins)."""
    tags: dict[str, str] = {}
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if not name.startswith("refs/tags/") or not SHA40_RE.match(sha):
            continue
        tag = name[len("refs/tags/"):]
        peeled = tag.endswith("^{}")
        tag = tag[:-3] if peeled else tag
        if TAG_RE.match(tag) and (peeled or tag not in tags):
            tags[tag] = sha.lower()
    return tags


def _remote_head(out: str) -> str:
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == "HEAD" and SHA40_RE.match(sha):
            return sha.lower()
    return ""


def _require_approved(git: _Git, ref: BaseRef, runner: Runner | None, timeout: float) -> None:
    """The commit must be the commit of a version tag or an ancestor of the default branch head. A commit that only
    a pull request or a fork holds is served by the same URL, so a bare SHA does not prove the owners approved it."""
    run = runner or _default_runner
    base = ["git", *SAFE_OPTS]
    url = url_for(ref)

    def listing(*args: str) -> str:  # options first, then the URL, then the patterns: `--tags` or `HEAD`
        options = [a for a in args if a.startswith("-")]
        patterns = [a for a in args if not a.startswith("-")]
        code, out, err = run([*base, "ls-remote", *options, url, *patterns], _env(), timeout)
        if code != 0:
            raise BaseError(f"toolkit.yaml: 'tld.extends': the base {ref.label} is not cached and could not be fetched "
                            f"({_first_line(err)[:200]}); run again with network access")
        return _str(out)

    if ref.sha in _remote_tags(listing("--tags")).values():
        _fetch_commit(git, ref)
        return
    head = _remote_head(listing("HEAD"))
    refused = BaseError(f"toolkit.yaml: 'tld.extends': the commit {ref.sha[:7]} is not on a tag or the default branch "
                        f"of {ref.owner}/{ref.repo}")
    if not head:
        raise refused
    code, _, err = git("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", url, head)  # the whole history of the head
    if code != 0:
        raise BaseError(f"toolkit.yaml: 'tld.extends': the base {ref.label} is not cached and could not be fetched "
                        f"({_first_line(err)[:200]}); run again with network access")
    if git("merge-base", "--is-ancestor", ref.sha, head)[0] != 0:
        raise refused


def fetch(project: str | Path, ref: BaseRef, timeout: float = FETCH_TIMEOUT, runner: Runner | None = None) -> str:
    """The text of the base at `ref`: from the cache, else fetched by commit and cached. BaseError on failure."""
    git_dir = common_dir(project)
    if git_dir is None:
        raise BaseError(f"toolkit.yaml: 'tld.extends': the base {ref.label} is not cached and could not be fetched "
                        f"(not a git repository); run again with network access")
    hit = cached(git_dir, ref)
    if hit is not None:
        return hit
    bare = _base_dir(git_dir) / "objects.git"
    _init_bare(bare, runner, timeout)
    git = _Git(bare, runner, timeout)
    _require_approved(git, ref, runner, timeout)
    blob, size = _blob_at(git, ref)
    if size > MAX_BYTES:
        raise BaseError(f"toolkit.yaml: base {ref.label}: is larger than {MAX_BYTES} bytes")
    code, data, err = git("cat-file", "blob", blob)
    if code != 0:
        raise BaseError(f"toolkit.yaml: 'tld.extends': the base {ref.label} could not be read ({_first_line(err)[:200]})")
    if not _blob_matches(data, blob):
        raise BaseError(f"toolkit.yaml: 'tld.extends': the base {ref.label} does not match its git object id")
    _, errors = check_base_text(data, ref.label)
    if errors:
        raise BaseError("\n".join(errors))  # nothing refused is ever cached
    _store(git_dir, ref, data, blob)
    return data.decode("utf-8")


# ---- the newest pin ------------------------------------------------------------------------------------------

def _tag_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def latest_pin(source: str, runner: Runner | None = None, timeout: float = FETCH_TIMEOUT) -> tuple[str, str | None]:
    """(commit, tag) of the newest version tag whose commit has the file, else (default branch head, None).

    Tags match `v?<digits>(.<digits>)*` and sort by their numeric parts (v10 after v9). A tag is checked by
    fetching its commit into a scratch repository; the newest tag without the file is skipped."""
    owner, repo, path = parse_source(source)
    probe = BaseRef(owner, repo, path, "0" * 40)
    run = runner or _default_runner
    env = _env()
    base = ["git", *SAFE_OPTS]

    def ls_remote(*args: str) -> str:
        code, out, err = run([*base, "ls-remote", *args], env, timeout)
        if code != 0:
            raise BaseError(f"toolkit.yaml: 'tld.extends': could not list {owner}/{repo} ({_first_line(err)[:200]})")
        return _str(out)

    tags = _remote_tags(ls_remote("--tags", url_for(probe)))
    with tempfile.TemporaryDirectory(prefix="tld-base-") as scratch:
        bare = Path(scratch) / "probe.git"
        _init_bare(bare, runner, timeout)
        git = _Git(bare, runner, timeout)
        for tag in sorted(tags, key=_tag_key, reverse=True)[:MAX_TAGS_TRIED]:
            candidate = BaseRef(owner, repo, path, tags[tag])
            try:
                _fetch_commit(git, candidate)
                _blob_at(git, candidate)
            except BaseError:
                continue
            return candidate.sha, tag
        head = _remote_head(ls_remote(url_for(probe), "HEAD"))
        if not head:
            raise BaseError(f"toolkit.yaml: 'tld.extends': {owner}/{repo} has no default branch to pin")
        candidate = BaseRef(owner, repo, path, head)
        _fetch_commit(git, candidate)
        _blob_at(git, candidate)
        return head, None


# ---- command line --------------------------------------------------------------------------------------------

def _cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        raw = path.read_bytes()
    except OSError:
        print(f"base: cannot read '{path}'", file=sys.stderr)
        return 1
    _, errors = check_base_text(raw, str(path))
    for line in errors:
        print(line, file=sys.stderr)
    if errors:
        return 1
    print("base: OK")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    profile_path = Path(args.profile)
    try:
        if args.ref:
            from tld.profile import resolve as rs
            sha, problem = rs.resolve_ref(Path.cwd(), args.ref)
            if problem:
                print(f"toolkit.yaml: {problem}", file=sys.stderr)
                return 1
            shown = rs._git(Path.cwd(), "show", f"{sha}:{profile_path.as_posix()}")
            if shown is None or shown.returncode != 0:
                raise OSError("no such file at the ref")
            profile = yaml.safe_load(shown.stdout)
            profile_path = Path.cwd() / profile_path  # the repository the cache belongs to
        else:
            profile = yaml.safe_load(profile_path.read_text())
    except (OSError, yaml.YAMLError):
        print(f"toolkit.yaml: no readable profile at '{profile_path}'", file=sys.stderr)
        return 1
    tld = profile.get("tld") if isinstance(profile, dict) else None
    if not isinstance(tld, dict) or "extends" not in tld:
        print("no base")
        return 0
    try:
        ref = parse_extends(tld["extends"])
        root = profile_path.resolve().parent.parent
        git_dir = common_dir(root)
        was_cached = git_dir is not None and cached(git_dir, ref) is not None
        fetch(root, ref)
    except BaseError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{ref.label} ({'cached' if was_cached else 'fetched'})")
    return 0


def _cmd_latest(args: argparse.Namespace) -> int:
    try:
        sha, tag = latest_pin(args.source)
    except BaseError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps({"sha": sha, "tag": tag}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld profile base", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="check a base file before it is tagged")
    p.add_argument("file")
    p.set_defaults(run=_cmd_check)
    p = sub.add_parser("fetch", help="fill the cache with the base a profile extends")
    p.add_argument("profile", nargs="?", default=DEFAULT_PROFILE)
    p.add_argument("--ref", help="read the profile from this git ref of the current repository (for example the "
                                 "default branch, whose base the trusted copy needs)")
    p.set_defaults(run=_cmd_fetch)
    p = sub.add_parser("latest", help="the newest pin of <owner>/<repo>/<path>")
    p.add_argument("source")
    p.set_defaults(run=_cmd_latest)
    args = ap.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
