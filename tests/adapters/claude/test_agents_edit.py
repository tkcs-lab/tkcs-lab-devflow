"""The four edit-capable agents (design D1)."""
import pytest

from agents_support import check_agent_file
from conftest import CLAUDE

AGENTS = ["tech-writer", "website-maintainer", "debugger", "refactorer"]


def text(name):
    return (CLAUDE / "agents" / f"{name}.md").read_text()


@pytest.mark.parametrize("name", AGENTS)
def test_agent_file_is_valid(name):
    check_agent_file(CLAUDE / "agents" / f"{name}.md")


@pytest.mark.parametrize("name", AGENTS)
def test_every_agent_states_the_mode_rules(name):
    body = text(name)
    assert "Mode: edit" in body
    assert "review mode" in body


@pytest.mark.parametrize("name", ["tech-writer", "website-maintainer"])
def test_docs_agents_load_docs_review(name):
    assert "Load the `docs-review` skill" in text(name)


def test_website_maintainer_fields():
    body = text("website-maintainer")
    for needle in ("Website build", "Website links", "n/a"):
        assert needle in body


def test_refactorer_has_verify_fast():
    assert "Verify (fast)" in text("refactorer")


def test_debugger_names_root_cause():
    assert "root cause" in text("debugger")
