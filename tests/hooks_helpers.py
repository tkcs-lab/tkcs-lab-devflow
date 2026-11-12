"""Helpers for the guardrail hook tests: build repos, build hook events, run a hook.

Most tests call the hook's `evaluate` through `_common.execute` (the same code path as the script:
JSON in, exit code and stderr out). `run_script` runs the real script in a subprocess for the
contract tests.
"""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import CLAUDE

from tld.guard import _common  # noqa: F401  (re-exported for tests)

HOOKS = CLAUDE / "hooks"  # the Claude Code hook entry scripts (thin shims over the core modules)
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
import claude_adapter  # noqa: E402  (the Claude adapter: event JSON -> Action -> Decision -> exit code)
# hook name -> entry script stem in adapters/claude/hooks/
MODULES = {"no-merge": "no_merge", "no-force-push": "no_force_push", "no-git-tag": "no_git_tag",
           "secret-scan": "secret_scan", "protect-paths": "protect_paths", "dod-gate": "dod_gate",
           "plan-gate": "plan_gate", "model-check": "model_check", "board-gate": "board_gate"}
# hook name -> core module that holds its policy
CORE = {"no-merge": "tld.guard.no_merge", "no-force-push": "tld.guard.no_force_push",
        "no-git-tag": "tld.guard.no_git_tag", "secret-scan": "tld.guard.secret_scan",
        "protect-paths": "tld.guard.protect_paths", "dod-gate": "tld.dod.gate",
        "plan-gate": "tld.guard.plan_gate", "model-check": "tld.guard.model_check",
        "board-gate": "tld.guard.board_gate"}
FAIL_CLOSED = {"no-merge": True, "no-force-push": True, "no-git-tag": True, "secret-scan": False,
               "protect-paths": False, "dod-gate": False, "plan-gate": False,
               "model-check": False, "board-gate": False}
BASH_GUARDS = ("no-merge", "no-force-push", "no-git-tag", "protect-paths")
PROFILE = "git:\n  main_branch: main\n  branch_pattern: \"<type>/<kebab-case>\"\n"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@example.test", "-c", "user.name=t",
                           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                          check=True, capture_output=True, text=True).stdout


def make_repo(path, branch, profile=PROFILE):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    if profile is not None:
        (path / ".tld").mkdir(exist_ok=True)
        (path / ".tld" / "toolkit.yaml").write_text(profile)
    (path / "README.md").write_text("demo\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    git(path, "tag", "v1.0")
    if branch != "main":
        git(path, "checkout", "-q", "-b", branch)
    return path


def make_repo_with_origin(path, branch="feature/demo", committed=PROFILE, working=None):
    """A repo whose `main` (with `committed` profile) is pushed to a bare origin, checked out on `branch`.
    `working` replaces the working tree's profile after checkout. The guards read trust from origin."""
    path = Path(path)
    repo = make_repo(path, "main", committed)
    bare = path.parent / (path.name + "-origin.git")
    git(path.parent, "init", "-q", "--bare", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    if branch != "main":
        git(repo, "checkout", "-q", "-b", branch)
    if working is not None:
        (repo / ".tld").mkdir(exist_ok=True)
        (repo / ".tld" / "toolkit.yaml").write_text(working)
    return repo


def module(name):
    return importlib.import_module(CORE[name])


def event(tool, cwd, **tool_input):
    return {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": tool_input}


def bash(command, cwd):
    return event("Bash", cwd, command=command)


def run(hook, payload, project=None):
    """The hook's verdict on an event, through the Claude adapter: a Result (code 0 allow, 2 deny)."""
    old = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(project or payload.get("cwd") or os.getcwd())
    try:
        return claude_adapter.execute(hook, json.dumps(payload))
    finally:
        if old is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old


def run_script(hook, payload, project=None, stdin=None, extra_env=None):
    """Run the real script as Claude Code does: JSON on stdin, exit code and stderr back."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project or payload["cwd"]), **(extra_env or {})}
    return subprocess.run([sys.executable, str(HOOKS / f"{MODULES[hook]}.py")], input=stdin if stdin is not None
                          else json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)


def verdicts(hooks, command, cwd):
    return {h: run(h, bash(command, cwd)).code for h in hooks}
