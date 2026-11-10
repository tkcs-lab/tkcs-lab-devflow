"""Hook-only tests: feed the guardrail hook scripts directly, no model call.

The harness (evals/harness/hookcheck.py) is tested against throwaway hooks now. The cases in
evals/hook_cases.yaml run against plugins/devflow/hooks/hooks.json as soon as the guardrail hooks exist
(until then that test is skipped, and the guardrail-* tasks are skipped with the same reason).
"""
import json
import stat

import pytest

from evals.harness.hookcheck import CASES, HOOKS_JSON, decide, load_cases, pretooluse_hooks


def make_plugin(tmp_path, script: str, matcher="Bash"):
    root = tmp_path / "plug"
    (root / "hooks").mkdir(parents=True)
    (root / "scripts").mkdir()
    sh = root / "scripts" / "h.sh"
    sh.write_text("#!/bin/bash\n" + script)
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    (root / "hooks" / "hooks.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": matcher, "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/h.sh"}]}]}}))
    return root / "hooks" / "hooks.json"


def test_exit_2_denies(tmp_path):
    hj = make_plugin(tmp_path, 'grep -q "git merge" && { echo "no merges" >&2; exit 2; }; exit 0\n')
    assert decide(hj, "Bash", {"command": "git merge x"}, tmp_path) == ("deny", "no merges")
    assert decide(hj, "Bash", {"command": "git status"}, tmp_path)[0] == "allow"


def test_json_deny_decision_denies(tmp_path):
    hj = make_plugin(tmp_path, 'cat >/dev/null; echo \'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"r"}}\'\n')
    assert decide(hj, "Bash", {"command": "x"}, tmp_path) == ("deny", "r")


def test_other_exit_codes_do_not_deny(tmp_path):
    hj = make_plugin(tmp_path, "exit 1\n")
    assert decide(hj, "Bash", {"command": "git merge"}, tmp_path)[0] == "allow"  # non-blocking error per the hooks docs


def test_matcher_limits_the_tools(tmp_path):
    hj = make_plugin(tmp_path, "exit 2\n", matcher="Bash")
    assert pretooluse_hooks(hj, "Edit") == []
    assert decide(hj, "Edit", {}, tmp_path)[0] == "allow"


def test_payload_follows_the_documented_shape(tmp_path):
    hj = make_plugin(tmp_path, 'python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(2 if d[\'tool_name\']==\'Bash\' and d[\'hook_event_name\']==\'PreToolUse\' and d[\'tool_input\'][\'command\']==\'x\' else 0)"\n')
    assert decide(hj, "Bash", {"command": "x"}, tmp_path)[0] == "deny"


def test_case_file_is_well_formed():
    cases = load_cases()
    assert len({c["name"] for c in cases}) == len(cases)
    assert {c["expect"] for c in cases} == {"deny", "allow"}
    for c in cases:
        assert set(c) == {"name", "tool", "input", "expect"}


def test_case_file_agrees_with_the_transcript_classifier():
    """The same commands the hook must deny are the ones the forbidden_ops graders look for."""
    from evals.harness.graders import classify_command
    for c in load_cases():
        if c["tool"] == "Bash":
            assert bool(classify_command(c["input"]["command"])) == (c["expect"] == "deny"), c["name"]


@pytest.mark.skipif(not HOOKS_JSON.exists(), reason="plugins/devflow/hooks/hooks.json not in this checkout (guardrail hooks plan not merged)")
@pytest.mark.parametrize("case", load_cases() if CASES.exists() else [], ids=lambda c: c["name"])
def test_real_hooks(case, tmp_path):
    verdict, reason = decide(HOOKS_JSON, case["tool"], case["input"], tmp_path)
    assert verdict == case["expect"], reason
