"""Fixture builders: synthetic, own git history, deterministic, no remote but the local one the runner adds."""
import subprocess

import pytest
from conftest import ROOT

from evals.fixtures import builder
from evals.harness.common import git
from evals.harness.runner import build_fixture
from evals.harness.taskspec import discover

BUILDERS = ["tiny_app", "review_seeded", "guardrail"]


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
    errors, _, _ = vp.validate(yaml.safe_load((tmp_path / "r" / ".claude/toolkit.yaml").read_text()), tmp_path / "r")
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


def test_guardrail_fixture_records_protected_refs_and_the_fake_secret_marker(tmp_path):
    task = [t for t in discover() if t.id == "guardrail-merge"][0]
    work, expected = build_fixture(task, tmp_path)
    assert expected["protected_refs"]["origin/main"] == git("rev-parse", "origin/main", cwd=work).strip()
    assert not (work / ".env").exists()
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
