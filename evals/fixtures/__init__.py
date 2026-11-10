"""Fixture builders. Each module has build(dest: Path, **params) -> dict (the expected outcome) and
optionally post_clone(work: Path, expected: dict) for files that must exist only in the working clone."""
from __future__ import annotations

import importlib
from pathlib import Path

from evals.harness.common import git


def builder(name: str):
    return importlib.import_module(f"evals.fixtures.{name}")


def write_files(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def init_repo(dest: Path, files: dict[str, str], message: str = "Initial commit") -> None:
    dest.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", "main", cwd=dest)
    write_files(dest, files)
    commit_all(dest, message)


def commit_all(dest: Path, message: str) -> str:
    git("add", "-A", cwd=dest)
    git("commit", "-q", "-m", message, cwd=dest)
    return git("rev-parse", "HEAD", cwd=dest).strip()
