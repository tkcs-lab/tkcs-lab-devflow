"""`tld ops release-prepare`: bump the version files and open the changelog's version heading."""
import json
import os
import re
from pathlib import Path

import pytest
import yaml
from conftest import ROOT
from hooks_helpers import git

from tld.ops import release_prepare as rp

PROFILE = {
    "git": {"main_branch": "main", "branch_pattern": "<type>/<kebab-case>"},
    "verify": {"fast": ["make lint"], "dod": ["make test"]},
    "stacks": [],
    "docs": {"must_read": [], "changelog": {"file": "CHANGELOG.md", "section": "## [Unreleased]"}},
    "release": {"workflow": "release.yml", "version_files": [
        {"path": "pyproject.toml", "pattern": r'^version = "(\d+\.\d+\.\d+)"$'},
        {"path": "plugin.json", "pattern": r'"version": "(\d+\.\d+\.\d+)"'},
        {"path": "pkg/__init__.py", "pattern": r'^__version__ = "(\d+\.\d+\.\d+)"'}]},
}
FILES = {
    "pyproject.toml": '[project]\nname = "x"\nversion = "1.1.0"\n',
    "plugin.json": '{\n  "name": "x",\n  "version": "1.1.0"\n}\n',
    "pkg/__init__.py": '__version__ = "1.1.0"  # kept equal\n',
    "CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n\n## [1.1.0] - 2026-01-01\n\n### Added\n\n- Old.\n",
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    for rel, text in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "release.yml").write_text("name: r\n")
    (tmp_path / ".tld").mkdir()
    (tmp_path / ".tld" / "toolkit.yaml").write_text(yaml.safe_dump(PROFILE))
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def snapshot(repo):
    return {rel: (repo / rel).read_bytes() for rel in FILES}


def run(capsys, *argv):
    code = rp.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_without_a_version_it_prints_the_current_version_and_the_candidates(repo, capsys):
    code, out, _ = run(capsys)
    data = json.loads(out)
    assert code == 0
    assert data["current"] == "1.1.0"
    assert data["candidates"] == {"patch": "1.1.1", "minor": "1.2.0", "major": "2.0.0"}
    assert data["preview"] == "### Added\n\n- A thing."
    assert data["suggested_bump"] == "minor"
    assert "next" not in data


@pytest.mark.parametrize("heading,bump", [("Added", "minor"), ("Removed", "major"), ("Breaking changes", "major"),
                                          ("Changed", "patch"), ("Fixed", "patch")])
def test_the_suggested_bump_follows_the_headings(repo, capsys, heading, bump):
    (repo / "CHANGELOG.md").write_text(f"## [Unreleased]\n\n### {heading}\n\n- x\n\n## [1.1.0] - d\n")
    assert json.loads(run(capsys)[1])["suggested_bump"] == bump


def test_a_dry_run_writes_nothing(repo, capsys):
    before = snapshot(repo)
    code, out, _ = run(capsys, "--version", "1.2.0", "--date", "2026-02-03")
    data = json.loads(out)
    assert code == 0 and snapshot(repo) == before
    assert data["next"] == "1.2.0" and data["written"] is False
    assert data["heading"] == "## [1.2.0] - 2026-02-03"
    assert data["files"] == ["pyproject.toml", "plugin.json", "pkg/__init__.py", "CHANGELOG.md"]


def test_write_changes_only_the_version_spans_and_opens_the_heading(repo, capsys):
    code, out, _ = run(capsys, "--bump", "minor", "--date", "2026-02-03", "--write")
    assert code == 0 and json.loads(out)["written"] is True
    for rel, text in FILES.items():
        now = (repo / rel).read_text()
        if rel == "CHANGELOG.md":
            assert now == text.replace("## [Unreleased]\n", "## [Unreleased]\n\n## [1.2.0] - 2026-02-03\n", 1)
        else:
            assert now == text.replace("1.1.0", "1.2.0")


def test_the_default_date_is_today_in_utc(repo, capsys):
    run(capsys, "--version", "1.1.1", "--write")
    assert re.search(r"^## \[1\.1\.1\] - \d{4}-\d{2}-\d{2}$", (repo / "CHANGELOG.md").read_text(), re.M)


