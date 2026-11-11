#!/usr/bin/env python3
"""Check and inventory a repository's docs index: the thin CLAUDE.md -> docs index -> leaf docs chain.

    docs_index.py check     [--profile .claude/toolkit.yaml] [--root .] [--index PATH] [--stale-days N]
                            [--max-claude-lines 60] [--max-index-lines 150] [--max-doc-lines 400]
                            [--strict] [--json]
    docs_index.py inventory [--profile .claude/toolkit.yaml] [--root .] [--index PATH] [--json]

`check` exits 1 on an error (and, with --strict, on a warning); 2 when it cannot run (no `docs.index`
in the profile and no --index). `inventory` always exits 0 and prints, for every markdown file under
the docs directory (the index's directory), its title, line count, first sentence, last change, and
who links to it, so a session can build or tidy the index without reading every doc.

Errors:  CLAUDE.md missing, too long, or not linking to the index; the index missing or too long;
         a broken relative link in CLAUDE.md or an index file; a doc no index file links to
         (plan documents, the archive directory and the index files themselves excepted); an ADR the
         ADR index does not list (when the profile has `docs.adr_dir`).
Warnings: a broken link in another doc; a doc longer than --max-doc-lines; an index entry with no
         description; an index link listed twice; with --stale-days, a doc not changed in git for that
         many days (the cheapest cleanup signal; never an error).

Index files are the index itself plus every README.md reachable from it by links (the ADR index is
one). Python 3.11+, stdlib and PyYAML, no network. Reads files only; it never writes anything.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

DEFAULT_PROFILE = ".claude/toolkit.yaml"
MAX_CLAUDE_LINES = 60
MAX_INDEX_LINES = 150
MAX_DOC_LINES = 400
ARCHIVE_DIRS = {"archive", "archived"}
PLAN_NAME = re.compile(r"-plan(-manual-steps)?\.(md|html)$")
LINK = re.compile(r"\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
MIN_DESCRIPTION = 12  # characters outside the link text on an index line


def strip_code(text: str, inline: bool = True) -> list[tuple[int, str]]:
    """(line number, line) pairs outside fenced code blocks; inline code removed unless inline=False."""
    out, fenced = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.append((n, re.sub(r"`[^`]*`", "", line) if inline else line))
    return out


def links_of(path: Path) -> list[tuple[int, str, str, str]]:
    """(line, text, target, line text) for every relative link in a markdown file."""
    found = []
    for n, line in strip_code(path.read_text(errors="replace")):
        for m in LINK.finditer(line):
            target = m.group(2).split("#")[0]
            if not target or SCHEME.match(target) or target.startswith("/"):
                continue
            found.append((n, m.group(1), target, line))
    return found


def resolve(path: Path, target: str) -> Path:
    return (path.parent / target).resolve()


def load_config(args) -> dict:
    root = Path(args.root).resolve()
    cfg = {"root": root, "index": None, "adr_dir": None, "adr_index": None}
    profile = Path(args.profile) if args.profile else root / DEFAULT_PROFILE
    if profile.is_file():
        data = yaml.safe_load(profile.read_text()) or {}
        docs = data.get("docs", {}) if isinstance(data, dict) else {}
        cfg["index"] = docs.get("index")
        cfg["adr_dir"] = docs.get("adr_dir")
        cfg["adr_index"] = docs.get("adr_index")
    if args.index:
        cfg["index"] = args.index
    if not cfg["index"]:
        print("toolkit.yaml: missing required key 'docs.index' (or pass --index)", file=sys.stderr)
        raise SystemExit(2)
    cfg["index"] = (root / cfg["index"]).resolve()
    cfg["docs_dir"] = cfg["index"].parent
    return cfg


def git_age_days(root: Path, path: Path):
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%ct", "--", str(path)],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return None if not out else (time.time() - int(out)) / 86400


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def docs_under(cfg) -> list[Path]:
    return sorted(p for p in cfg["docs_dir"].rglob("*.md")
                  if p.is_file() and not (ARCHIVE_DIRS & set(p.relative_to(cfg["docs_dir"]).parts[:-1])))


def index_files(cfg) -> list[Path]:
    """The index plus every README.md reachable from it through links (breadth first)."""
    seen, queue = [], [cfg["index"]]
    while queue:
        cur = queue.pop(0)
        if cur in seen or not cur.is_file():
            continue
        seen.append(cur)
        for _, _, target, _ in links_of(cur):
            nxt = resolve(cur, target)
            if nxt.name == "README.md" and nxt.suffix == ".md":
                queue.append(nxt)
    return seen


def check(cfg, args) -> tuple[list[str], list[str]]:
    root, index = cfg["root"], cfg["index"]
    errors: list[str] = []
    warnings: list[str] = []

    claude = root / "CLAUDE.md"
    if not claude.is_file():
        errors.append("CLAUDE.md: missing (a thin CLAUDE.md that points to the docs index is required)")
    else:
        n = len(claude.read_text().splitlines())
        if n > args.max_claude_lines:
            errors.append(f"CLAUDE.md: {n} lines, over {args.max_claude_lines}: it is loaded in every session, "
                          "move the detail into docs/ and link the index")
        if index not in {resolve(claude, t) for _, _, t, _ in links_of(claude)}:
            errors.append(f"CLAUDE.md: does not link to the docs index ({rel(root, index)})")
        for n, _, target, _ in links_of(claude):
            if not resolve(claude, target).exists():
                errors.append(f"CLAUDE.md:{n}: broken link '{target}'")

    if not index.is_file():
        errors.append(f"{rel(root, index)}: the docs index is missing")
        return errors, warnings
    n = len(index.read_text().splitlines())
    if n > args.max_index_lines:
        errors.append(f"{rel(root, index)}: {n} lines, over {args.max_index_lines}: split the long sections "
                      "into a README.md per directory and link them from the index")

    idx_files = index_files(cfg)
    listed: set[Path] = set()
    for f in idx_files:
        seen_targets: set[Path] = set()
        for n, text, target, line in links_of(f):
            dest = resolve(f, target)
            if not dest.exists():
                errors.append(f"{rel(root, f)}:{n}: broken link '{target}'")
                continue
            listed.add(dest)
            is_entry = bool(re.match(r"\s*([-*+]|\d+\.|\|)", line))
            if is_entry and dest.is_file():
                if dest in seen_targets:
                    warnings.append(f"{rel(root, f)}:{n}: '{target}' is listed twice in this file")
                seen_targets.add(dest)
                rest = LINK.sub("", line)
                rest = re.sub(r"[\s|*_\-–—:.,;()`>]+", " ", rest).strip()
                if len(rest) < MIN_DESCRIPTION:
                    warnings.append(f"{rel(root, f)}:{n}: '{target}' has no description "
                                    "(say what it answers and when to read it)")

    docs = docs_under(cfg)
    index_set = set(idx_files)
    for d in docs:
        if d in index_set or PLAN_NAME.search(d.name) or d in listed:
            continue
        errors.append(f"{rel(root, d)}: not listed in the docs index (add a row, or move it to archive/)")

    adr_dir = cfg["adr_dir"]
    if adr_dir:
        adr_path = (root / adr_dir).resolve()
        adr_index = (root / cfg["adr_index"]).resolve() if cfg["adr_index"] else None
        if adr_index and adr_index.is_file() and adr_path.is_dir():
            adr_listed = {resolve(adr_index, t) for _, _, t, _ in links_of(adr_index)}
            for p in sorted(adr_path.glob("*.md")):
                if p.resolve() != adr_index and p.name.lower() != "readme.md" and p.resolve() not in adr_listed:
                    errors.append(f"{rel(root, p)}: not listed in the ADR index ({rel(root, adr_index)})")

    for d in docs:
        if d in index_set:
            continue
        lines = len(d.read_text(errors="replace").splitlines())
        if lines > args.max_doc_lines and not PLAN_NAME.search(d.name):
            warnings.append(f"{rel(root, d)}: {lines} lines, over {args.max_doc_lines}: split it so a reader "
                            "can open only the part they need")
        for n, _, target, _ in links_of(d):
            if not resolve(d, target).exists():
                warnings.append(f"{rel(root, d)}:{n}: broken link '{target}'")

    if args.stale_days:
        for d in docs:
            if PLAN_NAME.search(d.name):
                continue
            age = git_age_days(root, d)
            if age is not None and age > args.stale_days:
                warnings.append(f"{rel(root, d)}: not changed for {int(age)} days: confirm it is current, "
                                "or move it to archive/")
    return errors, warnings


def first_sentence(text: str) -> str:
    body = []
    for _, line in strip_code(text, inline=False):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith("---") or s.startswith(">") and not body:
            if body:
                break
            continue
        body.append(s)
    para = LINK.sub(lambda m: m.group(1), " ".join(body))
    m = re.match(r"(.{20,240}?[.!?])(\s|$)", para)
    return (m.group(1) if m else para[:200]).strip()


def inventory(cfg) -> list[dict]:
    root = cfg["root"]
    idx_files = index_files(cfg)
    inbound: dict[Path, list[str]] = {}
    scan = [root / "CLAUDE.md", *docs_under(cfg)]
    for f in scan:
        if f.is_file():
            for _, _, target, _ in links_of(f):
                inbound.setdefault(resolve(f, target), []).append(rel(root, f))
    listed = {resolve(f, t) for f in idx_files for _, _, t, _ in links_of(f)}
    out = []
    for d in docs_under(cfg):
        text = d.read_text(errors="replace")
        title = next((m.group(1).strip() for m in re.finditer(r"^#\s+(.+)$", text, re.M)), d.stem)
        age = git_age_days(root, d)
        out.append({
            "path": rel(root, d),
            "title": title,
            "lines": len(text.splitlines()),
            "summary": first_sentence(text),
            "age_days": None if age is None else int(age),
            "linked_from": sorted(set(inbound.get(d, []))),
            "in_index": d in listed or d in idx_files,
            "plan": bool(PLAN_NAME.search(d.name)),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "inventory"):
        p = sub.add_parser(name)
        p.add_argument("--profile", help=f"profile path (default {DEFAULT_PROFILE} under --root)")
        p.add_argument("--root", default=".", help="repository root (default: the current directory)")
        p.add_argument("--index", help="docs index path relative to --root (overrides docs.index)")
        p.add_argument("--json", action="store_true")
    c = sub.choices["check"]
    c.add_argument("--stale-days", type=int, default=0, help="warn about docs unchanged in git for this many days")
    c.add_argument("--max-claude-lines", type=int, default=MAX_CLAUDE_LINES)
    c.add_argument("--max-index-lines", type=int, default=MAX_INDEX_LINES)
    c.add_argument("--max-doc-lines", type=int, default=MAX_DOC_LINES)
    c.add_argument("--strict", action="store_true", help="exit 1 on a warning too")
    args = ap.parse_args(argv)
    cfg = load_config(args)

    if args.cmd == "inventory":
        items = inventory(cfg)
        if args.json:
            print(json.dumps(items, indent=2))
        else:
            for i in items:
                flag = "" if i["in_index"] or i["plan"] else "  [NOT IN INDEX]"
                age = "" if i["age_days"] is None else f", {i['age_days']}d"
                print(f"{i['path']} ({i['lines']} lines{age}){flag}\n    {i['title']}: {i['summary']}")
        return 0

    errors, warnings = check(cfg, args)
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    else:
        for e in errors:
            print(f"error: {e}")
        for w in warnings:
            print(f"warning: {w}")
        print(f"docs index: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
