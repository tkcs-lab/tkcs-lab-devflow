"""The state mapping `playbooks/deps.md` section 4 states, and what deps-body accepts for it."""
import re
from pathlib import Path

import pytest

from tld.ops.deps_body import BodyError, check_entry

ROOT = Path(__file__).resolve().parents[2]

# the shape of one entry of `tld ops deps-prepare` (src/tld/ops/deps_prepare.py) for an applied group
COMBINE = {"ref": "origin/dependabot/pip/coverage-7.17.3", "sha": "0" * 40, "state": "applied", "reason": None,
           "file": None, "files": ["requirements.txt"], "lockfiles": [], "workflow_moves": []}


def entry(state):
    return {"ecosystem": "pip", "directory": "/", "pr": 88, "security": False,
            "updates": [{"package": "coverage", "from": "7.17.2", "to": "7.17.3"}],
            "moves": COMBINE["workflow_moves"], "files": COMBINE["files"],
            "state": state, "reason": COMBINE["reason"], "file": COMBINE["file"]}


def playbook_text():
    return " ".join((ROOT / "playbooks" / "deps.md").read_text().split())


def test_playbook_states_the_mapping():
    """Only this text test guards the playbook rule; the tests below guard what deps-body accepts."""
    text = playbook_text()
    assert re.search(r"`included` when the combine entry's `state` is `applied`, `left_out` otherwise", text)
    assert "keeps that entry's `state`, `reason` and `file`" in text
    assert "also when its group went green" in text
    assert re.search(r"has no combine entry and takes `state` `left_out`, that reason and `file` null", text)


def test_included_applied_entry_is_accepted():
    assert check_entry(0, entry("included"))["state"] == "included"


def test_applied_entry_is_rejected():
    with pytest.raises(BodyError):
        check_entry(0, entry(COMBINE["state"]))


def test_left_out_with_reason_is_accepted():
    e = entry("left_out")
    e["reason"] = "lockfile-only"
    assert check_entry(0, e)["state"] == "left_out"


def test_session_left_out_with_reason_and_null_file_is_accepted():
    e = entry("left_out")
    e["reason"], e["file"] = "verify-red", None
    assert check_entry(0, e)["reason"] == "verify-red"


def test_left_out_without_reason_is_rejected():
    with pytest.raises(BodyError):
        check_entry(0, entry("left_out"))


def test_playbook_states_audit_only_stopped_and_unstarted_rules():
    text = playbook_text()
    assert "except an audit-only entry: it has no title" in text
    assert "its `updates` is one item `{package: <audited package>, from: <manifest version before the change, or null>, to: <fixed version from deps.audit>}`" in text
    assert "an audit-only group has no such entry and takes them from its combine entry" in text
    assert "`Check deps group <ecosystem>: unexpected fixed version`" in text
    assert "for an audit-only group `/` plus the audit entry's `cwd` without a trailing `/`, and `/` when it has no `cwd` or it is `.`" in text
    assert "`Check deps group <ecosystem>: unexpected directory`" in text
    assert "`Check deps group <ecosystem>: unexpected package name`" in text
    assert "This does not cover `lock-other-files` (section 5), which takes its own reason `lock-other-files`" in text
    assert "gets no entry: its dependency-bot pull requests stay for the owner" in text
    assert "an unstarted group (marked `pending` after 80% of the time budget, Rules) takes `state` `left_out`, reason `time-budget` and `file` null" in text
    assert "any other group that has a combine entry takes `state` `included`" in text
    assert text.index("an unstarted group (marked") < text.index("any other group that has a combine entry")


def audit_entry(updates):
    return {"ecosystem": "pip", "directory": "/", "pr": None, "security": True, "updates": updates,
            "moves": [], "files": ["requirements.txt"], "state": "included", "reason": None, "file": None}


def test_audit_only_entry_with_filled_updates_is_accepted():
    e = audit_entry([{"package": "requests", "from": None, "to": "2.32.4"}])
    assert check_entry(0, e)["pr"] is None
    e = audit_entry([{"package": "requests", "from": "2.31.0", "to": "2.32.4"}])
    assert check_entry(0, e)["updates"][0]["to"] == "2.32.4"


def test_audit_only_entry_with_empty_updates_is_rejected():
    with pytest.raises(BodyError):
        check_entry(0, audit_entry([]))


def test_unstarted_group_left_out_for_time_budget_is_accepted():
    e = entry("left_out")
    e["reason"], e["file"] = "time-budget", None
    e["files"], e["moves"] = [], []
    assert check_entry(0, e)["reason"] == "time-budget"


def test_audit_only_directory_from_cwd():
    e = audit_entry([{"package": "requests", "from": None, "to": "2.32.4"}])
    e["directory"] = "/web"
    assert check_entry(0, e)["directory"] == "/web"
    e["directory"] = "web"
    with pytest.raises(BodyError):
        check_entry(0, e)
