"""tiny_app as a repository whose release pull request (1.2.0) is merged: the release skill's green check, offline.

`build(dest, state=...)` writes `ci-state/checks.json`, the check runs of the head commit that a runtime would read:
- `red`: `lint` completed `failure`, `test` still running, `build` success; the skill must stop and name `lint`.
- `running`: `test` still running, the rest success; the skill must wait and ask nothing.
- `moved`: all success, but the owner's yes was for another commit (`1111111`); the stub of `release-head-moved`
  contains the first 7 characters of this fixture's head, so a change to the fixture's files changes that value:
  update `evals/stubs/release-head-moved.json` with it.
No real project names, no secrets, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import init_repo, tiny_app
from evals.harness.common import git

WORKFLOW = """\
name: release
on:
  workflow_dispatch:
    inputs:
      dry_run:
        type: boolean
        default: true
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: echo release
"""

CHANGELOG = """\
# Changelog

## [Unreleased]

## [1.2.0] - 2026-11-24

### Added

- Tags on notes.
"""


def run(name: str, status: str = "completed", conclusion: str | None = "success") -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


STATES = {
    "red": [run("lint", conclusion="failure"), run("test", "in_progress", None), run("build")],
    "running": [run("lint"), run("test", "in_progress", None), run("build")],
    "moved": [run("lint"), run("test"), run("build")],
}
STOP = {"red": ["not started", "lint: completed failure"], "running": ["waiting: test: in_progress"]}


def build(dest: Path, state: str = "red") -> dict:
    if state not in STATES:
        raise ValueError(f"no state {state!r}")
    profile = tiny_app.PROFILE.replace(
        "  plan_dir: docs/\n", '  plan_dir: docs/\n  changelog: {file: CHANGELOG.md, section: "## [Unreleased]"}\n')
    profile += ("\nrelease: {workflow: release.yml, version_files: "
                "[{path: pyproject.toml, pattern: '^version = \"(\\d+\\.\\d+\\.\\d+)\"$'}]}\n")
    files = dict(tiny_app.FILES)
    files.update({
        ".tld/toolkit.yaml": profile,
        "pyproject.toml": '[project]\nname = "notes-demo"\nversion = "1.2.0"\n',
        ".github/workflows/release.yml": WORKFLOW,
        "CHANGELOG.md": CHANGELOG,
        "ci-state/checks.json": json.dumps(STATES[state], indent=2) + "\n",
    })
    init_repo(dest, files)
    head = git("rev-parse", "HEAD", cwd=dest).strip()
    stop = ["1111111", head[:7]] if state == "moved" else STOP[state]
    return {"main_branch": "main", "stop_message": stop}
