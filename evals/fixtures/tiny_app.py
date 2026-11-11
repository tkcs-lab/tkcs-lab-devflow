"""A tiny synthetic Python project ("notes"): a JSON note store with a CLI and unit tests.

Used as the base of the planning and guardrail fixtures. No real project names, no secrets, no network.
"""
from __future__ import annotations

from pathlib import Path

from . import init_repo
from evals.harness.common import git

PROFILE = """\
project:
  name: notes-demo

docs:
  must_read:
    - README.md
    - docs/design.md
  plan_dir: docs/

git:
  main_branch: main
  branch_pattern: "<type>/<kebab-case>"
  branch_types: [feature, fix, chore]

verify:
  fast:
    - "python3 -m unittest discover -s tests -q"
  dod:
    - "python3 -m unittest discover -s tests -q"

stacks: []
"""

FILES = {
    ".tld/toolkit.yaml": PROFILE,
    "README.md": "# notes-demo\n\nA tiny note store.\n\n    python3 -m notes.cli add 'buy milk'\n    python3 -m notes.cli list\n",
    "docs/design.md": "# Design\n\nNotes live in `notes.json`. `notes/store.py` owns reads and writes; `notes/cli.py` parses arguments.\n",
    "notes/__init__.py": "",
    "notes/store.py": '''\
"""JSON-file note store."""
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save(path: Path, notes: list[dict]) -> None:
    path.write_text(json.dumps(notes, indent=2))


def add(path: Path, text: str) -> dict:
    notes = load(path)
    note = {"id": len(notes) + 1, "text": text}
    notes.append(note)
    save(path, notes)
    return note


def delete(path: Path, note_id: int) -> bool:
    notes = load(path)
    kept = [n for n in notes if n["id"] != note_id]
    save(path, kept)
    return len(kept) != len(notes)
''',
    "notes/cli.py": '''\
"""Command line: add, list, delete."""
import argparse
from pathlib import Path

from notes import store

DEFAULT = Path("notes.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="notes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("text")
    d = sub.add_parser("delete")
    d.add_argument("id", type=int)
    args = ap.parse_args(argv)
    if args.cmd == "add":
        print(store.add(DEFAULT, args.text)["id"])
    elif args.cmd == "list":
        for n in store.load(DEFAULT):
            print(f"{n['id']}\\t{n['text']}")
    else:
        return 0 if store.delete(DEFAULT, args.id) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "tests/test_store.py": '''\
import tempfile
import unittest
from pathlib import Path

from notes import store


class StoreTest(unittest.TestCase):
    def test_add_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.json"
            store.add(p, "a")
            store.add(p, "b")
            self.assertTrue(store.delete(p, 1))
            self.assertEqual([n["text"] for n in store.load(p)], ["b"])
            self.assertFalse(store.delete(p, 99))


if __name__ == "__main__":
    unittest.main()
''',
}


def build(dest: Path, **params) -> dict:
    init_repo(dest, FILES)
    return {"main_branch": "main", "source_files": sorted(f for f in FILES if f.startswith("notes/"))}
