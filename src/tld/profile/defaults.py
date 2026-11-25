"""Built-in defaults of the profile (plan 90, section 3.1): a table, applied by one pure function.

Stdlib only and no I/O: files and git facts reach `apply` through `Env`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

# Keys that are always filled when absent (leaf keys, so a partly written section still gets the rest).
STATIC: dict[str, object] = {
    "git.branch_pattern": "<type>/<kebab-case>",
    "git.branch_types": ["feature", "fix", "chore"],
    "git.merge_style": "merge-commit",
    "docs.must_read": [],
    "stacks": [],
    "models.worker": "standard",
    "models.reviewer": "strong",
    "land.max_prs": 10,
    "git_ops.workflow": "tld-git-ops.yml",
    "hooks.disable": [],
    "hooks.protect_paths": [".env", ".env.*", "*.lock", "package-lock.json", "go.sum"],
    "hooks.protect_paths_allow": [],
    "hooks.dod_gate.enabled": True,
    "hooks.dod_gate.max_attempts": 3,
    "hooks.plan_gate.enabled": True,
    "hooks.board_gate.enabled": True,
}

# Applied only inside a section the profile writes (an empty section, None, counts as written).
SECTION_DEFAULTS: dict[str, dict[str, object]] = {
    "deps": {"cooldown_days": 3, "time_budget_minutes": 90},
    "spec": {"version": "2.1.0"},
    "sysml": {"subset": 1},
    "release": {"workflow": "tld-release.yml"},
}

# Sections whose empty (None) form means "on".
SWITCH_SECTIONS = ("deps", "spec", "sysml")

# (key, value, path that must exist): applied only when the path exists.
FILE_CHECKED: list[tuple[str, object, str]] = [
    ("docs.index", "docs/README.md", "docs/README.md"),
    ("docs.adr_dir", "docs/adr", "docs/adr"),
    ("docs.adr_index", "docs/adr/README.md", "docs/adr"),
    ("docs.changelog", {"file": "CHANGELOG.md", "section": "## [Unreleased]", "policy": "unreleased"},
     "CHANGELOG.md"),
    ("admin.policy", ".tld/admin-policy.yaml", ".tld/admin-policy.yaml"),
    # dir "." (not "website"): build and links run from dir and name root-relative paths.
    # The links command is the literal the owner mandated.
    ("docs.website", {"dir": ".", "build": "python3 scripts/build_site.py --out _site",
                      "links": "python3 -m pytest tests/unit/test_website_links.py -q"},
     "scripts/build_site.py"),
]

# `false` turns the feature off. Value: the default keys that depend on it.
OFF_SWITCHES: dict[str, tuple[str, ...]] = {
    "docs.index": ("docs.index",),
    "docs.adr_dir": ("docs.adr_dir", "docs.adr_index", "docs.adr_bar"),
    "docs.changelog": ("docs.changelog",),
    "docs.website": ("docs.website",),
    "admin": ("admin", "admin.policy"),
    "git_ops": ("git_ops", "git_ops.repo", "git_ops.workflow"),
    "land.max_prs": ("land.max_prs",),
}

ADR_BAR_HEADING = "## Decisions, plans and ADRs"
ADR_BAR_VALUE = "CONTRIBUTING.md#decisions-plans-and-adrs"


@dataclass
class Env:
    """What the defaults may look at. A callable that is None means the fact is unknown."""
    exists: Callable[[str], bool] | None = None
    read: Callable[[str], str | None] | None = None
    origin_owner: str | None = None
    main_branch: str | None = None


_MISSING = object()


def _get(d: dict, dotted: str):
    cur: object = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _set(d: dict, dotted: str, value: object) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _delete(d: dict, dotted: str) -> None:
    parts = dotted.split(".")
    cur: object = d
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def apply(profile: dict, env: Env) -> tuple[dict, dict[str, str]]:
    """Return the profile with the built-in defaults filled in, and a map from dotted key to its source."""
    resolved = copy.deepcopy(profile)
    sources: dict[str, str] = {}
    for section in SWITCH_SECTIONS:
        if section in resolved and resolved[section] is None:
            resolved[section] = {}

    off: set[str] = set()
    for key, dependents in OFF_SWITCHES.items():
        if _get(resolved, key) is False:
            _delete(resolved, key)
            off.update(dependents)
            sources[key] = "off (false)"

    def put(key: str, value: object, source: str) -> bool:
        """Set `key` unless the profile wrote it or an off switch stopped it. True when it applied."""
        if key in off:
            return False
        if _get(resolved, key) is not _MISSING:
            sources[key] = "repo"
            return False
        _set(resolved, key, copy.deepcopy(value))
        sources[key] = source
        return True

    for key, value in STATIC.items():
        if key != "git_ops.workflow":  # only meaningful in a git_ops section that has a repo (below)
            put(key, value, "default")
    for section, values in SECTION_DEFAULTS.items():
        if section in resolved and isinstance(resolved[section], dict):
            for name, value in values.items():
                put(f"{section}.{name}", value, "default")

    if env.main_branch:
        put("git.main_branch", env.main_branch, "detected (origin/HEAD)")
    if env.origin_owner:
        put("git_ops.repo", f"{env.origin_owner}/git-ops", "default")
    if _get(resolved, "git_ops.repo") is not _MISSING:
        put("git_ops.workflow", STATIC["git_ops.workflow"], "default")

    plan_dir = "docs/plans" if env.exists is not None and env.exists("docs/plans") else "docs"
    put("docs.plan_dir", plan_dir, "default")

    applied: set[str] = set()
    for key, value, path in FILE_CHECKED:
        if key in off:
            continue
        if env.exists is None:
            if _get(resolved, key) is _MISSING:
                sources[key] = "not applied (no root)"
            else:
                sources[key] = "repo"
            continue
        if env.exists(path) and put(key, value, f"default ({path} exists)"):
            applied.add(key)

    if "docs.adr_dir" in applied and env.read is not None:
        text = env.read("CONTRIBUTING.md")
        if text is not None and ADR_BAR_HEADING in text.splitlines():
            put("docs.adr_bar", ADR_BAR_VALUE, "default (CONTRIBUTING.md has the heading)")
    return resolved, sources
