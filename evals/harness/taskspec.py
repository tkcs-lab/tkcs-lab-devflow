"""Load and validate evals/tasks/<id>/task.yaml."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .common import TASKS_DIR, EVALS, plugin_script

SCHEMA = EVALS / "schema" / "task.schema.json"
DEFAULT_REPEATS = 3
DEFAULT_TIMEOUT_S = 900
DEFAULT_CEILING_USD = 2.0


@dataclass
class Task:
    id: str
    description: str
    fixture: dict
    graders: list[dict]
    command: str | None = None
    arguments: str = ""
    prompt: str | None = None
    expected: dict = field(default_factory=dict)
    plugin_ref: str = "HEAD"
    model: str | None = None
    repeats: int = DEFAULT_REPEATS
    timeout_s: int = DEFAULT_TIMEOUT_S
    cost_ceiling_usd: float = DEFAULT_CEILING_USD
    requires: list[str] = field(default_factory=list)
    plugin_extra: list[str] = field(default_factory=list)
    dir: Path | None = None

    def full_prompt(self) -> str:
        if self.prompt:
            return self.prompt
        return f"{self.command} {self.arguments}".strip()


def validate_task_data(data, graders_known: set[str] | None = None) -> list[str]:
    """Error messages for a parsed task.yaml (empty list when valid)."""
    vp = plugin_script("validate_profile")
    if not isinstance(data, dict):
        return ["task.yaml must be a mapping"]
    schema = json.loads(SCHEMA.read_text())
    errors: list[str] = []
    vp.check(data, schema, schema, "", errors)
    if errors:
        return errors
    fx = data["fixture"]
    if bool(fx.get("builder")) == bool(fx.get("path")):
        errors.append("fixture: give exactly one of 'builder' or 'path'")
    if not data.get("command") and not data.get("prompt"):
        errors.append("give 'command' (+ 'arguments') or a free 'prompt'")
    if data.get("command") and data.get("prompt"):
        errors.append("give 'command' or 'prompt', not both")
    if "cost_ceiling_usd" in data and not (isinstance(data["cost_ceiling_usd"], (int, float))
                                          and not isinstance(data["cost_ceiling_usd"], bool)
                                          and data["cost_ceiling_usd"] > 0):
        errors.append("cost_ceiling_usd must be a positive number")
    if graders_known is not None:
        for g in data["graders"]:
            name = g if isinstance(g, str) else g["name"]
            if name not in graders_known:
                errors.append(f"unknown grader '{name}'")
    return errors


def load_task(task_dir: Path, graders_known: set[str] | None = None) -> Task:
    path = task_dir / "task.yaml"
    data = yaml.safe_load(path.read_text())
    errors = validate_task_data(data, graders_known)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    if data["id"] != task_dir.name:
        raise ValueError(f"{path}: id '{data['id']}' must equal the directory name '{task_dir.name}'")
    graders = [{"name": g} if isinstance(g, str) else dict(g) for g in data["graders"]]
    plugin = data.get("plugin", {})
    return Task(
        id=data["id"], description=data["description"], fixture=data["fixture"], graders=graders,
        command=data.get("command"), arguments=data.get("arguments", ""), prompt=data.get("prompt"),
        expected=data.get("expected", {}), plugin_ref=plugin.get("ref", "HEAD"), model=data.get("model"),
        repeats=data.get("repeats", DEFAULT_REPEATS), timeout_s=data.get("timeout_s", DEFAULT_TIMEOUT_S),
        cost_ceiling_usd=float(data.get("cost_ceiling_usd", DEFAULT_CEILING_USD)),
        requires=data.get("requires", []), plugin_extra=plugin.get("extra", []), dir=task_dir,
    )


def discover(tasks_dir: Path = TASKS_DIR, graders_known: set[str] | None = None,
             only: list[str] | None = None) -> list[Task]:
    tasks = []
    for d in sorted(p for p in tasks_dir.iterdir() if (p / "task.yaml").is_file()):
        if only and d.name not in only:
            continue
        tasks.append(load_task(d, graders_known))
    missing = set(only or []) - {t.id for t in tasks}
    if missing:
        raise ValueError(f"no such task: {', '.join(sorted(missing))}")
    return tasks
