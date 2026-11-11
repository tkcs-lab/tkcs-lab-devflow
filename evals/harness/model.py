"""Plain data types shared by the runner, the agents and the graders."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentRequest:
    workdir: Path
    prompt: str
    plugin_dirs: list[Path]
    model: str | None
    timeout_s: int
    max_budget_usd: float
    task_id: str = ""
    repeat: int = 1


@dataclass
class AgentResult:
    exit_status: int = 0
    result_text: str = ""
    actions: list[dict] = field(default_factory=list)     # the neutral action log (harness/actions.py)
    transcript: list[dict] = field(default_factory=list)  # the runtime's own events; stored, never graded
    turns: int = 0
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0})
    cost_usd: float = 0.0
    duration_s: float = 0.0
    model: str = ""
    aborted: str | None = None  # "timeout" | "cost_ceiling" | None
    error: str | None = None


@dataclass
class Doc:
    ref: str   # "worktree" or a branch name
    path: str
    text: str


@dataclass
class Artifacts:
    """What is left of a run: the final git state, as plain data."""
    base_sha: str = ""
    head: str = ""
    refs: dict[str, str] = field(default_factory=dict)       # "main", "origin/plan/x", "tag:v1" -> sha
    start_refs: dict[str, str] = field(default_factory=dict)  # the same, before the agent ran
    status: str = ""                                          # git status --porcelain
    changed_files: list[str] = field(default_factory=list)    # union over HEAD, worktree and all other refs
    diff: str = ""
    merge_commits: list[str] = field(default_factory=list)
    documents: list[Doc] = field(default_factory=list)
    origin_path: str | None = None                            # the bare origin repository, when graders may search it


@dataclass
class GradeResult:
    passed: bool
    reason: str
    value: object = None  # e.g. the noise count; reported, not judged


@dataclass
class GradeContext:
    artifacts: Artifacts
    expected: dict
    actions: list[dict]
    result_text: str
    workdir: Path | None = None
    params: dict = field(default_factory=dict)

    def docs(self, glob: str) -> list[Doc]:
        from fnmatch import fnmatch
        return [d for d in self.artifacts.documents if fnmatch(d.path, glob)]
