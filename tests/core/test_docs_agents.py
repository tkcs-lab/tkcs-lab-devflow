"""The documentation of the agents and /setup names what it must and its links resolve."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import ROOT

DOCS = ROOT / "docs"
AGENTS = ["architect", "code-reviewer", "security-reviewer", "test-architect", "tech-writer",
          "website-maintainer", "ux-reviewer", "debugger", "dependency-auditor", "refactorer"]
POINTS = ["make_plan", "implement_phase", "implement_final", "review", "dod"]
LINKED = [DOCS / "architecture" / "agents.md", DOCS / "guides" / "setup.md", DOCS / "architecture" / "design.md", DOCS / "architecture" / "hooks.md",
          DOCS / "guides" / "maintenance.md", ROOT / "README.md"]


def test_agents_doc_names_agents_and_points():
    text = (DOCS / "architecture" / "agents.md").read_text()
    for name in AGENTS + POINTS:
        assert f"`{name}`" in text, name


def test_setup_doc_names_scripts_and_branch():
    text = (DOCS / "guides" / "setup.md").read_text()
    for needle in ("tld profile survey", "tld profile patch", "chore/toolkit-profile"):
        assert needle in text, needle


def test_readme_mentions_setup_and_agents_doc():
    text = (ROOT / "README.md").read_text()
    assert "/setup" in text
    assert "docs/architecture/agents.md" in text
    assert "ten commands" in text


def test_hooks_doc_documents_allow_profile():
    text = (DOCS / "architecture" / "hooks.md").read_text()
    for needle in ("guard allow-profile", "guard end-allow", "two hours"):
        assert needle in text, needle


@pytest.mark.parametrize("doc", LINKED, ids=lambda p: p.name)
def test_relative_links_resolve(doc):
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        assert (doc.parent / path).exists(), f"{doc.name}: {target}"
