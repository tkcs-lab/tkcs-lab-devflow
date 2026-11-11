#!/usr/bin/env python3
"""Scan a repository for documentation facts (input to /setup).

Usage: tld profile survey-docs [ROOT]

Prints the result of `scan(ROOT)` (default `.`) as JSON, 2-space indented: the must-read files, the
docs index (`docs/README.md` or `docs/index.md`), the decision-record directory and its index, the changelog and its unreleased heading, and the
documentation website (directory, tool, build and link-check commands).

Exit 0 ok; 1 ROOT is not a directory (`survey_docs: <message>`).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "build", "dist", "Pods", ".build",
             "__pycache__", "DerivedData"}
MUST_READ = ["README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "SECURITY.md"]
ADR_DIRS = ["docs/adr", "docs/adrs", "docs/decisions", "doc/adr", "adr"]
INDEXES = ["docs/README.md", "docs/index.md"]
CHANGELOGS = ["CHANGELOG.md", "CHANGES.md", "HISTORY.md"]
UNRELEASED = re.compile(r"^##\s+\[?Unreleased\]?")
LINK_SCRIPT = re.compile(r"^(check[-:_]?links?|link[-:_]?check|linkcheck|links)$")
# (config file relative to the directory, tool, file that must sit beside it or None)
CONFIGS = [
    ("docusaurus.config.js", "docusaurus", None),
    ("docusaurus.config.ts", "docusaurus", None),
    ("mkdocs.yml", "mkdocs", None),
    ("astro.config.mjs", "astro", None),
    ("astro.config.js", "astro", None),
    ("astro.config.ts", "astro", None),
    (".vitepress/config.js", "vitepress", None),
    (".vitepress/config.ts", "vitepress", None),
    (".vitepress/config.mjs", "vitepress", None),
    ("_config.yml", "jekyll", None),
    ("hugo.toml", "hugo", None),
    ("hugo.yaml", "hugo", None),
    ("config.toml", "hugo", "content"),
    ("conf.py", "sphinx", "index.rst"),
]
TOOL_BUILD = {"mkdocs": "mkdocs build --strict", "jekyll": "bundle exec jekyll build",
              "hugo": "hugo --minify", "sphinx": "sphinx-build -b html . _build/html"}


def _scripts(directory: Path) -> dict:
    try:
        data = json.loads((directory / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def _find_config(directory: Path) -> tuple[str, str] | None:
    for rel, tool, beside in CONFIGS:
        if (directory / rel).is_file() and (beside is None or (directory / beside).exists()):
            return rel, tool
    return None


def _website(root: Path) -> dict | None:
    dirs = [(".", root)]
    try:
        names = sorted(p.name for p in root.iterdir()
                       if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith("."))
    except OSError:
        names = []
    dirs += [(n, root / n) for n in names]
    for label, directory in dirs:
        found = _find_config(directory)
        if not found:
            continue
        rel, tool = found
        scripts = _scripts(directory)
        build = "npm run build" if "build" in scripts else TOOL_BUILD.get(tool)
        links = next((f"npm run {k}" for k in scripts if LINK_SCRIPT.match(k)), None)
        evidence = rel if label == "." else f"{label}/{rel}"
        return {"dir": label, "tool": tool, "build": build, "links": links, "evidence": [evidence]}
    return None


def _changelog(root: Path) -> dict | None:
    for name in CHANGELOGS:
        path = root / name
        if path.is_file():
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                lines = []
            section = next((ln.strip() for ln in lines if UNRELEASED.match(ln)), None)
            return {"file": name, "section": section}
    return None


def scan(root: Path) -> dict:
    root = Path(root)
    must_read = [n for n in MUST_READ if (root / n).is_file()]
    docs = root / "docs"
    if docs.is_dir():
        extra = {p.relative_to(root).as_posix() for pat in ("design*.md", "architecture*.md")
                 for p in docs.glob(pat) if p.is_file()}
        must_read += sorted(extra)
    adr_dir = next((d for d in ADR_DIRS if (root / d).is_dir()), None)
    adr_index = None
    if adr_dir:
        adr_index = next((f"{adr_dir}/{n}" for n in ("README.md", "index.md")
                          if (root / adr_dir / n).is_file()), None)
    index = next((n for n in INDEXES if (root / n).is_file()), None)
    return {"must_read": must_read, "index": index, "adr_dir": adr_dir, "adr_index": adr_index,
            "changelog": _changelog(root), "website": _website(root)}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(".")
    if not root.is_dir():
        print(f"survey_docs: {root} is not a directory", file=sys.stderr)
        return 1
    print(json.dumps(scan(root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
