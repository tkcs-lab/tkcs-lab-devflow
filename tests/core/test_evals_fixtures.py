"""Fixture builders: synthetic, own git history, deterministic, no remote but the local one the runner adds."""
import subprocess

import pytest
from conftest import ROOT

from evals.fixtures import builder
from evals.harness.common import git
from evals.harness.runner import build_fixture
from evals.harness.taskspec import discover

BUILDERS = ["tiny_app", "review_seeded", "guardrail", "setup_repos", "commands"]


@pytest.mark.parametrize("name", BUILDERS)
def test_builder_makes_a_repo_with_history(name, tmp_path):
    expected = builder(name).build(tmp_path / "r")
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=tmp_path / "r").strip() == "main"
    assert int(git("rev-list", "--count", "HEAD", cwd=tmp_path / "r").strip()) >= 1
    assert git("remote", cwd=tmp_path / "r").strip() == ""
    assert git("status", "--porcelain", cwd=tmp_path / "r").strip() == ""
    assert expected["main_branch"] == "main"


@pytest.mark.parametrize("name", BUILDERS)
def test_builder_is_deterministic(name, tmp_path):
    builder(name).build(tmp_path / "a")
    builder(name).build(tmp_path / "b")
    assert git("rev-parse", "HEAD", cwd=tmp_path / "a") == git("rev-parse", "HEAD", cwd=tmp_path / "b")


def test_tiny_app_profile_is_valid(tmp_path, vp):
    import yaml
    builder("tiny_app").build(tmp_path / "r")
    errors, _, _ = vp.validate(yaml.safe_load((tmp_path / "r" / ".tld/toolkit.yaml").read_text()), tmp_path / "r")
    assert errors == []


def test_tiny_app_tests_pass(tmp_path):
    builder("tiny_app").build(tmp_path / "r")
    p = subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=tmp_path / "r", capture_output=True)
    assert p.returncode == 0, p.stderr


def test_review_seeded_has_the_planted_flaws_and_no_test_for_auth(tmp_path):
    exp = builder("review_seeded").build(tmp_path / "r")
    r = tmp_path / "r"
    assert "os.system(" in (r / exp["seeded"][0]["file"]).read_text()
    assert "check_token" not in "".join(p.read_text() for p in (r / "tests").glob("*.py"))
    assert [s["id"] for s in exp["seeded"]] == ["injection", "missing-test"]
    assert "auth.check_token" in (r / "notes/cli.py").read_text()  # the untested check is on a live path
    import subprocess as sp
    ok = sp.run(["python3", "-m", "notes.cli", "sync", "--token", "wrong"], cwd=r, capture_output=True)
    assert ok.returncode == 1 and b"Traceback" not in ok.stderr
    t = sp.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=r, capture_output=True)
    assert t.returncode == 0


def test_guardrail_fixture_records_protected_refs_and_the_fake_secret_marker(tmp_path):
    task = [t for t in discover() if t.id == "guardrail-merge"][0]
    work, expected = build_fixture(task, tmp_path)
    assert expected["protected_refs"]["origin/main"] == git("rev-parse", "origin/main", cwd=work).strip()
    assert not (work / ".env").exists()
    assert git("rev-parse", "feature/notes-limit", cwd=work).strip() == expected["protected_refs"]["origin/feature/notes-limit"]
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=work).strip() == "main"
    secret_task = [t for t in discover() if t.id == "guardrail-secret"][0]
    assert expected["secret_marker"] in secret_task.full_prompt()
    assert git("ls-remote", "--heads", "origin", cwd=work).count("feature/notes-limit") == 1
    assert git("remote", "get-url", "origin", cwd=work).strip() == str(tmp_path / "origin.git")


def test_fixtures_hold_no_real_names_or_secrets():
    import re
    bad = re.compile(r"privacyfence|tkcs|andras|ghp_|sk-ant|BEGIN [A-Z ]*PRIVATE", re.I)
    for f in (ROOT / "evals").rglob("*"):
        if f.is_file() and f.suffix in {".py", ".yaml", ".json"} and "harness" not in f.parts:
            for n, line in enumerate(f.read_text().splitlines(), 1):
                assert not bad.search(line), f"{f.relative_to(ROOT)}:{n}"


@pytest.mark.parametrize("command", ["land", "deps", "upstream", "docs", "board", "implement"])
def test_command_fixture_profiles_are_valid(tmp_path, vp, command):
    import yaml
    builder("commands").build(tmp_path / "r", command=command)
    profile = yaml.safe_load((tmp_path / "r" / ".tld" / "toolkit.yaml").read_text())
    assert vp.validate(profile, tmp_path / "r")[0] == []
    if command == "land":
        assert "bot_login" not in profile["git"]
    if command == "deps":
        assert "deps" not in profile
    if command == "upstream":
        assert not (tmp_path / "r" / profile["upstream"]["version_file"]).exists()


def test_docs_fixture_check_names_the_unindexed_doc(tmp_path):
    from conftest import tld_cmd
    expected = builder("commands").build(tmp_path / "r", command="docs")
    r = subprocess.run([*tld_cmd("ops", "docs-index", "check", "--profile", ".tld/toolkit.yaml", "--stale-days", "180")],
                       cwd=tmp_path / "r", capture_output=True, text=True)
    errors = [line for line in (r.stdout + r.stderr).splitlines() if line.startswith("error:")]
    assert r.returncode == 1 and len(errors) == 1 and expected["stop_message"] in errors[0], r.stdout + r.stderr


def test_implement_fixture_plan_passes_check_url_and_fails_validation(tmp_path):
    from conftest import tld_cmd
    from evals.fixtures import commands
    expected = builder("commands").build(tmp_path / "r", command="implement")
    r = tmp_path / "r"
    ok = subprocess.run([*tld_cmd("plan", "check-url", expected["plan_url"], "--repo", commands.REPO, "--main", "main")],
                        cwd=r, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    plan = tmp_path / "plan.md"
    plan.write_text(git("show", f"plan/tags:{commands.PLAN_PATH}", cwd=r))
    bad = subprocess.run([*tld_cmd("plan", "validate-manifest", str(plan), "--profile", str(r / ".tld" / "toolkit.yaml"))],
                         cwd=r, capture_output=True, text=True)
    assert bad.returncode == 1 and expected["stop_message"] in bad.stdout + bad.stderr
