"""The state mapping `playbooks/deps.md` section 4 states: deps-prepare's `applied` becomes `included` for deps-body."""
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


def mapped(state, section3_state="applied"):
    """The playbook's rule: a section 3 left_out entry keeps its state; any other maps the combine entry."""
    if section3_state == "left_out":
        return "left_out"
    return "included" if state == "applied" else "left_out"


def test_playbook_states_the_mapping():
    text = " ".join((ROOT / "playbooks" / "deps.md").read_text().split())
    assert re.search(r"`included` when the combine entry's `state` is `applied`, `left_out` otherwise", text)
    assert "keeps that entry's `state`, `reason` and `file`" in text


def test_mapped_applied_entry_is_accepted():
    assert check_entry(0, entry(mapped(COMBINE["state"])))["state"] == "included"


def test_unmapped_applied_entry_is_rejected():
    with pytest.raises(BodyError):
        check_entry(0, entry(COMBINE["state"]))


def test_left_out_in_section_3_stays_left_out():
    state = mapped(COMBINE["state"], section3_state="left_out")
    assert state == "left_out"
    e = entry(state)
    e["reason"] = "lockfile-only"
    assert check_entry(0, e)["state"] == "left_out"
