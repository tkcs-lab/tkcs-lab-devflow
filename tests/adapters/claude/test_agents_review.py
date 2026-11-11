"""The six read-only agents (design D1)."""
import pytest

from agents_support import check_agent_file
from conftest import CLAUDE

AGENTS = ["architect", "code-reviewer", "security-reviewer", "test-architect", "ux-reviewer",
          "dependency-auditor"]


def text(name):
    return (CLAUDE / "agents" / f"{name}.md").read_text()


@pytest.mark.parametrize("name", AGENTS)
def test_agent_file_is_valid(name):
    check_agent_file(CLAUDE / "agents" / f"{name}.md")


@pytest.mark.parametrize("name", AGENTS)
def test_every_agent_lists_the_mode_input(name):
    assert "`Mode`" in text(name)


def test_security_reviewer_postures():
    body = text("security-reviewer")
    for needle in ("## Threat model", "critical", "standard", "low"):
        assert needle in body


def test_architect_mentions_adr():
    assert "ADR" in text("architect")


def test_dependency_auditor_has_audit_commands():
    assert "Audit commands" in text("dependency-auditor")


def test_ux_reviewer_has_stack_skills():
    assert "Stack skills" in text("ux-reviewer")
