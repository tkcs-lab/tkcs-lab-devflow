"""profile_survey.survey on the /setup fixtures and on small hand-made trees."""
import json
import subprocess
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "plugins" / "devflow" / "scripts"))
import profile_survey as ps  # noqa: E402
from evals.fixtures.setup_repos import build  # noqa: E402

SCRIPT = ROOT / "plugins" / "devflow" / "scripts" / "profile_survey.py"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def ev(path):
    return ps.survey(path)["evidence"]


def test_security_heavy(tmp_path):
    build(tmp_path, "security_heavy")
    out = ps.survey(tmp_path)
    e = out["evidence"]
    assert out["proposal"] is None
    assert [s["name"] for s in e["stacks"]] == ["python"]
    [wf] = e["ci"]["workflows"]
    assert wf["triggers"] == ["push", "pull_request"]
    assert e["verify_evidence"]["ci_runs"] == [
        {"workflow": "ci.yml", "job": "test", "run": "python -m pytest -q"}]
    assert e["ci"]["dispatchable"] == []
    assert e["git"]["main_branch"] == "main"
    assert e["git"]["has_history"] is True
    assert e["signals"]["security"]["score"] >= 3


def test_ios_ui_app(tmp_path):
    build(tmp_path, "ios_ui_app")
    e = ev(tmp_path)
    assert [s["name"] for s in e["stacks"]] == ["swift", "ipados"]
    [d] = e["ci"]["dispatchable"]
    assert d["workflow"] == "macos-tests.yml"
    assert "macOS" in d["use_when"] and "macos-latest" in d["use_when"]
    assert d["notes"] == "No inputs."


def test_docs_website(tmp_path):
    build(tmp_path, "docs_website")
    e = ev(tmp_path)
    assert [s["name"] for s in e["stacks"]] == ["go"]
    assert e["other_stacks"] == []
    assert e["docs"]["website"]["tool"] == "docusaurus"


def test_bare(tmp_path):
    build(tmp_path, "bare")
    e = ev(tmp_path)
    assert e["stacks"] == []
    assert e["ci"]["workflows"] == []


def test_package_json_and_makefile(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps(
        {"scripts": {"test": "jest", "lint": "eslint .", "start": "node x"}}))
    (tmp_path / "Makefile").write_text("test:\n\techo\nrelease:\n\techo\nlint:\n\techo\n")
    e = ev(tmp_path)
    assert e["other_stacks"] == [{"name": "node", "evidence": ["package.json"], "skill": False}]
    assert e["verify_evidence"]["package_scripts"] == {"test": "jest", "lint": "eslint ."}
    assert e["verify_evidence"]["make_targets"] == ["test", "lint"]


def test_not_a_git_repository(tmp_path):
    assert ev(tmp_path)["git"] == {"main_branch": None, "has_history": False, "branch_prefixes": {}}


def write_wf(path, name, text):
    d = path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_dispatch_inputs_on_windows(tmp_path):
    write_wf(tmp_path, "win.yml",
             "on:\n  workflow_dispatch:\n    inputs:\n      a: {}\n      b: {}\n"
             "jobs:\n  t:\n    runs-on: windows-latest\n    steps:\n      - run: echo hi\n")
    [d] = ev(tmp_path)["ci"]["dispatchable"]
    assert d == {"workflow": "win.yml", "use_when": "Build or test on Windows (runs-on: windows-latest)",
                 "notes": "Inputs: a, b"}


def test_on_as_list_and_string(tmp_path):
    write_wf(tmp_path, "a.yml", "on: [push, workflow_dispatch]\njobs:\n  t:\n    runs-on: [self-hosted, macos-14]\n    steps: []\n")
    write_wf(tmp_path, "b.yml", "on: pull_request\njobs: {}\n")
    e = ev(tmp_path)["ci"]
    assert [w["triggers"] for w in e["workflows"]] == [["push", "workflow_dispatch"], ["pull_request"]]
    assert e["workflows"][0]["runs_on"] == ["self-hosted", "macos-14"]
    assert [d["workflow"] for d in e["dispatchable"]] == ["a.yml"]


def repo_on_branch(path, branch="claude/x"):
    git(path, "init", "-q", "-b", branch)
    git(path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i")


def test_main_branch_from_origin_ref(tmp_path):
    repo_on_branch(tmp_path)
    git(tmp_path, "remote", "add", "origin", str(tmp_path / "nowhere"))
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert ev(tmp_path)["git"]["main_branch"] == "main"


def test_main_branch_null_with_remote_only(tmp_path):
    repo_on_branch(tmp_path)
    git(tmp_path, "remote", "add", "origin", str(tmp_path / "nowhere"))
    assert ev(tmp_path)["git"]["main_branch"] is None


def test_branch_prefixes(tmp_path):
    repo_on_branch(tmp_path, "main")
    git(tmp_path, "remote", "add", "origin", str(tmp_path / "nowhere"))
    for b in ("feature/a", "feature/b", "fix/c"):
        git(tmp_path, "branch", b)
    git(tmp_path, "update-ref", "refs/remotes/origin/feature/a", "HEAD")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    assert ev(tmp_path)["git"]["branch_prefixes"] == {"feature": 2, "fix": 1}


def test_cli(tmp_path):
    build(tmp_path, "bare")
    proc = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert set(out) == {"root", "evidence", "proposal"}
    assert out["proposal"] is None
