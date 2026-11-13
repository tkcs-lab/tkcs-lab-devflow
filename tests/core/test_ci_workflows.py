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


BUILD_PERMISSIONS = {"contents": "read", "checks": "read", "packages": "write"}
PUBLISH_PERMISSIONS = {"contents": "read", "packages": "write"}
RELEASE_WORKFLOW = "release.yml"


def permission_problems(doc, workflow: str) -> list[str]:
    """Why a workflow breaks the permission rule: top-level `{contents: read}` everywhere; a job may add its own
    `permissions` only in one of two cases. (1) The job named `build` of release.yml, which has no `environment` (it
    runs without an approval and never sees the owner token) and exactly BUILD_PERMISSIONS. (2) Any job with
    `environment: tld-release` and exactly PUBLISH_PERMISSIONS (the release workflow's publish job). Everything else is
    rejected: other jobs, other workflows, other permission sets, any other environment. `workflow` is the file name."""
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
        if not isinstance(perms, dict):
            problems.append(f"job {name} permissions are {perms!r}, not a mapping")
            continue
        environment = job.get("environment")
        if environment is None and workflow == RELEASE_WORKFLOW and name == "build":
            if perms != BUILD_PERMISSIONS:
                problems.append(f"job build permissions {perms!r} are not {BUILD_PERMISSIONS}")
            continue
        if environment != "tld-release":
            problems.append(f"job {name} has permissions but not environment: tld-release "
                            f"(only the build job of {RELEASE_WORKFLOW} may have none)")
        elif perms != PUBLISH_PERMISSIONS:
            problems.append(f"job {name} permissions {perms!r} are not {PUBLISH_PERMISSIONS}")
    return problems


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_actions_are_pinned_and_permissions_read_only(name):
    doc = load(name)
    assert permission_problems(doc, name) == []
    for job in doc["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def job_doc(permissions, environment="tld-release", top=None, job_name="release"):
    job = {"runs-on": "ubuntu-latest", "permissions": permissions, "steps": []}
    if environment is not None:
        job["environment"] = environment
    return {"permissions": {"contents": "read"} if top is None else top, "jobs": {job_name: job}}


# (doc, workflow) pairs the rule rejects
BAD_CASES = [
    (job_doc(BUILD_PERMISSIONS, environment=None), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment="other"), "release.yml"),
    (job_doc({"contents": "write"}), "release.yml"),
    (job_doc({"packages": "write", "issues": "write"}), "release.yml"),
    (job_doc(PUBLISH_PERMISSIONS, top="write-all"), "release.yml"),
    (job_doc("write-all"), "release.yml"),
    (job_doc(PUBLISH_PERMISSIONS, top={"contents": "read", "packages": "write"}), "release.yml"),
    ({"jobs": {"release": {"runs-on": "ubuntu-latest", "steps": []}}}, "release.yml"),
    (job_doc(PUBLISH_PERMISSIONS, environment=None), "release.yml"),
    (job_doc({"packages": "write"}), "release.yml"),
    (job_doc({"contents": "read", "packages": "write", "id-token": "write"}), "release.yml"),
    # the build job of release.yml
    (job_doc(BUILD_PERMISSIONS, environment=None, job_name="build"), "test.yml"),
    (job_doc(BUILD_PERMISSIONS, environment=None, job_name="build"), "mutation.yml"),
    (job_doc({"packages": "write"}, environment=None, job_name="build"), "release.yml"),
    (job_doc({"contents": "read", "packages": "write"}, environment=None, job_name="build"), "release.yml"),
    (job_doc({**BUILD_PERMISSIONS, "id-token": "write"}, environment=None, job_name="build"), "release.yml"),
    (job_doc({**BUILD_PERMISSIONS, "checks": "write"}, environment=None, job_name="build"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment="other", job_name="build"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment="tld-release", job_name="build"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment=None, job_name="publish"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment="", job_name="build"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment=False, job_name="build"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment=None, job_name="Build"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment=None, job_name="other"), "release.yml"),
    (job_doc(BUILD_PERMISSIONS, environment=None, top="write-all", job_name="build"), "release.yml"),
]
BAD_IDS = ["no-environment", "other-environment", "contents-write", "extra-write", "top-write-all", "job-write-all",
           "top-packages-write", "no-top-level", "publish-shape-without-environment", "packages-without-contents",
           "third-permission", "build-in-test-yml", "build-in-other-workflow", "build-packages-only",
           "build-without-checks", "build-extra-permission", "build-checks-write", "build-other-environment",
           "build-with-approval-and-build-permissions", "publish-job-with-build-permissions-no-environment",
           "build-empty-environment", "build-false-environment",
           "build-name-case", "other-job-with-build-permissions-no-environment", "build-top-write-all"]


@pytest.mark.parametrize("doc, workflow", BAD_CASES, ids=BAD_IDS)
def test_permission_rule_rejects(doc, workflow):
    assert permission_problems(doc, workflow)


def test_permission_rule_accepts_the_two_release_jobs():
    assert permission_problems(job_doc(BUILD_PERMISSIONS, environment=None, job_name="build"), "release.yml") == []
    assert permission_problems(job_doc(PUBLISH_PERMISSIONS, job_name="publish"), "release.yml") == []


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
