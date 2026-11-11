"""hooks.json, the scripts it names, the profile schema for the hooks section, and the docs."""
import ast
import json
import re
import os
import subprocess
import sys

import pytest
import yaml

from conftest import ROOT, TLD, CLAUDE
from hooks_helpers import FAIL_CLOSED, HOOKS, MODULES, bash, git, make_repo, module, run, run_script

from tld.guard import _common
from evals.harness.hookcheck import matcher_matches

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
        m = re.fullmatch(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/adapters/claude/hooks/([a-z_]+\.py)"', hook["command"])
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
    ("no_merge.py", "mcp__github__create_or_update_file", True), ("no_merge.py", "mcp__github__delete_file", True),
    ("secret_scan.py", "NotebookEdit", True), ("protect_paths.py", "NotebookEdit", True),
    ("no_force_push.py", "Bash", True), ("no_force_push.py", "Write", False),
    ("no_git_tag.py", "Bash", True), ("no_git_tag.py", "Edit", False),
    ("no_git_tag.py", "mcp__github__actions_run_trigger", True), ("no_git_tag.py", "mcp__github__merge_pull_request", False),
    ("no_force_push.py", "mcp__github__actions_run_trigger", False),
    ("secret_scan.py", "Write", True), ("secret_scan.py", "Edit", True), ("secret_scan.py", "MultiEdit", True),
    ("secret_scan.py", "Bash", True),  # S16: secrets written from Bash (echo ghp_... > f) are scanned too
    ("protect_paths.py", "Write", True), ("protect_paths.py", "Edit", True), ("protect_paths.py", "MultiEdit", True),
    ("protect_paths.py", "Bash", True), ("protect_paths.py", "Read", False),
])
def test_matchers(script, tool, listens):
    for _, matcher, hook in entries():
        if hook["command"].endswith(f'/hooks/{script}"'):
            assert matcher_matches(matcher, tool) is listens, (script, matcher, tool)


@pytest.mark.parametrize("matcher, tool, expected", [
    ("Bash", "Bash", True), ("Bash", "BashOutput", False), ("Write|Edit", "Edit", True), ("Write|Edit", "MultiEdit", False),
    ("mcp__.*__push_files", "mcp__github__push_files", True), ("mcp__.*__push", "mcp__github__push_files", True),
    ("", "Anything", True), ("*", "Anything", True), (None, "Anything", True),
])
def test_matcher_matches_follows_claude_codes_rule(matcher, tool, expected):
    assert matcher_matches(matcher, tool) is expected


@pytest.mark.parametrize("hook", sorted(MODULES))
def test_internal_error_fails_per_hook(hook, monkeypatch, tmp_path):
    mod = module(hook)

    def boom(ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "evaluate", boom)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    from tld.guard.action import Action
    action = Action("shell", str(tmp_path), str(tmp_path), command="ls")
    decision = _common.run_guard(mod.NAME, mod.evaluate, FAIL_CLOSED[hook], action)
    assert decision.verdict == ("deny" if FAIL_CLOSED[hook] else "error")
    assert "internal error (RuntimeError" in decision.reason


def test_stop_hook_has_the_longest_timeout():
    timeouts = {h["command"].split("/")[-1]: h["timeout"] for _, _, h in entries()}
    assert timeouts['dod_gate.py"'] == 1800 and all(v <= 20 for k, v in timeouts.items() if "dod_gate" not in k)
    assert 1800 > module("dod-gate").TOTAL_BUDGET_SECONDS


def test_every_hook_command_runs_as_written(feature_repo, tmp_path):
    """The command string is run through a shell with the plugin root substituted, as Claude Code does."""
    event = json.dumps({"cwd": str(feature_repo), "tool_name": "Bash", "tool_input": {"command": "ls"},
                        "hook_event_name": "PreToolUse", "session_id": "x"})
    for _, _, hook in entries():
        cmd = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
        r = subprocess.run(cmd, shell=True, input=event, capture_output=True, text=True, timeout=60,
                           env={"PATH": __import__("os").environ["PATH"], "CLAUDE_PROJECT_DIR": str(feature_repo)})
        assert r.returncode == 0, (cmd, r.stderr)


