"""What this repository's CI promises (CONTRIBUTING.md): the matrix, the coverage gate, the browser tests failing
instead of skipping, the checks after pytest, the stub evals, and pinned actions with read-only permissions."""
import re

import pytest
import yaml
from conftest import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def steps(doc, job):
    return [s.get("run", "") for s in doc["jobs"][job]["steps"]]


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_actions_are_pinned_and_permissions_read_only(name):
    doc = load(name)
    assert doc["permissions"] == {"contents": "read"}
    for job in doc["jobs"].values():
        assert "permissions" not in job
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_the_test_workflow_runs_every_check():
    doc = load("test.yml")
    job = doc["jobs"]["test"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.13"]
    assert job["env"]["TLD_REQUIRE_BROWSER"] == "1"
    run = "\n".join(steps(doc, "test"))
    assert "python -m pytest tests -q --cov" in run and "-m 'not slow'" not in run
    assert "claude plugin validate ." in run and re.search(r'CLAUDE_CODE_VERSION: "\d+\.\d+\.\d+"', (WORKFLOWS / "test.yml").read_text())
    assert re.search(r'PLAYWRIGHT_VERSION: "\d+\.\d+\.\d+"', (WORKFLOWS / "test.yml").read_text())
    assert "playwright\" install --with-deps chromium" in run or "playwright install --with-deps chromium" in run
    for check in ("launcher/tld profile validate", "launcher/tld plan validate-manifest", "launcher/tld board validate-record",
                  "launcher/tld ops repo-admin validate-policy", "launcher/tld ops docs-index check",
                  "evals/run.py validate", "evals/run.py check-baseline", "--agent stub", "--require-pass"):
        assert check in run, check


def test_the_coverage_gate_is_configured():
    import tomllib
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["coverage"]
    assert cfg["run"]["branch"] is True and cfg["run"]["source_pkgs"] == ["tld"] and "subprocess" in cfg["run"]["patch"]
    assert 80 <= cfg["report"]["fail_under"] < 100
    req = (ROOT / "tests" / "requirements.txt").read_text()
    assert re.search(r"^pytest-cov==", req, re.M) and re.search(r"^coverage==", req, re.M)


def test_the_mutation_workflow_is_weekly_and_on_demand():
    doc = load("mutation.yml")
    on = doc.get("on", doc.get(True))
    assert "workflow_dispatch" in on and on["schedule"]
    assert any("tests/mutation/run_mutants.py" in r for r in steps(doc, "mutation"))
