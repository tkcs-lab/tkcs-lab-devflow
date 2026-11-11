"""Paths, shared helpers and loading of the plugin's own validators (the ready-made graders).

Nothing here knows about a particular agent runtime; the runtime adapters live in evals/adapters/.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals"
PLUGIN = ROOT  # the tld plugin is sourced from the repository root
# what the plugin needs at run time: its manifest, the adapters, the launcher, the core package and the
# neutral content the commands follow (playbooks, roles, checklists, stacks)
PLUGIN_PATHS = (".claude-plugin", "adapters", "bin", "src", "playbooks", "roles", "checklists", "stacks")
CORE_MODULES = {"validate_profile": "tld.profile.validate", "validate_manifest": "tld.plan.manifest",
                "validate_status_record": "tld.board.record", "docs_index": "tld.ops.docs_index"}
TASKS_DIR = EVALS / "tasks"
STUBS_DIR = EVALS / "stubs"
BASELINES_DIR = EVALS / "baselines"
RESULTS_DIR = EVALS / "results"
TRANSCRIPTS_DIR = EVALS / "transcripts"

_cache: dict[str, object] = {}


def plugin_script(name: str):
    """Import one of the core modules the graders reuse (validators, the docs index)."""
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
    return os.environ.get("PATH", "/usr/bin:/bin")


def plugin_git_sha() -> str:
    try:
        sha = git("rev-parse", "HEAD", cwd=ROOT).strip()
        dirty = bool(git("status", "--porcelain", "--", *PLUGIN_PATHS, cwd=ROOT).strip())
        return sha + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


_PROXY_VARS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS",
               "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
_GIT_IDENTITY = {"GIT_AUTHOR_NAME": "tld-evals", "GIT_COMMITTER_NAME": "tld-evals",
                 "GIT_AUTHOR_EMAIL": "evals@example.invalid", "GIT_COMMITTER_EMAIL": "evals@example.invalid"}


def clean_env(home: Path | None = None, keep_proxy: bool = False, keep: frozenset[str] = frozenset(),
              drop=lambda key: False) -> dict[str, str]:
    """An environment with an empty HOME (no stored logins or config), no GitHub or cloud credentials and no
    proxy variables of the caller, so a stray push or API call cannot succeed. `keep` names credential variables
    to pass through anyway (the model's key); `drop(key)` removes more (an adapter's own session variables)."""
    env = {}
    for k, v in os.environ.items():
        up = k.upper()
        if k not in keep and any(s in up for s in ("TOKEN", "SECRET", "PASSWORD", "AWS_", "GH_", "GITHUB")):
            continue
        if up in _PROXY_VARS and not keep_proxy:
            continue
        if k not in keep and drop(k):
            continue
        env[k] = v
    if home is None:
        home = Path(tempfile.mkdtemp(prefix="evals-home-"))
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    for k, v in _GIT_IDENTITY.items():
        env.setdefault(k, v)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env
