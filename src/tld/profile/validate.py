#!/usr/bin/env python3
"""Validate .tld/toolkit.yaml against schema/profile.schema.json.

    tld profile validate [PROFILE] [--root DIR] [--resolved] [--no-file-checks]

Exit 0 when valid, 1 with one error per line otherwise. --resolved prints the profile as JSON with
the schema's documented defaults filled in (the only defaults there are). `tld.version`, when set, is
checked against the running tld (src/tld/profile/version.py). Python 3.11+, PyYAML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

import tld
from tld.profile import version as tv

SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "profile.schema.json"
DEFAULT_PROFILE = ".tld/toolkit.yaml"
# The roles that are review dimensions of the review playbook (playbooks/review.md); only they can run at `review`.
REVIEW_ROLES = ("security-reviewer", "dependency-auditor", "test-architect", "tech-writer", "website-maintainer")
DIFF_POINTS = ("implement_phase", "implement_final", "dod")
HELP = "see docs/reference/profile-reference.md in the tkcs-lab-devflow repo"

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
}


def _is(value, name: str) -> bool:
    if name == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _ref(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    node = root
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return {**node, **{k: v for k, v in schema.items() if k != "$ref"}}


def check(value, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    """Validate the JSON Schema subset the profile schema uses."""
    schema = _ref(schema, root)
    if "oneOf" in schema:
        if any(_errs(value, s, root, path) == [] for s in schema["oneOf"]):
            return
        typed = [s for s in schema["oneOf"] if "type" in s and _is(value, s["type"])]
        if typed:  # right kind of value, wrong content: report that option's own errors
            check(value, typed[0], root, path, errors)
        else:
            errors.append(f"'{path}': {_describe(schema['oneOf'])}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"'{path}': must be one of {', '.join(map(str, schema['enum']))} (got {value!r})")
        return
    t = schema.get("type")
    if t and not _is(value, t):
        errors.append(f"'{path}': must be {_article(t)} (got {type(value).__name__})")
        return
    if t == "string" and len(value) < schema.get("minLength", 0):
        errors.append(f"'{path}': must not be empty")
    if t == "string" and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"'{path}': does not match {schema['pattern']}")
    if t == "integer":
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"'{path}': must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"'{path}': must be at most {schema['maximum']}")
    if t == "array":
        if len(value) < schema.get("minItems", 0):
            errors.append(f"'{path}': needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            check(item, schema.get("items", {}), root, f"{path}[{i}]", errors)
    if t == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"missing required key '{_join(path, key)}'")
        for key, sub in value.items():
            if key in props:
                check(sub, props[key], root, _join(path, key), errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"unknown key '{_join(path, key)}' (typo? {HELP})")


def _errs(value, schema, root, path) -> list[str]:
    out: list[str] = []
    check(value, schema, root, path, out)
    return out


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _article(t: str) -> str:
    return {"object": "a mapping", "array": "a list", "string": "a string", "boolean": "true/false"}.get(t, t)


def _describe(options: list[dict]) -> str:
    names = [_article(o["type"]) for o in options if "type" in o]
    return "must be " + " or ".join(names)


def apply_defaults(value: dict, schema: dict, root: dict) -> dict:
    """Fill the schema's `default`s for keys that are absent; normalise plan_dir."""
    out = json.loads(json.dumps(value))
    for key, sub in schema.get("properties", {}).items():
        sub = _ref(sub, root)
        if sub.get("type") == "object" and sub.get("properties"):
            if key in out or any("default" in _ref(p, root) for p in sub["properties"].values()):
                out[key] = apply_defaults(out.get(key) or {}, sub, root)
        elif key not in out and "default" in sub:
            out[key] = sub["default"]
    return out


