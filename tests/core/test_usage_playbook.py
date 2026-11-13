"""The usage playbook sends a reading and writes no status record; the pieces that carry it agree."""
from conftest import ROOT

PLAYBOOKS = ROOT / "playbooks"


def test_usage_playbook_names_the_action_and_the_command():
    text = (PLAYBOOKS / "usage.md").read_text()
    assert "read_usage()" in text and "`tld board usage" in text
    assert "`attended: false`" in text or "attended: false" in text


def test_usage_playbook_writes_no_status_record_and_says_why():
    text = (PLAYBOOKS / "usage.md").read_text()
    assert "(policies/status-board.md)" not in text
    assert "No status record" in text and "bury the board" in text


def test_status_board_names_both_and_excludes_usage():
    text = (PLAYBOOKS / "policies" / "status-board.md").read_text()
    assert "read_usage()" in text and "tld board usage <file>" in text
    assert "usage playbook is excluded" in text


def test_runtime_defines_read_usage():
    assert "### read_usage()" in (PLAYBOOKS / "runtime.md").read_text()


def test_wrapper_delegates_to_the_playbook():
    text = (ROOT / "adapters" / "claude" / "commands" / "usage.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/playbooks/usage.md" in text and "scheduled task" in text
