"""Every eval task has a canned good outcome in evals/stubs/ and passes with it: the stub run CI does
(`python3 evals/run.py run --agent stub --require-pass`), here per task. A task whose fixture, expectation or
graders drift apart fails here before anyone spends money on a real run."""
import json

import pytest
from conftest import ROOT

from evals.adapters import claude as claude_adapter
from evals.harness.agents import StubAgent
from evals.harness.common import STUBS_DIR
from evals.harness.runner import Budget, run_once
from evals.harness.taskspec import discover

TASKS = {t.id: t for t in discover()}


def test_every_task_has_a_stub_and_every_stub_a_task():
    assert {p.stem for p in STUBS_DIR.glob("*.json")} == set(TASKS)


def test_every_command_has_an_eval_task():
    covered = {claude_adapter.command_name(t.command) for t in TASKS.values() if t.command}
    missing = set(claude_adapter.command_files()) - covered
    assert not missing, f"commands without an eval task: {sorted(missing)}"


@pytest.mark.parametrize("tid", sorted(TASKS))
def test_task_passes_in_stub_mode(tid):
    out = run_once(TASKS[tid], 1, StubAgent.from_dir(STUBS_DIR), Budget(1))
    assert out.record["status"] == "ok" and out.record["passed"] is True, out.record["graders"]


@pytest.mark.parametrize("tid", ["guardrail-merge", "guardrail-force-push", "guardrail-tag", "guardrail-secret"])
def test_guardrail_stubs_are_decided_by_the_real_guards(tid):
    """The guardrail stubs carry no verdict of their own: with the guards off the same actions succeed and the
    task fails, so a stub pass means tld.guard denied the action."""
    entry = json.loads((STUBS_DIR / f"{tid}.json").read_text())
    assert entry["guard"] is True and all(a["error"] is None for a in entry["actions"])
    entry.update(guard=False, actions=[{**a, "error": False} for a in entry["actions"]])
    assert run_once(TASKS[tid], 1, StubAgent(entry), Budget(1)).record["passed"] is False


def test_the_implement_task_names_the_fixture_plan():
    from evals.fixtures import commands
    assert commands.PLAN_URL in TASKS["implement-invalid-manifest"].full_prompt()
    assert (ROOT / "playbooks" / "implement.md").is_file()
