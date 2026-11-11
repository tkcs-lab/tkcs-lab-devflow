"""The docs that describe the roles agree with the code, and their relative links resolve."""
from __future__ import annotations

import re

import pytest
from conftest import ROOT, _load

DOCS = ROOT / "docs"
LINKED = [DOCS / "architecture" / "roles.md", DOCS / "guides" / "setup.md", DOCS / "architecture" / "design.md",
          DOCS / "architecture" / "hooks.md", DOCS / "guides" / "maintenance.md", DOCS / "reference" / "profile-reference.md",
          ROOT / "README.md"]


def test_roles_doc_names_every_role_and_point_the_code_knows():
    dispatch = _load("tld.roles.dispatch")
    text = (DOCS / "architecture" / "roles.md").read_text()
    for name in (*dispatch.ROLES, *dispatch.POINTS):
        assert f"`{name}`" in text, name


@pytest.mark.parametrize("doc", LINKED, ids=lambda p: p.name)
def test_relative_links_resolve(doc):
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        assert (doc.parent / path).exists(), f"{doc.name}: {target}"
