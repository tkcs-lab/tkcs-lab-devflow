"""hooks.json, the scripts it names, the profile schema for the hooks section, and the docs."""
import ast
import json
import re
import subprocess
import sys

import pytest
import yaml

from conftest import DEVFLOW, ROOT
from hooks_helpers import HOOKS, MODULES

import _common

HOOKS_JSON = HOOKS / "hooks.json"


def entries():
    data = json.loads(HOOKS_JSON.read_text())
    for event_name, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                yield event_name, group.get("matcher"), hook


def test_hooks_json_is_valid_and_every_script_exists():
    data = json.loads(HOOKS_JSON.read_text())
    assert set(data["hooks"]) == {"PreToolUse", "Stop"}
    scripts = []
    for event_name, matcher, hook in entries():
        assert hook["type"] == "command" and isinstance(hook["timeout"], int) and hook["timeout"] > 0
        m = re.fullmatch(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([a-z_]+\.py)"', hook["command"])
        assert m, hook["command"]
        assert (HOOKS / m.group(1)).is_file(), m.group(1)
        scripts.append(m.group(1))
        if event_name == "PreToolUse":
            assert matcher and re.compile(matcher)
        else:
            assert matcher is None
    assert sorted(scripts) == sorted(f"{m}.py" for m in MODULES.values()), "each hook is registered exactly once"


@pytest.mark.parametrize("script, tool, listens", [
    ("no_merge.py", "Bash", True), ("no_merge.py", "mcp__github__merge_pull_request", True),
    ("no_merge.py", "mcp__github__enable_pr_auto_merge", True), ("no_merge.py", "mcp__github__pull_request_review_write", True),
    ("no_merge.py", "mcp__github__push_files", True), ("no_merge.py", "mcp__github__create_branch", False),
    ("no_merge.py", "Write", False),
    ("no_force_push.py", "Bash", True), ("no_force_push.py", "Write", False),
    ("no_git_tag.py", "Bash", True), ("no_git_tag.py", "Edit", False),
    ("secret_scan.py", "Write", True), ("secret_scan.py", "Edit", True), ("secret_scan.py", "MultiEdit", True),
    ("secret_scan.py", "Bash", False),
    ("protect_paths.py", "Write", True), ("protect_paths.py", "Edit", True), ("protect_paths.py", "MultiEdit", True),
    ("protect_paths.py", "Bash", True), ("protect_paths.py", "Read", False),
])
def test_matchers(script, tool, listens):
    for _, matcher, hook in entries():
        if hook["command"].endswith(f'/hooks/{script}"'):
            assert bool(re.fullmatch(matcher, tool)) is listens, (script, matcher, tool)


def test_stop_hook_has_the_longest_timeout():
    timeouts = {h["command"].split("/")[-1]: h["timeout"] for _, _, h in entries()}
    assert timeouts['dod_gate.py"'] == 1800 and all(v <= 20 for k, v in timeouts.items() if "dod_gate" not in k)
    assert 1800 > __import__("dod_gate").TOTAL_BUDGET_SECONDS


def test_every_hook_command_runs_as_written(feature_repo, tmp_path):
    """The command string is run through a shell with the plugin root substituted, as Claude Code does."""
    event = json.dumps({"cwd": str(feature_repo), "tool_name": "Bash", "tool_input": {"command": "ls"},
                        "hook_event_name": "PreToolUse", "session_id": "x"})
    for _, _, hook in entries():
        cmd = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(DEVFLOW))
        r = subprocess.run(cmd, shell=True, input=event, capture_output=True, text=True, timeout=60,
                           env={"PATH": __import__("os").environ["PATH"], "CLAUDE_PROJECT_DIR": str(feature_repo)})
        assert r.returncode == 0, (cmd, r.stderr)


