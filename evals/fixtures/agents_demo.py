"""tiny_app plus a profile with a `roles` block, and a feature branch with one commit that changes notes/store.py.

The runner clones the repository; post_clone puts the clone on `feature/agents-demo`, so the /dod diff
against origin/main is not empty. No real project names, no secrets, no network.
"""
from __future__ import annotations

from pathlib import Path

from . import commit_all, init_repo, tiny_app
from evals.harness.common import git

BRANCH = "feature/agents-demo"


def _profile(posture: str) -> str:
    return tiny_app.PROFILE + (
        "\nroles:\n"
        "  posture:\n"
        f"    security: {posture}\n"
        "  required:\n"
        "    - {role: security-reviewer, at: [dod], blocking: false}\n"
    )


def build(dest: Path, posture: str = "critical") -> dict:
    files = dict(tiny_app.FILES)
    files[".tld/toolkit.yaml"] = _profile(posture)
    init_repo(dest, files)
    git("checkout", "-q", "-b", BRANCH, cwd=dest)
    store = dest / "notes" / "store.py"
    store.write_text(store.read_text().replace(
        "def load(path: Path) -> list[dict]:",
        "def count(path: Path) -> int:\n    return len(load(path))\n\n\ndef load(path: Path) -> list[dict]:"))
    commit_all(dest, "Add count helper to the store")
    git("checkout", "-q", "main", cwd=dest)
    return {"main_branch": "main", "posture": posture}


def post_clone(work: Path, expected: dict) -> None:
    """Leave the clone on the feature branch."""
    git("checkout", "-q", "-b", BRANCH, f"origin/{BRANCH}", cwd=work)
