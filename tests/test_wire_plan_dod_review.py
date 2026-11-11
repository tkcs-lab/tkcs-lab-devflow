"""The /make-plan, /dod and /review commands name the agent-dispatch wiring."""
from __future__ import annotations

from pathlib import Path

import pytest

COMMANDS = Path(__file__).resolve().parent.parent / "plugins" / "devflow" / "commands"

EXPECTED = {
    "make-plan.md": ["--at make_plan", "architect", "Agents:"],
    "dod.md": ["--at dod", "AGENT-REPORT", "required agent did not run"],
    "review.md": ["--at review", "AGT"],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_command_is_wired(name):
    text = (COMMANDS / name).read_text()
    for needle in ["agent-dispatch", "agents.py required", *EXPECTED[name]]:
        assert needle in text, f"{name}: {needle}"
