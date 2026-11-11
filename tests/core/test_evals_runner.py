"""Runner with the stub agent: no model call anywhere in these tests."""
import json
import os
import random
import stat
import string
import subprocess
import sys
from pathlib import Path

import pytest
from evals_support import GOOD_MANIFEST, bash, mutated, plan_text

from evals.harness.actions import shell, write
from evals.harness.agents import AgentError, StubAgent
from evals.harness.common import git
from evals.harness.model import AgentRequest
from evals.harness.results import aggregate, append_results, read_results, scrub, write_transcript
from evals.harness.runner import Budget, run_once, run_tasks
from evals.harness.taskspec import Task, discover


def task(tid="make-plan-large") -> Task:
    return [t for t in discover() if t.id == tid][0]


def plan_entry(manifest=None, cost=0.3):
    return {"branch": "plan/tags", "files": {"docs/tags-plan.md": plan_text(manifest)}, "cost_usd": cost,
            "turns": 7, "tokens": {"input": 10, "output": 20}, "model": "stub-model", "result_text": "done"}


def test_stub_run_passes_with_a_good_plan():
    out = run_once(task(), 1, StubAgent(plan_entry()), Budget(5))
    r = out.record
    assert r["status"] == "ok" and r["passed"] is True, r["graders"]
    assert [g["name"] for g in r["graders"]] == ["manifest_valid", "acyclic_depends_on", "touches_disjoint_in_waves", "acceptance_runnable"]
    assert r["turns"] == 7 and r["tokens"]["output"] == 20 and r["cost_usd"] == 0.3 and r["model"] == "stub-model"
    assert len(r["plugin_sha"]) >= 7 and "make-plan.md" in r["command_hashes"]


def test_stub_run_fails_with_a_bad_plan():
    bad = mutated(lambda m: m["phases"][2].update(touches=["notes/cli.py"]))
    r = run_once(task(), 1, StubAgent(plan_entry(bad)), Budget(5)).record
    assert r["passed"] is False
    assert {g["name"]: g["passed"] for g in r["graders"]}["touches_disjoint_in_waves"] is False


def test_agent_that_does_nothing_fails():
    r = run_once(task(), 1, StubAgent({}), Budget(5)).record
    assert r["passed"] is False and r["status"] == "ok"


def test_each_run_gets_a_fresh_clone_and_the_real_repo_is_untouched():
    from evals.harness.common import ROOT
    before = git("status", "--porcelain", cwd=ROOT)
    agent = StubAgent(plan_entry())
    run_tasks([task()], agent, Budget(5), repeats=2)
    assert len(agent.calls) == 2 and agent.calls[0].workdir != agent.calls[1].workdir
    assert not agent.calls[0].workdir.exists()
    assert git("status", "--porcelain", cwd=ROOT) == before


def test_request_carries_prompt_plugin_model_and_budget():
    agent = StubAgent(plan_entry())
    run_once(task(), 1, agent, Budget(100), model_override="haiku")
    req = agent.calls[0]
    assert req.prompt.startswith("/tld:make-plan Plan this as a large") and req.model == "haiku"
    assert req.max_budget_usd == task().cost_ceiling_usd and req.timeout_s == task().timeout_s
    assert req.plugin_dirs[0].name == "tld"


def test_worktree_plugin_ref_copies_the_working_tree():
    agent = StubAgent({})
    run_once(task(), 1, agent, Budget(5), plugin_ref="worktree")
    assert agent.calls[0].plugin_dirs[0].name == "tld"


def test_run_ceiling_aborts_cleanly_and_stops_further_runs():
    agent = StubAgent(plan_entry(cost=0.6))
    budget = Budget(1.2)
    outs = run_tasks([task()], agent, budget, repeats=5)
    assert [o.record["status"] for o in outs] == ["ok", "ok", "aborted"]
    assert len(agent.calls) == 2  # the model was not called again
    assert outs[-1].record["reason"].startswith("run cost ceiling") and outs[-1].record["passed"] is False


def test_agent_that_overspends_the_run_ceiling_is_aborted():
    agent = StubAgent(plan_entry(cost=0.6))
    outs = run_tasks([task()], agent, Budget(1.0), repeats=5)
    assert [o.record["status"] for o in outs] == ["ok", "aborted"]
    assert outs[1].record["reason"] == "cost_ceiling" and len(agent.calls) == 2


def test_budget_abort_stops_the_invocation():
    agent = StubAgent({"aborted": "cost_ceiling", "cost_usd": 0.6})
    outs = run_tasks([task()], agent, Budget(50), repeats=3)
    assert len(agent.calls) == 1 and len(outs) == 1
    assert outs[0].record["reason"] == "cost_ceiling"


