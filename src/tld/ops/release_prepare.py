#!/usr/bin/env python3
"""Prepare a release: bump the version files and open the changelog's version heading.

Usage: release_prepare.py [--profile FILE] [--version X.Y.Z | --bump patch|minor|major] [--date YYYY-MM-DD]
                          [--write] [--check [--base REF]]

Reads `release.version_files` and `docs.changelog` from the profile; run it from the repository root.
No version argument: prints JSON with `current`, `candidates`, `suggested_bump` and `preview` (the unreleased
entry). With `--version` or `--bump`: the same plus `next`, `files`, `heading` and `written`; `--write` applies it
(every new content is computed first, written to a temporary file, then moved into place, then re-read).
`--check --version X.Y.Z` verifies a prepared release; with `--base REF` it also verifies that nothing but the
changelog and the version lines changed since REF.

Exit 0 ok; 1 a problem (`release-prepare: <problem>`); 2 a usage error.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from tld.profile import validate as pv

DEFAULT_PROFILE = ".tld/toolkit.yaml"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BUMPS = ("patch", "minor", "major")


class ReleaseError(Exception):
    """A problem that stops the command (exit 1)."""


def _tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def _bumped(current: str) -> dict[str, str]:
    major, minor, patch = _tuple(current)
    return {"patch": f"{major}.{minor}.{patch + 1}", "minor": f"{major}.{minor + 1}.0", "major": f"{major + 1}.0.0"}


def _read(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"cannot read {path}: {exc}")


def _inside(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ReleaseError(f"{rel} is outside the repository")
    return target


def _span(rel: str, pattern: str, text: str) -> re.Match:
    found = list(re.finditer(pattern, text, re.M))
    if not found:
        raise ReleaseError(f"no match for the pattern in {rel}")
    if len(found) > 1:
        raise ReleaseError(f"{len(found)} matches for the pattern in {rel}")
    return found[0]


def _versions(profile: dict, root: Path) -> list[tuple[str, str, str, re.Match]]:
    """(path, pattern, text, match) of every version file; they must agree on the version."""
    out = []
    for vf in profile["release"]["version_files"]:
        text = _read(_inside(root, vf["path"]))
        out.append((vf["path"], vf["pattern"], text, _span(vf["path"], vf["pattern"], text)))
    first = out[0]
    for other in out[1:]:
        if other[3].group(1) != first[3].group(1):
            raise ReleaseError(f"version files disagree: {first[0]} has {first[3].group(1)}, "
                               f"{other[0]} has {other[3].group(1)}")
    return out


def _heading(section: str, text: str) -> re.Match | None:
    return re.search(r"^" + re.escape(section.strip()) + r"[ \t]*(?=\r?$)", text, re.M)


def _body(text: str, start: int, level: int) -> str:
    """The text after a heading up to the next heading of the same or a higher level."""
    rest = text[start:]
    end = re.search(r"^#{1," + str(level) + r"}[ \t]", rest, re.M)
    return rest[:end.start()] if end else rest


def _has_entries(body: str) -> bool:
    return any(line.strip() and not line.lstrip().startswith("#") for line in body.splitlines())


def _suggested(body: str) -> str:
    if re.search(r"^###\s+(Removed|Breaking)\b", body, re.M | re.I):
        return "major"
    if re.search(r"^###\s+Added\b", body, re.M | re.I):
        return "minor"
    return "patch"


def plan(profile: dict, root: Path, version_or_bump: str | None, date: str) -> dict:
    """What a release would change. `version_or_bump` is X.Y.Z, patch|minor|major or None (only report).
    Raises ReleaseError before anything is touched; the result holds `edits` (path -> new text) for `apply`."""
    root = Path(root)
    versions = _versions(profile, root)
    current = versions[0][3].group(1)
    candidates = _bumped(current)
    cl = profile["docs"]["changelog"]
    cl_text = _read(_inside(root, cl["file"]))
    head = _heading(cl["section"], cl_text)
    if head is None:
        raise ReleaseError(f"{cl['file']} has no section '{cl['section']}'")
    level = len(cl["section"].strip()) - len(cl["section"].strip().lstrip("#"))
    body = _body(cl_text, head.end(), level)
    if not _has_entries(body):
        raise ReleaseError(f"the unreleased section of {cl['file']} is empty")
    result = {"current": current, "candidates": candidates, "suggested_bump": _suggested(body),
              "preview": body.strip()}
    if version_or_bump is None:
        return result
    nxt = candidates.get(version_or_bump) or version_or_bump
    if not SEMVER.match(nxt):
        raise ReleaseError(f"{nxt} is not X.Y.Z")
    if _tuple(nxt) <= _tuple(current):
        raise ReleaseError(f"{nxt} is not higher than {current}")
    if re.search(r"^## \[" + re.escape(nxt) + r"\]", cl_text, re.M):
        raise ReleaseError(f"{cl['file']} already has a heading for {nxt}")
    nl = "\r\n" if "\r\n" in cl_text else "\n"
    heading = f"## [{nxt}] - {date}"
    edits = {}
    for rel, _pattern, text, m in versions:
        edits[rel] = text[:m.start(1)] + nxt + text[m.end(1):]
    edits[cl["file"]] = cl_text[:head.end()] + nl + nl + heading + cl_text[head.end():]
    return {**result, "next": nxt, "files": [*edits], "heading": heading, "written": False,
            "edits": edits, "root": root, "profile": profile}


def _agree(profile: dict, root: Path, version: str) -> bool:
    try:
        if any(v[3].group(1) != version for v in _versions(profile, root)):
            return False
        cl = profile["docs"]["changelog"]
        return re.search(r"^## \[" + re.escape(version) + r"\]", _read(_inside(root, cl["file"])), re.M) is not None
    except ReleaseError:
        return False


def apply(prepared: dict) -> None:
    """Write the planned contents: temporary files first, then `os.replace`, then re-read and compare."""
    root = Path(prepared["root"])
    temps: list[tuple[str, Path]] = []
    try:
        for rel, content in prepared["edits"].items():
            target = _inside(root, rel)
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                fh.write(content.encode("utf-8"))
            os.chmod(tmp, target.stat().st_mode & 0o7777)
            temps.append((tmp, target))
        for tmp, target in temps:
            os.replace(tmp, target)
    finally:
        for tmp, _target in temps:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
    if not _agree(prepared["profile"], root, prepared["next"]):
        raise ReleaseError("the files do not agree after writing")
    prepared["written"] = True


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError(f"git {' '.join(args)} failed: {exc}")
    if r.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.returncode}")
    return r.stdout


def _changed_since(root: Path, merge_base: str) -> set[str]:
    names = set(_git(root, "diff", "--name-only", "--no-renames", merge_base).splitlines())
    for line in _git(root, "status", "--porcelain").splitlines():
        names.update(p.strip() for p in line[3:].split(" -> "))
    return names


def check(profile: dict, root: Path, version: str, base: str | None) -> list[str]:
    """The problems of a prepared release (empty when it is in order)."""
    root = Path(root)
    problems: list[str] = []
    if not SEMVER.match(version):
        return [f"{version} is not X.Y.Z"]
    try:
        for rel, _pattern, _text, m in _versions(profile, root):
            if m.group(1) != version:
                problems.append(f"{rel} has {m.group(1)}, not {version}")
    except ReleaseError as exc:
        problems.append(str(exc))
    cl = profile["docs"]["changelog"]
    try:
        text = _read(_inside(root, cl["file"]))
    except ReleaseError as exc:
        return [*problems, str(exc)]
    entry = re.search(r"^## \[" + re.escape(version) + r"\][^\r\n]*", text, re.M)
    if entry is None or not _has_entries(_body(text, entry.end(), 2)):
        problems.append(f"{cl['file']} has no non-empty entry for {version}")
    if _heading(cl["section"], text) is None:
        problems.append(f"{cl['file']} has no section '{cl['section']}'")
    if base is not None and not problems:
        problems += _base_problems(profile, root, base, version)
    return problems


def _diff_lines(diff: str) -> list[str]:
    """The added and removed lines of a one-file diff: everything after the first hunk header."""
    lines = diff.splitlines()
    first = next((i for i, line in enumerate(lines) if line.startswith("@@")), len(lines))
    return [line for line in lines[first:] if line[:1] in ("+", "-")]


def _base_problems(profile: dict, root: Path, base: str, version: str) -> list[str]:
    if base.startswith("-"):
        return [f"{base} is not a git ref"]
    cl_file = profile["docs"]["changelog"]["file"]
    files = {vf["path"]: vf["pattern"] for vf in profile["release"]["version_files"]}
    try:
        merge_base = _git(root, "merge-base", base, "HEAD").strip()
        changed = _changed_since(root, merge_base)
        problems = [f"{name} changed since {base}, but is neither the changelog nor a version file"
                    for name in sorted(changed - set(files) - {cl_file})]
        for rel, pattern in files.items():
            if rel not in changed:
                continue
            if not _git(root, "ls-files", "--", rel).strip():
                problems.append(f"{rel} is not tracked by git")
                continue
            for line in _diff_lines(_git(root, "diff", "-U0", "--no-renames", merge_base, "--", rel)):
                if not re.search(pattern, line[1:].rstrip("\r"), re.M):
                    problems.append(f"{rel}: the changed line {line!r} is not a version line")
            problems += _rebuild_problems(root, merge_base, rel, pattern, version)
        return problems
    except ReleaseError as exc:
        return [str(exc)]


def _rebuild_problems(root: Path, merge_base: str, rel: str, pattern: str, version: str) -> list[str]:
    """The file must equal its base content with only the version replaced (nothing else on any line)."""
    old = _git(root, "show", f"{merge_base}:{rel}")
    try:
        m = _span(rel, pattern, old)
    except ReleaseError as exc:
        return [f"{exc} at the base"]
    expected = old[:m.start(1)] + version + old[m.end(1):]
    if _read(_inside(root, rel)).replace("\r\n", "\n") != expected.replace("\r\n", "\n"):
        return [f"{rel} differs from its base content in more than the version"]
    return []


def _load(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ReleaseError(f"no profile at '{p}'")
    try:
        profile = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise ReleaseError(f"{p} is not valid YAML: {exc}")
    errors, _warnings, resolved = pv.validate(profile, None)
    if errors:
        raise ReleaseError("\n".join(f"toolkit.yaml: {e}" for e in errors))
    changelog = resolved.get("docs", {}).get("changelog")
    if "release" not in resolved:
        raise ReleaseError("the profile has no 'release' section")
    if not isinstance(changelog, dict) or "section" not in changelog:
        raise ReleaseError("the profile has no 'docs.changelog' with a 'section'")
    return resolved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="release_prepare.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--version", help="the version to release, X.Y.Z")
    ap.add_argument("--bump", choices=BUMPS, help="raise this part of the current version")
    ap.add_argument("--date", help="the release date, YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--write", action="store_true", help="apply the change")
    ap.add_argument("--check", action="store_true", help="verify a prepared release (needs --version)")
    ap.add_argument("--base", help="with --check: the ref the release branch started from")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    def usage(message: str) -> int:
        print(f"release-prepare: {message}", file=sys.stderr)
        return 2

    if args.version and args.bump:
        return usage("--version and --bump cannot be used together")
    if args.base and not args.check:
        return usage("--base needs --check")
    if args.check and not args.version:
        return usage("--check needs --version")
    if args.check and (args.write or args.bump):
        return usage("--check cannot be combined with --write or --bump")
    if args.date is not None:
        try:
            datetime.date.fromisoformat(args.date)
            valid = DATE.match(args.date)
        except ValueError:
            valid = None
        if not valid:
            return usage("--date must be YYYY-MM-DD")
    date = args.date or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    root = Path.cwd()
    try:
        profile = _load(args.profile)
        if args.check:
            problems = check(profile, root, args.version, args.base)
            for problem in problems:
                print(f"release-prepare: {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"release-prepare: ok {args.version}")
            return 0
        prepared = plan(profile, root, args.version or args.bump, date)
        if args.write and "next" in prepared:
            apply(prepared)
        elif args.write:
            return usage("--write needs --version or --bump")
    except ReleaseError as exc:
        print(f"release-prepare: {exc}", file=sys.stderr)
        return 1
    for key in ("edits", "root", "profile"):
        prepared.pop(key, None)
    print(json.dumps(prepared, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
