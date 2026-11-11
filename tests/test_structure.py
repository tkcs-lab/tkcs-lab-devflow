import json
import re

import yaml

from conftest import DEVFLOW, ROOT


def frontmatter(path):
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no front matter"
    return yaml.safe_load(m.group(1))


def test_marketplace_lists_existing_plugins():
    mp = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert mp["name"] == "claude-toolkit"
    names = []
    for plugin in mp["plugins"]:
        src = ROOT / plugin["source"]
        meta = json.loads((src / ".claude-plugin" / "plugin.json").read_text())
        assert meta["name"] == plugin["name"]
        names.append(plugin["name"])
    assert names == ["devflow", "stack-python", "stack-swift", "stack-ipados", "stack-go"]


def test_plugin_versions_agree():
    versions = {json.loads(p.read_text())["version"] for p in ROOT.glob("plugins/*/.claude-plugin/plugin.json")}
    assert len(versions) == 1


CORE_COMMANDS = ("make-plan", "implement", "dod", "review")
COMMANDS = tuple(sorted(p.stem for p in (DEVFLOW / "commands").glob("*.md")))


def test_core_commands_exist():
    assert set(CORE_COMMANDS) <= set(COMMANDS)


def test_no_session_start_wording_in_the_plugins():
    for path in (DEVFLOW.parent).rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            assert "SessionStart" not in path.read_text(errors="ignore"), path


def test_project_profile_finds_synced_plugins():
    text = (DEVFLOW / "skills" / "project-profile" / "SKILL.md").read_text()
    assert "plugins/synced" in text


def test_commands_have_front_matter():
    for name in COMMANDS:
        fm = frontmatter(DEVFLOW / "commands" / f"{name}.md")
        assert fm["description"]
    assert frontmatter(DEVFLOW / "commands" / "make-plan.md")["model"] == "opus"
    assert frontmatter(DEVFLOW / "commands" / "review.md")["model"] == "opus"
    assert frontmatter(DEVFLOW / "commands" / "implement.md")["model"] == "sonnet"


def test_skills_have_matching_names():
    skills = list(ROOT.glob("plugins/*/skills/*/SKILL.md"))
    assert {p.parent.name for p in skills} == {
        "project-profile", "pr-steward", "review-checklist", "secure-code-review", "test-review", "docs-review",
        "status-board", "repo-admin", "git-ops", "agent-dispatch", "profile-setup", "stack-python", "stack-swift", "stack-ipados", "stack-go"}
    for path in skills:
        fm = frontmatter(path)
        assert fm["name"] == path.parent.name
        assert len(fm["description"]) > 40


def test_commands_load_the_profile_skill_first():
    for name in COMMANDS:
        text = (DEVFLOW / "commands" / f"{name}.md").read_text()
        assert "project-profile" in text
        assert "never substitute" in " ".join(text.split())


def test_commands_call_the_validators():
    assert "validate_manifest.py" in (DEVFLOW / "commands" / "implement.md").read_text()
    assert "validate_manifest.py" in (DEVFLOW / "commands" / "make-plan.md").read_text()
    assert "validate_profile.py" in (DEVFLOW / "skills" / "project-profile" / "SKILL.md").read_text()
    assert "review_decisions.py" in (DEVFLOW / "commands" / "review.md").read_text()


def test_review_hands_over_to_make_plan():
    review = (DEVFLOW / "commands" / "review.md").read_text()
    make_plan = (DEVFLOW / "commands" / "make-plan.md").read_text()
    for skill in ("secure-code-review", "test-review", "docs-review"):
        assert f"`{skill}`" in review
    # The header fields and section names /make-plan relies on are the ones /review writes.
    for text in ("review_slug", "ready-for-plan", "decisions-pending", "Findings to fix", "Not doing",
                 "Issues created", "Suggested grouping", "/review apply"):
        assert text in review, text
        assert text in make_plan, text


def test_every_profile_key_in_the_schema_is_documented():
    schema = json.loads((DEVFLOW / "schema" / "profile.schema.json").read_text())
    reference = (ROOT / "docs" / "profile-reference.md").read_text()

    def walk(node, prefix):
        for key, sub in node.get("properties", {}).items():
            dotted = f"{prefix}{key}"
            assert f"`{dotted}" in reference, f"{dotted} is not in docs/profile-reference.md"
            if sub.get("type") == "object":
                walk(sub, dotted + ".")

    walk(schema, "")
