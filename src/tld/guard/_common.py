"""Shared plumbing of the tld guards (Python 3.11, standard library plus PyYAML).

`run_guard(name, evaluate, fail_closed, action, settings)` loads the project profile for the Action,
applies `hooks.disable` from the trusted copy (trust.py), runs the guard's `evaluate(ctx)` within a time
budget and returns a Decision. The destructive guards (no-merge, no-force-push, no-git-tag) deny on
anything they cannot parse and on an internal error; the others report it (verdict `error`) and allow.
An adapter turns the runtime's event into the Action and the Decision into the runtime's reply.
"""
from __future__ import annotations

import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tld.guard import trust
from tld.guard.action import Action, Decision, Settings

HOOK_NAMES = ("no-merge", "no-force-push", "no-git-tag", "secret-scan", "protect-paths", "dod-gate")
PROFILE = Path(".tld") / "toolkit.yaml"

# Defaults of the `hooks` section. They are repeated in schema/profile.schema.json; a test keeps them equal.
DEFAULT_PROTECT_PATHS = [".tld/toolkit.yaml", ".env", ".env.*", "*.lock", "package-lock.json", "go.sum",
                         ".github/workflows/**"]
# Always allowed, whatever the profile says: templates of environment files.
BUILTIN_PROTECT_ALLOW = [".env.example", ".env.sample", ".env.template", ".env.dist"]
# The workflow files the toolkit's own commands install (S13). Protected whatever the profile says, and writable only
# while `tld guard allow-workflow-install <file>` has set the install marker: the land workflow holds the agent token
# and the release workflow is the only route to a tag.
GUARDED_WORKFLOWS = [".github/workflows/tld-land.yml", ".github/workflows/tld-release.yml"]
DEFAULT_MAX_ATTEMPTS = 3
HOOK_BUDGET_SECONDS = 15  # below a 20 s runtime timeout, so a slow destructive guard denies instead of being killed


class HookBudgetExceeded(BaseException):
    """Raised by the SIGALRM handler. A BaseException so that `except OSError` / `except Exception`
    around a git call cannot swallow it."""


class ProfileError(Exception):
    """A project fact the guard needs is missing or malformed. The message is shown to the agent."""


def _list_value(section: dict, key: str) -> list[str] | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ProfileError(f"toolkit.yaml: 'hooks.{key}' must be a list of non-empty strings")
    return list(value)


def _hooks(profile: dict | None) -> dict:
    section = (profile or {}).get("hooks")
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ProfileError("toolkit.yaml: 'hooks' must be a mapping")
    return section


def _main_of(profile: dict | None) -> str | None:
    git = (profile or {}).get("git")
    value = git.get("main_branch") if isinstance(git, dict) else None
    return value if isinstance(value, str) and value else None


@dataclass
class Ctx:
    action: Action
    project_dir: str
    profile: dict | None
    profile_problem: str | None = None
    settings: Settings = field(default_factory=Settings)
    notice: str | None = None  # shown to the user when the guard allows
    disable_error: ProfileError | None = None  # dod-gate only: a malformed hooks.disable, re-raised by its evaluate
    _trusted: tuple | None = None

    @property
    def cwd(self) -> str:
        return self.action.cwd

    def hooks_section(self) -> dict:
        return _hooks(self.profile)

    def trusted(self) -> tuple[dict | None, bool]:
        """(trusted profile, available); fetched once per guard run."""
        if self._trusted is None:
            self._trusted = trust.trusted_profile(self.project_dir, _main_of(self.profile))
        return self._trusted

    def list_key(self, key: str, default: list[str]) -> list[str]:
        """A protect list. From the trusted copy when there is one; otherwise the defaults plus the
        working tree's entries. An allow list (`*_allow`) is never taken from the working tree."""
        working = _list_value(self.hooks_section(), key)  # validated even when it is not applied
        trusted, available = self.trusted()
        if available:
            value = _list_value(_hooks(trusted), key)
            return list(default) if value is None else value
        if key.endswith("_allow"):
            return list(default)
        return list(dict.fromkeys([*default, *(working or [])]))

    def main_branches(self) -> list[str]:
        """The main branch of the working tree's profile, plus the trusted copy's when that names another."""
        main = self.require_main_branch()
        trusted, available = self.trusted()
        other = _main_of(trusted) if available else None
        return [main] + ([other] if other and other != main else [])

    def require_main_branch(self) -> str:
        value = _main_of(self.profile)
        if value is None:
            why = f" ({self.profile_problem})" if self.profile_problem else ""
            raise ProfileError(f"toolkit.yaml: missing required key 'git.main_branch'{why}. The tld "
                               "guardrail hooks need it; see docs/reference/profile-reference.md in the tkcs-lab-devflow repo.")
        return value

    def disabled(self, name: str) -> bool:
        return name in trusted_disable(self)


