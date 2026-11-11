import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEVFLOW = ROOT / "plugins" / "devflow"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(ROOT) not in sys.path:  # the evals/ package (the eval harness lives outside the plugin)
    sys.path.insert(0, str(ROOT))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, DEVFLOW / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its own module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def vm():
    return _load("validate_manifest")


@pytest.fixture(scope="session")
def vp():
    return _load("validate_profile")


@pytest.fixture(scope="session")
def ra():
    return _load("repo_admin")


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
