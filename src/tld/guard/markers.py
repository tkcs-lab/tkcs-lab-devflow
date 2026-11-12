"""Short-lived markers that let one guarded step through (`tld guard allow-*`, ended by `tld guard end-allow`).

A marker is a JSON file under `<git dir>/tld/` (per checkout, never committed) with the time it was written
and, for some kinds, what it allows. It is a deliberate step a command takes, not a control: any session that
can run a command can write one. The rulesets on GitHub are the control (docs/guides/admin.md).
"""
from __future__ import annotations

import calendar
import json
import os
import sys
import time
from pathlib import Path

from tld.dod.gate import state_dir
from tld.guard._common import GUARDED_WORKFLOWS, find_project

# kind -> (file name, lifetime in seconds)
KINDS = {
    "profile": ("protect-paths-profile.json", 7200),            # /setup edits .tld/toolkit.yaml
    "workflow-install": ("protect-paths-workflow.json", 900),   # /land or repo-admin installs a tld workflow file
    "git-ops": ("git-ops-confirm.json", 600),                    # a real (dry_run false) git-ops run after the user's yes
    "plan-open": ("plan-gate-open.json", 28800),                 # /implement workers: edits allowed in this checkout (plan-gate)
}
KEEP_ON_CLEAR = ("plan-open",)   # `end-allow` leaves these in place
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def path(project: str, kind: str) -> Path:
    return state_dir(project) / KINDS[kind][0]


def write(project: str, kind: str, **data) -> Path:
    target = path(project, kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"written_at": time.strftime(STAMP, time.gmtime()), **data}))
    return target


def read(project: str, kind: str) -> dict | None:
    """The marker's data while it is younger than its lifetime; None when it is missing, malformed or expired."""
    try:
        with open(path(project, kind), encoding="utf-8") as f:
            data = json.load(f)
        written = calendar.timegm(time.strptime(data["written_at"], STAMP))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return data if 0 <= time.time() - written <= KINDS[kind][1] else None


def clear(project: str) -> None:
    for kind in KINDS:
        if kind in KEEP_ON_CLEAR:
            continue
        try:
            path(project, kind).unlink()
        except FileNotFoundError:
            pass


def _workflow_files(args: list[str]) -> list[str] | None:
    """The guarded workflow files named by `args` (a file name or its path); None when one is not such a file."""
    out = []
    for a in args:
        rel = a[2:] if a.startswith("./") else a
        rel = rel if "/" in rel else f".github/workflows/{rel}"
        if rel not in GUARDED_WORKFLOWS:
            return None
        out.append(rel)
    return out or None


def cli(argv: list[str]) -> int:
    project = find_project(os.getcwd())[0]
    if argv[:1] == ["--allow-profile"]:
        where = write(project, "profile")
        print(f"protect-paths: .tld/toolkit.yaml may be edited for the next 2 hours ({where})")
        return 0
    if argv[:1] == ["--allow-workflow-install"]:
        files = _workflow_files(argv[1:])
        if files is None:
            print("protect-paths: allow-workflow-install takes one or more of: "
                  + ", ".join(os.path.basename(f) for f in GUARDED_WORKFLOWS), file=sys.stderr)
            return 2
        where = write(project, "workflow-install", files=files)
        print(f"protect-paths: {', '.join(files)} may be written for the next 15 minutes ({where})")
        return 0
    if argv[:1] == ["--allow-git-ops"]:
        where = write(project, "git-ops")
        print(f"no-git-tag: git-ops may run with dry_run false for the next 10 minutes ({where})")
        return 0
    if argv[:1] == ["--allow-plan"]:
        where = write(project, "plan-open")
        print(f"plan-gate: edits are allowed in this checkout for the next 8 hours ({where})")
        return 0
    if argv[:1] == ["--end-allow"]:
        clear(project)
        print("protect-paths: .tld/toolkit.yaml is protected again; workflow installs and real git-ops runs are off")
        return 0
    print("usage: tld guard allow-profile | allow-workflow-install <file>... | allow-git-ops | allow-plan | end-allow", file=sys.stderr)
    return 2
