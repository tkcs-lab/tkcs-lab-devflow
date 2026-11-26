"""Merge a base profile with a repository profile and enforce the guarded keys (plan 90, section 3.4).

Pure. `tld.guard._common.HOOK_NAMES` is read inside a function only: `tld.guard` imports the profile package.
"""
from __future__ import annotations

import copy
import re

POSTURE_RANK = {"low": 0, "standard": 1, "critical": 2}
GATES = ("dod_gate", "plan_gate", "board_gate")
from tld.profile.defaults import STATIC

# tld's own protect list (the built-in floor when a base sets none): one copy, in defaults.STATIC.
BUILTIN_PROTECT_PATHS = list(STATIC["hooks.protect_paths"])
_ROLE = r"[a-z][a-z0-9-]*"
_OVERRIDE_RE: re.Pattern[str] | None = None


def hook_names() -> tuple[str, ...]:
    from tld.guard._common import HOOK_NAMES
    return tuple(HOOK_NAMES)


def __getattr__(name: str):
    """`OVERRIDE_RE` is built on first use, so importing this module never imports tld.guard."""
    global _OVERRIDE_RE
    if name == "OVERRIDE_RE":
        if _OVERRIDE_RE is None:
            hooks = "|".join(re.escape(h) for h in hook_names())
            _OVERRIDE_RE = re.compile(
                rf"\A(?:hooks\.disable\.(?:{hooks})|hooks\.protect_paths|hooks\.protect_paths_allow"
                rf"|hooks\.(?:dod|plan|board)_gate\.enabled|roles\.posture\.security|roles\.required\.{_ROLE})\Z")
        return _OVERRIDE_RE
    raise AttributeError(name)


# ---------------------------------------------------------------------------------------------- merge

def _union(first: list, second: list) -> list:
    out = list(first)
    out.extend(x for x in second if x not in out)
    return out


def _merge_roles(base_roles: list, repo_roles: list, warnings: list[str]) -> list:
    out = copy.deepcopy(base_roles)
    for entry in repo_roles:
        same = next((i for i, b in enumerate(out) if b.get("role") == entry.get("role")), None)
        if same is None:
            out.append(copy.deepcopy(entry))
            continue
        b = out[same]
        b["at"] = _union(b.get("at", []), entry.get("at", []))
        if "blocking" in b or "blocking" in entry:
            b["blocking"] = bool(b.get("blocking")) or bool(entry.get("blocking"))
        if "when" in entry:
            if "when" in b:
                b["when"] = _union(b["when"], entry["when"])
            else:
                warnings.append(f"'roles.required[{same}].when': no effect, the base runs {b.get('role')} "
                                "on every diff")
    return out


def _walk(base: dict, repo: dict, path: str, sources: dict[str, str], warnings: list[str]) -> dict:
    out: dict = {}
    for key in list(base) + [k for k in repo if k not in base]:
        dotted = f"{path}.{key}" if path else key
        in_base, in_repo = key in base, key in repo
        if in_base and in_repo and isinstance(base[key], dict) and isinstance(repo[key], dict):
            out[key] = _walk(base[key], repo[key], dotted, sources, warnings)
        elif in_base and in_repo and dotted == "verify.dod_manual" and isinstance(base[key], list):
            out[key] = _union(base[key], repo[key] or [])
            sources[dotted] = "base, repo"
        elif in_base and in_repo and dotted == "roles.required" and isinstance(base[key], list):
            out[key] = _merge_roles(base[key], repo[key] or [], warnings)
            sources[dotted] = "base, repo"
        elif in_repo:
            out[key] = copy.deepcopy(repo[key])
            _mark(sources, dotted, repo[key], "repo")
        else:
            out[key] = copy.deepcopy(base[key])
            _mark(sources, dotted, base[key], "base")
    return out


def _mark(sources: dict[str, str], dotted: str, value: object, source: str) -> None:
    if isinstance(value, dict) and value:
        for k, v in value.items():
            _mark(sources, f"{dotted}.{k}", v, source)
    else:
        sources[dotted] = source


def merge_with_warnings(base: dict, repo: dict, allow: list[str] = ()) -> tuple[dict, dict[str, str], list[str]]:
    """Like `merge`, and also the warnings (a repository `when` that has no effect)."""
    sources: dict[str, str] = {}
    warnings: list[str] = []
    merged = _walk(base, repo, "", sources, warnings)
    roles = merged.get("roles")
    if isinstance(roles, dict) and isinstance(roles.get("required"), list):
        dropped = {r for r in roles.get("disable") or [] if f"roles.required.{r}" in allow}
        if dropped:
            roles["required"] = [e for e in roles["required"]
                                 if not (e.get("role") in dropped and _from_base(base, e.get("role")))]
    return merged, sources, warnings


