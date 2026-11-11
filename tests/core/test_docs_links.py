"""The docs that describe the roles agree with the code, and every relative link and anchor in a Markdown file resolves."""
from __future__ import annotations

import re

import pytest
from conftest import ROOT, _load

DOCS = ROOT / "docs"
SKIP = {".git", "node_modules", ".venv", ".pytest_cache", "__pycache__", "transcripts", "results"}
MARKDOWN = sorted(p for p in ROOT.rglob("*.md") if not SKIP & set(p.relative_to(ROOT).parts))


def slug(heading: str) -> str:
    """GitHub's anchor of a heading: lower case, markup and punctuation dropped, spaces to '-'."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip().lower().replace("`", ""))
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path) -> set[str]:
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
    found, seen = set(), {}
    for heading in re.findall(r"^#+\s+(.+?)\s*#*$", text, re.M):
        s = slug(heading)
        found.add(s if s not in seen else f"{s}-{seen[s]}")
        seen[s] = seen.get(s, 0) + 1
    return found


def test_roles_doc_names_every_role_and_point_the_code_knows():
    dispatch = _load("tld.roles.dispatch")
    text = (DOCS / "architecture" / "roles.md").read_text()
    for name in (*dispatch.ROLES, *dispatch.POINTS):
        assert f"`{name}`" in text, name


def test_every_markdown_file_is_checked():
    names = {p.relative_to(ROOT).as_posix() for p in MARKDOWN}
    assert {"README.md", "AGENTS.md", "CHANGELOG.md", "docs/README.md", "playbooks/runtime.md"} <= names


@pytest.mark.parametrize("doc", MARKDOWN, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_and_anchors_resolve(doc):
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or "<" in target:
            continue
        path, _, fragment = target.partition("#")
        resolved = doc.parent / path if path else doc
        assert resolved.exists(), f"{doc.name}: {target}"
        if fragment and resolved.suffix == ".md":
            assert fragment in anchors(resolved), f"{doc.name}: {target} (no such heading)"


def test_the_anchor_rule_matches_github():
    assert slug("Rulesets, the agent account and the environments") == "rulesets-the-agent-account-and-the-environments"
    assert slug("`no-merge`") == "no-merge" and slug("1. Decisions") == "1-decisions"