def test_scripts_are_small_stdlib_plus_pyyaml_python_311_without_network():
    stdlib = set(sys.stdlib_module_names)
    local = {"tld", "claude_adapter"}  # the core package and the Claude adapter the entry scripts import
    forbidden = {"socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "httpx", "aiohttp"}
    for path in [*HOOKS.glob("*.py"), *(TLD / "guard").glob("*.py"), TLD / "dod" / "gate.py"]:
        tree = ast.parse(path.read_text(), feature_version=(3, 11))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= stdlib | local | {"yaml"}, (path.name, imported - stdlib - local)
        assert not imported & forbidden, (path.name, imported & forbidden)
        assert len(path.read_text().splitlines()) < 480, f"{path.name} is no longer small"


def test_hook_names_agree_everywhere():
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    assert tuple(schema["properties"]["hooks"]["properties"]["disable"]["items"]["enum"]) == _common.HOOK_NAMES
    assert set(_common.HOOK_NAMES) == set(MODULES)
    for name in MODULES:
        assert module(name).NAME == name


def test_schema_defaults_equal_the_hooks_built_in_defaults():
    props = json.loads((TLD / "schema" / "profile.schema.json").read_text())["properties"]["hooks"]["properties"]
    assert props["protect_paths"]["x-hook-default"] == _common.DEFAULT_PROTECT_PATHS
    assert props["protect_paths_allow"]["x-hook-default"] == []
    assert props["disable"]["x-hook-default"] == []
    gate = props["dod_gate"]["properties"]
    assert gate["enabled"]["x-hook-default"] is False
    assert gate["max_attempts"]["x-hook-default"] == _common.DEFAULT_MAX_ATTEMPTS


def test_template_documents_the_defaults_and_stays_valid(vp):
    text = (TLD / "templates" / "toolkit.yaml").read_text()
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
EXEMPT_LINE = "`tld dod exempt`"


@pytest.mark.parametrize("name, exempt", [("implement", True), ("make-plan", True), ("review", True), ("land", True),
                                          ("setup", True), ("deps", False), ("docs", False), ("upstream", False),
                                          ("dod", False), ("board", False)])
def test_which_playbooks_mark_the_session_exempt(name, exempt):
    assert (EXEMPT_LINE in " ".join((ROOT / "playbooks" / f"{name}.md").read_text().split())) is exempt


# ---- docs ----------------------------------------------------------------------------------------
def test_docs_cover_every_hook_and_key():
    doc = (ROOT / "docs" / "architecture" / "hooks.md").read_text()
    for name in _common.HOOK_NAMES:
        assert f"`{name}`" in doc, name
    for key in ("hooks.disable", "hooks.protect_paths", "hooks.protect_paths_allow", "hooks.dod_gate.enabled",
                "hooks.dod_gate.max_attempts", "stop_hook_active", "tld dod exempt", "Branch protection and CI"):
        assert key in doc, key
    for heading in ("What the hooks do not protect", "How the dod-gate recognises a session", "Compatibility with the commands"):
        assert heading in doc, heading
    for command in ("/implement", "/land", "/deps", "/upstream", "/review", "/make-plan"):
        assert command in doc, command
    readme = (ROOT / "README.md").read_text()
    assert "## Guardrails" in readme and "docs/architecture/hooks.md" in readme
    assert "hooks.md" in (ROOT / "docs" / "reference" / "profile-reference.md").read_text()


# ---- profile trust and loud errors ---------------------------------------------------------------
def test_disable_must_be_a_list(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", "git:\n  main_branch: main\nhooks:\n  disable: no-merge\n")
    r = run("no-merge", bash("gh pr merge 1", repo))
    assert r.code == 2 and "hooks.disable" in r.stderr


def test_a_non_list_disable_in_the_working_tree_blocks_even_with_a_committed_profile(tmp_path):
    repo = make_repo(tmp_path / "r", "main", "git:\n  main_branch: main\n")
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feature/demo")
    (repo / ".tld" / "toolkit.yaml").write_text("git:\n  main_branch: main\nhooks:\n  disable: no-merge\n")
    r = run("no-merge", bash("gh pr merge 1", repo))
    assert r.code == 2 and "hooks.disable" in r.stderr


def test_a_budget_alarm_after_evaluate_still_denies(monkeypatch):
    from tld.guard.action import Action
    armed = object()
    monkeypatch.setattr(_common, "_arm_budget", lambda: (armed,))

    def late_alarm(token):
        if token and not getattr(late_alarm, "done", False):
            late_alarm.done = True
            raise _common.HookBudgetExceeded()

    monkeypatch.setattr(_common, "_disarm_budget", late_alarm)
    decision = _common.run_guard("no-merge", lambda ctx: None, True, Action("shell", "/", "/", command="ls"))
    assert decision.verdict == "deny" and "took longer" in decision.reason


def test_walks_up_from_cwd_without_project_dir(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    sub = repo / "sub"
    sub.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    payload = bash("git push origin main", sub)
    r = subprocess.run([sys.executable, str(HOOKS / "no_merge.py")], input=json.dumps(payload), capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 2 and "missing required key" not in r.stderr


def test_hooks_without_pyyaml(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "yaml.py").write_text("raise ImportError('no yaml here')\n")
    env = {"PYTHONPATH": str(fake)}
    r = run_script("no-merge", bash("git push -u origin feature/x", repo), project=repo, extra_env=env)
    assert r.returncode == 2 and "PyYAML is not installed" in r.stderr
    assert run_script("no-merge", bash("gh pr merge 1", repo), project=repo, extra_env=env).returncode == 2


def test_disable_in_a_branch_with_a_bogus_main_branch_is_ignored(tmp_path):
    repo = make_repo(tmp_path / "r", "main", "git:\n  main_branch: main\n")
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feature/demo")
    (repo / ".tld" / "toolkit.yaml").write_text("git:\n  main_branch: nosuch\nhooks:\n  disable: [no-merge]\n")
    assert run("no-merge", bash("gh pr merge 1", repo)).code == 2
