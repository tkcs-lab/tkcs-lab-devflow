"""Shared plumbing of the devflow guardrail hooks (Python 3.11, standard library plus PyYAML).

Contract with Claude Code (see docs/hooks.md): the event JSON arrives on stdin; exit 0 allows;
exit 2 blocks and the stderr text goes back to the agent; any other exit code is a non-blocking
error that only the user sees. The destructive hooks (no-merge, no-force-push, no-git-tag) block on
anything they cannot parse or on an internal error; the others report it and allow.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, NamedTuple

HOOK_NAMES = ("no-merge", "no-force-push", "no-git-tag", "secret-scan", "protect-paths", "dod-gate")
PROFILE = Path(".claude") / "toolkit.yaml"

# Defaults of the `hooks` section. They are repeated in schema/profile.schema.json; a test keeps them equal.
DEFAULT_PROTECT_PATHS = [".claude/toolkit.yaml", ".env", ".env.*", "*.lock", "package-lock.json", "go.sum",
                         ".github/workflows/**"]
# Always allowed, whatever the profile says: templates and files the toolkit's own commands install.
BUILTIN_PROTECT_ALLOW = [".env.example", ".env.sample", ".env.template", ".env.dist",
                         ".github/workflows/devflow-land.yml", ".github/workflows/devflow-release.yml"]
DEFAULT_MAX_ATTEMPTS = 3
HOOK_BUDGET_SECONDS = 15  # below the 20 s hook timeout, so a slow destructive hook denies instead of being killed


class HookBudgetExceeded(BaseException):
    """Raised by the SIGALRM handler. A BaseException so that `except OSError` / `except Exception`
    around a git call cannot swallow it."""


def exit_import_error(name: str, exc: BaseException) -> None:
    """A destructive hook could not load its helpers: deny (exit 2) instead of crashing with status 1."""
    print(f"devflow {name}: internal error while loading ({type(exc).__name__}: {exc}).", file=sys.stderr)
    sys.exit(2)


class ProfileError(Exception):
    """A project fact the hook needs is missing or malformed. The message is shown to the agent."""


@dataclass
class Ctx:
    payload: dict
    cwd: str
    project_dir: str
    profile: dict | None
    profile_problem: str | None = None
    tool: str = ""
    tool_input: dict = field(default_factory=dict)
    notice: str | None = None  # shown to the user (stdout `systemMessage`) when the hook allows
    disable_error: ProfileError | None = None  # dod-gate only: a malformed hooks.disable, re-raised by its evaluate

    def hooks_section(self) -> dict:
        section = (self.profile or {}).get("hooks")
        if section is None:
            return {}
        if not isinstance(section, dict):
            raise ProfileError("toolkit.yaml: 'hooks' must be a mapping")
        return section

    def list_key(self, key: str, default: list[str]) -> list[str]:
        value = self.hooks_section().get(key)
        if value is None:
            return list(default)
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise ProfileError(f"toolkit.yaml: 'hooks.{key}' must be a list of non-empty strings")
        return value

    def require_main_branch(self) -> str:
        git = (self.profile or {}).get("git")
        value = git.get("main_branch") if isinstance(git, dict) else None
        if not isinstance(value, str) or not value:
            why = f" ({self.profile_problem})" if self.profile_problem else ""
            raise ProfileError(f"toolkit.yaml: missing required key 'git.main_branch'{why}. The devflow "
                               "guardrail hooks need it; see docs/profile-reference.md in the claude-toolkit repo.")
        return value

    def disabled(self, name: str) -> bool:
        return name in trusted_disable(self)


def _committed_profile(project: str, main: str) -> dict | None:
    """The profile as committed on origin/<main>, else <main>; None when neither can be read."""
    import yaml
    for ref in (f"origin/{main}", main):
        try:
            r = subprocess.run(["git", "-C", project, "show", f"{ref}:{PROFILE.as_posix()}"], capture_output=True,
                               text=True, timeout=5, stdin=subprocess.DEVNULL)
            if r.returncode == 0:
                data = yaml.safe_load(r.stdout)
                return data if isinstance(data, dict) else None
        except (OSError, subprocess.SubprocessError, yaml.YAMLError):
            continue
    return None


def _disable_list(profile: dict) -> list[str]:
    section = profile.get("hooks")
    if section is None:
        return []
    if not isinstance(section, dict):
        raise ProfileError("toolkit.yaml: 'hooks' must be a mapping")
    value = section.get("disable")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ProfileError("toolkit.yaml: 'hooks.disable' must be a list of non-empty strings")
    return list(value)


def trusted_disable(ctx: Ctx) -> list[str]:
    """`hooks.disable` as committed on the main branch, so a branch cannot switch a guardrail off for itself.
    With no commit yet (or no repository) no trusted copy can exist and the working tree's list is used."""
    if ctx.profile is None:
        return []
    working = _disable_list(ctx.profile)  # validated even when only the committed list is applied
    git = ctx.profile.get("git")
    main = git.get("main_branch") if isinstance(git, dict) else None
    try:
        head = subprocess.run(["git", "-C", ctx.project_dir, "rev-parse", "--verify", "-q", "HEAD"],
                              capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        head = False
    if not head:
        return working
    committed = _committed_profile(ctx.project_dir, main) if isinstance(main, str) and main else None
    if committed is None:
        return []
    if committed.get("hooks") != ctx.profile.get("hooks"):
        ctx.notice = (f"the working tree's hooks section differs from the committed {main} profile; "
                      "only the committed hooks.disable is applied")
    return _disable_list(committed)


def find_project(cwd: str) -> tuple[str, dict | None, str | None]:
    """Project directory, parsed profile (or None) and the reason there is none."""
    starts = []
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    start = Path(cwd or os.getcwd())
    outside = False
    if env:
        root = Path(env).resolve()
        starts.append(Path(env))
        try:
            inside = start.resolve().is_relative_to(root)
        except OSError:
            inside = False
        if inside:  # the walk up from cwd stops at the project directory
            for d in (start, *start.parents):
                starts.append(d)
                if d.resolve() == root:
                    break
        else:
            outside = True
    else:
        starts += [start, *start.parents]
    for d in starts:
        path = d / PROFILE
        if path.is_file():
            try:
                import yaml
                data = yaml.safe_load(path.read_text())
            except ImportError:
                return str(d), None, "PyYAML is not installed"
            except Exception as exc:  # YAML error or unreadable file
                return str(d), None, f"{PROFILE} is not valid YAML: {str(exc).splitlines()[0] if str(exc) else exc}"
            if not isinstance(data, dict):
                return str(d), None, f"{PROFILE} must be a YAML mapping"
            return str(d), data, None
    if outside and (start / PROFILE).is_file():
        return env or str(start), None, f"{PROFILE} outside CLAUDE_PROJECT_DIR ignored"
    return env or str(start), None, f"no {PROFILE} found from {start}"


def make_ctx(payload: dict) -> Ctx:
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    project, profile, problem = find_project(cwd)
    tool_input = payload.get("tool_input")
    return Ctx(payload, cwd, project, profile, problem, str(payload.get("tool_name") or ""),
               tool_input if isinstance(tool_input, dict) else {})


class Result(NamedTuple):
    code: int
    stderr: str = ""
    stdout: str = ""


def _arm_budget():
    """Start the time budget; returns the previous handler, or None when SIGALRM is unavailable."""
    if not hasattr(signal, "SIGALRM"):
        return None

    def on_alarm(signum, frame):  # noqa: ARG001
        raise HookBudgetExceeded()
    try:
        previous = signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, HOOK_BUDGET_SECONDS)
    except (ValueError, OSError):  # not the main thread
        return None
    return (previous,)