def _from_base(base: dict, role: str | None) -> bool:
    return any(e.get("role") == role for e in (base.get("roles") or {}).get("required") or [])


def merge(base: dict, repo: dict, allow: list[str] = ()) -> tuple[dict, dict[str, str]]:
    """Deep-merge `repo` over `base`: scalars and lists of the repository replace the base's, except
    `verify.dod_manual` (appended) and `roles.required` (merged by role). Returns the merged profile and a map
    from dotted key to `base`, `repo` or `base, repo`."""
    merged, sources, _ = merge_with_warnings(base, repo, allow)
    return merged, sources


# ------------------------------------------------------------------------------------- guarded keys

def _hooks(p: dict) -> dict:
    h = p.get("hooks")
    return h if isinstance(h, dict) else {}


def _gate_enabled(p: dict, gate: str) -> bool | None:
    g = _hooks(p).get(gate)
    if isinstance(g, dict) and isinstance(g.get("enabled"), bool):
        return g["enabled"]
    return None


def _posture(p: dict) -> str | None:
    posture = (p.get("roles") or {}).get("posture") or {}
    return posture.get("security")


def _rank(value: str | None, unknown: int) -> int:
    """Rank of a posture; a missing value is `standard`, an unknown one gets `unknown`."""
    return POSTURE_RANK.get(value or "standard", unknown)


def _required(p: dict) -> list:
    return (p.get("roles") or {}).get("required") or []


def guarded_errors(floor: dict, merged: dict, allow: list[str], label: str) -> list[str]:
    """What a repository may not write against its floor (the base plus tld's built-in values)."""
    errors: list[str] = []
    ao = "tld.allow_override"

    floor_disable = _hooks(floor).get("disable") or []
    for hook in _hooks(merged).get("disable") or []:
        if hook not in floor_disable and f"hooks.disable.{hook}" not in allow:
            errors.append(f"toolkit.yaml: 'hooks.disable': '{hook}' is switched on by the base {label}; the "
                          f"repository cannot switch it off unless the base lists 'hooks.disable.{hook}' in {ao}")

    repo_posture = _posture(merged) or "standard"
    if repo_posture not in POSTURE_RANK:
        errors.append(f"toolkit.yaml: 'roles.posture.security': must be one of critical, standard, low "
                      f"(got {repo_posture!r})")
    else:
        floor_rank = _rank(_posture(floor), POSTURE_RANK["critical"])
    if repo_posture in POSTURE_RANK and POSTURE_RANK[repo_posture] < floor_rank \
            and "roles.posture.security" not in allow:
        base_posture = next(k for k, v in POSTURE_RANK.items() if v == floor_rank)
        errors.append(f"toolkit.yaml: 'roles.posture.security': '{repo_posture}' is weaker than the base's "
                      f"'{base_posture}' (critical > standard > low); allowed only when the base lists "
                      f"'roles.posture.security' in {ao}")

    disabled = (merged.get("roles") or {}).get("disable") or []
    for entry in _required(floor):
        role = entry.get("role")
        if role in disabled and f"roles.required.{role}" not in allow:
            points = ", ".join(entry.get("at", []))
            errors.append(f"toolkit.yaml: 'roles.disable': '{role}' is required by the base {label} at {points}; "
                          f"allowed only when the base lists 'roles.required.{role}' in {ao}")

    floor_paths = _hooks(floor).get("protect_paths")
    who = f"the base {label}" if floor_paths is not None else "tld's default list"
    floor_paths = BUILTIN_PROTECT_PATHS if floor_paths is None else floor_paths
    merged_paths = _hooks(merged).get("protect_paths")
    merged_paths = BUILTIN_PROTECT_PATHS if merged_paths is None else merged_paths
    if "hooks.protect_paths" not in allow:
        for pattern in floor_paths:
            if pattern not in merged_paths:
                errors.append(f"toolkit.yaml: 'hooks.protect_paths': leaves out '{pattern}', which {who} "
                              f"protects; list it, or have the base list 'hooks.protect_paths' in {ao}")

    floor_allow = _hooks(floor).get("protect_paths_allow") or []
    if "hooks.protect_paths_allow" not in allow:
        for pattern in _hooks(merged).get("protect_paths_allow") or []:
            if pattern not in floor_allow:
                errors.append(f"toolkit.yaml: 'hooks.protect_paths_allow': '{pattern}' widens what the base "
                              f"{label} protects; allowed only when the base lists "
                              f"'hooks.protect_paths_allow' in {ao}")

    for gate in GATES:
        floor_on = _gate_enabled(floor, gate)
        if (floor_on is None or floor_on) and _gate_enabled(merged, gate) is False \
                and f"hooks.{gate}.enabled" not in allow:
            errors.append(f"toolkit.yaml: 'hooks.{gate}.enabled': false switches off a gate the base turns on; "
                          f"allowed only when the base lists 'hooks.{gate}.enabled' in {ao}")
    return errors


