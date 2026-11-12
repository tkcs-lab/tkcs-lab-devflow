#!/usr/bin/env python3
"""The deviations log next to a plan: what the implement orchestrator did differently from the plan.

    deviations.py init  --plan PLAN.md|MANIFEST.yaml --out FILE
    deviations.py add   --file FILE --section NAME --tag TAG (--text TEXT | --none)
    deviations.py check --file FILE --plan PLAN.md|MANIFEST.yaml [--done ID[,ID...] | --all]
                        [--scope-results FILE]

`init` writes one `## <phase id>` section per manifest phase (in order), then `## Final review` and
`## Finishing`, each holding the single line `- pending`. `add` replaces a `- pending` line or appends
a bullet. `check` lists every problem as `deviations: <problem>` and exits 1, or prints `deviations: OK`.
Python 3.11+, stdlib and PyYAML, no network.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from tld.plan import phases

TAGS = ("worker", "review", "scope", "retry", "conflict", "gate", "level", "final")
TEXT_MAX = 500
PENDING = "- pending"
FINAL, FINISHING = "Final review", "Finishing"
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
INTRO = (
    "Written by the implement orchestrator after each phase merge; workers never edit this file.",
    'Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.',
)


class DeviationsError(Exception):
    """Printed as `deviations: <message>`."""


def phase_ids(plan: str) -> tuple[str, list[str]]:
    try:
        manifest = phases.load_manifest(plan)
    except phases.PlanError as exc:
        raise DeviationsError(str(exc)) from None
    return manifest["plan_slug"], [p["id"] for p in manifest["phases"]]


def read_lines(path: str) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8").split("\n")
    except OSError as exc:
        raise DeviationsError(f"cannot read '{path}': {exc.strerror or exc}") from None


def sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Section name -> (index of its heading, index after its last line)."""
    heads = [(i, ln[3:].strip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    return {name: (i, heads[n + 1][0] if n + 1 < len(heads) else len(lines))
            for n, (i, name) in enumerate(heads)}


def clean(text: str) -> str:
    return CONTROL.sub("?", text)[:TEXT_MAX]


def do_init(plan: str, out: str) -> None:
    slug, ids = phase_ids(plan)
    parts = [f"# Deviations: {slug}", "", *INTRO]
    for name in [*ids, FINAL, FINISHING]:
        parts += ["", f"## {name}", "", PENDING]
    try:
        Path(out).write_text("\n".join(parts) + "\n", encoding="utf-8")
    except OSError as exc:
        raise DeviationsError(f"cannot write '{out}': {exc.strerror or exc}") from None


def do_add(path: str, section: str, tag: str, text: str | None) -> None:
    if tag not in TAGS:
        raise DeviationsError(f"unknown tag '{clean(tag)}' (one of {', '.join(TAGS)})")
    lines = read_lines(path)
    found = sections(lines)
    if section not in found:
        raise DeviationsError(f"no section '{clean(section)}' in {path}")
    bullet = "- None." if text is None else f"- {tag}: {clean(text)}"
    start, end = found[section]
    body = range(start + 1, end)
    pending = [i for i in body if lines[i].strip() == PENDING]
    if pending:
        lines[pending[0]] = bullet
    else:
        bullets = [i for i in body if lines[i].startswith("- ")]
        lines.insert((bullets[-1] if bullets else start) + 1, bullet)
    try:
        Path(path).write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        raise DeviationsError(f"cannot write '{path}': {exc.strerror or exc}") from None


def section_for(label: str) -> str:
    if re.fullmatch(r"fix-\d+", label):
        return FINAL
    m = re.fullmatch(r"(.+)-rev\d+", label)
    return m.group(1) if m else label


def scope_entries(path: str) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DeviationsError(f"scope results '{path}' are unreadable") from None
    if not isinstance(data, list):
        raise DeviationsError(f"scope results '{path}' are unreadable")
    return [e for e in data if isinstance(e, dict)]


def do_check(path: str, plan: str, done: list[str], every: bool, scope_results: str | None) -> list[str]:
    _, ids = phase_ids(plan)
    lines = read_lines(path)
    found = sections(lines)
    problems: list[str] = []
    for pid in done:
        if pid not in ids:
            problems.append(f"no phase '{pid}' in the manifest")
    wanted = [*ids, FINAL, FINISHING] if every else [p for p in done if p in ids]
    for name in wanted:
        if name not in found:
            problems.append(f"no section '{name}'")
        elif any(lines[i].strip() == PENDING for i in range(found[name][0] + 1, found[name][1])):
            problems.append(f"section '{name}' is still pending")
    if scope_results:
        for entry in scope_entries(scope_results):
            label = entry.get("label")
            if not isinstance(label, str):
                continue
            name = section_for(label)
            if name not in found:
                problems.append(f"scope entry '{clean(label)}' has no section '{clean(name)}'")
                continue
            text = "\n".join(lines[found[name][0] + 1:found[name][1]])
            for item in entry.get("out_of_scope") or []:
                p = item.get("path") if isinstance(item, dict) else None
                if isinstance(p, str) and p not in text and clean(p) not in text:
                    problems.append(f"out-of-scope path '{clean(p)}' is not listed in section '{name}'")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld plan deviations", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="write a deviations file with a pending section per phase")
    i.add_argument("--plan", required=True)
    i.add_argument("--out", required=True)
    a = sub.add_parser("add", help="record one deviation, or none, under a section")
    a.add_argument("--file", required=True)
    a.add_argument("--section", required=True)
    a.add_argument("--tag", required=True)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--none", action="store_true")
    c = sub.add_parser("check", help="list pending sections and unrecorded out-of-scope paths")
    c.add_argument("--file", required=True)
    c.add_argument("--plan", required=True)
    cg = c.add_mutually_exclusive_group()
    cg.add_argument("--done", default="", help="comma-separated phase ids whose sections must be filled")
    cg.add_argument("--all", action="store_true")
    c.add_argument("--scope-results")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "init":
            do_init(args.plan, args.out)
        elif args.cmd == "add":
            do_add(args.file, args.section, args.tag, None if args.none else args.text)
        else:
            done = [x for x in args.done.split(",") if x]
            problems = do_check(args.file, args.plan, done, args.all, args.scope_results)
            for p in problems:
                print(f"deviations: {p}")
            if problems:
                return 1
            print("deviations: OK")
    except DeviationsError as exc:
        print(f"deviations: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
