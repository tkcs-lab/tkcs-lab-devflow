#!/usr/bin/env python3
"""The run record's items of a plan, and a check that a record lists them all.

    tld plan record-items PLAN [--add ID[=TITLE]]... [--check RECORD]

Without --check it prints one JSON list of run-record items: one per manifest phase in manifest order, then
`final-review`, then one per --add. With --check (RECORD is a status record JSON file, or `-` for stdin) it
prints `items: missing <id>` for every expected id the record's `phases` lack, or `items: ok (<n> expected)`.

Exit 0 ok, 1 missing items, 2 usage or unreadable input. Python 3.11+, PyYAML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from tld.plan.manifest import extract_manifest

PROG = "tld plan record-items"
ID_RE = r"[a-z0-9][a-z0-9-]{0,63}"
FINAL = "final-review"


class InputError(Exception):
    """Unreadable or malformed input: main prints it and returns 2."""


def _item(id_: str, title: str, depends_on: list, complexity) -> dict:
    return {"id": id_, "title": title, "depends_on": depends_on, "complexity": complexity,
            "state": "pending", "session": None, "branch": None, "started_at": None, "finished_at": None}


def build_items(manifest, adds: list[str]) -> list[dict]:
    """Phase items in manifest order, `final-review`, then the added ones; ValueError on a bad or duplicate id."""
    if not isinstance(manifest, dict):
        raise ValueError("the manifest is not a mapping")
    phases = manifest.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("the manifest has no 'phases' list")
    items: list[dict] = []
    for i, phase in enumerate(phases, 1):
        if not isinstance(phase, dict):
            raise ValueError(f"phase {i} is not a mapping")
        id_, title, deps = phase.get("id"), phase.get("title"), phase.get("depends_on")
        if not isinstance(id_, str):
            raise ValueError(f"phase {i} has no string 'id'")
        if not isinstance(title, str):
            raise ValueError(f"phase '{id_}' has no string 'title'")
        if not isinstance(deps, list):
            raise ValueError(f"phase '{id_}' has no 'depends_on' list")
        complexity = phase.get("complexity")
        items.append(_item(id_, title, list(deps), complexity if isinstance(complexity, str) else None))
    known = {item["id"] for item in items}
    for item in items:
        for dep in item["depends_on"]:
            if not isinstance(dep, str) or not re.fullmatch(ID_RE, dep) or dep not in known:
                raise ValueError(f"phase {item['id']!r} has a depends_on entry that is not a phase id: {str(dep)[:80]!r}")
    items.append(_item(FINAL, "Final review", [p["id"] for p in items], None))
    for spec in adds:
        id_, sep, title = spec.partition("=")
        items.append(_item(id_, title if sep and title else id_, [], None))
    seen: set = set()
    for item in items:
        id_ = item["id"]
        if not re.fullmatch(ID_RE, id_):
            raise ValueError(f"invalid item id {id_[:80]!r}")
        if id_ in seen:
            raise ValueError(f"duplicate item id {id_[:80]!r}")
        seen.add(id_)
    return items


def _load_record(source: str) -> list[str]:
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text()
        record = json.loads(text)
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read record '{source}': {exc}")
    except RecursionError:
        raise InputError("record is nested too deeply")
    except ValueError as exc:
        raise InputError(f"record is not valid JSON: {exc}")
    if not isinstance(record, dict):
        raise InputError("record is not a JSON object")
    phases = record.get("phases")
    if not isinstance(phases, list):
        raise InputError("record has no 'phases' list")
    ids = []
    for i, entry in enumerate(phases, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise InputError(f"record phases entry {i} is not an object with a string 'id'")
        ids.append(entry["id"])
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--add", action="append", default=[], metavar="ID[=TITLE]")
    ap.add_argument("--check", metavar="RECORD")
    args = ap.parse_args(argv)  # a usage error exits 2 by itself

    try:
        path = Path(args.plan)
        if not path.is_file():
            raise InputError(f"no such file '{path}'")
        try:
            manifest = yaml.safe_load(extract_manifest(path.read_text()))
        except RecursionError:
            raise InputError("manifest is nested too deeply")
        except yaml.YAMLError as exc:
            raise InputError(f"manifest is not valid YAML: {exc}")
        except (ValueError, OSError) as exc:  # no heading, no block, unreadable or not UTF-8 text
            raise InputError(str(exc))
        try:
            items = build_items(manifest, args.add)
        except ValueError as exc:
            raise InputError(str(exc))
        if args.check is None:
            print(json.dumps(items))
            return 0
        have = set(_load_record(args.check))
    except InputError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    missing = [item["id"] for item in items if item["id"] not in have]
    for id_ in missing:
        print(f"items: missing {id_}")
    if missing:
        return 1
    print(f"items: ok ({len(items)} expected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
