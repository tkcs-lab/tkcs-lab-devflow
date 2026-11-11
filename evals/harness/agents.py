"""The agent seam: anything with run(AgentRequest) -> AgentResult.

The core ships one agent, StubAgent, which replays canned outputs (pytest and the CI stub run use it). The
agents that call a model live in the runtime adapters (evals/adapters/<name>/) and are found by name with
`get_agent`.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Protocol

from .actions import apply_guards, validate
from .common import git
from .model import AgentRequest, AgentResult

ADAPTERS = {"claude": "evals.adapters.claude"}


class Agent(Protocol):
    name: str

    def run(self, req: AgentRequest) -> AgentResult: ...


class AgentError(RuntimeError):
    pass


def adapter(name: str):
    """The adapter module of a runtime (`claude`): Agent, CHECKED_AGAINST, command_file, command_model,
    credential_problem."""
    if name not in ADAPTERS:
        raise KeyError(f"no adapter '{name}' (known: {', '.join(sorted(ADAPTERS))})")
    return importlib.import_module(ADAPTERS[name])


class StubAgent:
    """Replays canned outputs. `canned` is one dict or a list (one per repeat, the last one repeats).

    A canned entry: files {path: text}, delete_files [paths], branch (commit the files on this branch and push it),
    commit_message, result_text, actions (the neutral action log), guard (true: decide every shell, write and
    github_op action with the real tld guards in the work clone, instead of trusting its `error`), transcript
    (stored only), turns, tokens, cost_usd, duration_s, model, exit_status, aborted, error.
    """
    name = "stub"

    def __init__(self, canned: dict | list[dict] | None = None, by_task: dict[str, dict | list[dict]] | None = None):
        self.canned = canned
        self.by_task = by_task or {}
        self.calls: list[AgentRequest] = []

    @classmethod
    def from_dir(cls, directory: Path) -> "StubAgent":
        by_task = {p.stem: json.loads(p.read_text()) for p in sorted(Path(directory).glob("*.json"))}
        return cls(by_task=by_task)

    def _entry(self, req: AgentRequest) -> dict:
        src = self.by_task.get(req.task_id, self.canned)
        if src is None:
            raise AgentError(f"stub agent has no canned output for task '{req.task_id}'")
        if isinstance(src, list):
            return src[min(req.repeat - 1, len(src) - 1)]
        return src

    def run(self, req: AgentRequest) -> AgentResult:
        self.calls.append(req)
        c = self._entry(req)
        wd = req.workdir
        root = wd.resolve()
        actions = c.get("actions", [])
        problems = validate(actions)
        if problems:
            raise AgentError("stub actions: " + "; ".join(problems))
        if c.get("guard"):
            actions = apply_guards(actions, wd)
        for rel in c.get("delete_files", []):
            if not (wd / rel).resolve().is_relative_to(root):
                raise AgentError(f"stub file path escapes the workdir: {rel}")
            (wd / rel).unlink(missing_ok=True)
        for rel, text in c.get("files", {}).items():
            p = wd / rel
            if not p.resolve().is_relative_to(root):
                raise AgentError(f"stub file path escapes the workdir: {rel}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if c.get("branch"):
            git("checkout", "-q", "-b", c["branch"], cwd=wd)
            git("add", "-A", cwd=wd)
            git("commit", "-q", "-m", c.get("commit_message", "stub change"), cwd=wd)
            git("push", "-q", "origin", c["branch"], cwd=wd)
        res = AgentResult(
            exit_status=c.get("exit_status", 0), result_text=c.get("result_text", ""), actions=actions,
            transcript=c.get("transcript", []), turns=c.get("turns", 1),
            cost_usd=c.get("cost_usd", 0.0), duration_s=c.get("duration_s", 0.0),
            model=c.get("model", "stub"), aborted=c.get("aborted"), error=c.get("error"),
        )
        res.tokens = {**res.tokens, **c.get("tokens", {})}
        return res
