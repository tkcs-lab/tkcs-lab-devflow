#!/usr/bin/env python3
"""Scan a repository for the facts setup proposes as profile values (input to /setup).

Usage: survey_repo.py [ROOT]  (called by survey.py; not a registered tld command)

Prints `scan(ROOT)` (default `.`) as JSON, 2-space indented, with the keys:

- `codeowners`: the `@login` tokens of `.github/CODEOWNERS`, `CODEOWNERS` or `docs/CODEOWNERS` (the
  first file that exists), in order of first appearance, without duplicates. `@org/team` tokens and
  email addresses are skipped; the bot (`bot=` argument) is never listed.
- `version_files`: `{path, pattern}` for every file whose version line is found: `pyproject.toml`
  (`^version = "..."`), `package.json` (`^\\s*"version": "..."`), `Cargo.toml` (`^version = "..."`
  inside `[package]`).
- `deps_audit`: `{ecosystem, run, cwd?}` entries: pip-audit for a runtime lockfile, `npm audit` for
  each directory with a `package-lock.json`, `govulncheck` for a `go.mod`.
- `lock_freshness`: one `{when, run, lockfiles}` entry only when a `scripts/*lock*.sh` exists and the
  manifests and lockfiles are found (`when`: manifests at the root; `lockfiles`: lock files found).
- `adr_bar`: `CONTRIBUTING.md#<anchor>` of the first heading that names decisions or ADRs, else null.

Read-only. Files are untrusted data: reads are bounded, content is only matched, nothing found in a
file is ever run. Exit 0 ok; 1 ROOT is not a directory (`survey_repo: <message>`).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "build", "dist", "Pods", ".build",
             "__pycache__", "DerivedData"}
MAX_BYTES = 200000
MAX_FILES = 5000
MAX_DEPTH = 4
CODEOWNERS_FILES = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
LOGIN = re.compile(r"^@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))$")
PYPROJECT_VERSION = r'^version = "([^"]+)"'
PACKAGE_VERSION = r'^\s*"version": "([^"]+)"'
CARGO_VERSION = r'^version = "([^"]+)"'
LOCK_REQUIREMENTS = re.compile(r"^requirements/.+\.lock\.txt$|^requirements[^/]*\.txt$")
ADR_HEADING = re.compile(r"\b(adrs?|decisions?)\b", re.I)


def _read(path: Path) -> str | None:
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _walk(root: Path):
    """Yield (relative posix path) of files under root, skipping SKIP_DIRS, bounded in count and depth."""
    count = 0
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_symlink():
                continue
            if p.is_dir():
                if p.name not in SKIP_DIRS and depth < MAX_DEPTH:
                    stack.append((p, depth + 1))
            elif p.is_file():
                count += 1
                if count > MAX_FILES:
                    return
                yield p.relative_to(root).as_posix()


def _codeowners(root: Path, bot: str | None) -> list[str]:
    for name in CODEOWNERS_FILES:
        text = _read(root / name)
        if text is None:
            continue
        out: list[str] = []
        for line in text.splitlines():
            line = line.split("#", 1)[0]
            for token in line.split()[1:]:  # the first token is the path pattern
                m = LOGIN.match(token)
                if not m:
                    continue
                login = m.group(1)
                if bot and login.lower() == bot.lower():
                    continue
                if login not in out:
                    out.append(login)
        return out
    return []


def _cargo_package_version(text: str) -> bool:
    in_package = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_package = s == "[package]"
        elif in_package and re.match(CARGO_VERSION, line):
            return True
    return False


def _version_files(root: Path) -> list[dict]:
    found: list[dict] = []
    text = _read(root / "pyproject.toml")
    if text is not None and re.search(PYPROJECT_VERSION, text, re.M):
        found.append({"path": "pyproject.toml", "pattern": PYPROJECT_VERSION})
    text = _read(root / "package.json")
    if text is not None and re.search(PACKAGE_VERSION, text, re.M):
        found.append({"path": "package.json", "pattern": PACKAGE_VERSION})
    text = _read(root / "Cargo.toml")
    if text is not None and _cargo_package_version(text):
        found.append({"path": "Cargo.toml", "pattern": CARGO_VERSION})
    return found


def _deps_audit(root: Path, files: list[str]) -> list[dict]:
    out: list[dict] = []
    locks = sorted(f for f in files if LOCK_REQUIREMENTS.match(f))
    if locks:
        preferred = [f for f in locks if f.endswith(".lock.txt")] or locks
        runtime = next((f for f in preferred if "dev" not in Path(f).name), preferred[0])
        out.append({"ecosystem": "pip", "run": f"pip-audit --strict -r {runtime}"})
    for f in files:
        name = Path(f).name
        folder = Path(f).parent.as_posix()
        if name == "package-lock.json":
            entry = {"ecosystem": "npm", "run": "npm audit --omit=dev --audit-level=high"}
            if folder != ".":
                entry["cwd"] = folder
            out.append(entry)
        elif name == "go.mod":
            entry = {"ecosystem": "go", "run": "govulncheck ./..."}
            if folder != ".":
                entry["cwd"] = folder
            out.append(entry)
    return out


MANIFESTS = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml")
LOCKFILES = re.compile(r"^(requirements/.+\.lock\.txt|requirements[^/]*\.lock|poetry\.lock|uv\.lock|"
                       r"package-lock\.json|go\.sum|Cargo\.lock)$")


def _lock_freshness(files: list[str]) -> list[dict]:
    """One entry when a `scripts/*lock*.sh` exists and the manifests and lockfiles it concerns are known."""
    scripts = sorted(f for f in files if re.match(r"^scripts/[^/]*lock[^/]*\.sh$", f))
    when = [m for m in MANIFESTS if m in files]
    lockfiles = sorted(f for f in files if LOCKFILES.match(f))
    if not scripts or not when or not lockfiles:
        return []
    return [{"when": when, "run": f"bash {scripts[0]}", "lockfiles": lockfiles}]


def _anchor(heading: str) -> str:
    text = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s", "-", text)


def _adr_bar(root: Path) -> str | None:
    text = _read(root / "CONTRIBUTING.md")
    if text is None:
        return None
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if m and ADR_HEADING.search(m.group(1)):
            return f"CONTRIBUTING.md#{_anchor(m.group(1))}"
    return None


def scan(root, bot: str | None = None) -> dict:
    root = Path(root)
    files = sorted(_walk(root))
    return {
        "codeowners": _codeowners(root, bot),
        "version_files": _version_files(root),
        "deps_audit": _deps_audit(root, files),
        "lock_freshness": _lock_freshness(files),
        "adr_bar": _adr_bar(root),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(".")
    if not root.is_dir():
        print(f"survey_repo: {root} is not a directory", file=sys.stderr)
        return 1
    print(json.dumps(scan(root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
