"""Compare against a baseline: the threshold is in repeats."""
import pytest

from evals.harness.compare import compare


def tasks(**kw):
    return {k: {"runs": r, "passes": p, "pass_rate": p / r, "graders": {}} for k, (p, r) in kw.items()}


BASE = {"tasks": tasks(a=(3, 3), b=(2, 3))}


def test_equal_is_ok():
    assert compare(BASE, tasks(a=(3, 3), b=(2, 3))).ok


def test_drop_of_exactly_one_repeat_is_allowed():
    assert compare(BASE, tasks(a=(2, 3), b=(2, 3))).ok


def test_drop_of_more_than_one_repeat_is_flagged():
    c = compare(BASE, tasks(a=(1, 3), b=(2, 3)))
    assert c.regressions == ["a"] and "DROP" in "\n".join(c.lines)


def test_threshold_is_configurable():
    assert compare(BASE, tasks(a=(1, 3)), threshold_repeats=2).ok
    assert not compare(BASE, tasks(a=(0, 3)), threshold_repeats=2).ok
    assert not compare(BASE, tasks(a=(2, 3)), threshold_repeats=0).ok


def test_different_repeat_counts_are_scaled():
    assert compare(BASE, tasks(a=(5, 5))).ok
    assert compare(BASE, tasks(a=(8, 10))).regressions == ["a"]  # 80% vs 100% over 10 runs = 2 repeats


def test_improvement_new_and_missing_tasks_are_reported_not_flagged():
    c = compare(BASE, tasks(b=(3, 3), c=(1, 1)))
    text = "\n".join(c.lines)
    assert c.ok and "improved" in text and "new task" in text and "not run" in text


def test_skipped_current_task_is_not_a_regression():
    cur = {"a": {"runs": 0, "passes": 0, "pass_rate": None, "graders": {}}}
    assert compare(BASE, cur).ok


def test_grader_level_drop_is_listed():
    base = {"tasks": {"a": {"runs": 3, "passes": 3, "pass_rate": 1.0, "graders": {"g": {"runs": 3, "passes": 3}}}}}
    cur = {"a": {"runs": 3, "passes": 3, "pass_rate": 1.0, "graders": {"g": {"runs": 3, "passes": 2}}}}
    assert "grader g: 3/3 -> 2/3" in "\n".join(compare(base, cur).lines)


def test_cli_exit_code_on_regression(tmp_path):
    import json
    from evals.harness import cli
    from evals.harness.results import append_results
    recs = [{"task": "a", "repeat": i, "status": "ok", "passed": i == 1, "graders": [], "cost_usd": 0, "turns": 1} for i in (1, 2, 3)]
    res = tmp_path / "r.jsonl"
    append_results(res, recs)
    base = tmp_path / "b.json"
    base.write_text(json.dumps({"tasks": tasks(a=(3, 3))}))
    assert cli.main(["compare", str(res), "--baseline", str(base)]) == 1
    assert cli.main(["compare", str(res), "--baseline", str(base), "--threshold", "2"]) == 0
