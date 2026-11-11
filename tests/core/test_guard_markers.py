"""The short-lived allow markers: the tld workflow files (S13) and real git-ops runs (S12)."""
import json
import subprocess
import sys
import time

import pytest

from conftest import BIN
from hooks_helpers import bash, event, make_repo, run

LAND, RELEASE = ".github/workflows/tld-land.yml", ".github/workflows/tld-release.yml"
REAL = "gh workflow run tld-git-ops.yml -R o/central -f repo=o/r -f action=delete-branch -f name=x -f dry_run=false"


def tld(repo, *args):
    return subprocess.run([sys.executable, str(BIN), "guard", *args], cwd=repo, capture_output=True, text=True, timeout=60)


def write(repo, path):
    return run("protect-paths", event("Write", repo, file_path=path, content="x\n"))


def mcp(checkout, **inputs):
    return run("no-git-tag", event("mcp__github__actions_run_trigger", checkout, method="run_workflow",
                                   workflow_id="tld-git-ops.yml", ref="main", inputs=inputs)).code


def age(repo, name, seconds):
    marker = repo / ".git" / "tld" / name
    data = json.loads(marker.read_text())
    data["written_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds))
    marker.write_text(json.dumps(data))


# --------------------------------------------------------------------------- S13: workflow install


def test_the_tld_workflow_files_are_protected_without_the_marker(fresh_repo):
    for path in (LAND, RELEASE):
        r = write(fresh_repo, path)
        assert r.code == 2 and "tld guard allow-workflow-install" in r.stderr, r.stderr


def test_the_marker_allows_only_the_files_it_names(fresh_repo):
    r = tld(fresh_repo, "allow-workflow-install", "tld-land.yml")
    assert r.returncode == 0 and "may be written for the next 15 minutes" in r.stdout
    assert write(fresh_repo, LAND).code == 0
    assert write(fresh_repo, str(fresh_repo / LAND)).code == 0
    assert run("protect-paths", bash("cp /tmp/x .github/workflows/tld-land.yml", fresh_repo)).code == 0
    assert write(fresh_repo, RELEASE).code == 2
    assert write(fresh_repo, ".github/workflows/ci.yml").code == 2, "other workflow files stay protected"
    assert write(fresh_repo, ".tld/toolkit.yaml").code == 2


def test_both_files_and_paths_are_accepted(fresh_repo):
    assert tld(fresh_repo, "allow-workflow-install", "tld-release.yml", ".github/workflows/tld-land.yml").returncode == 0
    assert write(fresh_repo, LAND).code == 0 and write(fresh_repo, RELEASE).code == 0


@pytest.mark.parametrize("args", [[], ["ci.yml"], [".github/workflows/x/tld-land.yml"], ["tld-land.yml", "deploy.yml"]])
def test_only_the_tld_workflow_files_can_be_named(fresh_repo, args):
    r = tld(fresh_repo, "allow-workflow-install", *args)
    assert r.returncode == 2 and "takes one or more of: tld-land.yml, tld-release.yml" in r.stderr
    assert not (fresh_repo / ".git" / "tld" / "protect-paths-workflow.json").exists()


def test_the_install_marker_lapses_and_end_allow_ends_it(fresh_repo):
    tld(fresh_repo, "allow-workflow-install", "tld-land.yml")
    age(fresh_repo, "protect-paths-workflow.json", 16 * 60)
    assert write(fresh_repo, LAND).code == 2
    tld(fresh_repo, "allow-workflow-install", "tld-land.yml")
    assert tld(fresh_repo, "end-allow").returncode == 0
    assert write(fresh_repo, LAND).code == 2


def test_the_profile_cannot_unlock_the_tld_workflow_files(tmp_path):
    from hooks_helpers import make_repo_with_origin
    committed = "git:\n  main_branch: main\nhooks:\n  protect_paths: []\n  protect_paths_allow: ['.github/workflows/**']\n"
    repo = make_repo_with_origin(tmp_path / "r", committed=committed)
    assert write(repo, ".github/workflows/ci.yml").code == 0
    assert write(repo, LAND).code == 2


def test_a_marker_in_one_checkout_does_not_unlock_another(tmp_path):
    a, b = make_repo(tmp_path / "a", "feature/x"), make_repo(tmp_path / "b", "feature/x")
    tld(a, "allow-workflow-install", "tld-land.yml")
    assert write(a, LAND).code == 0 and write(b, LAND).code == 2


def test_the_markers_themselves_are_protected(fresh_repo):
    r = run("protect-paths", bash("echo '{}' > .git/tld/protect-paths-workflow.json", fresh_repo))
    assert r.code == 2
    assert write(fresh_repo, ".git/tld/git-ops-confirm.json").code == 2


# --------------------------------------------------------------------------- S12: real git-ops runs


@pytest.mark.parametrize("command", [
    REAL, REAL.replace("dry_run=false", "dry_run=False"), REAL.replace("-f dry_run", "-F dry_run"),
    REAL.replace("-f dry_run=false", "--field=dry_run=false"),
    "gh workflow run tld-git-ops -f dry_run=0",
    "gh api -X POST repos/o/c/actions/workflows/tld-git-ops.yml/dispatches -f ref=main -f inputs[dry_run]=false",
    "gh api -X POST repos/o/c/actions/workflows/tld-git-ops.yml/dispatches --input missing.json",
    "gh workflow run tld-git-ops.yml --json",
])
def test_a_real_git_ops_dispatch_needs_the_marker(fresh_repo, command):
    r = run("no-git-tag", bash(command, fresh_repo))
    assert r.code == 2 and "tld guard allow-git-ops" in r.stderr, (command, r.stderr)
    assert tld(fresh_repo, "allow-git-ops").returncode == 0
    assert run("no-git-tag", bash(command, fresh_repo)).code == 0, command


@pytest.mark.parametrize("command", [
    REAL.replace("dry_run=false", "dry_run=true"), "gh workflow run tld-git-ops.yml -f repo=o/r -f name=x",
    "gh api -X POST repos/o/c/actions/workflows/tld-git-ops.yml/dispatches -f ref=main -f inputs[dry_run]=true",
])
def test_a_git_ops_dry_run_needs_no_marker(fresh_repo, command):
    assert run("no-git-tag", bash(command, fresh_repo)).code == 0, command


def test_an_input_file_is_read_for_dry_run(fresh_repo):
    (fresh_repo / "dry.json").write_text(json.dumps({"ref": "main", "inputs": {"dry_run": "true"}}))
    (fresh_repo / "real.json").write_text(json.dumps({"ref": "main", "inputs": {"dry_run": "false"}}))
    api = "gh api -X POST repos/o/c/actions/workflows/tld-git-ops.yml/dispatches --input "
    assert run("no-git-tag", bash(api + "dry.json", fresh_repo)).code == 0
    assert run("no-git-tag", bash(api + "real.json", fresh_repo)).code == 2


def test_mcp_dispatch(fresh_repo):
    assert mcp(fresh_repo, repo="o/r", action="delete-branch", name="x", dry_run="true") == 0
    assert mcp(fresh_repo, repo="o/r", action="delete-branch", name="x") == 0
    assert mcp(fresh_repo, dry_run="false") == 2
    assert mcp(fresh_repo, dry_run=False) == 2
    assert run("no-git-tag", event("mcp__github__actions_run_trigger", fresh_repo, method="run_workflow",
                                   workflow_id="tld-git-ops.yml", ref="main", inputs='{"dry_run": "false"}')).code == 2
    tld(fresh_repo, "allow-git-ops")
    assert mcp(fresh_repo, dry_run="false") == 0


def test_the_git_ops_marker_lapses_after_ten_minutes_and_end_allow_ends_it(fresh_repo):
    tld(fresh_repo, "allow-git-ops")
    age(fresh_repo, "git-ops-confirm.json", 11 * 60)
    assert run("no-git-tag", bash(REAL, fresh_repo)).code == 2
    tld(fresh_repo, "allow-git-ops")
    assert run("no-git-tag", bash(REAL, fresh_repo)).code == 0
    tld(fresh_repo, "end-allow")
    assert run("no-git-tag", bash(REAL, fresh_repo)).code == 2


def test_a_git_ops_workflow_renamed_in_the_profile_is_guarded_too(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/x")
    profile = repo / ".tld" / "toolkit.yaml"
    profile.write_text(profile.read_text() + "git_ops:\n  repo: o/central\n  workflow: branch-ops.yml\n")
    assert run("no-git-tag", bash("gh workflow run branch-ops.yml -f dry_run=false", repo)).code == 2
    assert run("no-git-tag", bash("gh workflow run branch-ops.yml -f dry_run=true", repo)).code == 0


def test_the_marker_never_opens_the_release_workflow(fresh_repo):
    tld(fresh_repo, "allow-git-ops")
    r = run("no-git-tag", bash("gh workflow run tld-release.yml -f dry_run=false", fresh_repo))
    assert r.code == 2 and "only by the release workflow (tld-release), which the owner runs by hand" in r.stderr


# --------------------------------------------------------------------------- plan-gate: the worker marker

PLAN = "plan-gate-open.json"


def test_allow_plan_writes_the_marker_in_the_git_dir(fresh_repo):
    r = tld(fresh_repo, "allow-plan")
    assert r.returncode == 0 and "edits are allowed in this checkout for the next 8 hours" in r.stdout, r.stderr
    assert (fresh_repo / ".git" / "tld" / PLAN).is_file()


def test_end_allow_does_not_remove_the_plan_marker(fresh_repo):
    tld(fresh_repo, "allow-plan")
    tld(fresh_repo, "allow-git-ops")
    assert tld(fresh_repo, "end-allow").returncode == 0
    assert (fresh_repo / ".git" / "tld" / PLAN).is_file()
    assert not (fresh_repo / ".git" / "tld" / "git-ops-confirm.json").exists()


def test_plan_marker_lapses_after_eight_hours(fresh_repo):
    from tld.guard import markers
    tld(fresh_repo, "allow-plan")
    project = str(fresh_repo)
    assert markers.read(project, "plan-open") is not None
    age(fresh_repo, PLAN, 28801)
    assert markers.read(project, "plan-open") is None


def test_allow_plan_help_writes_no_marker(fresh_repo):
    r = tld(fresh_repo, "allow-plan", "--help")
    assert r.returncode == 0 and r.stdout.strip()
    assert not (fresh_repo / ".git" / "tld" / PLAN).exists()


def test_implement_playbook_tells_workers_to_open_the_plan_marker():
    from conftest import ROOT

    text = (ROOT / "playbooks" / "implement.md").read_text()
    assert text.count("tld guard allow-plan") >= 2
    start = text.index("> You are the final reviewer")
    end = text.index("at least one blocking finding.", start)
    assert "allow-plan" not in text[start:end]
