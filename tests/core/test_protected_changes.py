import re

from conftest import ROOT

POLICY = ROOT / "playbooks" / "policies" / "protected-changes.md"
RUNTIME = ROOT / "playbooks" / "runtime.md"
SKILL = ROOT / "adapters" / "claude" / "skills" / "runtime" / "SKILL.md"
STEWARD = ROOT / "playbooks" / "policies" / "pr-steward.md"


def section(text, heading):
    match = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, heading
    return match.group(1)


def test_the_policy_has_its_sections_and_six_steps():
    text = POLICY.read_text()
    assert text.startswith("# Protected changes\n")
    for heading in ("## What is protected", "## The report line", "## The flow", "## Main's profile only"):
        assert re.search(rf"^{re.escape(heading)}$", text, re.M), heading
    flow = section(text, "## The flow")
    assert re.findall(r"^(\d+)\. ", flow, re.M) == ["1", "2", "3", "4", "5", "6"]


def test_the_flow_holds_the_safety_steps():
    text = POLICY.read_text()
    flow = section(text, "## The flow")
    for needle in ("sha256", "patch --dry-run", "Never merge", "protected-change skipped:", "needs_you"):
        assert needle in flow, needle
    for needle in ("untrusted-text.md", ".env*"):
        assert needle in text, needle


def test_the_policy_names_no_runtime_tool():
    text = POLICY.read_text()
    for name in ("create_or_update_file", "create_session", "send_message", "Claude"):
        assert name not in text, name


def test_the_runtime_action_exists_in_both_maps():
    for path in (RUNTIME, SKILL):
        rows = [ln for ln in path.read_text().splitlines() if ln.startswith("| `github.file_put")]
        assert len(rows) == 1, path


def test_pr_steward_lists_the_protected_branch():
    text = STEWARD.read_text()
    assert "chore/protected-<slug>-<yyyymmdd>" in text
    assert "implement, an attended session" in text


def test_the_flow_pins_the_base_and_checks_the_write():
    text = POLICY.read_text()
    flow = section(text, "## The flow")
    for needle in ("pinned SHA", "blob", "never reuse it", "git hash-object", "exactly one commit",
                   "git diff --name-only", "fail closed", "extended git header"):
        assert needle in flow, needle
    for needle in ("GUARDED_WORKFLOWS", "ALWAYS_PROTECTED", ".mcp.json"):
        assert needle in section(text, "## What is protected"), needle


def test_the_skill_row_passes_the_recorded_blob():
    row = [ln for ln in SKILL.read_text().splitlines() if ln.startswith("| `github.file_put")][0]
    assert "recorded blob id" in row and "optimistic-concurrency" in row


def test_the_flow_checks_the_whole_diff_and_the_excluded_set():
    flow = section(POLICY.read_text(), "## The flow")
    for needle in ("--no-renames", "excluded set", "never routed into this flow", "canonical", "`..` segment",
                   "/dev/null", "more than one", "patch --dry-run -p1", "bidi", "longer than any backtick run",
                   "head SHA", "a draft for a workflow path", "run the workflow at once"):
        assert needle in flow, needle


def test_the_allow_set_and_the_lockfile_rule_are_in_the_policy():
    text = POLICY.read_text()
    protected = section(text, "## What is protected")
    flow = section(text, "## The flow")
    for part in (protected, flow):
        assert "BUILTIN_PROTECT_ALLOW" in part and "protect_paths_allow" in part
        assert "lock command" in part and "not blocking" in part
    assert "deliberately not marked recommended" in flow
    assert "with a tracking issue, the diff of the posted comment" in flow
