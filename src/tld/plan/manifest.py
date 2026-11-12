#!/usr/bin/env python3
"""Validate a plan's implementation manifest, for /make-plan (before it pushes) and /implement (before it starts).

    tld plan validate-manifest PLAN.md|MANIFEST.yaml [--profile .tld/toolkit.yaml] [--ref REF]

PLAN.md: the first fenced yaml block under the '## Implementation manifest' heading is checked.
Exit 0 (warnings go to stderr) or 1 with one error per line. Python 3.11+, PyYAML.
"""
from __future__ import annotations

import argparse
import fnmatch
import posixpath
import re
import sys
from pathlib import Path

import yaml

HEADING = "## Implementation manifest"
LEVELS = ("strong", "standard", "fast")
WILDCARDS = "*?["
TOP_KEYS = ("plan_slug", "feature_branch", "tracking_issue", "closes", "max_parallel", "manual_before",
            "manual_after", "manual", "verify_after_merge", "screenshots_after_merge", "final_checks", "phases")
PHASE_KEYS = ("id", "title", "depends_on", "complexity", "touches", "brief", "acceptance", "human_gate",
              "worker_level", "worker_level_reason")
HINTS = {  # legacy keys (claude-toolkit) and what replaced them
    "worker_model": "use worker_level (strong, standard or fast); tld migrate rewrites it",
    "worker_model_reason": "use worker_level_reason; tld migrate rewrites it",
    "manual_steps_artifact": "manual steps now reach the owner as asks (manual_before / manual_after); remove it",
    "manual_steps_source": "manual steps now reach the owner as asks (manual_before / manual_after); remove it",
}


def _unknown(keys, known, where: str) -> list[str]:
    out = []
    for key in keys:
        if key in known:
            continue
        hint = HINTS.get(key) or ("manual steps now reach the owner as asks; remove it"
                                  if str(key).startswith("manual_steps_") else f"known keys: {', '.join(known)}")
        out.append(f"{where}unknown key '{key}': {hint}")
    return out


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


def _norm(path: str) -> str:
    return path.strip().removeprefix("./")


def path_matches(path: str, pattern: str) -> bool:
    """True when the file `path` is named by one `touches` entry.

    The one glob semantics of the toolkit (the overlap check below and scope_check.py share it):
    an entry is a literal path, a directory prefix ending in '/', or an fnmatch glob. In a glob
    `*` and `**` both match across '/', so `src/**/x.py` needs at least one directory between
    `src/` and `x.py`.
    """
    path, pattern = _norm(path), _norm(pattern)
    if path == pattern:
        return True
    if any(c in pattern for c in WILDCARDS):
        return fnmatch.fnmatchcase(path, pattern)
    return pattern.endswith("/") and path.startswith(pattern)


def paths_overlap(a: str, b: str) -> bool:
    """True when two `touches` entries could name the same file."""
    a, b = _norm(a), _norm(b)
    if a == b:
        return True
    a_glob, b_glob = any(c in a for c in WILDCARDS), any(c in b for c in WILDCARDS)
    if a_glob and b_glob:
        pa, pb = _static_prefix(a), _static_prefix(b)
        return pa.startswith(pb) or pb.startswith(pa)
    if a_glob:
        return path_matches(b, a)
    if b_glob:
        return path_matches(a, b)
    return path_matches(b, a) or path_matches(a, b)


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


