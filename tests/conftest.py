import importlib.util
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
