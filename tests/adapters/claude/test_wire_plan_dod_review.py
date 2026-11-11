"""The /make-plan, /dod and /review commands name the agent-dispatch wiring."""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import CLAUDE

COMMANDS = CLAUDE / "commands"

EXPECTED = {
    "make-plan.md": ["--at make_plan", "architect", "Agents:"],
    "dod.md": ["--at dod", "AGENT-REPORT", "required agent did not run"],
    "review.md": ["--at review", "AGT"],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_command_is_wired(name):
    text = (COMMANDS / name).read_text()
    for needle in ["agent-dispatch", "roles required", *EXPECTED[name]]:
        assert needle in text, f"{name}: {needle}"