def test_scripts_are_small_stdlib_plus_pyyaml_python_311_without_network():
    stdlib = set(sys.stdlib_module_names)
    local = {p.stem for p in HOOKS.glob("*.py")}
    forbidden = {"socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "httpx", "aiohttp"}
    for path in HOOKS.glob("*.py"):
        tree = ast.parse(path.read_text(), feature_version=(3, 11))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= stdlib | local | {"yaml"}, (path.name, imported - stdlib - local)
        assert not imported & forbidden, (path.name, imported & forbidden)
        assert len(path.read_text().splitlines()) < 420, f"{path.name} is no longer small"


def test_hook_names_agree_everywhere():
    schema = json.loads((DEVFLOW / "schema" / "profile.schema.json").read_text())
    assert tuple(schema["properties"]["hooks"]["properties"]["disable"]["items"]["enum"]) == _common.HOOK_NAMES
    assert set(_common.HOOK_NAMES) == set(MODULES)
    for name, mod in MODULES.items():
        assert __import__(mod).NAME == name


def test_schema_defaults_equal_the_hooks_built_in_defaults():
    props = json.loads((DEVFLOW / "schema" / "profile.schema.json").read_text())["properties"]["hooks"]["properties"]
    assert props["protect_paths"]["x-hook-default"] == _common.DEFAULT_PROTECT_PATHS
    assert props["protect_paths_allow"]["x-hook-default"] == []
    assert props["disable"]["x-hook-default"] == []
    gate = props["dod_gate"]["properties"]
    assert gate["enabled"]["x-hook-default"] is False
    assert gate["max_attempts"]["x-hook-default"] == _common.DEFAULT_MAX_ATTEMPTS


def test_template_documents_the_defaults_and_stays_valid(vp):
    text = (ROOT / "templates" / "toolkit.yaml").read_text()
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("# hooks:"))
    block = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        block.append(re.sub(r"^# ?", "", line))
    hooks = yaml.safe_load("\n".join(block))["hooks"]
    assert hooks["protect_paths"] == _common.DEFAULT_PROTECT_PATHS and hooks["dod_gate"]["enabled"] is False
    profile = yaml.safe_load(text)
    profile["hooks"] = hooks
    errors, _, _ = vp.validate(profile)
    assert errors == []
    assert vp.validate(yaml.safe_load(text))[0] == []


@pytest.mark.parametrize("hooks, message", [
    ({"disable": ["no-such-hook"]}, "'hooks.disable[0]': must be one of"),
    ({"dod_gate": {"max_attempts": 0}}, "'hooks.dod_gate.max_attempts': must be at least 1"),
    ({"dod_gate": {"enabled": "yes"}}, "'hooks.dod_gate.enabled': must be true/false"),
    ({"protect_paths": ".env"}, "'hooks.protect_paths': must be a list"),
    ({"mystery": 1}, "unknown key 'hooks.mystery'"),
])
def test_schema_rejects_bad_hooks_sections(vp, hooks, message):
    profile = {"docs": {"must_read": []}, "git": {"main_branch": "main", "branch_pattern": "x"},
               "verify": {"fast": [], "dod": ["true"]}, "stacks": [], "hooks": hooks}
    errors, _, _ = vp.validate(profile)
    assert any(message in e for e in errors), errors


def test_resolved_profile_is_unchanged_by_the_hooks_section(vp):
    profile = {"docs": {"must_read": []}, "git": {"main_branch": "main", "branch_pattern": "x"},
               "verify": {"fast": [], "dod": ["true"]}, "stacks": []}
    assert "hooks" not in vp.validate(profile)[2]


# ---- the commands that mark themselves exempt -----------------------------------------------------
EXEMPT_LINE = 'python3 "<devflow root>/hooks/dod_gate.py" --exempt'


@pytest.mark.parametrize("name, exempt", [("implement", True), ("make-plan", True), ("review", True), ("land", True),
                                          ("deps", False), ("upstream", False), ("dod", False), ("board", False)])
def test_which_commands_mark_the_session_exempt(name, exempt):
    assert (EXEMPT_LINE in (DEVFLOW / "commands" / f"{name}.md").read_text()) is exempt


# ---- docs ----------------------------------------------------------------------------------------
def test_docs_cover_every_hook_and_key():
    doc = (ROOT / "docs" / "hooks.md").read_text()
    for name in _common.HOOK_NAMES:
        assert f"`{name}`" in doc, name
    for key in ("hooks.disable", "hooks.protect_paths", "hooks.protect_paths_allow", "hooks.dod_gate.enabled",
                "hooks.dod_gate.max_attempts", "stop_hook_active", "dod_gate.py --exempt", "Branch protection and CI"):
        assert key in doc, key
    for heading in ("What the hooks do not protect", "How the dod-gate recognises a session", "Compatibility with the commands"):
        assert heading in doc, heading
    for command in ("/implement", "/land", "/deps", "/upstream", "/review", "/make-plan"):
        assert command in doc, command
    readme = (ROOT / "README.md").read_text()
    assert "## Guardrails" in readme and "docs/hooks.md" in readme
    assert "hooks.md" in (ROOT / "docs" / "profile-reference.md").read_text()