def _is_plan_record(entry: str, plan_dir: str, plan_slug: str = "") -> bool:
    """True when a touches entry grants write scope over <plan_dir>/<slug>/plan.md or deviations.md.

    Judged with `path_matches`, the matcher that enforces scope, so globs (`docs/plans/*`, `**/plan.md`),
    directory prefixes (`docs/plans/14/`), whitespace and `..` spellings count. A glob counts only when it aims
    at the plan records (its literal prefix is inside `plan_dir`, it ends in plan.md or deviations.md, or it is `*`/`**`);
    a broad docs glob such as `docs/*.md` is left to the overlap check. The records tried are those of
    this plan's slug, of a placeholder slug and of the slug the entry itself names. A bare `<plan_dir>/` entry
    is left alone. Under a `plan_dir` of one segment (`docs/`) the slug named by the entry is not tried, so
    `docs/adr/**` stays valid."""
    name = _norm(entry)
    if not name:
        return False
    base = plan_dir.rstrip("/")
    wild = any(c in name for c in WILDCARDS)
    if not wild:
        name = posixpath.normpath(name) + ("/" if name.endswith("/") else "")
    if name == base + "/":
        return False
    if re.fullmatch(re.escape(base) + r"/[^/]+/(plan|deviations)\.md", name):
        return True
    def clean(seg: str) -> str:
        return re.sub(r"[*?\[\]]+", "a", seg)
    parts = name.split("/")
    slugs = {plan_slug or "x", "x"}
    depth = len(base.split("/"))
    if depth >= 2 and len(parts) > depth:
        slugs.add(clean(parts[depth]))
    if len(parts) >= 2 and re.search(r"[A-Za-z]", parts[-1]):
        slugs.add(clean(parts[-2]))
    if wild:  # `docs/*.md` is an ordinary docs phase: a glob counts only when it aims at the plan records
        aims = ((depth >= 2 and _static_prefix(name).startswith(base + "/")) or parts[-1] in ("plan.md", "deviations.md")
                or all(seg in ("*", "**") for seg in parts))
        if not aims:
            return False
    return any(path_matches(f"{base}/{sl}/{f}", name) for sl in slugs for f in ("plan.md", "deviations.md"))


def validate(manifest, profile: dict | None = None, *, plan_dir: str = "docs/plans") -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return ["the manifest must be a YAML mapping"], []

    errors += _unknown(manifest, TOP_KEYS, "")
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
        errors += _unknown(ph, PHASE_KEYS, f"phase '{pid}': ")
        for field in ("title", "brief", "acceptance"):
            if not _nonempty(ph.get(field)):
                errors.append(f"phase '{pid}' is missing '{field}'")
        if "acceptance" in ph and _nonempty(ph["acceptance"]) and not isinstance(ph["acceptance"], list):
            errors.append(f"phase '{pid}': 'acceptance' must be a list")
        cx = ph.get("complexity")
        if cx is not None and cx not in ("S", "M"):
            errors.append(f"phase '{pid}': complexity must be S or M (got {cx!r}); there is no L, split the phase")
        wl = ph.get("worker_level")
        if wl is not None and wl not in LEVELS:
            errors.append(f"phase '{pid}': worker_level must be one of {', '.join(LEVELS)} (got {wl!r})")
        if wl == "strong" and not _nonempty(ph.get("worker_level_reason")):
            errors.append(f"phase '{pid}': worker_level: strong needs a worker_level_reason")
        if wl == "fast" and cx != "S":
            errors.append(f"phase '{pid}': worker_level: fast needs complexity S")
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
            for entry in t or []:
                if _is_plan_record(entry, plan_dir, str(manifest.get("plan_slug") or "")):
                    errors.append(f"phase '{pid}': touches '{entry}' is a plan record; "
                                  "a phase never edits a plan or its deviations file")
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
    ap.add_argument("--profile", help="resolved or raw .tld/toolkit.yaml, to check feature_branch against git.branch_types")
    ap.add_argument("--ref", help="the branch the plan file is on: it may only be on main or on its own feature branch")
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
    plan_dir = "docs/plans"
    main_branch = "main"
    if isinstance(profile, dict):
        docs, git = profile.get("docs"), profile.get("git")
        if isinstance(docs, dict) and docs.get("plan_dir"):
            plan_dir = str(docs["plan_dir"])
        if isinstance(git, dict) and git.get("main_branch"):
            main_branch = str(git["main_branch"])
    errors, warnings = validate(manifest, profile, plan_dir=plan_dir.rstrip("/") or plan_dir)
    for w in warnings:
        print(f"manifest: warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"manifest: {e}", file=sys.stderr)
    if errors:
        return 1
    if args.ref:
        ref = args.ref
        if ref == "plan/" + manifest["plan_slug"]:
            print(f"manifest: old-layout plan on '{ref}' (deprecated)", file=sys.stderr)
        elif ref not in (main_branch, manifest["feature_branch"]):
            print(f"manifest: the plan is on '{ref}', but it may only be on '{main_branch}' "
                  f"or on its own feature branch '{manifest['feature_branch']}'", file=sys.stderr)
            return 1
    n = len(manifest["phases"])
    print(f"manifest: OK ({manifest['plan_slug']}, {n} phase{'s' if n != 1 else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
