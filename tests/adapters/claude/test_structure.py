"""Contracts of the thin Claude adapter: manifests, command and agent wrappers, and the runtime map."""
import json
import re

import pytest

from conftest import ROOT, TLD, CLAUDE, frontmatter

PLAYBOOKS = ROOT / "playbooks"
RUNTIME_SKILL = CLAUDE / "skills" / "runtime" / "SKILL.md"
COMMANDS = tuple(sorted(p.stem for p in (CLAUDE / "commands").glob("*.md")))
AGENTS = tuple(sorted(p.stem for p in (CLAUDE / "agents").glob("*.md")))
SKILLS = tuple(sorted(p.parent.name for p in CLAUDE.glob("skills/*/SKILL.md")))
EDIT_ROLES = {"tech-writer", "website-maintainer", "debugger", "refactorer"}


def level_aliases() -> dict[str, str]:
    """level -> alias, from the one table in the runtime skill."""
    rows = re.findall(r"^\| `(strong|standard|fast)` \| `([a-z]+)` \| `(claude-[a-z0-9-]+)` \|$",
                      RUNTIME_SKILL.read_text(), re.M)
    return {level: alias for level, alias, _ in rows}


# ---- manifests ------------------------------------------------------------------------------
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
    import tld
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    package = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert plugin == package == tld.__version__  # one version: the release workflow tags v<version>


def test_session_start_is_only_used_by_model_check():
    allowed = {CLAUDE / "hooks" / name for name in ("hooks.json", "claude_adapter.py", "model_check.py")}
    for path in [*CLAUDE.rglob("*"), *TLD.rglob("*")]:
        if path.is_file() and "__pycache__" not in path.parts and path not in allowed:
            assert "SessionStart" not in path.read_text(errors="ignore"), path
    data = json.loads((CLAUDE / "hooks" / "hooks.json").read_text())
    commands = [h["command"] for group in data["hooks"]["SessionStart"] for h in group["hooks"]]
    assert commands and all(c.endswith("/adapters/claude/hooks/model_check.py\"") for c in commands), commands


# ---- commands -------------------------------------------------------------------------------
def test_every_playbook_command_has_a_wrapper():
    assert COMMANDS == tuple(sorted(("setup", "review", "make-plan", "implement", "dod", "land", "deps",
                                     "upstream", "docs", "board", "migrate", "ci", "usage")))


@pytest.mark.parametrize("name", COMMANDS)
def test_command_is_a_thin_wrapper_of_its_playbook(name):
    path = CLAUDE / "commands" / f"{name}.md"
    fm = frontmatter(path)
    assert set(fm) <= {"description", "argument-hint", "model"} and len(fm["description"]) > 40
    if "model" in fm:
        assert fm["model"] in level_aliases().values(), fm["model"]
    text = path.read_text()
    playbook = f"${{CLAUDE_PLUGIN_ROOT}}/playbooks/{name}.md"
    assert playbook in text and (PLAYBOOKS / f"{name}.md").is_file()
    assert "`tld:runtime`" in text and "$ARGUMENTS" in text
    assert len(text) < 1500, f"{name}.md is not thin ({len(text)} bytes)"


def test_commands_that_must_run_on_a_level():
    aliases = level_aliases()
    assert frontmatter(CLAUDE / "commands" / "make-plan.md")["model"] == aliases["strong"]
    assert frontmatter(CLAUDE / "commands" / "review.md")["model"] == aliases["strong"]
    assert frontmatter(CLAUDE / "commands" / "implement.md")["model"] == aliases["standard"]
    assert frontmatter(CLAUDE / "commands" / "usage.md")["model"] == aliases["fast"]


# ---- skills ---------------------------------------------------------------------------------
def test_skills_are_the_runtime_map_and_two_pointers():
    assert SKILLS == ("ask", "git-ops", "release", "repo-admin", "runtime")
    for name in SKILLS:
        fm = frontmatter(CLAUDE / "skills" / name / "SKILL.md")
        assert fm["name"] == name and len(fm["description"]) > 40


@pytest.mark.parametrize("name", ["ask", "git-ops", "release", "repo-admin"])
def test_pointer_skill_names_an_existing_playbook(name):
    text = (CLAUDE / "skills" / name / "SKILL.md").read_text()
    assert f"${{CLAUDE_PLUGIN_ROOT}}/playbooks/{name}.md" in text and (PLAYBOOKS / f"{name}.md").is_file()
    assert "`tld:runtime`" in text