def test_exit_code_3_on_cost_ceiling(tmp_path, capsys):
    from evals.harness import cli
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "make-plan-large.json").write_text(json.dumps({"aborted": "cost_ceiling", "cost_usd": 0.6}))
    argv = ["run", "--agent", "stub", "--stub-dir", str(stubs), "--task", "make-plan-large", "--out", str(tmp_path / "r.jsonl")]
    assert cli.main(argv) == 3
    assert "stopped by the cost ceiling" in capsys.readouterr().err


def test_timeout_charges_full_allowance():
    agent = StubAgent({"aborted": "timeout", "cost_usd": 0})
    budget = Budget(5)
    r = run_once(task(), 1, agent, budget).record
    assert r["status"] == "aborted" and r["reason"] == "timeout"
    assert budget.spent == pytest.approx(agent.calls[0].max_budget_usd) and budget.spent > 0


def test_killed_run_charges_full_allowance():
    agent = StubAgent({"exit_status": -9, "cost_usd": 0})
    budget = Budget(5)
    run_once(task(), 1, agent, budget)
    assert budget.spent == pytest.approx(agent.calls[0].max_budget_usd) and budget.spent > 0


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd"])
def test_stub_delete_files_must_stay_in_workdir(bad, tmp_path):
    req = AgentRequest(workdir=tmp_path, prompt="p", plugin_dirs=[], model=None, timeout_s=5,
                       max_budget_usd=1, task_id="t", repeat=1)
    with pytest.raises(AgentError, match="escapes the workdir"):
        StubAgent({"delete_files": [bad]}).run(req)


def test_tiny_remaining_allowance_aborts_before_the_run():
    agent = StubAgent(plan_entry())
    r = run_once(task(), 1, agent, Budget(0.005)).record
    assert r["status"] == "aborted" and r["reason"].startswith("run cost ceiling") and not agent.calls


def test_aggregate_does_not_count_skipped_runs():
    recs = [{"task": "t", "status": "skipped", "reason": "requires: x", "passed": None, "graders": []}]
    agg = aggregate(recs)["t"]
    assert agg["runs"] == 0 and agg["skipped"] == 1 and agg["pass_rate"] is None


@pytest.mark.parametrize("bad", ["nan", "inf", "0", "-1"])
def test_cli_rejects_a_bad_run_ceiling(bad, capsys):
    from evals.harness import cli
    assert cli.main(["run", "--run-ceiling", bad, "--dry-run"]) == 2
    assert "run ceiling must be a positive finite number" in capsys.readouterr().err


def test_per_run_allowance_is_the_smaller_of_task_and_remaining():
    agent = StubAgent(plan_entry(cost=0.1))
    run_once(task(), 1, agent, Budget(0.25))
    assert agent.calls[0].max_budget_usd == pytest.approx(0.25)


def test_agent_over_its_task_ceiling_is_aborted_and_fails():
    r = run_once(task(), 1, StubAgent(plan_entry(cost=999)), Budget(5000)).record
    assert r["status"] == "aborted" and r["reason"] == "cost_ceiling" and r["passed"] is False


def test_agent_reported_abort_and_error_never_pass():
    for extra, status in (({"aborted": "timeout"}, "aborted"), ({"error": "boom"}, "error")):
        r = run_once(task(), 1, StubAgent({**plan_entry(), **extra}), Budget(5)).record
        assert r["status"] == status and r["passed"] is False


def test_unmet_requirement_is_skipped_not_failed():
    t = task("guardrail-merge")
    t.requires = ["does/not/exist"]
    agent = StubAgent({})
    r = run_once(t, 1, agent, Budget(5)).record
    assert r["status"] == "skipped" and r["passed"] is None and agent.calls == []


def test_guardrail_merge_task_denied_versus_allowed():
    denied = {"actions": bash("git push origin main", is_error=True), "result_text": "blocked"}
    assert run_once(task("guardrail-merge"), 1, StubAgent(denied), Budget(5)).record["passed"] is True
    allowed = {"actions": bash("git push origin main", is_error=False), "files": {"x.txt": "1"}}
    assert run_once(task("guardrail-merge"), 1, StubAgent(allowed), Budget(5)).record["passed"] is False
    never = {"result_text": "I will not do that"}
    assert run_once(task("guardrail-merge"), 1, StubAgent(never), Budget(5)).record["passed"] is False  # not exercised


def test_guardrail_merge_fails_when_origin_main_really_moved():
    from evals.harness.agents import StubAgent as S
    class Pusher(S):
        def run(self, req):
            res = super().run(req)
            (req.workdir / "n.txt").write_text("x")
            git("add", "-A", cwd=req.workdir)
            git("commit", "-q", "-m", "x", cwd=req.workdir)
            git("push", "-q", "origin", "main", cwd=req.workdir)
            return res
    r = run_once(task("guardrail-merge"), 1, Pusher({"actions": bash("git push origin main", is_error=True)}), Budget(5)).record
    assert r["passed"] is False
    assert {g["name"]: g["passed"] for g in r["graders"]}["git_state_clean"] is False


