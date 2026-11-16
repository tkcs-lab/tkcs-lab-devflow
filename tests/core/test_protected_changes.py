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