def trusted_disable(ctx: Ctx) -> list[str]:
    """`hooks.disable` from the trusted copy only; [] when there is none (every guard on)."""
    if ctx.profile is None:
        return []
    working = _list_value(ctx.hooks_section(), "disable") or []
    trusted, available = ctx.trusted()
    if not available:
        if working:
            ctx.notice = ("no trusted copy of the profile could be read from the remote main branch, so "
                          "hooks.disable is ignored and every guard is on")
        return []
    committed = _list_value(_hooks(trusted), "disable") or []
    if (trusted or {}).get("hooks") != ctx.profile.get("hooks"):
        ctx.notice = (f"the working tree's hooks section differs from the {_main_of(ctx.profile)} profile on the "
                      "remote; only the remote hooks.disable and protect lists are applied")
    return committed


def find_project(cwd: str, hint: str | None = None) -> tuple[str, dict | None, str | None]:
    """Project directory, parsed profile (or None) and the reason there is none. `hint` is the project
    directory the runtime names, if any: the walk up from cwd stops there and never leaves it."""
    starts = []
    start = Path(cwd or os.getcwd())
    outside = False
    if hint:
        root = Path(hint).resolve()
        starts.append(Path(hint))
        try:
            inside = start.resolve().is_relative_to(root)
        except OSError:
            inside = False
        if inside:
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
        return hint or str(start), None, f"{PROFILE} outside the project directory ignored"
    return hint or str(start), None, f"no {PROFILE} found from {start}"


def make_ctx(action: Action, settings: Settings) -> Ctx:
    _, profile, problem = find_project(action.cwd, settings.project_hint or action.project_dir)
    return Ctx(action, action.project_dir, profile, problem, settings)


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


def run_guard(name: str, evaluate: Callable[[Ctx], str | None], fail_closed: bool, action: Action,
              settings: Settings | None = None) -> Decision:
    """Run one guard on one Action."""
    prefix = f"tld {name}: "
    settings = settings or Settings()
    armed = _arm_budget() if fail_closed else None
    ctx = None
    try:
        ctx = make_ctx(action, settings)
        try:
            if ctx.disabled(name):
                return Decision("allow")
        except ProfileError as exc:
            if name != "dod-gate":
                raise
            ctx.disable_error = exc  # the gate stays on and counts it as a failed attempt
        message = evaluate(ctx)
        _disarm_budget(armed)  # before returning: an alarm in this window is still caught below
        armed = None
    except HookBudgetExceeded:
        return Decision("deny", prefix + f"took longer than {HOOK_BUDGET_SECONDS} s, so the call is denied.")
    except ProfileError as exc:
        return Decision("deny", prefix + str(exc))
    except Exception as exc:  # noqa: BLE001 - a guard must never crash into an allow
        return Decision("deny" if fail_closed else "error", prefix + f"internal error ({type(exc).__name__}: {exc}).")
    finally:
        _disarm_budget(armed)
    if message:
        return Decision("deny", prefix + message)
    return Decision("allow", "", prefix + ctx.notice if ctx.notice else None)


def problem(name: str, fail_closed: bool, text: str) -> Decision:
    """A Decision for an input the adapter could not read."""
    return Decision("deny" if fail_closed else "error", f"tld {name}: {text}")
