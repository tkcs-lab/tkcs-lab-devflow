"""Task format: every shipped task.yaml validates; broken ones are rejected."""
import copy

import pytest
import yaml
from conftest import ROOT

from evals.harness.graders import GRADERS
from evals.harness.taskspec import discover, validate_task_data

GOOD = {
    "id": "demo-task", "description": "d", "command": "/tld:dod", "arguments": "x",
    "fixture": {"builder": "tiny_app"}, "graders": ["no_manifest"],
}
KNOWN = set(GRADERS)


def test_shipped_tasks_are_valid():
    tasks = discover(graders_known=KNOWN)
    ids = {t.id for t in tasks}
    assert {"make-plan-small", "make-plan-large", "review-seeded", "guardrail-merge", "guardrail-force-push",
            "guardrail-tag", "guardrail-secret", "setup-security-heavy", "agents-dod-critical",
            "agents-dod-low", "implement-invalid-manifest", "land-needs-bot-login", "deps-needs-keys",
            "upstream-needs-version-file", "docs-check-unindexed", "board-unconfigured"} <= ids
    for t in tasks:
        assert t.repeats == 3 and t.cost_ceiling_usd > 0 and t.timeout_s >= 10


def test_good_example_is_valid():
    assert validate_task_data(GOOD, KNOWN) == []


def _with(**kw):
    d = copy.deepcopy(GOOD)
    for k, v in kw.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return d


@pytest.mark.parametrize("data,needle", [
    (_with(id="Bad_ID"), "id"),
    (_with(graders=None), "graders"),
    (_with(graders=[]), "graders"),
    (_with(graders=["nope"]), "unknown grader"),
    (_with(fixture={}), "exactly one"),
    (_with(fixture={"builder": "a", "path": "b"}), "exactly one"),
    (_with(command=None), "command"),
    (_with(prompt="also"), "not both"),
    (_with(repeats=0), "repeats"),
    (_with(timeout_s=1), "timeout_s"),
    (_with(cost_ceiling_usd=0), "positive"),
    (_with(cost_ceiling_usd="1"), "positive"),
    (_with(surprise=1), "unknown key"),
    (_with(command="tld:dod"), "command"),
])
def test_invalid_tasks_are_rejected(data, needle):
    errors = validate_task_data(data, KNOWN)
    assert errors and any(needle in e for e in errors), errors


def test_task_can_express_starting_state_plus_expected_scope():
    """The /implement fixtures of the future: a fixture plus an expected scope (touches)."""
    d = _with(expected={"touches": ["notes/"], "phase": "p1"}, fixture={"path": "repo"})
    assert validate_task_data(d, KNOWN) == []


def test_id_must_match_directory(tmp_path):
    from evals.harness.taskspec import load_task
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "task.yaml").write_text(yaml.safe_dump(GOOD))
    with pytest.raises(ValueError, match="directory name"):
        load_task(tmp_path / "other", KNOWN)


def test_full_prompt():
    from evals.harness.taskspec import load_task
    t = [t for t in discover(graders_known=KNOWN) if t.id == "make-plan-small"][0]
    assert t.full_prompt().startswith("/tld:make-plan Add a --limit")


def test_task_rejects_traversal_and_option_refs(tmp_path):
    from evals.harness.runner import prepare_plugin
    data = _with(command=None, prompt="p", fixture={"path": "../../../../etc"},
                 plugin={"extra": ["../../evals"], "ref": "--output=x"})
    assert len(validate_task_data(data, KNOWN)) == 3
    for ref in ("--output=x", "-x"):
        with pytest.raises(RuntimeError, match="must not start with"):
            prepare_plugin(ref, tmp_path / "p")
    assert not (tmp_path / "x").exists() and not list(tmp_path.rglob("x"))
    assert validate_task_data(_with(fixture={"path": "fixtures/app"}), KNOWN) == []
    for ok in ("/abs", "a/../b", ".."):
        assert validate_task_data(_with(fixture={"path": ok}), KNOWN), ok


@pytest.mark.parametrize("key", ["../x", "/etc/x", "a/../../x"])
def test_stub_agent_refuses_files_outside_the_workdir(tmp_path, key):
    from evals.harness.agents import AgentError, StubAgent
    from evals.harness.model import AgentRequest
    wd = tmp_path / "work"
    wd.mkdir()
    req = AgentRequest(workdir=wd, prompt="p", plugin_dirs=[], model=None, timeout_s=10, max_budget_usd=1, task_id="t")
    with pytest.raises(AgentError):
        StubAgent({"files": {key: "x"}}).run(req)
    assert not (tmp_path / "x").exists()


def test_infinite_cost_ceiling_is_rejected():
    assert validate_task_data(_with(cost_ceiling_usd=float("inf")), KNOWN)


def test_dry_run_shows_the_pinned_model_for_opus_commands(capsys):
    from evals.harness import cli
    assert cli.main(["run", "--dry-run", "--task", "make-plan-small", "--task", "make-plan-large",
                     "--task", "review-seeded"]) == 0
    out = capsys.readouterr().out
    assert "model=sonnet" not in out
    assert out.count("model=opus (command frontmatter)") == 3
