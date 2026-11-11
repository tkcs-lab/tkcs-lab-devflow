"""Paths, shared helpers and loading of the plugin's own validators (the ready-made graders)."""
from __future__ import annotations

import hashlib
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals"
PLUGIN = ROOT  # the tld plugin is sourced from the repository root
CLAUDE = ROOT / "adapters" / "claude"
# what the plugin needs at run time: its manifest, the Claude adapter, the launcher and the core package
PLUGIN_PATHS = (".claude-plugin", "adapters", "bin", "src")
CORE_MODULES = {"validate_profile": "tld.profile.validate", "validate_manifest": "tld.plan.manifest",
                "validate_status_record": "tld.board.record"}
TASKS_DIR = EVALS / "tasks"
BASELINES_DIR = EVALS / "baselines"
RESULTS_DIR = EVALS / "results"
TRANSCRIPTS_DIR = EVALS / "transcripts"

_cache: dict[str, object] = {}


def plugin_script(name: str):
    """Import one of the core validators (tld.profile.validate, tld.plan.manifest, tld.board.record)."""
    if name not in _cache:
        src = str(ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        _cache[name] = importlib.import_module(CORE_MODULES[name])
    return _cache[name]


def git(*args: str, cwd: Path, check: bool = True) -> str:
    env = {
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd), "PATH": _path(),
        "GIT_AUTHOR_NAME": "Eval Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Eval Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {p.stderr.strip()}")
    return p.stdout


def _path() -> str:
    import os
    return os.environ.get("PATH", "/usr/bin:/bin")


def plugin_git_sha() -> str:
    try:
        sha = git("rev-parse", "HEAD", cwd=ROOT).strip()
        dirty = bool(git("status", "--porcelain", "--", *PLUGIN_PATHS, cwd=ROOT).strip())
        return sha + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def command_hashes(plugin_dir: Path = PLUGIN) -> dict[str, str]:
    out = {}
    for p in sorted((plugin_dir / "adapters" / "claude" / "commands").glob("*.md")):
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out
