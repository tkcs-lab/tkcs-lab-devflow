"""tld plan deviations init, add and check (src/tld/plan/deviations.py)."""
import json

import pytest
import yaml

from tld.plan import deviations

MANIFEST = {
    "plan_slug": "demo",
    "feature_branch": "feature/demo",
    "max_parallel": 2,
    "phases": [
        {"id": "p1", "title": "one", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["a.py"]},
        {"id": "p2", "title": "two", "depends_on": ["p1"], "brief": "b", "acceptance": ["a"], "touches": ["b.py"]},
    ],
}


@pytest.fixture()
def plan(tmp_path):
    path = tmp_path / "demo-plan.md"
    path.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(MANIFEST) + "```\n")
    return str(path)


@pytest.fixture()
def log(tmp_path, plan):
    out = str(tmp_path / "deviations.md")
    assert deviations.main(["init", "--plan", plan, "--out", out]) == 0
    return out


def add(log, section, tag="worker", *rest):
    return deviations.main(["add", "--file", log, "--section", section, "--tag", tag, *rest])


def test_init_writes_a_pending_section_per_phase(log):
    lines = open(log).read().split("\n")
    assert lines[0] == "# Deviations: demo"
    assert lines[2] == "Written by the implement orchestrator after each phase merge; workers never edit this file."
    assert lines[3] == ('Every deviation from the plan is listed under its phase. "None." means the phase '
                        'followed the plan.')
    heads = [ln for ln in lines if ln.startswith("## ")]
    assert heads == ["## p1", "## p2", "## Final review", "## Finishing"]
    assert lines.count("- pending") == 4


def test_init_reports_a_bad_plan_and_an_unwritable_out(tmp_path, capsys):
    assert deviations.main(["init", "--plan", str(tmp_path / "none.md"), "--out", str(tmp_path / "o.md")]) == 1
    assert capsys.readouterr().out.startswith("deviations: cannot read")


def test_add_replaces_pending_and_appends(log):
    assert add(log, "p1", "worker", "--text", "first") == 0
    assert add(log, "p1", "retry", "--text", "second") == 0
    text = open(log).read()
    assert "## p1\n\n- worker: first\n- retry: second\n\n## p2" in text
    assert text.count("- pending") == 3


def test_add_none_writes_none(log):
    assert add(log, "p2", "worker", "--none") == 0
    assert "## p2\n\n- None.\n" in open(log).read()


def test_add_cuts_and_cleans_text(log):
    assert add(log, "p1", "worker", "--text", "a\x00b\nc" + "x" * 600) == 0
    bullet = [ln for ln in open(log).read().split("\n") if ln.startswith("- worker:")][0]
    assert bullet.startswith("- worker: a?b?c")
    assert len(bullet) == len("- worker: ") + 500


def test_add_rejects_an_unknown_section_and_tag(log, capsys):
    assert add(log, "p9", "worker", "--text", "x") == 1
    assert "deviations: no section 'p9'" in capsys.readouterr().out
    assert add(log, "p1", "bogus", "--text", "x") == 1
    assert "deviations: unknown tag 'bogus'" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        add(log, "p1", "worker")
    with pytest.raises(SystemExit):
        add(log, "p1", "worker", "--text", "x", "--none")
    assert add("/nonexistent/f.md", "p1", "worker", "--none") == 1


def test_check_fails_on_a_pending_done_phase(log, plan, capsys):
    add(log, "p1", "worker", "--none")
    assert deviations.main(["check", "--file", log, "--plan", plan, "--done", "p1"]) == 0
    assert capsys.readouterr().out == "deviations: OK\n"
    assert deviations.main(["check", "--file", log, "--plan", plan, "--done", "p1,p2,p9"]) == 1
    out = capsys.readouterr().out
    assert "deviations: section 'p2' is still pending" in out
    assert "deviations: no phase 'p9' in the manifest" in out
    assert deviations.main(["check", "--file", log, "--plan", plan]) == 0


def test_check_all_fails_on_any_pending(log, plan, capsys):
    assert deviations.main(["check", "--file", log, "--plan", plan, "--all"]) == 1
    assert capsys.readouterr().out.count("is still pending") == 4
    for s in ("p1", "p2", "Final review", "Finishing"):
        add(log, s, "worker", "--none")
    assert deviations.main(["check", "--file", log, "--plan", plan, "--all"]) == 0


def test_check_requires_out_of_scope_paths_in_the_section(tmp_path, log, plan, capsys):
    res = tmp_path / "scope.json"
    res.write_text(json.dumps([{"label": "p1", "out_of_scope": [{"path": "x/y.py"}, {"path": "z.py"}]}]))
    add(log, "p1", "scope", "--text", "scope: x/y.py")
    args = ["check", "--file", log, "--plan", plan, "--scope-results", str(res)]
    assert deviations.main(args) == 1
    out = capsys.readouterr().out
    assert "out-of-scope path 'z.py' is not listed in section 'p1'" in out
    assert "x/y.py" not in out
    add(log, "p1", "scope", "--text", "scope: z.py")
    assert deviations.main(args) == 0


def test_check_maps_fix_and_rev_labels(tmp_path, log, plan, capsys):
    res = tmp_path / "scope.json"
    entries = [{"label": "fix-2", "out_of_scope": [{"path": "f.py"}]},
               {"label": "p2-rev1", "out_of_scope": [{"path": "r.py"}]},
               {"label": "nosuch", "out_of_scope": []},
               {"label": 5}, "junk"]
    res.write_text(json.dumps(entries))
    args = ["check", "--file", log, "--plan", plan, "--scope-results", str(res)]
    assert deviations.main(args) == 1
    out = capsys.readouterr().out
    assert "'f.py' is not listed in section 'Final review'" in out
    assert "'r.py' is not listed in section 'p2'" in out
    assert "scope entry 'nosuch' has no section 'nosuch'" in out
    add(log, "Final review", "final", "--text", "f.py")
    add(log, "p2", "scope", "--text", "r.py")
    res.write_text(json.dumps(entries[:2]))
    assert deviations.main(args) == 0


def test_check_reports_unreadable_scope_results_and_missing_sections(tmp_path, log, plan, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert deviations.main(["check", "--file", log, "--plan", plan, "--scope-results", str(bad)]) == 1
    assert "unreadable" in capsys.readouterr().out
    bad.write_text("{}")
    assert deviations.main(["check", "--file", log, "--plan", plan, "--scope-results", str(bad)]) == 1
    empty = tmp_path / "empty.md"
    empty.write_text("# Deviations: demo\n")
    assert deviations.main(["check", "--file", str(empty), "--plan", plan, "--all"]) == 1
    assert "deviations: no section 'p1'" in capsys.readouterr().out
