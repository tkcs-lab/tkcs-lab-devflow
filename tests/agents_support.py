"""Shared checks for the agent files in plugins/devflow/agents (design D1)."""
import re
from pathlib import Path

import yaml

ALLOWED_TOOLS = {"Read", "Grep", "Glob", "Bash", "Skill", "Edit", "Write"}
BASE_TOOLS = {"Read", "Grep", "Glob", "Bash", "Skill"}
EDIT_AGENTS = {"tech-writer", "website-maintainer", "debugger", "refactorer"}
SECTIONS = ["Role", "Inputs", "Method", "Report", "Limits"]
KEYS = {"name", "description", "tools", "model"}

# agent -> (model, wrapped skill or None)
EXPECTED = {
    "architect": ("opus", None),
    "code-reviewer": ("opus", "review-checklist"),
    "security-reviewer": ("opus", "secure-code-review"),
    "test-architect": ("opus", "test-review"),
    "ux-reviewer": ("opus", None),
    "dependency-auditor": ("sonnet", None),
    "tech-writer": ("sonnet", "docs-review"),
    "website-maintainer": ("sonnet", "docs-review"),
    "debugger": ("sonnet", None),
    "refactorer": ("sonnet", None),
}


def split_front_matter(text: str):
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert match, "file has no front matter"
    return yaml.safe_load(match.group(1)), match.group(2)


def headings_outside_code(body: str) -> list[str]:
    """`##` headings at the start of a line, outside code fences."""
    found, fenced = [], False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            m = re.match(r"## (.+?)\s*$", line)
            if m:
                found.append(m.group(1))
    return found


def check_agent_file(path) -> None:
    path = Path(path)
    name = path.stem
    meta, body = split_front_matter(path.read_text())
    assert isinstance(meta, dict) and set(meta) == KEYS, f"{path}: keys are {sorted(meta)}"
    assert meta["name"] == name, f"{path}: name is {meta['name']!r}"
    assert len(str(meta["description"])) > 40, f"{path}: description too short"
    assert name in EXPECTED, f"{path}: unknown agent"
    model, skill = EXPECTED[name]
    assert meta["model"] == model, f"{path}: model is {meta['model']!r}"
    tools = [t.strip() for t in str(meta["tools"]).split(",")]
    assert set(tools) <= ALLOWED_TOOLS, f"{path}: unknown tools {set(tools) - ALLOWED_TOOLS}"
    assert BASE_TOOLS <= set(tools), f"{path}: tools lack {BASE_TOOLS - set(tools)}"
    has_edit = {"Edit", "Write"} <= set(tools)
    only_base = not ({"Edit", "Write"} & set(tools))
    if name in EDIT_AGENTS:
        assert has_edit, f"{path}: edit agent needs Edit and Write"
    else:
        assert only_base, f"{path}: read-only agent must not have Edit or Write"
    assert headings_outside_code(body)[:1] and headings_outside_code(body) == [
        s for s in SECTIONS], f"{path}: headings are {headings_outside_code(body)}"
    pattern = rf"^AGENT-REPORT {re.escape(name)} at=<point\|adhoc> verdict=<pass\|findings\|n/a> blocking=<n> non_blocking=<n>$"
    assert re.search(pattern, body, re.MULTILINE), f"{path}: AGENT-REPORT format line missing"
    if skill:
        assert f"Load the `{skill}` skill" in body, f"{path}: does not load {skill}"
