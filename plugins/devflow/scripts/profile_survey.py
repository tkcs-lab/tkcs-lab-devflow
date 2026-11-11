#!/usr/bin/env python3
"""Survey a repository for the facts /setup turns into a profile proposal.

Usage: profile_survey.py [ROOT]

Prints `survey(ROOT)` (default `.`) as JSON, 2-space indented: `root`, `evidence` and `proposal`.
`evidence` holds the stacks, other stacks, CI workflows and dispatchable workflows, the commands that
verify a change (CI run steps, Makefile targets, package scripts), git facts, and the results of
survey_docs.scan and survey_signals.scan. `proposal` is survey_proposal.build(evidence).

Read-only: runs `git` with argument lists and reads files; writes nothing.
Exit 0 ok; 1 ROOT is not a directory (`profile_survey: <message>`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import survey_docs  # noqa: E402
import survey_proposal  # noqa: E402
import survey_signals  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "build", "dist", "Pods", ".build",
             "__pycache__", "DerivedData"}
MAX_FILES = 5000
MAX_BYTES = 200000
MAKE_TARGETS = ("test", "tests", "check", "lint", "fmt", "format", "verify", "ci", "build")
PACKAGE_SCRIPTS = ("test", "lint", "build", "check", "typecheck")
DEVICE_FAMILY = re.compile(r'TARGETED_DEVICE_FAMILY\s*=\s*"?[^;"]*2')
PLIST_FAMILY = re.compile(r"<key>UIDeviceFamily</key>\s*<array>(.*?)</array>", re.S)
GIT_TIMEOUT = 15


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, env=_git_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _walk(root: Path):
    """Yield files under root, skipping SKIP_DIRS, at most MAX_FILES."""
    count = 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.is_symlink():
                    stack.append(p)
            elif p.is_file():
                count += 1
                if count > MAX_FILES:
                    return
                yield p


def _is_ipados(root: Path) -> bool:
    for p in _walk(root):
        if p.name not in ("project.pbxproj", "Info.plist"):
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if p.name == "project.pbxproj" and DEVICE_FAMILY.search(text):
            return True
        if p.name == "Info.plist":
            m = PLIST_FAMILY.search(text)
            if m and "<integer>2</integer>" in m.group(1):
                return True
    return False


def _stacks(root: Path) -> tuple[list[dict], list[dict]]:
    stacks: list[dict] = []
    py = [n for n in ("pyproject.toml", "setup.py", "requirements.txt") if (root / n).is_file()]
    if py:
        stacks.append({"name": "python", "evidence": py})
    if (root / "go.mod").is_file():
        stacks.append({"name": "go", "evidence": ["go.mod"]})
    sw = [n for n in ("Package.swift",) if (root / n).is_file()]
    try:
        sw += sorted(p.name for p in root.iterdir()
                     if p.is_dir() and p.suffix in (".xcodeproj", ".xcworkspace"))
    except OSError:
        pass
    if sw:
        stacks.append({"name": "swift", "evidence": sw})
        if _is_ipados(root):
            stacks.append({"name": "ipados", "evidence": sw})
    other = []
    if (root / "package.json").is_file():
        other.append({"name": "node", "evidence": ["package.json"], "skill": False})
    return stacks, other


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(k) for k in value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _workflow(path: Path, rel: str) -> dict | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    on = data.get("on", data.get(True))  # PyYAML reads the key `on` as the boolean True
    triggers = _as_list(on)
    dispatch_inputs: list[str] = []
    if isinstance(on, dict) and isinstance(on.get("workflow_dispatch"), dict):
        dispatch_inputs = _as_list(on["workflow_dispatch"].get("inputs"))
    runs_on: list[str] = []
    runs: list[dict] = []
    jobs = data.get("jobs")
    for job, body in (jobs.items() if isinstance(jobs, dict) else []):
        if not isinstance(body, dict):
            continue
        for label in _as_list(body.get("runs-on")) if not isinstance(body.get("runs-on"), dict) \
                else _as_list(body["runs-on"].get("labels")):
            if label not in runs_on:
                runs_on.append(label)
        for step in body.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append({"job": str(job), "run": step["run"].strip()})
    return {"file": rel, "triggers": triggers, "runs_on": runs_on, "runs": runs,
            "dispatch_inputs": dispatch_inputs}


def _ci(root: Path) -> dict:
    wf_dir = root / ".github" / "workflows"
    workflows: list[dict] = []
    if wf_dir.is_dir():
        for p in sorted(wf_dir.iterdir()):
            if p.is_file() and p.suffix in (".yml", ".yaml"):
                wf = _workflow(p, f".github/workflows/{p.name}")
                if wf:
                    workflows.append(wf)
    dispatchable = []
    for wf in workflows:
        if "workflow_dispatch" not in wf["triggers"]:
            continue
        label = next((l for l in wf["runs_on"] if "macos" in l.lower() or "windows" in l.lower()), None)
        if label is None:
            continue
        os_name = "macOS" if "macos" in label.lower() else "Windows"
        inputs = wf["dispatch_inputs"]
        dispatchable.append({"workflow": Path(wf["file"]).name,
                             "use_when": f"Build or test on {os_name} (runs-on: {label})",
                             "notes": "Inputs: " + ", ".join(inputs) if inputs else "No inputs."})
    return {"workflows": workflows, "dispatchable": dispatchable}


def _verify_evidence(root: Path, ci: dict) -> dict:
    ci_runs = [{"workflow": Path(wf["file"]).name, "job": r["job"], "run": r["run"]}
               for wf in ci["workflows"] if {"push", "pull_request"} & set(wf["triggers"])
               for r in wf["runs"]]
    make_targets: list[str] = []
    mk = root / "Makefile"
    if mk.is_file():
        try:
            text = mk.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        make_targets = [n for n in MAKE_TARGETS if re.search(rf"^{n}:", text, re.M)]
    scripts = _read_json(root / "package.json").get("scripts")
    package_scripts = {k: scripts[k] for k in PACKAGE_SCRIPTS
                       if isinstance(scripts, dict) and k in scripts}
    return {"ci_runs": ci_runs, "make_targets": make_targets, "package_scripts": package_scripts}


def _main_branch(root: Path) -> str | None:
    ref = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref.removeprefix("origin/")
    remotes = _git(root, "remote") or ""
    if remotes:
        out = _git(root, "ls-remote", "--symref", "origin", "HEAD") or ""
        m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", out, re.M)
        if m:
            return m.group(1)
        for name in ("main", "master"):
            if _git(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}"):
                return name
        return None
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD")


def _git_facts(root: Path) -> dict:
    empty = {"main_branch": None, "has_history": False, "branch_prefixes": {}}
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return empty
    count = _git(root, "rev-list", "--count", "HEAD")
    names: set[str] = set()
    for line in (_git(root, "branch", "--all", "--format=%(refname:short)") or "").splitlines():
        name = line.strip().removeprefix("origin/")
        if name and name not in ("HEAD", "origin") and "/" in name:
            names.add(name)
    prefixes: dict[str, int] = {}
    for name in sorted(names):
        head = name.split("/", 1)[0]
        prefixes[head] = prefixes.get(head, 0) + 1
    return {"main_branch": _main_branch(root), "has_history": bool(count and int(count) >= 1),
            "branch_prefixes": prefixes}


def survey(root: Path) -> dict:
    root = Path(root)
    stacks, other = _stacks(root)
    ci = _ci(root)
    evidence = {
        "stacks": stacks,
        "other_stacks": other,
        "ci": ci,
        "verify_evidence": _verify_evidence(root, ci),
        "git": _git_facts(root),
        "docs": survey_docs.scan(root),
        "signals": survey_signals.scan(root),
    }
    return {"root": str(root), "evidence": evidence, "proposal": survey_proposal.build(evidence)}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(".")
    if not root.is_dir():
        print(f"profile_survey: {root} is not a directory", file=sys.stderr)
        return 1
    print(json.dumps(survey(root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
