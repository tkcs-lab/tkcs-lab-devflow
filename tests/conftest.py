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
BIN = ROOT / "launcher" / "tld"             # the launcher; runs without installing the package
FIXTURES = Path(__file__).resolve().parent / "fixtures"

for _p in (str(SRC), str(ROOT)):  # the tld package, and the evals/ package (the eval harness)
    if _p not in sys.path:
        sys.path.insert(0, _p)


# One project's words that must not appear in the generic product (tests/core/test_no_project_words.py):
# the first consumer's name, its tools, its domain terms and its example branches and logins (C14).
FORBIDDEN = re.compile(
    r"privacy\s*fence|ruff|pytest|connector|approval gate|gated_call|gemini|ai studio|org-mode|mcpb|atlassian|"
    r"qa_fixture|andras|bandit|mypy", re.I)


# Read before the autouse fixture below removes every TLD_* variable from the tests' environment. CI sets it, so a
# test whose tool (node, Playwright, jq) is missing fails there instead of being skipped silently.
REQUIRE_BROWSER = os.environ.get("TLD_REQUIRE_BROWSER") == "1"


def missing_tool(reason: str) -> None:
    """Skip the test for a missing tool; fail it instead when TLD_REQUIRE_BROWSER=1 (CI)."""
    if REQUIRE_BROWSER:
        pytest.fail(f"TLD_REQUIRE_BROWSER=1 but {reason}")
    pytest.skip(reason)


def need_tool(name: str) -> None:
    import shutil
    if shutil.which(name) is None:
        missing_tool(f"{name} is not installed")


def need_browser() -> None:
    """node and its Playwright package (the board page tests drive Chromium from node)."""
    import subprocess
    need_tool("node")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, text=True).returncode != 0:
        missing_tool("playwright cannot be required")


@pytest.fixture()
def jq_installed():
    need_tool("jq")


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
def _repo_state(path) -> tuple:
    """HEAD, the config file, every untracked or changed path and the guards' state under .git/tld: what a
    read-only test must leave as it was."""
    import subprocess
    head = subprocess.run(["git", "-C", str(path), "rev-parse", "--symbolic-full-name", "HEAD"],
                          capture_output=True, text=True).stdout
    status = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--ignored", "--untracked-files=all"],
                            capture_output=True, text=True).stdout
    # trusted.json is the guards' cache of the remote profile: it is refreshed on a timer, not by a test
    state = sorted((str(p), p.read_bytes()) for p in (Path(path) / ".git" / "tld").rglob("*")
                   if p.is_file() and p.name != "trusted.json")
    return head, (Path(path) / ".git" / "config").read_text(), status, state


def _shared_repo(path, branch):
    from hooks_helpers import make_repo
    return make_repo(path, branch)


@pytest.fixture(scope="session")
def _feature_repo(tmp_path_factory):
    return _shared_repo(tmp_path_factory.mktemp("feature"), "feature/demo")


@pytest.fixture(scope="session")
def _main_repo(tmp_path_factory):
    return _shared_repo(tmp_path_factory.mktemp("onmain"), "main")


@pytest.fixture()
def feature_repo(_feature_repo):
    """A git repo with a profile (main branch `main`), a local tag v1.0, checked out on feature/demo.
    Built once per session and shared, so it is read-only: a test that changes it fails (use `fresh_repo`)."""
    before = _repo_state(_feature_repo)
    yield _feature_repo
    assert _repo_state(_feature_repo) == before, "a test changed the shared feature_repo: use fresh_repo"


@pytest.fixture()
def main_repo(_main_repo):
    """The same repo state, checked out on `main`; read-only like feature_repo."""
    before = _repo_state(_main_repo)
    yield _main_repo
    assert _repo_state(_main_repo) == before, "a test changed the shared main_repo: use a function-scoped repo"


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
