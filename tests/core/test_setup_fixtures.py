"""The four /setup survey fixture repositories (Design D12)."""
import subprocess
from pathlib import Path

import pytest
import yaml

from evals.fixtures import setup_repos

KEYS = {"main_branch", "repo", "stacks", "roles", "website", "dispatchable", "adr_dir", "adr_index", "changelog"}
BASE_KEYS = KEYS | {"extends", "extends_tag", "profile_roles"}
MD_COUNTS = {"docs_website": 11, "security_heavy": 3, "ios_ui_app": 1, "bare": 1, "base_with_tests": 1, "base_no_tests": 1}


@pytest.mark.parametrize("repo", setup_repos.REPOS)
def test_build_has_files_and_keys(repo, tmp_path):
    expected = setup_repos.build(tmp_path / "r", repo=repo)
    assert set(expected) == (BASE_KEYS if repo in setup_repos.BASE_REPOS else KEYS) and expected["repo"] == repo and expected["main_branch"] == "main"
    for rel in setup_repos.FILES[repo]:
        assert (tmp_path / "r" / rel).is_file(), rel
    assert len(list((tmp_path / "r").rglob("*.md"))) == MD_COUNTS[repo]
    assert not (tmp_path / "r/.tld/toolkit.yaml").exists()


@pytest.mark.parametrize("repo", setup_repos.REPOS)
def test_with_profile_is_valid(repo, tmp_path, vp):
    setup_repos.build(tmp_path / "r", repo=repo, with_profile=True)
    data = yaml.safe_load((tmp_path / "r/.tld/toolkit.yaml").read_text())
    errors, _, _ = vp.validate(data, tmp_path / "r")
    assert errors == []


def test_only_docs_website_has_adr_and_changelog(tmp_path):
    for repo in setup_repos.REPOS:
        exp = setup_repos.build(tmp_path / repo, repo=repo)
        if repo == "docs_website":
            assert exp["adr_dir"] == "docs/adr" and exp["adr_index"] == "docs/adr/README.md"
            assert exp["changelog"] == {"file": "CHANGELOG.md", "section": "## [Unreleased]"}
        else:
            assert exp["adr_dir"] is exp["adr_index"] is exp["changelog"] is None


def test_docs_markdown_have_headings_and_workflows_are_yaml(tmp_path):
    setup_repos.build(tmp_path / "d", repo="docs_website")
    for f in (tmp_path / "d").rglob("*.md"):
        assert any(line.startswith("#") for line in f.read_text().splitlines()), f
    for repo in ("security_heavy", "ios_ui_app"):
        setup_repos.build(tmp_path / repo, repo=repo)
        for f in (tmp_path / repo / ".github/workflows").glob("*.yml"):
            assert isinstance(yaml.safe_load(f.read_text()), dict)


def test_ios_has_exactly_two_swiftui_files_and_no_uikit(tmp_path):
    setup_repos.build(tmp_path / "r", repo="ios_ui_app")
    files = [f for f in (tmp_path / "r").rglob("*") if f.is_file() and ".git" not in f.relative_to(tmp_path / "r").parts]
    assert len([f for f in files if "import SwiftUI" in f.read_text()]) == 2
    assert not [f for f in files if "UIKit" in f.read_text()]


def _seeded(tmp_path, repo):
    """A fixture repository cloned the way the runner does, then post_clone."""
    src = tmp_path / "src"
    expected = setup_repos.build(src, repo=repo)
    subprocess.run(["git", "clone", "-q", str(src), str(tmp_path / "work")], check=True)
    setup_repos.post_clone(tmp_path / "work", expected)
    return tmp_path / "work", expected


@pytest.mark.parametrize("repo", setup_repos.BASE_REPOS)
def test_base_repository_has_its_base_seeded_offline(repo, tmp_path, vp):
    from tld.profile import base
    work, expected = _seeded(tmp_path, repo)
    ref = base.parse_extends(expected["extends"])
    assert base.cached(work / ".git", ref) == setup_repos.BASE_TEXT
    profile = yaml.safe_load(f"tld:\n  extends: {expected['extends']}\n  version: \">=1.6,<2\"\n"
                             "git:\n  main_branch: main\ndocs:\n  must_read: [README.md]\n"
                             "verify:\n  fast: [\"true\"]\n  dod: [\"true\"]\nstacks: []\n")
    errors, _, resolved = vp.validate(profile, work, fetch=False)
    assert errors == [] and resolved["roles"]["posture"]["security"] == "critical"


def test_the_makefile_repository_has_a_test_target_and_the_other_has_no_test_command(tmp_path):
    setup_repos.build(tmp_path / "a", repo="base_with_tests")
    setup_repos.build(tmp_path / "b", repo="base_no_tests")
    assert "\ntest:" in "\n" + (tmp_path / "a/Makefile").read_text()
    assert not (tmp_path / "b/Makefile").exists() and not (tmp_path / "b/.github").exists()


def test_security_heavy_with_a_base_expects_only_its_own_roles(tmp_path):
    exp = setup_repos.build(tmp_path / "r", repo="security_heavy", with_base=True)
    assert exp["roles"] == {"disable": ["website-maintainer"]} and exp["extends"] == setup_repos.BASE_EXTENDS


SETUP = (Path(__file__).resolve().parents[2] / "playbooks" / "setup.md").read_text()


def test_setup_playbook_keeps_the_deps_commands_owner_confirmed():
    """deps.audit and deps.lock_freshness are commands: never written unconfirmed, whatever the flags."""
    flat = " ".join(SETUP.split())
    assert "`deps.audit` and `deps.lock_freshness` are **commands**" in flat
    assert "never written unconfirmed, with or without `--accept-proposals`" in flat
    assert "a `deps.audit` or `deps.lock_freshness` command is **not written**" in flat
    assert '`answers.json` with `"blocking": false` for every proposed `blocking: true` entry' in flat
    assert "Never write `blocking: true`, `deps.audit` or `deps.lock_freshness` without the human's confirmation" in flat


def test_setup_playbook_keeps_the_bot_and_the_base_roles_out_of_the_profile():
    flat = " ".join(SETUP.split())
    assert "The bot login is never a code owner" in flat
    assert "never write `roles.disable` for a role the base requires" in flat
    assert "the posture is not asked" in flat.lower()


def test_setup_playbook_neutralises_the_proposal_before_writing():
    flat = " ".join(SETUP.split())
    assert "never straight from the survey's proposal" in flat
    assert "never run `set-block roles`" in flat
    assert "only for a `deps_*` confirm answered yes" in flat


def test_setup_playbook_never_pastes_a_repository_supplied_base_source():
    flat = " ".join(SETUP.split())
    assert 'tld profile base latest -- "$SRC"' in flat
    assert "never from the working tree" in flat and "origin/<main> --resolved" in flat
    assert "the existing pin stays unless the owner passes" in flat


def test_setup_playbook_leaves_an_unanswered_value_out_and_lists_it():
    flat = " ".join(SETUP.split())
    assert "never with a guessed command" in flat and "posted but not answered" in flat
    assert "in *update* mode, the base the profile already extends, read from the default branch" in flat
