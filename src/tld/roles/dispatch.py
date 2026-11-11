#!/usr/bin/env python3
"""Which roles a profile makes mandatory at a workflow point, and whether they ran.

    tld roles required --profile FILE --at POINT [--changed FILE]
    tld roles verify   --required FILE --report FILE

`required` validates the profile, applies the `roles` defaults (posture.security standard,
blocking false, disable [], extra_context []) and prints JSON: the roles that are required at POINT
(each `{role, blocking, matched, mode}`), the ones that do not apply, the posture, the disabled roles
and the extra context. `mode` is `edit` only for an edit role at `implement_phase` (C2: every other
point runs roles in review mode). `--changed` is a file with one repo-relative path per line (`-`
reads stdin); it is only needed for entries with `when` at a point that has a diff.

`verify` reads that JSON and a report text, looks for the last `AGENT-REPORT` line per required
role, prints `OK`, `MISSING` or `BLOCKED` per required item and a summary line. Exit 0 when nothing
is missing or blocked, else 1. The report line grammar is in roles/README.md.

Python 3.11+, standard library and PyYAML. These are the only defaults of the `roles` keys.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from tld.plan import manifest as vm  # noqa: E402
from tld.profile import validate as vp  # noqa: E402

POINTS = ("make_plan", "implement_phase", "implement_final", "review", "dod")
NO_DIFF_POINTS = ("make_plan", "review")
DEFAULT_POSTURE = "standard"
ROLES = ("architect", "code-reviewer", "security-reviewer", "test-architect", "ux-reviewer",
         "dependency-auditor", "tech-writer", "website-maintainer", "debugger", "refactorer")
EDIT_ROLES = ("tech-writer", "website-maintainer", "debugger", "refactorer")
EDIT_POINTS = ("implement_phase",)

REPORT_LINE = re.compile(
    r"^[>\s`]*AGENT-REPORT (?P<agent>[a-z-]+) at=(?P<at>[a-z_]+) "
    r"verdict=(?P<verdict>pass|findings|n/a) blocking=(?P<b>\d+) non_blocking=(?P<nb>\d+)[\s`]*$",
    re.MULTILINE,
)


class RolesError(Exception):
    """A usage or input problem; the message is printed as `tld roles: <message>`."""


def required(profile: dict, point: str, changed: list[str] | None) -> dict:
    """The roles required at `point` for a profile (a dict as `tld profile validate` accepts it)."""
    if point not in POINTS:
        raise RolesError(f"unknown point '{point}' (one of {', '.join(POINTS)})")
    block = (profile or {}).get("roles") or {}
    posture = (block.get("posture") or {}).get("security") or DEFAULT_POSTURE
    items: dict[str, dict] = {}
    not_applicable: list[dict] = []
    for entry in block.get("required") or []:
        if point not in entry["at"]:
            continue
        agent = entry["role"]
        when = entry.get("when")
        if not when:
            matched = ["always"]
        elif point in NO_DIFF_POINTS:
            not_applicable.append({"role": agent, "why": "no diff at this point"})
            continue
        else:
            if changed is None:
                raise RolesError("--changed is needed: roles.required has entries with 'when'")
            matched = [g for g in when if any(vm.path_matches(p, g) for p in changed)]
            if not matched:
                not_applicable.append({"role": agent, "why": "no changed file matches 'when'"})
                continue
        mode = "edit" if agent in EDIT_ROLES and point in EDIT_POINTS else "review"
        item = items.setdefault(agent, {"role": agent, "blocking": False, "matched": [], "mode": mode})
        item["blocking"] = item["blocking"] or bool(entry.get("blocking", False))
        item["matched"].extend(m for m in matched if m not in item["matched"])
    return {
        "point": point,
        "posture": {"security": posture},
        "extra_context": list(block.get("extra_context") or []),
        "disabled": list(block.get("disable") or []),
        "required": list(items.values()),
        "not_applicable": not_applicable,
    }


def verify(required: dict, report: str) -> tuple[list[str], bool]:
    """Output lines (one per required item, then the summary) and whether every required role is ok."""
    point = required["point"]
    last: dict[tuple[str, str], re.Match] = {}
    for m in REPORT_LINE.finditer(report):
        last[(m["agent"], m["at"])] = m
    lines: list[str] = []
    failed = 0
    items = required.get("required", [])
    for item in items:
        agent = item["role"]
        m = last.get((agent, point))
        if m is None or m["verdict"] == "n/a":
            lines.append(f"MISSING {agent} at={point}")
            failed += 1
            continue
        blocking = int(m["b"])
        if item.get("blocking") and blocking > 0:
            lines.append(f"BLOCKED {agent} at={point} blocking={blocking}")
            failed += 1
        else:
            lines.append(f"OK {agent} at={point} blocking={blocking}")
    if failed:
        lines.append(f"roles: FAILED ({failed} of {len(items)} required)")
    else:
        lines.append(f"roles: ok ({len(items)} required)")
    return lines, failed == 0


def _read(path: str) -> str:
    try:
        return sys.stdin.read() if path == "-" else Path(path).read_text()
    except OSError as exc:
        raise RolesError(f"cannot read '{path}': {exc.strerror or exc}") from exc


def _load_profile(path: str) -> dict:
    text = _read(path)
    try:
        profile = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RolesError(f"cannot read '{path}': not valid YAML: {exc}") from exc
    errors, _warnings, resolved = vp.validate(profile, None)
    if errors:
        raise RolesError("\n".join(f"toolkit.yaml: {e}" for e in errors))
    return resolved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rq = sub.add_parser("required", help="print the roles required at a point as JSON")
    rq.add_argument("--profile", required=True)
    rq.add_argument("--at", required=True)
    rq.add_argument("--changed")
    vf = sub.add_parser("verify", help="check a report against the output of `required`")
    vf.add_argument("--required", required=True)
    vf.add_argument("--report", required=True)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "required":
            if args.at not in POINTS:
                raise RolesError(f"unknown point '{args.at}' (one of {', '.join(POINTS)})")
            profile = _load_profile(args.profile)
            changed = None
            if args.changed is not None:
                changed = [ln.strip() for ln in _read(args.changed).splitlines() if ln.strip()]
            json.dump(required(profile, args.at, changed), sys.stdout, indent=2)
            print()
            return 0
        try:
            req = json.loads(_read(args.required))
        except json.JSONDecodeError as exc:
            raise RolesError(f"cannot read '{args.required}': not valid JSON: {exc}") from exc
        lines, ok = verify(req, _read(args.report))
        print("\n".join(lines))
        return 0 if ok else 1
    except RolesError as exc:
        print(f"tld roles: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
