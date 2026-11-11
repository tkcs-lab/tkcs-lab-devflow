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


# One project's words that must not appear in the generic product (tests/core/test_no_project_words.py):
# the first consumer's name, its tools, its domain terms and its example branches and logins (C14).
FORBIDDEN = re.compile(
    r"privacy\s*fence|ruff|pytest|connector|approval gate|gated_call|gemini|ai studio|org-mode|mcpb|atlassian|"
    r"qa_fixture|andras|bandit|mypy", re.I)


# Read before the autouse fixture below removes every TLD_* variable from the tests' environment.
REQUIRE_BROWSER = os.environ.get("TLD_REQUIRE_BROWSER") == "1"


def need_browser() -> None:
    """Skip a browser test when node or Playwright is missing; fail instead when TLD_REQUIRE_BROWSER=1 (CI)."""
    import shutil
    import subprocess
    reason = None
    if shutil.which("node") is None:
        reason = "node is not installed"
    elif subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, text=True).returncode != 0:
        reason = "playwright cannot be required"
    if reason is None:
        return
    if REQUIRE_BROWSER:
        pytest.fail(f"TLD_REQUIRE_BROWSER=1 but {reason}")
    pytest.skip(reason)


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


@pytest.fixture(autouse=True)
def _isolated_hook_env(monkeypatch):
    """Keep ambient git / gh / Claude / tld environment out of every test: the guards read GIT_CONFIG_*
    (including the COUNT/KEY_n/VALUE_n injection vars), GH_*, CLAUDE_* and TLD_*, and a value leaking in
    from the developer's shell or an earlier test would make a case pass or fail for the wrong reason."""
    for key in list(os.environ):
        if (key.startswith(("GH_", "CLAUDE_", "TLD_"))
                or key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GITHUB_TOKEN")
                or re.fullmatch(r"GIT_CONFIG_(KEY|VALUE)_\d+", key)):
            monkeypatch.delenv(key, raising=False)
