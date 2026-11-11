"""The single-source guard corpus (guard_cases.yaml): every verified bypass as a deny case and the
toolkit's own commands as allow cases, run through the Claude adapter (core policy) and, for a
sample, through the real hook scripts as subprocesses."""
import json
import os
import random
import string
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import ROOT
from hooks_helpers import HOOKS, make_repo, make_repo_with_origin, run

CASES = yaml.safe_load((Path(__file__).parent / "guard_cases.yaml").read_text())
SECRETS = {"ghp": lambda: "ghp_" + "".join(random.choices(string.ascii_letters + string.digits, k=36)),
           "glpat": lambda: "glpat-" + "".join(random.choices(string.ascii_letters + string.digits, k=20))}


def _fill(text, case):
    return text.replace("{SECRET}", SECRETS[case["secret"]]()) if text and "secret" in case else text


@pytest.fixture(scope="module")
def repos(tmp_path_factory):
    base = tmp_path_factory.mktemp("corpus")
    return {"plain": make_repo(base / "plain", "feature/demo"),
            "origin": make_repo_with_origin(base / "origin")}


def _payload(case, repo):
    cwd = str(repo)
    if case["kind"] == "shell":
        return {"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": _fill(case["command"], case)}}
    if case["kind"] == "write":
        return {"tool_name": "Write", "cwd": cwd,
                "tool_input": {"file_path": case["path"], "content": _fill(case.get("content", "x\n"), case)}}
    return {"tool_name": f"mcp__github__{case['op']}", "cwd": cwd, "tool_input": case.get("args", {})}


def _ids(case):
    return f"{case.get('note', 'ok')}-{case['guard']}-{case['expect']}-{case.get('command', case.get('path', case.get('op')))[:40]}"


@pytest.mark.parametrize("case", CASES, ids=[_ids(c) for c in CASES])
def test_corpus_through_the_adapter(case, repos, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(ROOT))
    repo = repos[case["repo"]]
    r = run(case["guard"], _payload(case, repo), project=repo)
    want = 0 if case["expect"] == "allow" else 2
    assert r.code == want, f"{case.get('note')}: {case} -> {r.code} {r.stderr}"


# A sample through the real hook scripts (JSON on stdin, exit code out), to pin the subprocess path too.
SAMPLE = [c for c in CASES if c["kind"] != "github_op"][::4]


@pytest.mark.parametrize("case", SAMPLE, ids=[_ids(c) for c in SAMPLE])
def test_corpus_through_the_real_scripts(case, repos):
    from hooks_helpers import MODULES
    repo = repos[case["repo"]]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    r = subprocess.run([sys.executable, str(HOOKS / f"{MODULES[case['guard']]}.py")],
                       input=json.dumps(_payload(case, repo)), capture_output=True, text=True, env=env, timeout=60)
    want = 0 if case["expect"] == "allow" else 2
    assert r.returncode == want, f"{case}: {r.returncode} {r.stderr}"
