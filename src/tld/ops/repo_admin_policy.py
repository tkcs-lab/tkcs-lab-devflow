"""The pure model of an inherited repo-admin policy: key classes, merge, guarded settings, derived logins.

Nothing here reads a file or calls the API, and the module never imports tld.ops.repo_admin (repo_admin imports it).
"""
from __future__ import annotations

import copy
import fnmatch
import json
import re
from dataclasses import dataclass

import yaml

# --------------------------------------------------------------------------- key classes

RUN_ONLY = ("org", "extends", "repos")
PRIVATE_ONLY = ("org_settings", "members", "apps", "tokens", "secrets", "variables")
ORG_LEVEL = PRIVATE_ONLY + ("labels", "webhooks", "deploy_keys", "branches", "branch_protection", "profile", "git_ops")
OVERRIDABLE = ("repo_settings", "security", "actions", "rulesets", "agent", "release", "workflow_lint", "config_dirs",
               "workflows", "workflow_params")
PER_REPO_ONLY = ("rulesets.default_branch.required_status_checks", "workflow_params", "config_dirs.known", "workflows[].params")
IRREVERSIBLE = (
    "secrets.delete_unused", "variables.delete_unused", "labels.delete_unused", "labels.delete_unlisted",
    "webhooks.delete", "deploy_keys.delete_unused", "branches.delete_merged",
    "tokens.fine_grained.max_unused_days", "tokens.fine_grained.revoke_expired",
)

# --------------------------------------------------------------------------- guarded settings

TRUE_KEYS = (
    "security.vulnerability_alerts", "security.automated_security_fixes", "security.secret_scanning",
    "security.secret_push_protection", "security.private_vulnerability_reporting", "rulesets.tags",
    "workflow_lint.require_permissions", "workflow_lint.forbid_pull_request_target",
)
FALSE_KEYS = ("rulesets.default_branch.admin_bypass", "actions.can_approve_pull_request_reviews")
ORDERED = {  # loosest first, stricter last
    "actions.default_workflow_permissions": ["write", "read"],
    "workflow_lint.pin_actions": ["third_party", "all"],
    "agent.branch_policy": ["protected_branches", "default_branch"],
}
EQUAL_KEYS = ("repo_settings.allow_merge_commit", "repo_settings.allow_squash_merge", "repo_settings.allow_rebase_merge")
LIST_KEYS = ("config_dirs.forbid", "config_dirs.require")
GUARDED_KEYS = tuple(sorted({*TRUE_KEYS, *FALSE_KEYS, *ORDERED, *EQUAL_KEYS, *LIST_KEYS}))

LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")

_MISSING = object()


def kind_of(doc: dict) -> str:
    """'run' for a policy with `org` (the file that is run, or an old whole policy), else 'override'."""
    return "run" if "org" in doc else "override"


# --------------------------------------------------------------------------- dotted access