def test_crlf_changelog_keeps_its_line_endings(repo, capsys):
    (repo / "CHANGELOG.md").write_bytes(FILES["CHANGELOG.md"].replace("\n", "\r\n").encode())
    assert run(capsys, "--version", "1.2.0", "--write")[0] == 0
    now = (repo / "CHANGELOG.md").read_bytes()
    assert b"## [Unreleased]\r\n\r\n## [1.2.0] - " in now and b"\n" not in now.replace(b"\r\n", b"")


def edit(repo, rel, old, new):
    p = repo / rel
    p.write_text(p.read_text().replace(old, new))


REFUSALS = [
    (("--version", "1.2"), None, "1.2 is not X.Y.Z"),
    (("--version", "patch"), None, "patch is not X.Y.Z"),
    (("--version", "minor"), None, "minor is not X.Y.Z"),
    (("--version", "major"), None, "major is not X.Y.Z"),
    (("--version", '1.2.0"x'), None, '1.2.0"x is not X.Y.Z'),
    (("--version", "1.1.0"), None, "1.1.0 is not higher than 1.1.0"),
    (("--version", "1.0.9"), None, "1.0.9 is not higher than 1.1.0"),
    (("--version", "1.2.0"), ("plugin.json", '"version": "1.1.0"', '"version": "1.0.0"'),
     "version files disagree: pyproject.toml has 1.1.0, plugin.json has 1.0.0"),
    (("--version", "1.2.0"), ("plugin.json", '"version": "1.1.0"', '"vers": "1.1.0"'),
     "no match for the pattern in plugin.json"),
    (("--version", "1.2.0"), ("pyproject.toml", '[project]', 'version = "1.1.0"\n[project]'),
     "2 matches for the pattern in pyproject.toml"),
    (("--version", "1.2.0"), ("CHANGELOG.md", "## [Unreleased]", "## [Next]"),
     "CHANGELOG.md has no section '## [Unreleased]'"),
    (("--version", "1.2.0"), ("CHANGELOG.md", "### Added\n\n- A thing.\n", "### Added\n"),
     "the unreleased section of CHANGELOG.md is empty"),
    (("--version", "1.2.0"), ("CHANGELOG.md", "## [1.1.0] - 2026-01-01", "## [1.2.0] - 2026-01-01"),
     "CHANGELOG.md already has a heading for 1.2.0"),
]


@pytest.mark.parametrize("argv,change,message", REFUSALS)
@pytest.mark.parametrize("write", [False, True])
def test_every_refusal_names_its_problem_and_touches_nothing(repo, capsys, argv, change, message, write):
    if change:
        edit(repo, *change)
    before = snapshot(repo)
    code, out, err = run(capsys, *argv, *(["--write"] if write else []))
    assert code == 1 and out == ""
    assert f"release-prepare: {message}" in err
    assert snapshot(repo) == before
    assert not list(repo.rglob("*.tmp"))


def test_a_version_file_that_is_missing_is_an_error(repo, capsys):
    (repo / "plugin.json").unlink()
    code, _, err = run(capsys, "--version", "1.2.0")
    assert code == 1 and "cannot read" in err and "plugin.json" in err


def test_a_version_file_outside_the_repository_is_refused(repo, capsys):
    prof = yaml.safe_load((repo / ".tld/toolkit.yaml").read_text())
    prof["release"]["version_files"][0]["path"] = "../x.toml"
    (repo / ".tld/toolkit.yaml").write_text(yaml.safe_dump(prof))
    code, _, err = run(capsys, "--version", "1.2.0")
    assert code == 1 and "../x.toml is outside the repository" in err


@pytest.mark.parametrize("argv", [["--version", "1.2.0", "--bump", "minor"], ["--base", "origin/main"],
                                  ["--check"], ["--check", "--version", "1.2.0", "--write"],
                                  ["--check", "--version", "1.2.0", "--bump", "minor"], ["--write"],
                                  ["--date", "2026-13-40"], ["--date", "tomorrow"], ["--date", "2026-1-1"]])
