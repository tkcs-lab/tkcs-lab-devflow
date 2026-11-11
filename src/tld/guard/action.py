"""The neutral input and output of every guard: an `Action` goes in, a `Decision` comes out.

An adapter (for example adapters/claude/hooks/) turns its runtime's event into an Action and the
Decision back into whatever its runtime expects. Nothing here knows about a particular agent runtime.

    Action(kind="shell", project_dir="/w", cwd="/w", command="git push -f")
    Action(kind="write", project_dir="/w", cwd="/w", path="/w/.env", content=(("the new text", "X=1"),))
    Action(kind="github_op", project_dir="/w", cwd="/w", op="merge_pull_request", args={"pullNumber": 3})
    Action(kind="stop", project_dir="/w", cwd="/w", session_id="s1", continuing=True)
"""
from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("shell", "write", "github_op", "stop")
VERDICTS = ("allow", "deny", "error")


@dataclass(frozen=True)
class Action:
    kind: str
    project_dir: str
    cwd: str
    command: str | None = None                      # shell
    path: str | None = None                         # write
    content: tuple[tuple[str, str], ...] = ()       # write: (where, text) pieces that would be written
    op: str | None = None                           # github_op: operation name, e.g. merge_pull_request
    args: dict = field(default_factory=dict)        # github_op: its arguments
    session_id: str | None = None                   # stop
    continuing: bool = False                        # stop: the runtime is already continuing after a block

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown action kind {self.kind!r}")


@dataclass(frozen=True)
class Settings:
    """What the adapter knows and the core cannot: protected paths of the runtime, where the plugin is."""
    extra_protected: tuple[str, ...] = ()   # patterns: repo-relative, or absolute / `~/` for outside the repo
    plugin_root: str | None = None          # the installed toolkit; always protected
    project_hint: str | None = None         # the runtime's project directory, if it names one


@dataclass(frozen=True)
class Decision:
    verdict: str                 # allow | deny | error (a non-blocking problem the user should see)
    reason: str = ""
    notice: str | None = None    # shown to the user when the action is allowed

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {self.verdict!r}")


def allow(notice: str | None = None) -> Decision:
    return Decision("allow", "", notice)


def deny(reason: str) -> Decision:
    return Decision("deny", reason)
