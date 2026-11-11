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
    transcript: list[dict] = field(default_factory=list)
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
    transcript: list[dict]
    result_text: str
    workdir: Path | None = None
    params: dict = field(default_factory=dict)

    def docs(self, glob: str) -> list[Doc]:
        from fnmatch import fnmatch
        return [d for d in self.artifacts.documents if fnmatch(d.path, glob)]


def tool_calls(transcript: list[dict]) -> list[dict]:
    """Each tool call of a stream-json transcript with its result: {id, name, input, is_error, output}.

    A call with no recorded result has is_error None.
    """
    calls: dict[str, dict] = {}
    order: list[str] = []
    for ev in transcript:
        msg = ev.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block["id"]] = {"id": block["id"], "name": block.get("name", ""),
                                      "input": block.get("input", {}), "is_error": None, "output": ""}
                order.append(block["id"])
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                c = calls[block["tool_use_id"]]
                c["is_error"] = bool(block.get("is_error"))
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
                c["output"] = str(content)
    return [calls[i] for i in order]