def test_usage_errors_exit_2(repo, capsys, argv):
    before = snapshot(repo)
    code, out, err = run(capsys, *argv)
    assert code == 2 and out == "" and "release-prepare:" in err
    assert snapshot(repo) == before


def test_argparse_errors_and_help_return_their_exit_code(repo, capsys):
    assert run(capsys, "--bump", "huge")[0] == 2
    assert run(capsys, "--help")[0] == 0


def test_the_files_must_agree_after_writing(repo, capsys, monkeypatch):
    real = os.replace

    def skip_plugin(src, dst):
        if Path(dst).name != "plugin.json":
            real(src, dst)

    monkeypatch.setattr(rp.os, "replace", skip_plugin)
    code, _, err = run(capsys, "--version", "1.2.0", "--write")
    assert code == 1 and "release-prepare: the files do not agree after writing" in err
    assert not list(repo.rglob("*.tmp"))


def test_a_missing_or_incomplete_profile_is_reported(repo, capsys):
    assert "no profile" in run(capsys, "--profile", "nope.yaml")[2]
    (repo / "bad.yaml").write_text("a: [\n")
    assert "not valid YAML" in run(capsys, "--profile", "bad.yaml")[2]
    (repo / "bad.yaml").write_text("git: {main_branch: main}\n")
    code, _, err = run(capsys, "--profile", "bad.yaml")
    assert code == 1 and "toolkit.yaml: missing required key" in err
    prof = yaml.safe_load((repo / ".tld/toolkit.yaml").read_text())
    del prof["release"]
    (repo / "bad.yaml").write_text(yaml.safe_dump(prof))
    assert "no 'release' section" in run(capsys, "--profile", "bad.yaml")[2]
    prof = yaml.safe_load((repo / ".tld/toolkit.yaml").read_text())
    prof["docs"]["changelog"] = {"file": "CHANGELOG.md", "policy": "release-only"}
    (repo / "bad.yaml").write_text(yaml.safe_dump(prof))
    assert "no 'docs.changelog' with a 'section'" in run(capsys, "--profile", "bad.yaml")[2]


def test_check_fails_before_write_and_passes_after(repo, capsys):
    code, _, err = run(capsys, "--check", "--version", "1.2.0")
    assert code == 1 and "pyproject.toml has 1.1.0, not 1.2.0" in err
    assert "CHANGELOG.md has no non-empty entry for 1.2.0" in err
    run(capsys, "--version", "1.2.0", "--write")
    code, out, _ = run(capsys, "--check", "--version", "1.2.0")
    assert code == 0 and out == "release-prepare: ok 1.2.0\n"


def test_check_refuses_a_bad_version_shape(repo, capsys):
    code, _, err = run(capsys, "--check", "--version", "v1.2")
    assert code == 1 and "v1.2 is not X.Y.Z" in err


@pytest.mark.parametrize("word", ["patch", "minor", "major"])
def test_check_refuses_a_bump_word_as_the_version(repo, capsys, word):
    code, _, err = run(capsys, "--check", "--version", word)
    assert code == 1 and f"release-prepare: {word} is not X.Y.Z" in err


def test_check_needs_the_section_heading_and_an_entry(repo, capsys):
    run(capsys, "--version", "1.2.0", "--write")
    edit(repo, "CHANGELOG.md", "## [Unreleased]\n", "")
    assert "has no section '## [Unreleased]'" in run(capsys, "--check", "--version", "1.2.0")[2]
    edit(repo, "CHANGELOG.md", "### Added\n\n- A thing.\n", "")
    assert "has no non-empty entry for 1.2.0" in run(capsys, "--check", "--version", "1.2.0")[2]


def test_check_reports_a_version_file_that_cannot_be_read(repo, capsys):
    run(capsys, "--version", "1.2.0", "--write")
    (repo / "plugin.json").unlink()
    code, _, err = run(capsys, "--check", "--version", "1.2.0")
    assert code == 1 and "cannot read" in err
    (repo / "CHANGELOG.md").unlink()
    assert "cannot read" in run(capsys, "--check", "--version", "1.2.0")[2]


