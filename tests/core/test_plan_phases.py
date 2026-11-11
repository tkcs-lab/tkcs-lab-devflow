"""tld plan check-url, branch-name and phase-status (src/tld/plan/phases.py): the mechanical steps of implement."""
import json
import subprocess

import pytest
import yaml

from conftest import tld_cmd

MANIFEST = {
    "plan_slug": "demo",
    "feature_branch": "feature/demo",
    "max_parallel": 2,
    "phases": [
        {"id": "p1", "title": "one", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["a.py"]},
        {"id": "p2", "title": "two", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["b.py"],
         "human_gate": True},
        {"id": "p3", "title": "three", "depends_on": ["p1"], "brief": "b", "acceptance": ["a"], "touches": ["c.py"]},
        {"id": "p4", "title": "four", "depends_on": ["p2"], "brief": "b", "acceptance": ["a"], "touches": ["d.py"]},
        {"id": "p5", "title": "five", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["e.py"]},
    ],
}


def run(*args, cwd=None):
    return subprocess.run([*tld_cmd("plan", *args)], capture_output=True, text=True, cwd=cwd)


@pytest.fixture()
def plan(tmp_path):
    path = tmp_path / "demo-plan.md"
    path.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(MANIFEST) + "```\n")
    return path


# ---- check-url (S14) ------------------------------------------------------------------------
@pytest.mark.parametrize("url, ref, path", [
    ("https://github.com/o/r/blob/main/docs/plans/x-plan.md", "main", "docs/plans/x-plan.md"),
    ("https://github.com/o/r/blob/plan/x-y/docs/plans/x-y-plan.md", "plan/x-y", "docs/plans/x-y-plan.md"),
    ("https://github.com/O/R/blob/plan/x/p.md", "plan/x", "p.md"),
])
def test_check_url_accepts_main_and_plan_branches_of_this_repo(url, ref, path):
    r = run("check-url", url, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["ref"] == ref and json.loads(r.stdout)["path"] == path


@pytest.mark.parametrize("url, message", [
    ("https://github.com/other/r/blob/main/p.md", "not in this repository"),
    ("https://github.com/o/r/blob/feature/x/p.md", "must be on 'main' or on a plan/<slug> branch"),
    ("https://github.com/o/r/blob/claude/abc/p.md", "must be on 'main'"),
    ("https://github.com/o/r/blob/plan/Bad_Slug/p.md", "kebab-case slug"),
    ("https://github.com/o/r/blob/main/../x.md", "'..'"),
    ("https://gitlab.com/o/r/blob/main/p.md", "not a plan URL"),
    ("https://github.com/o/r/tree/main/p.md", "not a plan URL"),
])
def test_check_url_refuses_everything_else(url, message):
    r = run("check-url", url, "--repo", "o/r")
    assert r.returncode == 1 and r.stderr.startswith("plan: ") and message in r.stderr


def test_check_url_main_branch_and_origin(tmp_path):
    assert run("check-url", "https://github.com/o/r/blob/trunk/p.md", "--repo", "o/r", "--main", "trunk").returncode == 0
    assert run("check-url", "https://github.com/o/r/blob/main/p.md", "--repo", "o/r", "--main", "trunk").returncode == 1
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:o/r.git"], cwd=tmp_path, check=True)
    assert run("check-url", "https://github.com/o/r/blob/main/p.md", cwd=tmp_path).returncode == 0
    assert run("check-url", "https://github.com/x/r/blob/main/p.md", cwd=tmp_path).returncode == 1


# ---- branch-name (C12) ----------------------------------------------------------------------
@pytest.mark.parametrize("args, expected", [
    (["--plan-slug", "deny-with-feedback"], "plan/deny-with-feedback"),
    (["--review-slug", "repo-2026-11-11"], "review/repo-2026-11-11"),
    (["--manifest", "{plan}"], "feature/demo"),
    (["--manifest", "{plan}", "--phase", "p2"], "feature/demo--p2"),
    (["--manifest", "{plan}", "--phase", "p2", "--rev", "1"], "feature/demo--p2-rev1"),
    (["--manifest", "{plan}", "--fix", "3"], "feature/demo--fix-3"),
])
def test_branch_names(plan, args, expected):
    r = run("branch-name", *[a.replace("{plan}", str(plan)) for a in args])
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected + "\n"


@pytest.mark.parametrize("args, message", [
    (["--plan-slug", "Not A Slug"], "kebab-case"),
    (["--manifest", "{plan}", "--phase", "p9"], "no phase 'p9'"),
    (["--manifest", "{plan}", "--rev", "1"], "--rev needs --phase"),
    (["--manifest", "{plan}", "--fix", "1", "--phase", "p1"], "--fix takes no --phase"),
    (["--manifest", "{plan}", "--fix", "0"], "count from 1"),
])
def test_branch_name_errors(plan, args, message):
    r = run("branch-name", *[a.replace("{plan}", str(plan)) for a in args])
    assert r.returncode == 1 and message in r.stderr


def test_branch_name_needs_a_valid_manifest(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text(yaml.safe_dump({"plan_slug": "x", "phases": []}))
    r = run("branch-name", "--manifest", str(bad))
    assert r.returncode == 1 and "run tld plan validate-manifest" in r.stderr


# ---- phase-status ---------------------------------------------------------------------------
def repo_with_trailers(root, *phase_ids):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    for msg in ["init", *[f"Merge demo {p}: t\n\nPlan-Phase: demo/{p}" for p in phase_ids],
                "unrelated\n\nPlan-Phase: other/p5"]:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
                        "--allow-empty", "-m", msg], cwd=root, check=True)
    return root


def status(plan, root, *args):
    r = run("phase-status", str(plan), "--repo", str(root), *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_phase_status_fresh_run(plan, tmp_path):
    (tmp_path / "r").mkdir()
    repo = repo_with_trailers(tmp_path / "r")
    s = status(plan, repo)
    assert s["done"] == [] and s["ready"] == ["p1", "p2", "p5"] and s["waiting"] == ["p3", "p4"]
    assert s["start"] == ["p1", "p2"] and s["all_done"] is False


def test_phase_status_with_done_running_and_a_gate(plan, tmp_path):
    (tmp_path / "r").mkdir()
    repo = repo_with_trailers(tmp_path / "r", "p1", "p2")
    s = status(plan, repo, "--running", "p5")
    assert s["done"] == ["p1", "p2"] and s["gated"] == ["p2"]
    assert s["ready"] == ["p3"] and s["waiting"] == ["p4"] and s["start"] == ["p3"]
    s = status(plan, repo, "--running", "p5", "--approved", "p2")
    assert s["gated"] == [] and s["ready"] == ["p3", "p4"] and s["start"] == ["p3"]


def test_phase_status_all_done_and_errors(plan, tmp_path):
    (tmp_path / "r").mkdir()
    repo = repo_with_trailers(tmp_path / "r", "p1", "p2", "p3", "p4", "p5")
    assert status(plan, repo)["all_done"] is True
    r = run("phase-status", str(plan), "--repo", str(repo), "--running", "nope")
    assert r.returncode == 1 and "no phase 'nope'" in r.stderr
    r = run("phase-status", str(plan), "--repo", str(repo), "--ref", "no-such-ref")
    assert r.returncode == 1 and "git log no-such-ref failed" in r.stderr