def semantic_checks(profile: dict, root_dir: Path | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    docs = profile.get("docs", {})
    changelog = docs.get("changelog")
    if isinstance(changelog, dict) and "section" not in changelog and changelog.get("policy") != "release-only":
        errors.append("missing required key 'docs.changelog.section' (only policy: release-only may leave it out)")
    if ("adr_index" in docs or "adr_bar" in docs) and "adr_dir" not in docs:
        errors.append("'docs.adr_index' / 'docs.adr_bar' need 'docs.adr_dir' (ADRs are used iff adr_dir is set)")
    git = profile.get("git", {})
    owners, bot = git.get("codeowners"), git.get("bot_login")
    if owners is not None and bot is not None and bot in owners:
        errors.append("'git.codeowners' must not contain 'git.bot_login': the agent cannot be its own code owner")
    if owners is not None and bot is None:
        errors.append("'git.codeowners' needs 'git.bot_login'")
    if bot is not None and owners is None:
        warnings.append("'git.bot_login' is set without 'git.codeowners': nobody is asked to review")
    tag_pattern = profile.get("upstream", {}).get("tag_pattern")
    if tag_pattern is not None:
        try:
            re.compile(tag_pattern)
        except re.error as exc:
            errors.append(f"'upstream.tag_pattern': not a valid regular expression ({exc})")
    stacks = profile.get("stacks", [])
    apple = [s for s in ("swift", "ipados") if s in stacks]
    if apple and not profile.get("ci", {}).get("dispatchable"):
        warnings.append(
            f"stack '{apple[0]}' is selected but 'ci.dispatchable' is empty: iOS/iPadOS/macOS builds "
            "and tests cannot run in the container, list a macOS workflow there"
        )
    if "ipados" in stacks and "swift" not in stacks:
        warnings.append("stack 'ipados' builds on 'swift': list both (stacks: [swift, ipados])")
    roles = profile.get("roles", {})
    disabled = roles.get("disable", [])
    for i, entry in enumerate(roles.get("required", [])):
        name, points = entry["role"], entry["at"]
        where = f"roles.required[{i}]"
        if name in disabled:
            errors.append(f"'{where}': '{name}' is listed in 'roles.disable'")
        if name == "website-maintainer" and "website" not in docs:
            errors.append(f"'{where}': 'website-maintainer' needs 'docs.website'")
        if "when" in entry and not any(pt in DIFF_POINTS for pt in points):
            errors.append(f"'{where}.when': needs a diff, but 'at' has no point with a diff "
                          "(only 'make_plan' and 'review' have none)")
        if "review" in points and name not in REVIEW_ROLES:
            errors.append(f"'{where}': '{name}' cannot run at 'review' (it has no review dimension; "
                          f"allowed: {', '.join(REVIEW_ROLES)})")
    spec = profile.get("tld", {}).get("version")
    if spec is not None:
        try:
            if not tv.satisfies(tld.__version__, spec):
                errors.append(f"'tld.version': this profile needs tld {spec}, but tld {tld.__version__} is running "
                              "(update the plugin, or change tld.version after reading the release notes)")
        except tv.SpecifierError as exc:
            errors.append(f"'tld.version': {exc}")
    if docs.get("index") and len(docs.get("must_read", [])) > 3:
        warnings.append(
            f"'docs.must_read' lists {len(docs['must_read'])} files while 'docs.index' is set: "
            "keep only what every task needs, the index routes the rest"
        )
    if root_dir is not None:
        paths = list(docs.get("must_read", []))
        if docs.get("index"):
            paths.append(docs["index"])
        if profile.get("project_steward"):
            paths.append(profile["project_steward"])
        if profile.get("admin", {}).get("policy"):
            paths.append(profile["admin"]["policy"])
        for p in paths:
            if not (root_dir / p.split("#")[0]).exists():
                errors.append(f"file not found: '{p}' (listed in the profile; checked from {root_dir})")
    return errors, warnings


def validate(profile, root_dir: Path | None = None) -> tuple[list[str], list[str], dict]:
    schema = json.loads(SCHEMA.read_text())
    errors: list[str] = []
    if not isinstance(profile, dict):
        return ["the profile must be a YAML mapping"], [], {}
    if "toolkit" in profile:
        return (["'toolkit' was removed: the toolkit is delivered only as plugins (docs/guides/delivery.md); "
                 "delete the 'toolkit' section"], [], {})
    if "agents" in profile:
        return (["'agents' was renamed to 'roles' (and each entry's 'agent' to 'role'): "
                 "rename the section"], [], {})
    check(profile, schema, schema, "", errors)
    if errors:
        return errors, [], {}
    resolved = apply_defaults(profile, schema, schema)
    resolved["docs"]["plan_dir"] = resolved["docs"]["plan_dir"].rstrip("/")
    sem_errors, warnings = semantic_checks(resolved, root_dir)
    return sem_errors, warnings, resolved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", nargs="?", default=DEFAULT_PROFILE)
    ap.add_argument("--root", help="repo root for file-existence checks (default: the profile's repo root)")
    ap.add_argument("--resolved", action="store_true", help="print the resolved profile as JSON")
    ap.add_argument("--no-file-checks", action="store_true", help="skip checking that listed files exist")
    args = ap.parse_args(argv)

    path = Path(args.profile)
    if not path.is_file():
        print(f"toolkit.yaml: no profile at '{path}'. Create one from the starter in "
              f"src/tld/templates/toolkit.yaml ({HELP}).", file=sys.stderr)
        return 1
    try:
        profile = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"toolkit.yaml: not valid YAML: {exc}", file=sys.stderr)
        return 1

    root_dir = None if args.no_file_checks else Path(args.root) if args.root else path.resolve().parent.parent
    errors, warnings, resolved = validate(profile, root_dir)
    for w in warnings:
        print(f"toolkit.yaml: warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"toolkit.yaml: {e}", file=sys.stderr)
        return 1
    if args.resolved:
        json.dump(resolved, sys.stdout, indent=2)
        print()
    else:
        print(f"toolkit.yaml: OK ({path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