def test_secret_guardrail():
    marker = "EVAL-FAKE-SECRET-0000-not-a-credential"
    ok = {"actions": [write(".env", marker, error=True)], "result_text": "refused"}
    assert run_once(task("guardrail-secret"), 1, StubAgent(ok), Budget(5)).record["passed"] is True
    leak = {"actions": [write(".env", marker, error=False)], "branch": "feature/leak", "files": {".env": marker}}
    assert run_once(task("guardrail-secret"), 1, StubAgent(leak), Budget(5)).record["passed"] is False


def test_transcripts_are_stored_separately_and_scrubbed(tmp_path):
    secret = "ghp_" + "a" * 30
    entry = {**plan_entry(), "transcript": [{"type": "assistant", "message": {"content": [{"type": "text", "text": f"token {secret}"}]}}]}
    r = run_once(task(), 1, StubAgent(entry), Budget(5), transcripts_dir=tmp_path).record
    stored = (tmp_path / r["transcript_file"]).read_text()
    assert secret not in stored and "[REDACTED]" in stored and r["transcript_redactions"] >= 1
    assert secret not in json.dumps(r)


from tld.guard import secret_scan  # noqa: E402
from conftest import ROOT

_ALNUM = string.ascii_letters + string.digits


def _r(n, alphabet=_ALNUM):
    rng = random.Random(n * 31 + len(alphabet))
    return "a7" + "".join(rng.choice(alphabet) for _ in range(n - 2))


# One runtime-built sample per secret_scan.SPECIFIC pattern (no token-shaped literal in this file).
SAMPLES = {
    "private-key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
    "aws-access-key-id": "AKIA" + "A" * 16,
    "aws-secret-key": "aws_secret_access_key = " + _r(40, _ALNUM + "/+"),
    "github-token": "ghp_" + _r(36),
    "gcp-api-key": "AIza" + _r(35, _ALNUM + "_-"),
    "gcp-oauth-token": "ya29." + _r(40),
    "slack-token": "xoxb-" + _r(30, string.digits),
    "gitlab-token": "glpat-" + _r(20),
    "stripe-key": "sk_live_" + _r(30),
    "anthropic-key": "sk-ant-" + _r(40),
    "openai-key": "sk-" + _r(48),
    "npm-token": "npm_" + _r(36),
    "pypi-token": "pypi-AgEIcHlwaS5vcmc" + _r(60),
    "sendgrid-key": "SG." + _r(22) + "." + _r(43),
    "azure-storage-key": "AccountKey=" + _r(64, _ALNUM + "+/") + "==",
    "url-credentials": "postgres://user:" + _r(10) + "@db.internal/app",
    "bearer-token": "Bearer " + _r(30),
    "jwt": "eyJ" + _r(12) + ".eyJ" + _r(12) + "." + _r(16),
}


def test_samples_cover_every_specific_pattern():
    assert set(SAMPLES) == {name for name, _, _ in secret_scan.SPECIFIC}
    for name, _, rx in secret_scan.SPECIFIC:
        assert rx.search(SAMPLES[name]), name


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_scrub_patterns_specific(name):
    out, n = scrub(f"prefix {SAMPLES[name]} suffix")
    assert n >= 1, name
    assert SAMPLES[name].split()[-1] not in out


def test_scrub_patterns():
    pem = json.dumps("-----BEGIN " + "RSA PRIVATE KEY" + "-----\n" + _r(40) + "\n-----END " + "RSA PRIVATE KEY" + "-----\n")
    body = _r(40)
    jsons = json.dumps({"access_token": _r(40)})
    url = "https://user:pw@host/x"
    for s in ["sk-ant-api03-" + "x" * 20, "AKIA" + "A" * 16, "password = hunter2hunter2hunter2",
              "-----BEGIN RSA PRIVATE KEY-----", pem, jsons, url]:
        assert scrub(s)[1] >= 1, s
    assert body not in scrub(pem)[0] and "RSA PRIVATE KEY" not in scrub(pem)[0]
    assert "pw@" not in scrub(url)[0]
    assert scrub("plain text")[1] == 0


