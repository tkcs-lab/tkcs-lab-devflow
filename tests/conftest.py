import importlib
import os
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TLD = SRC / "tld"                      # the core package
CLAUDE = ROOT / "adapters" / "claude"  # the Claude Code adapter (commands, skills, agents, hooks, mcp.json)
BIN = ROOT / "bin" / "tld"             # the launcher; runs without installing the package
FIXTURES = Path(__file__).resolve().parent / "fixtures"

for _p in (str(SRC), str(ROOT)):  # the tld package, and the evals/ package (the eval harness)
    if _p not in sys.path:
        sys.path.insert(0, _p)


# One project's words that must not appear in the generic product (tests/core/test_no_project_words.py).
FORBIDDEN = re.compile(r"privacyfence|ruff|pytest|src/privacyfence|connector", re.I)


def frontmatter(path):
    """The YAML front matter of a command, skill or agent file."""
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no front matter"
    return yaml.safe_load(m.group(1))


def tld_cmd(*words: str) -> list[str]:
    """The argv that runs `tld <words>` through the launcher, as a session would."""
    return [sys.executable, str(BIN), *words]


def _load(name: str):
    """Import a core module by its dotted name (e.g. `tld.plan.manifest`)."""
    return importlib.import_module(name)


@pytest.fixture(scope="session")
def vm():
    return _load("tld.plan.manifest")


@pytest.fixture(scope="session")
def vp():
    return _load("tld.profile.validate")


@pytest.fixture(scope="session")
def ra():
    return _load("tld.ops.repo_admin")


# ---- guardrail hooks -------------------------------------------------------------------------
@pytest.fixture(scope="session")
def feature_repo(tmp_path_factory):
    """A git repo with a profile (main branch `main`), a local tag v1.0, checked out on feature/demo."""
    from hooks_helpers import make_repo
    return make_repo(tmp_path_factory.mktemp("feature"), "feature/demo")


@pytest.fixture(scope="session")
def main_repo(tmp_path_factory):
    """The same repo state, checked out on `main`."""
    from hooks_helpers import make_repo
    return make_repo(tmp_path_factory.mktemp("onmain"), "main")


@pytest.fixture()
def fresh_repo(tmp_path):
    from hooks_helpers import make_repo
    return make_repo(tmp_path / "repo", "feature/demo")


@pytest.fixture(scope="session", autouse=True)
def _isolated_git_config():
    """No global or system git config (signing, hooks, aliases) leaks into the repositories tests build."""
    mp = pytest.MonkeyPatch()
    mp.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    mp.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    mp.setenv("GIT_CONFIG_NOSYSTEM", "1")
    yield
    mp.undo()