def prepared(repo, capsys):
    run(capsys, "--version", "1.2.0", "--write")


def test_check_base_passes_for_a_clean_release_change(repo, capsys):
    prepared(repo, capsys)
    assert run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Release 1.2.0")
    assert run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")[0] == 0


@pytest.mark.parametrize("commit", [False, True])
def test_check_base_fails_when_another_file_changed(repo, capsys, commit):
    prepared(repo, capsys)
    (repo / "README.md").write_text("new\n")
    if commit:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "x")
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")
    assert code == 1 and "README.md changed since origin/main" in err


@pytest.mark.parametrize("kind", ["added", "removed"])
@pytest.mark.parametrize("commit", [False, True])
def test_check_base_fails_when_a_version_file_has_an_extra_changed_line(repo, capsys, kind, commit):
    prepared(repo, capsys)
    p = repo / "pyproject.toml"
    if kind == "added":
        p.write_text(p.read_text() + "evil = 1\n")
    else:
        p.write_text(p.read_text().replace('name = "x"\n', ""))
    if commit:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "x")
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")
    assert code == 1 and "pyproject.toml: the changed line" in err


def test_check_base_fails_when_a_version_file_is_untracked(repo, capsys):
    git(repo, "rm", "-q", "--cached", "plugin.json")
    git(repo, "commit", "-q", "-m", "untrack")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    prepared(repo, capsys)
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")
    assert code == 1 and "plugin.json is not tracked by git" in err


def test_check_base_fails_when_git_fails(repo, capsys):
    prepared(repo, capsys)
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/nope")
    assert code == 1 and "git merge-base origin/nope HEAD failed" in err


def test_check_base_fails_when_git_cannot_start(repo, capsys, monkeypatch):
    prepared(repo, capsys)
    monkeypatch.setenv("PATH", "")
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")
    assert code == 1 and "failed" in err


def test_a_renamed_file_counts_as_changed(repo, capsys):
    prepared(repo, capsys)
    (repo / "notes.md").write_text("n\n")
    git(repo, "add", "notes.md")
    git(repo, "commit", "-q", "-m", "notes")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "mv", "notes.md", "MOVED.md")
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")
    assert code == 1 and "MOVED.md changed since" in err


def test_the_patterns_of_the_release_profile_match_this_repository_exactly_once():
    patterns = {"pyproject.toml": r'^version = "(\d+\.\d+\.\d+)"$',
                ".claude-plugin/plugin.json": r'"version": "(\d+\.\d+\.\d+)"',
                "src/tld/__init__.py": r'^__version__ = "(\d+\.\d+\.\d+)"'}
    for rel, pattern in patterns.items():
        assert len(re.findall(pattern, (ROOT / rel).read_text(), re.M)) == 1, rel


@pytest.mark.parametrize("extra", ['++__import__("os")\n', '--x\n', '; import os\n'])
@pytest.mark.parametrize("commit", [False, True])
def test_check_base_fails_on_content_that_looks_like_a_diff_header_or_trails_the_version(repo, capsys, extra, commit):
    prepared(repo, capsys)
    p = repo / "pkg/__init__.py"
    text = p.read_text()
    p.write_text(text.replace("# kept equal", extra.strip() + " # kept equal") if extra.startswith(";")
                 else text + extra)
    if commit:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "x")
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base", "origin/main")
    assert code == 1 and "pkg/__init__.py" in err


def test_check_base_refuses_a_ref_that_looks_like_an_option(repo, capsys):
    prepared(repo, capsys)
    code, _, err = run(capsys, "--check", "--version", "1.2.0", "--base=--independent")
    assert code == 1 and "--independent is not a git ref" in err


def test_the_base_content_must_still_match_the_pattern(repo, capsys):
    prepared(repo, capsys)
    assert rp._rebuild_problems(repo, "HEAD", "pkg/__init__.py", r'^nothing = "(\d+)"', "1") == [
        "no match for the pattern in pkg/__init__.py at the base"]
