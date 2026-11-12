#!/usr/bin/env python3
"""Check and inventory a repository's docs index: the thin CLAUDE.md -> docs index -> leaf docs chain.

    docs_index.py check     [--profile .tld/toolkit.yaml] [--root .] [--index PATH] [--stale-days N]
                            [--max-claude-lines 60] [--max-index-lines 150] [--max-doc-lines 400]
                            [--strict] [--json]
    docs_index.py inventory [--profile .tld/toolkit.yaml] [--root .] [--index PATH] [--json]
    docs_index.py move SRC DST [--root .] [--profile .tld/toolkit.yaml] [--apply] [--exclude GLOB]... [--json]

`move` renames one file and rewrites every reference to it (markdown links, root path mentions, quoted
path expressions in .py files, and the paths in the profile, such as `docs.must_read` or `docs.index`);
it is a dry run unless --apply is given, and it reports mentions it cannot rewrite safely as
`unresolved:` lines. The other two modes never write anything.

`check` exits 1 on an error (and, with --strict, on a warning); 2 when it cannot run (no `docs.index`
in the profile and no --index). `inventory` always exits 0 and prints, for every markdown file under
the docs directory (the index's directory), its title, line count, first sentence, last change, and
who links to it, so a session can build or tidy the index without reading every doc.

Errors:  CLAUDE.md missing, too long, or not linking to the index; the index missing or too long;
         a broken relative link in CLAUDE.md or an index file; a doc no index file links to
         (transient docs named *-plan.md, *-plan-manual-steps.md|html, *-review.md and *-deviations.md,
         <plan_dir>/<n>/plan.md and deviations.md, the archive and archived directories, and the index files themselves excepted); an ADR the
         ADR index does not list (when the profile has `docs.adr_dir`).
Warnings: a broken link in another doc; a doc longer than --max-doc-lines; an index entry with no
         description; an index link listed twice; with --stale-days, a doc not changed in git for that
         many days (the cheapest cleanup signal; never an error).

Messages are one per line, "error: ..." or "warning: ...", and the last line is always
`docs index: <e> error(s), <w> warning(s)`; --json prints {"errors": [...], "warnings": [...]}.
`inventory --json` prints a list of objects with the keys path, title, lines, summary, age_days,
linked_from, in_index and plan; without --json it prints two lines per doc, marking [NOT IN INDEX].
Without `docs.index` in the profile and without --index both modes print
"toolkit.yaml: missing required key 'docs.index' (or pass --index)" to stderr and exit 2.

Index files are the index itself plus every README.md reachable from it by links (the ADR index is
one). Python 3.11+, stdlib and PyYAML, no network. `check` and `inventory` read files only.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

from tld.plan import manifest as vm  # noqa: E402

DEFAULT_PROFILE = ".tld/toolkit.yaml"
MAX_CLAUDE_LINES = 60
MAX_INDEX_LINES = 150
MAX_DOC_LINES = 400
ARCHIVE_DIRS = {"archive", "archived"}
PLAN_NAME = re.compile(r"-(plan|review|deviations)(-manual-steps)?\.(md|html)$")


def is_plan_record(rel: str, plan_dir: str) -> bool:
    """True for `<plan_dir>/<n>/plan.md` and `<plan_dir>/<n>/deviations.md` (rel: posix path from the root)."""
    return re.fullmatch(re.escape(plan_dir.strip("/")) + r"/[^/]+/(plan|deviations)\.md", rel) is not None


LINK = re.compile(r"\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
SCAN_SUFFIXES = (".md", ".py", ".yaml", ".yml", ".json", ".html", ".js", ".toml", ".txt", ".sh")
DEFAULT_EXCLUDES = (".git/**", "tests/fixtures/**", "evals/fixtures/**", ".tld/toolkit.yaml")
MAX_CHANGE_LINES = 200
MAX_UNRESOLVED_LINES = 50
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
    cfg = {"root": root, "index": None, "adr_dir": None, "adr_index": None, "plan_dir": "docs/plans"}
    profile = Path(args.profile) if args.profile else root / DEFAULT_PROFILE
    if profile.is_file():
        data = yaml.safe_load(profile.read_text()) or {}
        docs = data.get("docs", {}) if isinstance(data, dict) else {}
        cfg["index"] = docs.get("index")
        cfg["adr_dir"] = docs.get("adr_dir")
        cfg["adr_index"] = docs.get("adr_index")
        cfg["plan_dir"] = str(docs.get("plan_dir") or "docs/plans").rstrip("/")
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


def is_transient(cfg, d: Path) -> bool:
    """A plan, review or deviations file: never indexed, never size- or age-checked."""
    return bool(PLAN_NAME.search(d.name)) or is_plan_record(rel(cfg["root"], d), cfg["plan_dir"])


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
        if d in index_set or is_transient(cfg, d) or d in listed:
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
        if lines > args.max_doc_lines and not is_transient(cfg, d):
            warnings.append(f"{rel(root, d)}: {lines} lines, over {args.max_doc_lines}: split it so a reader "
                            "can open only the part they need")
        for n, _, target, _ in links_of(d):
            if not resolve(d, target).exists():
                warnings.append(f"{rel(root, d)}:{n}: broken link '{target}'")

    if args.stale_days:
        for d in docs:
            if is_transient(cfg, d):
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
            "plan": is_transient(cfg, d),
        })
    return out


# ---------------------------------------------------------------------------------------------- move
# An edit is (start, end, new text, rule) on a file's text; rules never overlap (earlier rules win).

def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"`[^`]*`", line)]


def _relative_to(dst: str, from_dir: str) -> str:
    return posixpath.relpath(dst, from_dir or ".")


def link_edits(text: str, file_old: str, file_new: str, src: str, dst: str, exists) -> list[tuple]:
    """Edits for rule 1: markdown links outside fenced code. `exists(repo path)` says whether a file exists."""
    edits, fenced, pos = [], False, 0
    old_dir, new_dir = posixpath.dirname(file_old), posixpath.dirname(file_new)
    moved_file = file_old == src
    for line in text.splitlines(keepends=True):
        base = pos
        pos += len(line)
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        spans = _code_spans(line)
        for m in LINK.finditer(line):
            if any(a < m.end() and m.start() < b for a, b in spans):
                continue
            raw = m.group(2)
            target, sep, anchor = raw.partition("#")
            if not target or SCHEME.match(target) or target.startswith("/"):
                continue
            resolved = posixpath.normpath(posixpath.join(old_dir, target))
            if resolved == src:
                new_target = _relative_to(dst, new_dir)
            elif moved_file and exists(resolved):
                new_target = _relative_to(resolved, new_dir)
            else:
                continue
            if new_target != target:
                edits.append((base + m.start(2), base + m.end(2), new_target + sep + anchor, "link"))
    return edits


def mention_pattern(src: str) -> re.Pattern:
    return re.compile(r"(?<![\w./-])" + re.escape(src) + r"(?![\w-]|\.\w)")


def mention_edits(text: str, src: str, dst: str) -> list[tuple]:
    """Edits for rule 2: root path mentions anywhere in the text, code spans and fences included."""
    return [(m.start(), m.end(), dst, "mention") for m in mention_pattern(src).finditer(text)]


def expression_edits(text: str, src: str, dst: str) -> list[tuple]:
    """Edits for rule 3: `"docs" / "hooks.md"` style path expressions (only the matching tail)."""
    segs = src.split("/")
    joiner = [r"(?P=q)(?P<sep>\s*/\s*)(?P=q)"] + [r"(?P=q)\s*/\s*(?P=q)"] * (len(segs) - 2)
    body = re.escape(segs[0])
    for j, seg in zip(joiner, segs[1:]):
        body += j + re.escape(seg)
    pattern = re.compile(r"(?P<q>[\"'])" + body + r"(?P=q)")
    edits = []
    for m in pattern.finditer(text):
        before = text[max(0, m.start() - 20):m.start()]
        if re.search(r"[\"']\s*/\s*$", before):
            continue
        q, sep = m.group("q"), m.groupdict().get("sep") or " / "
        new = sep.join(f"{q}{seg}{q}" for seg in dst.split("/"))
        edits.append((m.start(), m.end(), new, "expression"))
    return edits


def _apply(text: str, edits: list[tuple]) -> tuple[str, list[dict]]:
    changes = []
    for start, end, new, _ in sorted(edits, reverse=True):
        changes.append({"line": _line_of(text, start), "old": text[start:end], "new": new})
        text = text[:start] + new + text[end:]
    changes.reverse()
    return text, changes


def rewrite_links(text, file_old, file_new, src, dst, exists=lambda p: False):
    return _apply(text, link_edits(text, file_old, file_new, src, dst, exists))


def rewrite_root_mentions(text, src, dst):
    return _apply(text, mention_edits(text, src, dst))


def rewrite_path_expressions(text, src, dst):
    return _apply(text, expression_edits(text, src, dst))


def find_unresolved(text: str, src: str, covered=()) -> list[tuple[int, str, str]]:
    """(line, kind, message) for mentions the rules cannot rewrite; `covered` are spans already handled."""
    found = []
    name = posixpath.basename(src)
    bare = re.compile(r"(?<![\w./-])" + re.escape(name) + r"(?![\w-]|\.\w)")
    url = re.compile(r"(?<=/)" + re.escape(src) + r"(?![\w-]|\.\w)")
    for m in bare.finditer(text):
        if not any(a <= m.start() < b for a, b in covered):
            found.append((_line_of(text, m.start()), "bare", f"mentions '{name}' without its directory"))
    for m in url.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if "http" in text[line_start:line_end if line_end >= 0 else len(text)]:
            found.append((_line_of(text, m.start()), "url", f"URL mentions '{src}'"))
    return sorted(found)


def plan_file(text: str, rel_path: str, src: str, dst: str, exists) -> tuple[str, list[dict], list[tuple]]:
    """The new text, the changes and the unresolved mentions of one file."""
    file_new = dst if rel_path == src else rel_path
    edits = link_edits(text, rel_path, file_new, src, dst, exists) if rel_path.endswith(".md") else []
    covered = [(m.start(), m.end()) for m in LINK.finditer(text)
               if posixpath.normpath(posixpath.join(posixpath.dirname(rel_path),
                                                    m.group(2).partition("#")[0] or "\0")) == src]
    extra = mention_edits(text, src, dst)
    if rel_path.endswith(".py"):
        extra += expression_edits(text, src, dst)
    for e in extra:
        if not any(e[0] < b[1] and b[0] < e[1] for b in edits):
            edits.append(e)
    covered += [(e[0], e[1]) for e in extra]
    new_text, changes = _apply(text, edits)
    return new_text, changes, find_unresolved(text, src, covered)


def tracked_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode().split("\0") if p]


def scanned_files(root: Path, excludes) -> list[str]:
    files = tracked_files(root)
    if files is None:
        files = []
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            files += [os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, "/") for n in names]
    keep = []
    for f in sorted(files):
        if not f.endswith(SCAN_SUFFIXES) or PLAN_NAME.search(posixpath.basename(f)):
            continue
        if any(vm.path_matches(f, g) for g in (*DEFAULT_EXCLUDES, *excludes)):
            continue
        if (root / f).is_file():
            keep.append(f)
    return keep


def is_tracked(root: Path, rel_path: str) -> bool:
    if not (root / ".git").exists():
        return False
    return subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel_path],
                          capture_output=True).returncode == 0


def run_move(args) -> int:
    root = Path(args.root).resolve()
    src, dst = posixpath.normpath(args.src), posixpath.normpath(args.dst)
    if not (root / src).is_file():
        print(f"move: '{args.src}' is not a file", file=sys.stderr)
        return 1
    if os.path.lexists(root / dst):
        print(f"move: '{args.dst}' already exists", file=sys.stderr)
        return 1
    exists = lambda p: (root / p).is_file()  # noqa: E731
    plans, changes, unresolved = {}, [], []
    scanned = scanned_files(root, args.exclude)
    for f in scanned:
        text = (root / f).read_text(errors="replace")
        new_text, ch, un = plan_file(text, f, src, dst, exists)
        for c in ch:
            changes.append({"file": f, **c})
        for line, kind, msg in un:
            unresolved.append({"file": f, "line": line, "kind": kind, "message": msg})
        if ch:
            plans[f] = new_text
    profile = Path(args.profile) if args.profile else root / DEFAULT_PROFILE
    if not profile.is_absolute():
        profile = root / profile
    prof_rel = os.path.relpath(profile, root).replace(os.sep, "/")
    if profile.is_file() and prof_rel not in scanned:
        text = profile.read_text(errors="replace")
        new_text, ch = _apply(text, mention_edits(text, src, dst))
        for c in ch:
            changes.append({"file": prof_rel, **c})
        if ch:
            plans[prof_rel] = new_text
    n_files = len({c["file"] for c in changes})
    summary = (f"{len(changes)} reference(s) in {n_files} file(s) would change, {len(unresolved)} unresolved"
               if not args.apply else None)

    if args.apply:
        made = []
        missing = (root / dst).parent
        while not missing.exists() and missing != root:
            made.append(missing)
            missing = missing.parent
        (root / dst).parent.mkdir(parents=True, exist_ok=True)
        error = None
        if is_tracked(root, src):
            proc = subprocess.run(["git", "-C", str(root), "mv", "--", src, dst], capture_output=True, text=True)
            if proc.returncode != 0:
                error = f"git mv failed: {(proc.stderr or proc.stdout).strip()}"
        elif os.path.lexists(root / dst):
            error = f"'{args.dst}' already exists"
        else:
            os.rename(root / src, root / dst)
        if error:
            for d in made:
                try:
                    d.rmdir()
                except OSError:
                    pass
            print(f"move: {error}", file=sys.stderr)
            return 1
        for f, new_text in plans.items():
            (root / (dst if f == src else f)).write_text(new_text)
        parent = (root / src).parent
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        summary = (f"moved {src} -> {dst}, rewrote {len(changes)} reference(s) in {n_files} file(s), "
                   f"{len(unresolved)} unresolved")

    if args.json:
        print(json.dumps({"src": src, "dst": dst, "applied": bool(args.apply), "changes": changes,
                          "unresolved": unresolved, "summary": f"move: {summary}"}, indent=2))
        return 0
    if not args.apply:
        print(f"move {src} -> {dst}")
        for c in changes[:MAX_CHANGE_LINES]:
            print(f"would rewrite {c['file']}:{c['line']}: {c['old']} -> {c['new']}")
        if len(changes) > MAX_CHANGE_LINES:
            print(f"and {len(changes) - MAX_CHANGE_LINES} more")
    for u in unresolved[:MAX_UNRESOLVED_LINES]:
        print(f"unresolved: {u['file']}:{u['line']}: {u['message']}")
    if len(unresolved) > MAX_UNRESOLVED_LINES:
        print(f"and {len(unresolved) - MAX_UNRESOLVED_LINES} more")
    print(f"move: {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "inventory"):
        p = sub.add_parser(name)
        p.add_argument("--profile", help=f"profile path (default {DEFAULT_PROFILE} under --root)")
        p.add_argument("--root", default=".", help="repository root (default: the current directory)")
        p.add_argument("--index", help="docs index path relative to --root (overrides docs.index)")
        p.add_argument("--json", action="store_true")
    mv = sub.add_parser("move", help="move a doc and rewrite every reference (dry run unless --apply)")
    mv.add_argument("src", metavar="SRC", help="repo-relative path of the file to move")
    mv.add_argument("dst", metavar="DST", help="repo-relative destination path (must not exist)")
    mv.add_argument("--root", default=".", help="repository root (default: the current directory)")
    mv.add_argument("--profile", help=f"profile whose paths are rewritten too (default {DEFAULT_PROFILE} under --root)")
    mv.add_argument("--apply", action="store_true", help="perform the move and the rewrites (default: dry run)")
    mv.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                    help="skip files matching this glob (repeatable; added to the default excludes)")
    mv.add_argument("--json", action="store_true")
    c = sub.choices["check"]
    c.add_argument("--stale-days", type=int, default=0, help="warn about docs unchanged in git for this many days")
    c.add_argument("--max-claude-lines", type=int, default=MAX_CLAUDE_LINES)
    c.add_argument("--max-index-lines", type=int, default=MAX_INDEX_LINES)
    c.add_argument("--max-doc-lines", type=int, default=MAX_DOC_LINES)
    c.add_argument("--strict", action="store_true", help="exit 1 on a warning too")
    args = ap.parse_args(argv)
    if args.cmd == "move":
        return run_move(args)
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