def _disarm_budget(armed) -> None:
    if armed:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, armed[0])


def execute(name: str, evaluate: Callable[[Ctx], str | None], fail_closed: bool, stdin_text: str) -> Result:
    """Run one hook on the raw stdin text."""
    prefix = f"devflow {name}: "
    problem_code = 2 if fail_closed else 1
    try:
        payload = json.loads(stdin_text)
        if not isinstance(payload, dict):
            raise ValueError("the event is not a JSON object")
    except ValueError as exc:
        return Result(problem_code, prefix + f"cannot read the hook event ({exc}).")
    armed = _arm_budget() if fail_closed else None
    try:
        ctx = make_ctx(payload)
        try:
            if ctx.disabled(name):
                return Result(0)
        except ProfileError as exc:
            if name != "dod-gate":
                raise
            ctx.disable_error = exc  # the gate stays on and counts it as a failed attempt
        message = evaluate(ctx)
        _disarm_budget(armed)  # before returning: an alarm in this window is still caught below
        armed = None
    except HookBudgetExceeded:
        return Result(2, prefix + f"took longer than {HOOK_BUDGET_SECONDS} s, so the call is denied.")
    except ProfileError as exc:
        return Result(2, prefix + str(exc))
    except Exception as exc:  # noqa: BLE001 - a hook must never crash into an allow
        return Result(problem_code, prefix + f"internal error ({type(exc).__name__}: {exc}).")
    finally:
        _disarm_budget(armed)
    if message:
        return Result(2, prefix + message)
    if ctx.notice:
        return Result(0, "", json.dumps({"systemMessage": prefix + ctx.notice}))
    return Result(0)


def main(name: str, evaluate: Callable[[Ctx], str | None], fail_closed: bool) -> None:
    result = execute(name, evaluate, fail_closed, sys.stdin.read())
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.code)
