#!/usr/bin/env python3
"""Pick the newest eligible release tag.

Usage: pick_release.py --pattern REGEX [--lines] [FILE|-]

Input is a JSON list of {"tag": str, "prerelease": bool (default false)}, or, with --lines, text
where every line is a bare tag or raw `git ls-remote --tags` output (`<sha>\\trefs/tags/<tag>`;
`^{}` lines are dropped). A tag is eligible when it matches the pattern, is not marked prerelease
and is stable (after an optional leading v or V only digits and dots). Prints the eligible tag with
the highest version (numeric, dot-separated parts, missing parts count as 0).

Exit 0 ok; 1 bad input or pattern (`pick_release: <message>`); 3 `pick_release: no eligible release`.
"""
import argparse
import json
import re
import sys

STABLE = re.compile(r"^[vV]?[0-9]+(\.[0-9]+)*$")


class PickError(Exception):
    """Bad input or pattern (exit 1)."""


class NoRelease(Exception):
    """No eligible release (exit 3)."""


def parse_json(text):
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PickError(f"input is not valid JSON ({exc})")
    if not isinstance(data, list):
        raise PickError("input must be a JSON list")
    entries = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("tag"), str):
            raise PickError(f"item {i} must be an object with a string 'tag'")
        pre = item.get("prerelease", False)
        if not isinstance(pre, bool):
            raise PickError(f"item {i}: 'prerelease' must be true or false")
        entries.append({"tag": item["tag"], "prerelease": pre})
    return entries


def parse_lines(text):
    entries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.endswith("^{}"):
            continue
        if "refs/tags/" in line:
            line = line.split("refs/tags/", 1)[1]
        entries.append({"tag": line.strip(), "prerelease": False})
    return entries


def _key(tag):
    parts = [int(p) for p in tag.lstrip("vV").split(".")]
    while parts and parts[-1] == 0:  # missing parts count as 0, so 1.0 == 1.0.0
        parts.pop()
    return tuple(parts)


def choose(entries, pattern):
    """Return the highest eligible tag; raise PickError or NoRelease."""
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise PickError(f"pattern does not compile ({exc})")
    best = None
    for e in entries:
        tag = e["tag"]
        if e["prerelease"] or not STABLE.match(tag) or not rx.search(tag):
            continue
        key = _key(tag)
        if best is None or (key, tag) > best:
            best = (key, tag)
    if best is None:
        raise NoRelease("no eligible release")
    return best[1]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pick_release.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--pattern", required=True, help="regular expression a tag must match")
    ap.add_argument("--lines", action="store_true", help="input is text lines, not JSON")
    ap.add_argument("file", nargs="?", default="-", help="input file, or - for stdin")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        entries = parse_lines(text) if args.lines else parse_json(text)
        print(choose(entries, args.pattern))
    except OSError as exc:
        print(f"pick_release: {exc}", file=sys.stderr)
        return 1
    except PickError as exc:
        print(f"pick_release: {exc}", file=sys.stderr)
        return 1
    except NoRelease:
        print("pick_release: no eligible release", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
