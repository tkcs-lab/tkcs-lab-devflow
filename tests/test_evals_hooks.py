"""Hook-only tests: feed the guardrail hook scripts directly, no model call.

The harness (evals/harness/hookcheck.py) is tested against throwaway hooks, and the cases in
evals/hook_cases.yaml run against plugins/devflow/hooks/hooks.json (skipped if a checkout has no hooks).
"""
import json
import stat

import pytest

from evals.harness.hookcheck import HOOKS_JSON, decide, load_cases, pretooluse_hooks


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
    """For the three operations the forbidden_ops graders look for, the classifier and the hook cases agree."""
    from evals.harness.graders import classify_command
    for c in load_cases():
        cmd = c["input"].get("command", "")
        if c["tool"] == "Bash" and cmd.startswith("git") and ".env" not in cmd:
            assert bool(classify_command(cmd)) == (c["expect"] == "deny"), c["name"]


GH_TOKEN = "ghp_" + "Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0hJ3lM6"  # built here, token-shaped, not a credential


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory):
    """The cwd of the hooks: a repository with the tiny_app profile (main branch `main`)."""
    from evals.fixtures import builder
    d = tmp_path_factory.mktemp("hookrepo") / "r"
    builder("tiny_app").build(d)
    return d


@pytest.mark.skipif(not HOOKS_JSON.exists(), reason="plugins/devflow/hooks/hooks.json is not in this checkout")
@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["name"])
def test_real_hooks(case, fixture_repo):
    tool_input = json.loads(json.dumps(case["input"]).replace("@@GH_TOKEN@@", GH_TOKEN))
    verdict, reason = decide(HOOKS_JSON, case["tool"], tool_input, fixture_repo)
    assert verdict == case["expect"], reason
    if verdict == "deny":
        assert GH_TOKEN not in reason  # the hook must not echo a secret back
