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


def test_playbook_states_the_mapping():
    """Only this text test guards the playbook rule; the tests below guard what deps-body accepts."""
    text = " ".join((ROOT / "playbooks" / "deps.md").read_text().split())
    assert re.search(r"`included` when the combine entry's `state` is `applied`, `left_out` otherwise", text)
    assert "keeps that entry's `state`, `reason` and `file`" in text
    assert "also when its group went green" in text
    assert re.search(r"has no combine entry and takes `state` `left_out`, that reason and `file` null", text)


def test_included_applied_entry_is_accepted():
    assert check_entry(0, entry("included"))["state"] == "included"


def test_applied_entry_is_rejected():
    with pytest.raises(BodyError):
        check_entry(0, entry(COMBINE["state"]))


def test_left_out_with_file_reason_is_accepted():
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