# ------------------------------------------------------------------------------------------- clamp

def _weaker(key: str, branch: str) -> str:
    return (f"toolkit.yaml: warning: '{key}' is weaker here than on {branch} (the remote default branch); "
            f"the {branch} value applies until this change is merged")


def clamp(trusted: dict, merged: dict, branch: str) -> tuple[dict, list[str]]:
    """Take the stricter value per guarded key of this branch and the default branch's resolved profile."""
    out = copy.deepcopy(merged)
    warnings: list[str] = []

    def hooks() -> dict:
        h = out.get("hooks")
        if not isinstance(h, dict):
            h = out["hooks"] = {}
        return h

    t_disable = _hooks(trusted).get("disable") or []
    m_disable = _hooks(out).get("disable") or []
    if sorted(t_disable) != sorted(m_disable):
        if any(h not in t_disable for h in m_disable):
            warnings.append(_weaker("hooks.disable", branch))
        hooks()["disable"] = list(t_disable)

    for gate in GATES:
        if _gate_enabled(trusted, gate) and _gate_enabled(out, gate) is False:
            hooks()[gate]["enabled"] = True
            warnings.append(_weaker(f"hooks.{gate}.enabled", branch))

    # A default branch without a posture means `standard`; an unknown trusted value counts as `critical`.
    t_rank = _rank(_posture(trusted), POSTURE_RANK["critical"])
    if t_rank > _rank(_posture(out), -1):
        t_post = next(k for k, v in POSTURE_RANK.items() if v == t_rank)
        roles = out.setdefault("roles", {})
        roles.setdefault("posture", {})["security"] = t_post
        warnings.append(_weaker("roles.posture.security", branch))

    t_paths = _hooks(trusted).get("protect_paths")
    if t_paths is not None:
        m_paths = _hooks(out).get("protect_paths")
        if m_paths is None or any(p not in m_paths for p in t_paths):
            hooks()["protect_paths"] = _union(t_paths, m_paths or [])
            warnings.append(_weaker("hooks.protect_paths", branch))

    m_allow = _hooks(out).get("protect_paths_allow")
    if m_allow:
        t_allow = _hooks(trusted).get("protect_paths_allow") or []
        kept = [p for p in m_allow if p in t_allow]
        if kept != m_allow:
            hooks()["protect_paths_allow"] = kept
            warnings.append(_weaker("hooks.protect_paths_allow", branch))

    _clamp_roles(trusted, out, branch, warnings)
    return out, warnings


def _clamp_roles(trusted: dict, out: dict, branch: str, warnings: list[str]) -> None:
    t_required = _required(trusted)
    if not t_required:
        return
    roles = out.setdefault("roles", {})
    required = roles.setdefault("required", [])
    for t in t_required:
        role = t.get("role")
        key = f"roles.required.{role}"
        entry = next((e for e in required if e.get("role") == role), None)
        if entry is None:
            required.append(copy.deepcopy(t))
            warnings.append(_weaker(key, branch))
        else:
            changed = False
            at = _union(entry.get("at", []), t.get("at", []))
            if at != entry.get("at"):
                entry["at"], changed = at, True
            if t.get("blocking") and not entry.get("blocking"):
                entry["blocking"], changed = True, True
            if "when" in entry:
                if "when" not in t:
                    del entry["when"]
                    changed = True
                elif any(w not in entry["when"] for w in t["when"]):
                    entry["when"] = _union(t["when"], entry["when"])
                    changed = True
            if changed:
                warnings.append(_weaker(key, branch))
        disabled = roles.get("disable") or []
        if role in disabled:
            roles["disable"] = [r for r in disabled if r != role]
            warnings.append(_weaker("roles.disable", branch))
