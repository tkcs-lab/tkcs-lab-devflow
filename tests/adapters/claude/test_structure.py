import json
import re


from conftest import ROOT, TLD, CLAUDE, frontmatter


def test_marketplace_lists_existing_plugins():
    mp = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert mp["name"] == "tkcs-lab-devflow" and mp["owner"]["name"] == "tkcs-lab"
    assert [p["name"] for p in mp["plugins"]] == ["tld"]
    assert mp["plugins"][0]["source"] == "./"
    meta = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert meta["name"] == "tld" and meta["author"]["name"] == "tkcs-lab"
    assert meta["homepage"] == "https://github.com/tkcs-lab/tkcs-lab-devflow"


def test_plugin_component_paths_point_into_the_claude_adapter():
    meta = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert meta["commands"] == "./adapters/claude/commands/" and meta["skills"] == "./adapters/claude/skills/"
    assert meta["hooks"] == "./adapters/claude/hooks/hooks.json" and meta["mcpServers"] == "./adapters/claude/mcp.json"
    assert meta["agents"] == sorted(f"./adapters/claude/agents/{p.name}" for p in (CLAUDE / "agents").glob("*.md"))
    for key in ("commands", "skills", "hooks", "mcpServers", "agents"):
        for path in meta[key] if isinstance(meta[key], list) else [meta[key]]:
            assert (ROOT / path).exists(), path


def test_plugin_versions_agree():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    package = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert plugin.replace("-", ".") == package


CORE_COMMANDS = ("make-plan", "implement", "dod", "review")
COMMANDS = tuple(sorted(p.stem for p in (CLAUDE / "commands").glob("*.md")))


def test_core_commands_exist():
    assert set(CORE_COMMANDS) <= set(COMMANDS)


def test_no_session_start_wording_in_the_plugins():
    for path in [*CLAUDE.rglob("*"), *TLD.rglob("*")]:
        if path.is_file() and "__pycache__" not in path.parts:
            assert "SessionStart" not in path.read_text(errors="ignore"), path


def test_project_profile_states_the_one_toolkit_rule():
    text = (CLAUDE / "skills" / "project-profile" / "SKILL.md").read_text()
    assert '"${CLAUDE_PLUGIN_ROOT}/bin/tld" <group> <command>' in text
    assert "plugins/cache" not in text and "plugins/synced" not in text


def test_commands_have_front_matter():
    for name in COMMANDS:
        fm = frontmatter(CLAUDE / "commands" / f"{name}.md")
        assert fm["description"]
    assert frontmatter(CLAUDE / "commands" / "make-plan.md")["model"] == "opus"
    assert frontmatter(CLAUDE / "commands" / "review.md")["model"] == "opus"
    assert frontmatter(CLAUDE / "commands" / "implement.md")["model"] == "sonnet"


def test_skills_have_matching_names():
    skills = list(CLAUDE.glob("skills/*/SKILL.md"))
    assert {p.parent.name for p in skills} == {
        "project-profile", "pr-steward", "review-checklist", "secure-code-review", "test-review", "docs-review",
        "status-board", "repo-admin", "git-ops", "agent-dispatch", "profile-setup", "docs-keeper", "stack-python", "stack-swift", "stack-ipados", "stack-go"}
    for path in skills:
        fm = frontmatter(path)
        assert fm["name"] == path.parent.name
        assert len(fm["description"]) > 40


def test_commands_load_the_profile_skill_first():
    for name in COMMANDS:
        text = (CLAUDE / "commands" / f"{name}.md").read_text()
        assert "project-profile" in text
        assert "never substitute" in " ".join(text.split())


def test_commands_call_the_validators():
    tld = '"${CLAUDE_PLUGIN_ROOT}/bin/tld" '
    assert tld + "plan validate-manifest" in (CLAUDE / "commands" / "implement.md").read_text()
    assert tld + "plan validate-manifest" in (CLAUDE / "commands" / "make-plan.md").read_text()
    assert tld + "profile validate" in (CLAUDE / "skills" / "project-profile" / "SKILL.md").read_text()
    assert tld + "review decisions" in (CLAUDE / "commands" / "review.md").read_text()


def test_review_hands_over_to_make_plan():
    review = (CLAUDE / "commands" / "review.md").read_text()
    make_plan = (CLAUDE / "commands" / "make-plan.md").read_text()
    for skill in ("secure-code-review", "test-review", "docs-review"):
        assert f"`{skill}`" in review
    # The header fields and section names /make-plan relies on are the ones /review writes.
    for text in ("review_slug", "ready-for-plan", "decisions-pending", "Findings to fix", "Not doing",
                 "Issues created", "Suggested grouping", "/review apply"):
        assert text in review, text
        assert text in make_plan, text


def test_every_profile_key_in_the_schema_is_documented():
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    reference = (ROOT / "docs" / "reference" / "profile-reference.md").read_text()

    def walk(node, prefix):
        for key, sub in node.get("properties", {}).items():
            dotted = f"{prefix}{key}"
            assert f"`{dotted}" in reference, f"{dotted} is not in docs/reference/profile-reference.md"
            if sub.get("type") == "object":
                walk(sub, dotted + ".")

    walk(schema, "")
