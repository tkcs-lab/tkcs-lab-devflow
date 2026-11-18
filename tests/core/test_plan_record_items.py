"""tld plan record-items: build the run record's items from a plan, or check a record lists them all."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tld.plan import record_items

ROOT = Path(__file__).resolve().parents[2]
KEYS = {"id", "title", "depends_on", "complexity", "state", "session", "branch", "started_at", "finished_at"}


def _plan(path: Path, phases: str | None = None, heading: bool = True) -> Path:
    phases = phases if phases is not None else (
        "  - {id: p1-a, title: First, depends_on: [], complexity: S}\n"
        "  - {id: p2-b, title: Second, depends_on: [p1-a], complexity: M}\n")
    body = f"plan_slug: x\nphases:\n{phases}"
    path.write_text(("## Implementation manifest\n\n" if heading else "# Plan\n\n") + f"```yaml\n{body}```\n")
    return path


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    return _plan(tmp_path / "plan.md")


def _item(id_, title, deps, complexity):
    return {"id": id_, "title": title, "depends_on": deps, "complexity": complexity, "state": "pending",
            "session": None, "branch": None, "started_at": None, "finished_at": None}


def _run(capsys, *argv):
    code = record_items.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def _items(capsys, plan, *adds):
    argv = [plan]
    for a in adds:
        argv += ["--add", a]
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return json.loads(out)


def _record(tmp_path, phases, name="rec.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"phases": phases}))
    return path


def test_prints_exact_items(plan, capsys):
    assert _items(capsys, plan) == [
        _item("p1-a", "First", [], "S"),
        _item("p2-b", "Second", ["p1-a"], "M"),
        _item("final-review", "Final review", ["p1-a", "p2-b"], None),
    ]
    assert all(set(i) == KEYS for i in _items(capsys, plan))


@pytest.mark.parametrize("spec,title", [("fix-1=Fix one", "Fix one"), ("fix-1", "fix-1"),
                                        ("fix-1=a=b", "a=b"), ("fix-1=", "fix-1")])
def test_add_titles(plan, capsys, spec, title):
    last = _items(capsys, plan, spec)[-1]
    assert last == _item("fix-1", title, [], None)


@pytest.mark.parametrize("adds", [["fix-1", "fix-1"], ["final-review"], ["p1-a"], ["Bad_Id"], ["=T"]])
def test_bad_adds_exit_2(plan, capsys, adds):
    argv = [plan]
    for a in adds:
        argv += ["--add", a]
    code, out, err = _run(capsys, *argv)
    assert (code, out) == (2, "")
    assert err.startswith("tld plan record-items: ")


def test_id_length_limit(plan, capsys):
    assert _items(capsys, plan, "a" * 64)[-1]["id"] == "a" * 64
    assert _run(capsys, plan, "--add", "a" * 65)[0] == 2


def test_missing_plan_and_manifest(tmp_path, capsys):
    assert _run(capsys, tmp_path / "nope.md")[0] == 2
    assert _run(capsys, _plan(tmp_path / "a.md", heading=False))[0] == 2
    assert _run(capsys, _plan(tmp_path / "b.md", phases="  []\n"))[0] == 2
    (tmp_path / "c.md").write_text("## Implementation manifest\n\n```yaml\nphases: [unclosed\n```\n")
    assert _run(capsys, tmp_path / "c.md")[0] == 2
    (tmp_path / "d.md").write_text("## Implementation manifest\n\n```yaml\n- a\n```\n")
    assert _run(capsys, tmp_path / "d.md")[0] == 2


@pytest.mark.parametrize("phases", [
    "  - {id: Bad_Id, title: T, depends_on: []}\n",
    "  - {id: p, title: T, depends_on: []}\n  - {id: p, title: U, depends_on: []}\n",
    "  - {id: final-review, title: T, depends_on: []}\n",
    "  - {id: p, depends_on: []}\n",
])
def test_bad_manifest_phases_exit_2(tmp_path, capsys, phases):
    code, out, err = _run(capsys, _plan(tmp_path / "p.md", phases=phases))
    assert (code, out) == (2, "")
    assert err.startswith("tld plan record-items: ")


def test_check_missing(plan, tmp_path, capsys):
    rec = _record(tmp_path, [{"id": "p1-a"}, {"id": "p2-b"}])
    assert _run(capsys, plan, "--check", rec) == (1, "items: missing final-review\n", "")


def test_check_ok_and_extras(plan, tmp_path, capsys):
    ids = ["p1-a", "p2-b", "final-review"]
    rec = _record(tmp_path, [{"id": i} for i in ids])
    assert _run(capsys, plan, "--check", rec) == (0, "items: ok (3 expected)\n", "")
    rec = _record(tmp_path, [{"id": i} for i in ids + ["fix-1", "other"]])
    assert _run(capsys, plan, "--check", rec)[0] == 0
    assert _run(capsys, plan, "--add", "fix-2", "--check", rec) == (1, "items: missing fix-2\n", "")


def test_check_bad_records_exit_2(plan, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    cases = ["not json", "[]", "{}", '{"phases": {}}', '{"phases": ["x"]}', '{"phases": [{"title": "t"}]}',
             '{"phases": [{"id": 1}]}']
    for text in cases:
        bad.write_text(text)
        code, out, err = _run(capsys, plan, "--check", bad)
        assert (code, out) == (2, ""), text
        assert err.startswith("tld plan record-items: "), text
    assert _run(capsys, plan, "--check", tmp_path / "missing.json")[0] == 2


def test_cli_registration_and_stdin(plan):
    cmd = [sys.executable, str(ROOT / "cli" / "tld"), "plan", "record-items", str(plan)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    assert [i["id"] for i in json.loads(out)] == ["p1-a", "p2-b", "final-review"]
    rec = json.dumps({"phases": [{"id": i["id"]} for i in json.loads(out)]})
    done = subprocess.run(cmd + ["--check", "-"], input=rec, capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, "items: ok (3 expected)\n")
