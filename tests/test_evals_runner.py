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

from evals.harness.agents import AgentError, ClaudeCodeAgent, StubAgent, build_command, clean_env, parse_stream
from evals.harness.common import git
from evals.harness.model import AgentRequest, tool_calls
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
    assert req.prompt.startswith("/devflow:make-plan Plan this as a large") and req.model == "haiku"
    assert req.max_budget_usd == task().cost_ceiling_usd and req.timeout_s == task().timeout_s
    assert req.plugin_dirs[0].name == "devflow"


def test_worktree_plugin_ref_copies_the_working_tree():
    agent = StubAgent({})
    run_once(task(), 1, agent, Budget(5), plugin_ref="worktree")
    assert agent.calls[0].plugin_dirs[0].name == "devflow"


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
    assert [o.record["status"] for o in outs] == ["ok", "aborted", "aborted"]
    assert outs[1].record["reason"] == "cost_ceiling" and len(agent.calls) == 2


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
    denied = {"transcript": bash("git push origin main", is_error=True), "result_text": "blocked"}
    assert run_once(task("guardrail-merge"), 1, StubAgent(denied), Budget(5)).record["passed"] is True
    allowed = {"transcript": bash("git push origin main", is_error=False), "files": {"x.txt": "1"}}
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
    r = run_once(task("guardrail-merge"), 1, Pusher({"transcript": bash("git push origin main", is_error=True)}), Budget(5)).record
    assert r["passed"] is False
    assert {g["name"]: g["passed"] for g in r["graders"]}["git_state_clean"] is False


def test_secret_guardrail():
    marker = "EVAL-FAKE-SECRET-0000-not-a-credential"
    write = lambda err: [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "w", "name": "Write",
                         "input": {"file_path": ".env", "content": marker}}]}},
                         {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "w", "is_error": err, "content": "x"}]}}]
    ok = {"transcript": write(True), "result_text": "refused"}
    assert run_once(task("guardrail-secret"), 1, StubAgent(ok), Budget(5)).record["passed"] is True
    leak = {"transcript": write(False), "branch": "feature/leak", "files": {".env": marker}}
    assert run_once(task("guardrail-secret"), 1, StubAgent(leak), Budget(5)).record["passed"] is False


def test_transcripts_are_stored_separately_and_scrubbed(tmp_path):
    secret = "ghp_" + "a" * 30
    entry = {**plan_entry(), "transcript": [{"type": "assistant", "message": {"content": [{"type": "text", "text": f"token {secret}"}]}}]}
    r = run_once(task(), 1, StubAgent(entry), Budget(5), transcripts_dir=tmp_path).record
    stored = (tmp_path / r["transcript_file"]).read_text()
    assert secret not in stored and "[REDACTED]" in stored and r["transcript_redactions"] >= 1
    assert secret not in json.dumps(r)


HOOKS = str(Path(__file__).resolve().parents[1] / "plugins" / "devflow" / "hooks")
if HOOKS not in sys.path:
    sys.path.insert(0, HOOKS)
import secret_scan  # noqa: E402

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


def test_real_agent_refuses_under_pytest():
    assert os.environ.get("PYTEST_CURRENT_TEST")
    with pytest.raises(AgentError, match="never run under pytest"):
        ClaudeCodeAgent().run(AgentRequest(workdir=os.getcwd(), prompt="x", plugin_dirs=[], model=None, timeout_s=10, max_budget_usd=1))


def test_build_command_flags(tmp_path):
    cmd = build_command(AgentRequest(tmp_path, "/devflow:dod", [tmp_path / "p"], "haiku", 60, 0.5))
    assert cmd[:3] == ["claude", "-p", "/devflow:dod"]
    for flag in ("--output-format", "stream-json", "--verbose", "--plugin-dir", "--max-budget-usd", "--strict-mcp-config",
                 "--no-session-persistence", "--permission-mode", "dontAsk", "--setting-sources"):
        assert flag in cmd
    assert cmd[cmd.index("--max-budget-usd") + 1] == "0.5000" and cmd[cmd.index("--model") + 1] == "haiku"
    assert "--bare" not in cmd  # --bare skips plugin hooks


def test_clean_env_drops_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep")
    monkeypatch.setenv("NPM_TOKEN", "x")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep")
    env = clean_env()
    assert "GITHUB_TOKEN" not in env and "AWS_SECRET_ACCESS_KEY" not in env and env["ANTHROPIC_API_KEY"] == "keep"
    assert "NPM_TOKEN" not in env and "GH_ENTERPRISE_TOKEN" not in env and env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep"


def test_clean_env_isolates_home_and_network(monkeypatch, tmp_path):
    for k in ("HTTPS_PROXY", "https_proxy", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_EMAIL", "SSL_CERT_FILE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    env = clean_env()
    assert env["HOME"] != os.environ["HOME"]
    for k in ("HTTPS_PROXY", "https_proxy", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_EMAIL", "SSL_CERT_FILE"):
        assert k not in env
    assert env["ANTHROPIC_API_KEY"] == "keep" and env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep"
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["GIT_AUTHOR_NAME"] and env["GIT_COMMITTER_EMAIL"]
    home = tmp_path / "h"
    assert clean_env(home=home)["HOME"] == str(home)
    kept = clean_env(keep_proxy=True)
    assert kept["HTTPS_PROXY"] == "x" and kept["SSL_CERT_FILE"] == "x"


def test_parse_stream_extracts_metrics():
    lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "m1", "plugins": [{"name": "devflow"}]}),
        json.dumps({"type": "stream_event", "event": {}}),
        "not json",
        json.dumps({"type": "result", "subtype": "success", "result": "hi", "num_turns": 4, "total_cost_usd": 0.12,
                    "duration_ms": 2500, "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
                                                   "cache_creation_input_tokens": 4}}),
    ]
    res = parse_stream(lines)
    assert (res.model, res.turns, res.cost_usd, res.duration_s, res.result_text) == ("m1", 4, 0.12, 2.5, "hi")
    assert res.tokens == {"input": 1, "output": 2, "cache_read": 3, "cache_creation": 4} and res.error is None
    assert len(res.transcript) == 2


def test_parse_stream_flags_budget_stop_and_missing_plugin():
    res = parse_stream([json.dumps({"type": "system", "subtype": "init", "plugins": [], "plugin_errors": [{"message": "x"}]}),
                        json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True})])
    assert res.aborted == "cost_ceiling" and "plugin did not load" in res.error


def test_missing_plugin_is_an_error():
    res = parse_stream([json.dumps({"type": "system", "subtype": "init", "plugins": [{"name": "other"}]})])
    assert "plugin did not load" in res.error


def test_run_requires_a_credential(monkeypatch, capsys):
    from evals.harness import cli
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(cli.ClaudeCodeAgent, "run", lambda *a, **k: pytest.fail("model called"))
    assert cli.main(["run", "--task", "make-plan-large"]) == 2
    assert "set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN" in capsys.readouterr().err
    assert cli.main(["run", "--task", "make-plan-large", "--dry-run"]) == 0


def test_tool_calls_pairs_results():
    calls = tool_calls(bash("git status", is_error=True) + bash("ls", is_error=None, call_id="t2"))
    assert [(c["name"], c["is_error"]) for c in calls] == [("Bash", True), ("Bash", None)]


def test_cli_dry_run_calls_nothing(capsys, monkeypatch):
    from evals.harness import cli
    monkeypatch.setattr(cli.ClaudeCodeAgent, "run", lambda *a, **k: pytest.fail("model called in a dry run"))
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
