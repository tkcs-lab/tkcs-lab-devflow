"""The /implement command names the agent-dispatch wiring."""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import CLAUDE

TEXT = (CLAUDE / "commands" / "implement.md").read_text()
FLAT = " ".join(TEXT.split())


@pytest.mark.parametrize("needle", [
    "3b", "2b", "--at implement_phase", "--at implement_final", "roles verify",
    "AGENT-REPORT", "agent-dispatch", "never substitute",
    "The orchestrator never runs an agent that has edit tools",
])
def test_implement_is_wired(needle):
    assert needle in FLAT


def test_verify_named_at_least_three_times():
    assert TEXT.count("roles verify") >= 3
