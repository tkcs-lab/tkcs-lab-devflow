"""The four /setup survey fixture repositories (Design D12)."""
import pytest
import yaml

from evals.fixtures import setup_repos

KEYS = {"main_branch", "repo", "stacks", "roles", "website", "dispatchable", "adr_dir", "adr_index", "changelog"}
MD_COUNTS = {"docs_website": 11, "security_heavy": 3, "ios_ui_app": 1, "bare": 1}


@pytest.mark.parametrize("repo", setup_repos.REPOS)
def test_build_has_files_and_keys(repo, tmp_path):
    expected = setup_repos.build(tmp_path / "r", repo=repo)
    assert set(expected) == KEYS and expected["repo"] == repo and expected["main_branch"] == "main"
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