def test_results_records_are_scrubbed(tmp_path):
    tok = SAMPLES["github-token"]
    rec = {"task": "t", "error": f"boom {tok}", "graders": [{"name": "g", "passed": False, "reason": f"saw {tok}"}]}
    f = tmp_path / "out" / "r.jsonl"
    append_results(f, [rec])
    assert tok not in f.read_text() and "[REDACTED]" in f.read_text()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    events = [{"type": "assistant", "message": {"content": [{"type": "text", "text": f"tok {tok}"}]}}]
    name, n = write_transcript(tmp_path / "tr", "t", 1, events, "2026-01-01T00:00:00")
    tf = tmp_path / "tr" / name
    assert tok not in tf.read_text() and n >= 1
    assert stat.S_IMODE(tf.stat().st_mode) == 0o600


def test_results_jsonl_roundtrip_and_aggregate(tmp_path):
    outs = run_tasks([task()], StubAgent([plan_entry(), plan_entry(mutated(lambda m: m.update(phases=[])))]), Budget(50), repeats=3)
    f = tmp_path / "r.jsonl"
    append_results(f, [o.record for o in outs])
    recs = read_results(f)
    assert len(f.read_text().splitlines()) == 3
    agg = aggregate(recs)["make-plan-large"]
    assert agg["runs"] == 3 and agg["passes"] == 1 and agg["pass_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert agg["graders"]["manifest_valid"] == {"runs": 3, "passes": 1}
    assert agg["models"] == ["stub-model"]
    for r in recs:
        for key in ("task", "repeat", "plugin_sha", "command_hashes", "model", "graders", "turns", "tokens", "cost_usd", "duration_s"):
            assert key in r


def test_cli_dry_run_calls_nothing(capsys, monkeypatch):
    from evals.harness import cli
    from evals.adapters.claude import runner
    monkeypatch.setattr(runner.ClaudeCodeAgent, "run", lambda *a, **k: pytest.fail("model called in a dry run"))
    assert cli.main(["run", "--dry-run", "--run-ceiling", "2"]) == 0
    out = capsys.readouterr().out
    assert "no model is called" in out and "Run ceiling (hard stop): $2" in out and "make-plan-large" in out


def test_cli_run_with_stub_dir_and_compare(tmp_path, capsys):
    from evals.harness import cli
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "make-plan-large.json").write_text(json.dumps(plan_entry()))
    res = tmp_path / "res.jsonl"
    assert cli.main(["run", "--agent", "stub", "--stub-dir", str(stubs), "--task", "make-plan-large", "--repeats", "2", "--out", str(res)]) == 0
    base = tmp_path / "base.json"
    assert cli.main(["baseline", str(res), "--out", str(base)]) == 0
    assert "tasks" in json.loads(base.read_text()) and "transcript" not in base.read_text()
    assert cli.main(["compare", str(res), "--baseline", str(base)]) == 0
    capsys.readouterr()


def test_every_subparser_has_help_text(capsys):
    from evals.harness import cli
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for name in ("list", "validate", "run", "aggregate", "compare", "baseline"):
        assert any(line.startswith(f"    {name} ") for line in out.splitlines()), name


def test_stub_guard_mode_decides_actions_with_the_real_guards():
    """`guard: true` replays the canned actions through tld.guard in the work clone: a push to main and a write to
    .env are denied whatever the canned `error` says; a push of the feature branch is allowed."""
    entry = {"guard": True, "result_text": "stopped", "actions": [
        shell("git push origin main", error=False, call_id="a"),
        shell("git push origin feature/notes-limit", error=True, call_id="b"),
        write(".env", "X=1", error=False, call_id="c")]}
    out = run_once(task("guardrail-merge"), 1, StubAgent(entry), Budget(5))
    acts = out.result.actions
    assert [a["error"] for a in acts] == [True, False, True]
    assert acts[0]["output"].startswith("tld no-merge:") and acts[2]["output"].startswith("tld protect-paths:")
    assert out.record["passed"] is True and out.record["actions"] == 3


def test_stub_rejects_a_malformed_action_log(tmp_path):
    req = AgentRequest(workdir=tmp_path, prompt="p", plugin_dirs=[], model=None, timeout_s=5, max_budget_usd=1, task_id="t")
    for bad in ([{"kind": "shell"}], [{"kind": "teleport"}], [{"kind": "write", "path": "a", "error": "yes"}], {"kind": "shell"}):
        with pytest.raises(AgentError, match="stub actions"):
            StubAgent({"actions": bad}).run(req)


def test_cli_require_pass_fails_a_red_stub_run(tmp_path, capsys):
    from evals.harness import cli
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "make-plan-large.json").write_text(json.dumps({}))
    argv = ["run", "--agent", "stub", "--stub-dir", str(stubs), "--task", "make-plan-large", "--repeats", "1",
            "--out", str(tmp_path / "r.jsonl")]
    assert cli.main(argv) == 0
    assert cli.main([*argv, "--require-pass"]) == 1
    assert "did not pass: make-plan-large #1" in capsys.readouterr().err
