"""The Claude Code adapter of the eval harness.

- runner.py   ClaudeCodeAgent: `claude -p --output-format stream-json` in the work clone, with the plugin loaded
- stream.py   stream-json events -> AgentResult and the neutral action log
- hookcheck.py the Claude Code hook protocol: feed adapters/claude/hooks/ PreToolUse JSON directly (no model)

The module-level names below are what the core asks an adapter for.
"""
from __future__ import annotations

import os
from pathlib import Path

from evals.harness.common import ROOT

from .runner import CHECKED_AGAINST, ClaudeCodeAgent as Agent  # noqa: F401

COMMANDS = ROOT / "adapters" / "claude" / "commands"


def command_name(command: str | None) -> str | None:
    """`/tld:dod` -> `dod`; None when the task has no command."""
    words = (command or "").split(maxsplit=1)
    if not words:
        return None
    return words[0].rsplit(":", 1)[-1].lstrip("/") or None


def command_files(plugin_dir: Path = ROOT) -> dict[str, Path]:
    """Every command of the plugin: name -> its command file."""
    return {p.stem: p for p in sorted((plugin_dir / "adapters" / "claude" / "commands").glob("*.md"))}


def command_model(command: str | None) -> str | None:
    """The `model:` key in the front matter of the plugin command a task runs, or None: it overrides --model."""
    name = command_name(command)
    path = COMMANDS / f"{name}.md" if name else None
    if path is None or not path.is_file():
        return None
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip().strip("\"'") or None
    return None


def credential_problem() -> str | None:
    """Why a real run cannot start, or None."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return None
    return ("set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN; the agent runs with an empty HOME "
            "and cannot use a stored login.")