def _get(doc, dotted: str):
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _set(doc: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    node = doc
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    node[parts[-1]] = value


def _leaf(value) -> bool:
    return not isinstance(value, dict) or not value


def _leaves(doc, prefix=()):
    """(path tuple, value) of every leaf: scalars, lists and empty mappings."""
    if _leaf(doc):
        yield prefix, doc
        return
    for key, value in doc.items():
        yield from _leaves(value, prefix + (str(key),))


def _walk_nulls(value, path: str, out: list[str]) -> None:
    if value is None:
        out.append(path)
    elif isinstance(value, dict):
        for key, child in value.items():
            _walk_nulls(child, f"{path}.{key}" if path else str(key), out)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _walk_nulls(child, f"{path}[{i}]", out)


# --------------------------------------------------------------------------- key errors


def _turns_on(key: str, value) -> bool:
    if key == "webhooks.delete":
        return isinstance(value, list) and bool(value)
    if key == "tokens.fine_grained.max_unused_days":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return value is True


def key_errors(doc, kind: str, where: str, public: str | None = None) -> list[str]:
    """The class errors of one file of kind 'override' or 'base'. Never raises, never looks at values beyond the rules."""
    if kind not in ("override", "base") or not isinstance(doc, dict):
        return []
    errors: list[str] = []
    for key in doc:
        if key in RUN_ONLY:
            if key == "extends" and kind == "base":
                errors.append(f"{where}: sets 'extends'; an extended file cannot extend another")
            else:
                errors.append(f"{where}: '{key}' is set only in the policy file you run")
        elif kind == "override" and key in ORG_LEVEL:
            errors.append(f"{where}: '{key}' is organisation-level; only the organisation's policy and the files it extends may set it")
        elif kind == "base" and public and key in PRIVATE_ONLY:
            errors.append(f"{where}: '{key}' is organisation-private and {public} is public; keep org_settings, members, "
                          "apps, tokens, secrets and variables in a file of a private repository")
    if kind == "base":
        for key in ("rulesets.default_branch.required_status_checks", "config_dirs.known", "workflow_params"):
            if _get(doc, key) is not _MISSING:
                errors.append(f"{where}: '{key}' is per repository; set it in each repository's override file")
        for key in IRREVERSIBLE:
            value = _get(doc, key)
            if value is not _MISSING and _turns_on(key, value):
                errors.append(f"{where}: '{key}' turns on an irreversible change; set it only in the policy file you run")
    workflows = doc.get("workflows")
    if isinstance(workflows, list):
        for i, entry in enumerate(workflows):
            if not isinstance(entry, dict):
                continue
            if kind == "override":
                if set(entry) - {"template", "params", "remove"}:
                    errors.append(f"{where}: 'workflows[{i}]': a repository override may set only template, params and remove")
                continue
            if "params" in entry:
                errors.append(f"{where}: 'workflows[{i}].params' is per repository; use workflow_params in each repository's override file")
            for key in entry:
                if key not in ("template", "params"):
                    errors.append(f"{where}: 'workflows[{i}].{key}': a base may set only template")
    nulls: list[str] = []
    _walk_nulls(doc, "", nulls)
    errors += [f"{where}: '{path}': null is not allowed" for path in nulls]
    return errors


# --------------------------------------------------------------------------- merge


def deep_merge(base: dict, over: dict) -> dict:
    """New objects; mappings merge key by key, lists and scalars of `over` replace."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def merge_layers(layers: list[tuple[str, dict]]) -> tuple[dict, dict[str, str]]:
    """Merge in order; also the dotted leaf key -> label of the layer that set its final value."""
    merged: dict = {}
    for _, doc in layers:
        merged = deep_merge(merged, doc)
    sources: dict[str, str] = {}
    for path, _ in _leaves(merged):
        label = ""
        for name, doc in layers:
            node = doc
            for part in path:
                node = node.get(part, _MISSING) if isinstance(node, dict) else _MISSING
                if node is _MISSING:
                    break
            if node is not _MISSING and _leaf(node):
                label = name
        sources[".".join(path)] = label
    return merged, sources


def clamp_irreversible(merged: dict, run_doc: dict) -> dict:
    """revoke_expired defaults to true; a base that supplies tokens.fine_grained must not switch it on for the run file."""
    out = copy.deepcopy(merged)
    fine = _get(out, "tokens.fine_grained")
    if _get(run_doc, "tokens.fine_grained") is _MISSING and isinstance(fine, dict) and "revoke_expired" not in fine:
        fine["revoke_expired"] = False
    return out


def apply_override(org: dict, override: dict) -> dict:
    """The effective policy of one repository: the override over the organisation policy, workflow_params copied into `workflows`."""
    merged = deep_merge(org, {k: v for k, v in override.items() if k != "workflow_params"})
    params = deep_merge(org.get("workflow_params") or {}, override.get("workflow_params") or {})
    merged.pop("workflow_params", None)
    if not params:
        return merged
    merged["workflow_params"] = params
    for entry in merged.get("workflows") or []:
        if isinstance(entry, dict) and entry.get("template") in params:
            entry["params"] = {**entry.get("params", {}), **params[entry["template"]]}
    return merged


# --------------------------------------------------------------------------- guarded settings


@dataclass(frozen=True)
class Loosening:
    key: str
    org_value: object
    value: object


def _loose(key: str, org_value, value) -> bool:
    if key in TRUE_KEYS:
        return org_value is True and isinstance(value, bool) and value is False
    if key in FALSE_KEYS:
        return org_value is False and value is True
    if key in ORDERED:
        order = ORDERED[key]
        return org_value in order and value in order and order.index(value) < order.index(org_value)
    if key in EQUAL_KEYS:
        return value != org_value
    if key in LIST_KEYS:
        return isinstance(org_value, list) and isinstance(value, list) and any(item not in value for item in org_value)
    return False


def loosened(org: dict, eff: dict) -> list[Loosening]:
    """Guarded keys the organisation sets and the effective policy makes looser."""
    out = []
    for key in GUARDED_KEYS:
        org_value, value = _get(org, key), _get(eff, key)
        if org_value is _MISSING or value is _MISSING:
            continue
        if _loose(key, org_value, value):
            out.append(Loosening(key, copy.deepcopy(org_value), copy.deepcopy(value)))
    return out


def clamp_guarded(org: dict, eff: dict, allowed: set[str]) -> tuple[dict, list[Loosening]]:
    """Put the organisation's value back wherever eff loosens a guarded key that is not in `allowed`."""
    out = copy.deepcopy(eff)
    found = []
    for item in loosened(org, eff):
        if item.key in allowed:
            continue
        found.append(item)
        if item.key in LIST_KEYS:
            kept = list(item.value)
            _set(out, item.key, kept + [x for x in item.org_value if x not in kept])
        else:
            _set(out, item.key, copy.deepcopy(item.org_value))
    return out, found


def allowed_for(run_policy: dict, repo_name: str) -> set[str]:
    """The guarded keys `repos.allow_loosen` lets this repository loosen (globs of repository names)."""
    allow = (run_policy.get("repos") or {}).get("allow_loosen") or {}
    out: set[str] = set()
    for glob, keys in allow.items():
        if fnmatch.fnmatchcase(repo_name, glob):
            out.update(keys)
    return out


# --------------------------------------------------------------------------- derived logins


def derive_logins(profile: dict | None) -> tuple[str | None, str | None, list[str]]:
    """(agent login, reviewer login, reasons for what is missing) from a repository's resolved profile."""
    if not isinstance(profile, dict):
        return None, None, ["no profile"]
    git = profile.get("git") if isinstance(profile.get("git"), dict) else {}
    reasons: list[str] = []
    bot = git.get("bot_login")
    agent = None
    if isinstance(bot, str) and bot:
        if LOGIN_RE.fullmatch(bot):
            agent = bot
        else:
            reasons.append("git.bot_login is not a plain login")
    else:
        reasons.append("no git.bot_login")
    owner = git.get("owner_login")
    reviewer = None
    if isinstance(owner, str) and owner:
        if LOGIN_RE.fullmatch(owner):
            reviewer = owner
        else:
            reasons.append("git.owner_login is not a plain login")
    else:
        owners = git.get("codeowners")
        if isinstance(owners, list) and len(owners) == 1:
            one = owners[0]
            if isinstance(one, str) and LOGIN_RE.fullmatch(one):
                reviewer = one
            else:
                reasons.append("git.codeowners entry is not a plain login")
        else:
            reasons.append("no git.owner_login and not exactly one git.codeowners entry")
    if reviewer is not None and agent is not None and reviewer.casefold() == agent.casefold():
        reviewer = None
        reasons.append("reviewer equals the agent login")
    return agent, reviewer, reasons


def drop_derived(doc: dict, agent: str | None, reviewer: str | None) -> dict:
    """A copy without the logins that equal the derived ones; a section that became empty goes too."""
    out = copy.deepcopy(doc)
    for section, key, derived in (("agent", "agent_login", agent), ("release", "reviewer_login", reviewer)):
        body = out.get(section)
        if derived is not None and isinstance(body, dict) and body.get(key) == derived:
            del body[key]
            if not body:
                del out[section]
    return out


# --------------------------------------------------------------------------- converting and rendering


def _minus(over: dict, org: dict) -> dict:
    out = {}
    for key, value in over.items():
        if key not in org:
            out[key] = value
        elif isinstance(value, dict) and isinstance(org[key], dict):
            rest = _minus(value, org[key])
            if rest:
                out[key] = rest
        elif value != org[key]:
            out[key] = value
    return out


def legacy_to_override(legacy: dict, org: dict) -> tuple[dict, list[str]]:
    """An old whole policy as the minimal override over the organisation policy, and one note per dropped section."""
    notes = [f"dropped organisation-level section '{key}'" for key in legacy if key in ORG_LEVEL]
    kept = {k: v for k, v in legacy.items() if k not in RUN_ONLY and k not in ORG_LEVEL and not str(k).startswith("_")}
    return _minus(kept, org), notes


def propose_override(existing: dict | None, detected: dict) -> dict:
    """The detected values, with every key the repository already wrote kept."""
    return deep_merge(detected, existing or {})


OVERRIDE_HEADER = ("# Repository override of the organisation's repo-admin policy (docs/guides/admin.md).\n"
                   "# Only what differs from the organisation policy belongs here.\n")


def render_override(doc: dict) -> str:
    return OVERRIDE_HEADER + yaml.safe_dump(doc, sort_keys=False)


def explain_lines(merged: dict, sources: dict[str, str]) -> list[str]:
    """One line per leaf, `<dotted key> = <json>  # <source>`, sorted by key."""
    rows = {".".join(path): value for path, value in _leaves(merged)}
    return [f"{key} = {json.dumps(rows[key], sort_keys=True, separators=(',', ':'))}  # {sources.get(key, '')}"
            for key in sorted(rows)]
