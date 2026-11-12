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


ALLOWED_JOB_PERMISSIONS = {("contents", "read"), ("packages", "write"), ("id-token", "write"), ("attestations", "write")}


def permission_problems(doc) -> list[str]:
    """Why a workflow breaks the permission rule: top-level `{contents: read}` everywhere; a job may add its own
    `permissions` only under `environment: tld-release`, and only from ALLOWED_JOB_PERMISSIONS."""
    problems = []
    if not isinstance(doc, dict):
        return ["the workflow is not a mapping"]
    if doc.get("permissions") != {"contents": "read"}:
        problems.append(f"top-level permissions are {doc.get('permissions')!r}, not {{contents: read}}")
    jobs = doc.get("jobs")
    for name, job in (jobs.items() if isinstance(jobs, dict) else []):
        if not isinstance(job, dict) or "permissions" not in job:
            continue
        perms = job["permissions"]
        if job.get("environment") != "tld-release":
            problems.append(f"job {name} has permissions but not environment: tld-release")
        if not isinstance(perms, dict):
            problems.append(f"job {name} permissions are {perms!r}, not a mapping")
            continue
        for key, value in perms.items():
            if (key, value) not in ALLOWED_JOB_PERMISSIONS:
                problems.append(f"job {name} permission {key}: {value} is not allowed")
    return problems


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_actions_are_pinned_and_permissions_read_only(name):
    doc = load(name)
    assert permission_problems(doc) == []
    for job in doc["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def job_doc(permissions, environment="tld-release", top=None):
    job = {"runs-on": "ubuntu-latest", "permissions": permissions, "steps": []}
    if environment is not None:
        job["environment"] = environment
    return {"permissions": {"contents": "read"} if top is None else top, "jobs": {"release": job}}


RELEASE_PERMISSIONS = {"contents": "read", "packages": "write"}


@pytest.mark.parametrize("doc", [
    job_doc(RELEASE_PERMISSIONS, environment=None),
    job_doc(RELEASE_PERMISSIONS, environment="other"),
    job_doc({"contents": "write"}),
    job_doc({"packages": "write", "issues": "write"}),
    job_doc(RELEASE_PERMISSIONS, top="write-all"),
    job_doc("write-all"),
    job_doc(RELEASE_PERMISSIONS, top={"contents": "read", "packages": "write"}),
    {"jobs": {"release": {"runs-on": "ubuntu-latest", "steps": []}}},
], ids=["no-environment", "other-environment", "contents-write", "extra-write", "top-write-all",
        "job-write-all", "top-packages-write", "no-top-level"])
def test_permission_rule_rejects(doc):
    assert permission_problems(doc)


def test_permission_rule_accepts_the_release_job():
    assert permission_problems(job_doc(RELEASE_PERMISSIONS)) == []


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
    for check in ("cli/tld profile validate", "cli/tld plan validate-manifest", "cli/tld board validate-record",
                  "cli/tld ops repo-admin validate-policy", "cli/tld ops docs-index check",
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
