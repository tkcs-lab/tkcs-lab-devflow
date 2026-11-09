#!/usr/bin/env python3
"""Validate a plan's implementation manifest, for /make-plan (before it pushes) and /implement (before it starts).

    validate_manifest.py PLAN.md|MANIFEST.yaml [--profile .claude/toolkit.yaml]

PLAN.md: the first fenced yaml block under the '## Implementation manifest' heading is checked.
Exit 0 (warnings go to stderr) or 1 with one error per line. Python 3.11+, PyYAML.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

import yaml

HEADING = "## Implementation manifest"
WILDCARDS = "*?["


def extract_manifest(text: str) -> str:
    """The yaml block under the manifest heading, or raise ValueError."""
    start = text.find(HEADING)
    if start < 0:
        raise ValueError(f"no '{HEADING}' heading: this command only runs plans that have a manifest")
    match = re.search(r"```yaml[^\n]*\n(.*?)\n```", text[start:], re.S)
    if not match:
        raise ValueError(f"no fenced ```yaml block under '{HEADING}'")
    return match.group(1)


def _nonempty(value) -> bool:
    return bool(value) and (not isinstance(value, str) or bool(value.strip()))


def _static_prefix(pattern: str) -> str:
    cut = min((pattern.find(c) for c in WILDCARDS if c in pattern), default=len(pattern))
    return pattern[:cut]


def paths_overlap(a: str, b: str) -> bool:
    """True when two `touches` entries could name the same file."""
    a, b = a.strip().removeprefix("./"), b.strip().removeprefix("./")
    if a == b:
        return True
    a_glob, b_glob = any(c in a for c in WILDCARDS), any(c in b for c in WILDCARDS)
    if a_glob and b_glob:
        pa, pb = _static_prefix(a), _static_prefix(b)
        return pa.startswith(pb) or pb.startswith(pa)
    if a_glob:
        return fnmatch.fnmatchcase(b, a)
    if b_glob:
        return fnmatch.fnmatchcase(a, b)
    return (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b))


def _reach(phases: dict[str, list[str]]) -> dict[str, set[str]]:
    """For each phase id, every phase it depends on, directly or not."""
    memo: dict[str, set[str]] = {}

    def visit(pid: str, trail: tuple[str, ...]) -> set[str]:
        if pid in memo:
            return memo[pid]
        out: set[str] = set()
        for dep in phases.get(pid, []):
            if dep in phases and dep not in trail:
                out.add(dep)
                out |= visit(dep, trail + (pid,))
        memo[pid] = out
        return out

    for pid in phases:
        visit(pid, ())
    return memo


def find_cycle(phases: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}

    def dfs(pid: str, stack: list[str]) -> list[str] | None:
        state[pid] = 1
        for dep in phases.get(pid, []):
            if dep not in phases:
                continue
            if state.get(dep) == 1:
                return stack[stack.index(dep):] + [dep] if dep in stack else [pid, dep]
            if dep not in state:
                found = dfs(dep, stack + [dep])
                if found:
                    return found
        state[pid] = 2
        return None

    for pid in phases:
        if pid not in state:
            found = dfs(pid, [pid])
            if found:
                return found
    return None


def validate(manifest, profile: dict | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return ["the manifest must be a YAML mapping"], []

    for key in ("plan_slug", "feature_branch", "phases"):
        if not _nonempty(manifest.get(key)):
            errors.append(f"missing required key '{key}'")
    branch = manifest.get("feature_branch")
    if isinstance(branch, str) and profile:
        types = profile.get("git", {}).get("branch_types")
        if types and branch.split("/")[0] not in types:
            errors.append(
                f"feature_branch '{branch}' does not start with one of {', '.join(t + '/' for t in types)} "
                f"(git.branch_pattern: {profile['git']['branch_pattern']})"
            )
    mp = manifest.get("max_parallel")
    if mp is not None and (not isinstance(mp, int) or isinstance(mp, bool) or mp < 1):
        errors.append("max_parallel must be a positive integer")
    def _pos_int(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 1

    ti = manifest.get("tracking_issue")
    if "tracking_issue" in manifest and not _pos_int(ti):
        errors.append("tracking_issue must be a positive integer")
    if "closes" in manifest:
        cl = manifest["closes"]
        if not (isinstance(cl, list) and all(_pos_int(x) for x in cl)):
            errors.append("closes must be a list of positive integers")
        elif _pos_int(ti) and ti in cl:
            warnings.append("closes contains tracking_issue")
    for key in ("verify_after_merge", "final_checks"):
        if key in manifest and not (isinstance(manifest[key], list) and all(isinstance(x, str) for x in manifest[key])):
            errors.append(f"'{key}' must be a list of strings")

    manual_after_key = "manual_after" if "manual_after" in manifest else "manual"
    for key, required in (("manual_before", ("id", "title", "why", "done_when")), (manual_after_key, ("id", "title", "why"))):
        items = manifest.get(key) or []
        if not isinstance(items, list):
            errors.append(f"'{key}' must be a list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{key}[{i}] must be a mapping")
                continue
            for field in required:
                if not _nonempty(item.get(field)):
                    errors.append(f"{key}[{i}] ({item.get('id', '?')}) is missing '{field}'")
    has_manual = bool(manifest.get("manual_before") or manifest.get(manual_after_key))
    if has_manual and not manifest.get("manual_steps_artifact"):
        warnings.append("there are manual steps but no 'manual_steps_artifact'")
    if manifest.get("manual_steps_artifact") and not manifest.get("manual_steps_source"):
        warnings.append("'manual_steps_artifact' is set without 'manual_steps_source'; a revision cannot republish it")

    phases = manifest.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("'phases' must be a non-empty list")
        return errors, warnings

    ids: list[str] = []
    deps: dict[str, list[str]] = {}
    touches: dict[str, list[str]] = {}
    for i, ph in enumerate(phases):
        if not isinstance(ph, dict):
            errors.append(f"phases[{i}] must be a mapping")
            continue
        pid = ph.get("id")
        if not _nonempty(pid) or not isinstance(pid, str):
            errors.append(f"phases[{i}] is missing 'id'")
            continue
        if pid in ids:
            errors.append(f"duplicate phase id '{pid}'")
        ids.append(pid)
        for field in ("title", "brief", "acceptance"):
            if not _nonempty(ph.get(field)):
                errors.append(f"phase '{pid}' is missing '{field}'")
        if "acceptance" in ph and _nonempty(ph["acceptance"]) and not isinstance(ph["acceptance"], list):
            errors.append(f"phase '{pid}': 'acceptance' must be a list")
        cx = ph.get("complexity")
        if cx is not None and cx not in ("S", "M"):
            errors.append(f"phase '{pid}': complexity must be S or M (got {cx!r}); there is no L, split the phase")
        wm = ph.get("worker_model")
        if wm is not None and wm not in ("opus", "sonnet"):
            errors.append(f"phase '{pid}': worker_model must be opus or sonnet (got {wm!r})")
        if wm == "opus" and not _nonempty(ph.get("worker_model_reason")):
            errors.append(f"phase '{pid}': worker_model: opus needs a worker_model_reason")
        d = ph.get("depends_on") or []
        if not isinstance(d, list):
            errors.append(f"phase '{pid}': depends_on must be a list")
            d = []
        deps[pid] = [x for x in d if isinstance(x, str)]
        t = ph.get("touches")
        if t is not None and not (isinstance(t, list) and all(isinstance(x, str) for x in t)):
            errors.append(f"phase '{pid}': touches must be a list of paths")
        else:
            touches[pid] = t or []
        if "human_gate" in ph and not isinstance(ph["human_gate"], bool):
            errors.append(f"phase '{pid}': human_gate must be true or false")

    for pid, ds in deps.items():
        for dep in ds:
            if dep not in ids:
                errors.append(f"phase '{pid}': depends_on names unknown phase '{dep}'")
            elif dep == pid:
                errors.append(f"phase '{pid}' depends on itself")

    cycle = find_cycle(deps)
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))
        return errors, warnings

    reach = _reach(deps)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if b in reach.get(a, set()) or a in reach.get(b, set()):
                continue
            for pa in touches.get(a, []):
                for pb in touches.get(b, []):
                    if paths_overlap(pa, pb):
                        errors.append(
                            f"phases '{a}' and '{b}' can run at the same time but both touch "
                            f"'{pa}' / '{pb}': add a depends_on edge or split the path"
                        )
    for pid in ids:
        if not touches.get(pid):
            warnings.append(f"phase '{pid}' has no 'touches'; overlap with parallel phases cannot be checked")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--profile", help="resolved or raw .claude/toolkit.yaml, to check feature_branch against git.branch_types")
    args = ap.parse_args(argv)

    path = Path(args.plan)
    if not path.is_file():
        print(f"manifest: no such file '{path}'", file=sys.stderr)
        return 1
    text = path.read_text()
    try:
        raw = extract_manifest(text) if path.suffix == ".md" else text
        manifest = yaml.safe_load(raw)
    except ValueError as exc:
        print(f"manifest: {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"manifest: not valid YAML: {exc}", file=sys.stderr)
        return 1

    profile = None
    if args.profile:
        profile = yaml.safe_load(Path(args.profile).read_text())
    errors, warnings = validate(manifest, profile)
    for w in warnings:
        print(f"manifest: warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"manifest: {e}", file=sys.stderr)
    if errors:
        return 1
    n = len(manifest["phases"])
    print(f"manifest: OK ({manifest['plan_slug']}, {n} phase{'s' if n != 1 else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
