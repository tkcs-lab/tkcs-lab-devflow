#!/usr/bin/env python3
"""Scan a repository for security, UI and test signals (input to /setup).

Usage: survey_signals.py [ROOT]

Prints the result of `scan(ROOT)` (default `.`) as JSON, 2-space indented: source and Markdown file
counts, the security categories (auth, crypto, credentials, egress, user_data, policy_docs) with the
categories that fire and their count as `score`, the UI files and their globs, and the test levels
found. Skipped directories, the 5000-file cap and the 200000-byte read limit are in the constants.

Exit 0 ok; 1 ROOT is not a directory (`survey_signals: <message>`).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "build", "dist", "Pods", ".build",
             "__pycache__", "DerivedData"}
MAX_FILES = 5000
MAX_BYTES = 200000
LIST_CUT = 20
EVIDENCE_CUT = 5
SOURCE_EXT = {".py", ".go", ".swift", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".rb", ".rs", ".c",
              ".cpp", ".m", ".php", ".cs", ".vue", ".svelte"}
UI_EXT = {".tsx", ".jsx", ".vue", ".svelte", ".xib", ".storyboard"}
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}
TEST_NAMES = ("test_*.py", "*_test.go", "*.test.*", "*.spec.*", "*Tests.swift")
E2E_DIRS = {"e2e", "end-to-end", "playwright", "cypress"}
INTEGRATION_DIRS = {"integration", "integrations", "contract", "contracts"}

CATEGORIES = {
    "auth": r"\b(oauth|jwt|login|authenticat\w*|authoriz\w*)\b",
    "crypto": r"\b(encrypt\w*|decrypt\w*|hmac|aes|rsa|cipher\w*|keychain)\b",
    "credentials": r"\b(password|passwd|api[_-]?key|secret[_-]?key|credential\w*)\b",
    "egress": (r"(\brequests\.(get|post|put)\b|\burllib\.request\b|\bhttpx\b|\burlsession\b"
               r"|\bnet/http\b|\baxios\b|\bfetch\()"),
    "user_data": r"\b(pii|gdpr|personal data|personally identifiable)\b",
}
PATTERNS = {name: re.compile(rx, re.I) for name, rx in CATEGORIES.items()}
POLICY_NAME = re.compile(r"threat[-_ ]?model|security[-_ ]?model", re.I)
ORDER = ["auth", "crypto", "credentials", "egress", "user_data", "policy_docs"]
SWIFT_UI = re.compile(r"import (SwiftUI|UIKit)")


def _walk(root: Path) -> list[str]:
    """Repo-relative POSIX paths of the files visited, in walk order, at most MAX_FILES."""
    found: list[str] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if len(found) >= MAX_FILES:
                return found
            found.append((Path(base) / name).relative_to(root).as_posix())
    return found


def _is_test_path(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    if any(p.lower() in TEST_DIRS or p.endswith("Tests") for p in parts[:-1]):
        return True
    return any(fnmatch.fnmatchcase(parts[-1], pat) for pat in TEST_NAMES)


def _read(root: Path, rel: str) -> str:
    path = root / rel
    try:
        if path.stat().st_size > MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _entry(files: set[str]) -> dict:
    return {"count": len(files), "files": sorted(files)[:LIST_CUT]}


def _globs(ui_files: list[str]) -> list[str]:
    root_files = {f for f in ui_files if "/" not in f}
    dirs = {str(PurePosixPath(f).parent) for f in ui_files if "/" in f}
    kept = {d for d in dirs
            if not any(o != d and d.startswith(o + "/") for o in dirs)}
    return sorted(root_files | {d + "/**" for d in kept})


def scan(root: Path) -> dict:
    root = Path(root)
    rels = _walk(root)
    cats: dict[str, set[str]] = {name: set() for name in ORDER}
    ui: list[str] = []
    evidence: dict[str, list[str]] = {"unit": [], "integration": [], "e2e": []}
    source = markdown = 0
    for rel in rels:
        p = PurePosixPath(rel)
        ext = p.suffix
        parts = p.parts
        test = _is_test_path(rel)
        if ext == ".md":
            markdown += 1
            names = (parts[-1],) + parts[:-1]
            if rel == "SECURITY.md" or any(POLICY_NAME.search(n) for n in names):
                cats["policy_docs"].add(rel)
        if ext in SOURCE_EXT:
            source += 1
        e2e = any(c.lower() in E2E_DIRS or c.endswith("UITests") for c in parts)
        integration = any(c.lower() in INTEGRATION_DIRS for c in parts)
        if e2e:
            evidence["e2e"].append(rel)
        if integration:
            evidence["integration"].append(rel)
        if test and not e2e and not integration:
            evidence["unit"].append(rel)
        if test:
            continue
        text = ""
        if ext in SOURCE_EXT:
            text = _read(root, rel)
            for name, rx in PATTERNS.items():
                if rx.search(text):
                    cats[name].add(rel)
        if ext in UI_EXT or (ext == ".swift" and SWIFT_UI.search(text)):
            ui.append(rel)
    ui.sort()
    firing = [n for n in ORDER if len(cats[n]) >= (1 if n == "policy_docs" else 2)]
    return {
        "source_files": source,
        "markdown_files": markdown,
        "security": {"categories": {n: _entry(cats[n]) for n in ORDER}, "firing": firing,
                     "score": len(firing)},
        "ui": {"files": ui[:LIST_CUT], "globs": _globs(ui)},
        "tests": {"levels": {k: bool(v) for k, v in evidence.items()},
                  "evidence": {k: sorted(v)[:EVIDENCE_CUT] for k, v in evidence.items()}},
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(".")
    if not root.is_dir():
        print(f"survey_signals: {root} is not a directory", file=sys.stderr)
        return 1
    print(json.dumps(scan(root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