def test_level_table_has_every_level_once():
    rows = re.findall(r"^\| `(strong|standard|fast)` \| `([a-z]+)` \| `(claude-[a-z0-9-]+)` \|$",
                      RUNTIME_SKILL.read_text(), re.M)
    assert sorted(r[0] for r in rows) == ["fast", "standard", "strong"]
    assert all(model.startswith(f"claude-{alias}-") for _, alias, model in rows)


def defined_actions() -> set[str]:
    names = set()
    for line in (PLAYBOOKS / "runtime.md").read_text().splitlines():
        if line.startswith("### "):
            names |= set(re.findall(r"([a-z_]+)\(", line))
        elif line.startswith("| `"):
            names |= set(re.findall(r"`([a-z_]+(?:\.[a-z_]+)?)\(", line.split("|")[1]))
    return names


def mapped_actions(text: str) -> set[str]:
    """The action names in the first cell of each runtime-map table row, one per code span (C8: whole cells,
    so `run_role` is not mapped by a row for `run_role_x`)."""
    names = set()
    for line in text.splitlines():
        if line.startswith("| `"):
            for span in re.findall(r"`([^`]+)`", line.split("|")[1]):
                m = re.fullmatch(r"([a-z_]+(?:\.[a-z_]+)?)(?:\(.*\))?", span.strip())
                if m:
                    names.add(m.group(1))
    return names


def test_runtime_map_maps_every_action():
    actions = defined_actions()
    assert len(actions) > 25
    missing = sorted(actions - mapped_actions(RUNTIME_SKILL.read_text()))
    assert missing == [], f"the runtime skill does not map: {missing}"


def test_the_mapping_check_reads_whole_cells():
    assert mapped_actions("| `run_role_x(a)` | t |\n| `a`, `b(c)` | t |\n| prose `run_role` | t |") == {"run_role_x", "a", "b"}


def test_run_role_takes_a_level_and_review_passes_the_reviewer_level():
    """C6: the optional level reaches the Agent tool's model parameter."""
    assert "### run_role(role, mode, point, context[, level])" in (PLAYBOOKS / "runtime.md").read_text()
    assert "`run_role(<role>, review, review, <context>, <the reviewer level>)`" in (PLAYBOOKS / "review.md").read_text()
    row = next(ln for ln in RUNTIME_SKILL.read_text().splitlines() if ln.startswith("| `run_role("))
    assert "`model` parameter as the level's alias" in row and "overrides the agent's front matter" in row


# ---- agents ---------------------------------------------------------------------------------
def test_one_agent_per_role():
    assert AGENTS == tuple(sorted(p.stem for p in (ROOT / "roles").glob("*.md")))


@pytest.mark.parametrize("name", AGENTS)
def test_agent_wraps_its_role_card(name):
    path = CLAUDE / "agents" / f"{name}.md"
    fm = frontmatter(path)
    assert set(fm) == {"name", "description", "tools", "model"} and fm["name"] == name
    level = re.search(r"\*\*Default level:\*\* `(\w+)`", (ROOT / "roles" / f"{name}.md").read_text()).group(1)
    assert fm["model"] == level_aliases()[level], f"{name}: model {fm['model']} is not the role's level {level}"
    tools = {t.strip() for t in fm["tools"].split(",")}
    assert {"Read", "Grep", "Glob", "Bash"} <= tools <= {"Read", "Grep", "Glob", "Bash", "Edit", "Write"}
    assert ({"Edit", "Write"} <= tools) == (name in EDIT_ROLES), name
    assert f"${{CLAUDE_PLUGIN_ROOT}}/roles/{name}.md" in path.read_text()


# ---- profile reference ----------------------------------------------------------------------
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


def test_review_hands_over_to_make_plan():
    """The header fields and section names make-plan reads are the ones review writes."""
    review = (PLAYBOOKS / "review.md").read_text()
    make_plan = (PLAYBOOKS / "make-plan.md").read_text()
    for text in ("review_slug", "ready-for-plan", "decisions-pending", "Findings to fix", "Not doing",
                 "Issues created", "Suggested grouping"):
        assert text in review and text in make_plan, text


def test_runtime_skill_has_the_environment_section():
    """The claude.ai network facts live in one section of the runtime skill."""
    text = RUNTIME_SKILL.read_text()
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings == ["Names", "Environment", "Levels", "Workers", "Roles and helpers", "The human", "GitHub"]
    section = text.split("## Environment", 1)[1].split("## Levels", 1)[0]
    for needle in ("**Limited**", "playbooks/policies/research.md", "docs/guides/cloud-environments.md",
                   "update_environment"):
        assert needle in section, needle
    assert "research sweep" not in text
    assert "research sweep" not in (PLAYBOOKS / "runtime.md").read_text()
