import re

import yaml

from conftest import DEVFLOW, ROOT

SKILL = DEVFLOW / "skills" / "git-ops" / "SKILL.md"
DOC = ROOT / "docs" / "git-ops.md"
TEMPLATE = DEVFLOW / "templates" / "devflow-git-ops.yml"


def test_skill_front_matter():
    m = re.match(r"---\n(.*?)\n---\n", SKILL.read_text(), re.S)
    assert m
    fm = yaml.safe_load(m.group(1))
    assert fm["name"] == "git-ops"
    assert len(fm["description"]) > 40


def test_skill_has_the_headings():
    text = SKILL.read_text()
    for heading in ("# Tags and branch deletion through the central workflow", "## Before anything",
                    "## The flow", "## The call", "## Rules", "## What it cannot do"):
        assert re.search(rf"^{re.escape(heading)}$", text, re.M), heading


def test_skill_mentions_the_exact_inputs_and_tool():
    text = SKILL.read_text()
    for word in ("actions_run_trigger", "devflow-git-ops.yml", "git_ops.repo", "dry_run",
                 "create-tag", "delete-branch", "add_repo"):
        assert word in text, word


def test_skill_forbids_unattended_runs():
    text = SKILL.read_text()
    assert "unattended" in text
    assert "never" in text.lower()


def test_docs_mention_every_input_and_secret():
    text = DOC.read_text()
    for word in ("repo", "action", "name", "ref", "message", "dry_run", "GIT_OPS_TOKEN", "git-ops",
                 "git-ops-allowlist.json", "protected_branches", "tag_pattern"):
        assert f"`{word}`" in text or word in text, word
    for word in ("`repo`", "`action`", "`name`", "`ref`", "`message`", "`dry_run`"):
        assert word in text, word


def test_docs_list_every_error_of_the_workflow():
    errors = re.findall(r"::error::([^\"\n]+)", TEMPLATE.read_text())
    assert len(errors) >= 18
    text = DOC.read_text()
    for err in errors:
        for piece in re.split(r"\$[A-Za-z_]+", err):
            piece = piece.strip(" :()")
            if len(piece) >= 4:
                assert piece in text, piece


def test_steward_names_the_one_route_to_a_tag():
    text = (DEVFLOW / "skills" / "pr-steward" / "SKILL.md").read_text()
    assert "Never push a release tag from a session" in text
    bullet = [b for b in re.split(r"\n(?=- )", text) if "Never push a release tag from a session" in b][0]
    assert "git-ops" in bullet


def test_readme_lists_git_ops():
    text = (ROOT / "README.md").read_text()
    assert "**`git-ops`**" in text
    assert "docs/git-ops.md" in text
