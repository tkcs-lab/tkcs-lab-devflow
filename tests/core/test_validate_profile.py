import copy
import json
import subprocess
import sys

import pytest
import yaml

from conftest import ROOT, TLD, FIXTURES, tld_cmd

MINIMAL = {
    "docs": {"must_read": []},
    "git": {"main_branch": "main", "branch_pattern": "<type>/<kebab-case>"},
    "verify": {"fast": ["make lint"], "dod": ["make test"]},
    "stacks": [],
}


def errs(vp, profile, root=None):
    return vp.validate(profile, root)[0]


def test_minimal_profile_is_valid(vp):
    assert errs(vp, MINIMAL) == []


@pytest.mark.parametrize("path,message", [
    (("docs",), "missing required key 'docs'"),
    (("docs", "must_read"), "missing required key 'docs.must_read'"),
    (("git",), "missing required key 'git'"),
    (("git", "main_branch"), "missing required key 'git.main_branch'"),
    (("git", "branch_pattern"), "missing required key 'git.branch_pattern'"),
    (("verify",), "missing required key 'verify'"),
    (("verify", "fast"), "missing required key 'verify.fast'"),
    (("verify", "dod"), "missing required key 'verify.dod'"),
    (("stacks",), "missing required key 'stacks'"),
])
def test_missing_required_key_is_named(vp, path, message):
    p = copy.deepcopy(MINIMAL)
    node = p
    for k in path[:-1]:
        node = node[k]
    del node[path[-1]]
    assert message in errs(vp, p)


def test_unknown_key_is_an_error(vp):
    p = copy.deepcopy(MINIMAL)
    p["verfy"] = {}
    p["git"]["main"] = "x"
    e = errs(vp, p)
    assert any("unknown key 'verfy'" in x for x in e)
    assert any("unknown key 'git.main'" in x for x in e)


@pytest.mark.parametrize("mutate,fragment", [
    (lambda p: p["stacks"].append(3), "'stacks[0]': must be a string"),
    (lambda p: p["verify"].update(fast="make lint"), "'verify.fast': must be a list"),
    (lambda p: p["verify"].update(dod=[]), "'verify.dod': needs at least 1 item"),
    (lambda p: p["verify"].update(dod=[{"cwd": "x"}]), "missing required key 'verify.dod[0].run'"),
    (lambda p: p["git"].update(merge_style="rebase"), "'git.merge_style': must be one of"),
    (lambda p: p.update(models={"worker": "gpt"}), "'models.worker': must be one of"),
    (lambda p: p["docs"].update(changelog={"file": "C.md"}), "missing required key 'docs.changelog.section'"),
    (lambda p: p.update(ci={"dispatchable": [{"workflow": "a.yml"}]}), "missing required key 'ci.dispatchable[0].use_when'"),
    (lambda p: p["git"].update(main_branch=""), "'git.main_branch': must not be empty"),
    (lambda p: p["verify"].update(after_merge_allow=[""]), "'verify.after_merge_allow[0]': must not be empty"),
    (lambda p: p["verify"].update(after_merge_allow="npm test"), "'verify.after_merge_allow': must be a list (got str)"),
    (lambda p: p["verify"].update(after_merge_allow=[3]), "'verify.after_merge_allow[0]': must be a string (got int)"),
])
def test_type_errors(vp, mutate, fragment):
    p = copy.deepcopy(MINIMAL)
    mutate(p)
    assert any(fragment in e for e in errs(vp, p)), errs(vp, p)


def test_after_merge_allow_accepted(vp):
    p = copy.deepcopy(MINIMAL)
    p["verify"]["after_merge_allow"] = ["npm test"]
    assert errs(vp, p) == []


def test_defaults_are_the_only_defaults(vp):
    _, _, resolved = vp.validate(MINIMAL)
    assert resolved["docs"]["plan_dir"] == "docs/plans"
    assert resolved["models"] == {"worker": "standard", "reviewer": "strong"}
    assert "adr_dir" not in resolved["docs"]
    assert "ci" not in resolved and "project_steward" not in resolved


def test_plan_dir_trailing_slash_normalised(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["plan_dir"] = "plans/"
    assert vp.validate(p)[2]["docs"]["plan_dir"] == "plans"


def test_adr_keys_need_adr_dir(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["adr_index"] = "docs/adr/README.md"
    assert any("adr_dir" in e for e in errs(vp, p))


def test_swift_without_dispatchable_warns(vp):
    p = copy.deepcopy(MINIMAL)
    p["stacks"] = ["swift"]
    e, w, _ = vp.validate(p)
    assert e == [] and any("macOS workflow" in x for x in w)
    p["ci"] = {"dispatchable": [{"workflow": "apple.yml", "use_when": "iOS tests"}]}
    assert vp.validate(p)[1] == []


def test_ipados_needs_swift_and_a_macos_workflow(vp):
    p = copy.deepcopy(MINIMAL)
    p["stacks"] = ["ipados"]
    e, w, _ = vp.validate(p)
    assert e == []
    assert any("macOS workflow" in x for x in w)
    assert any("stacks: [swift, ipados]" in x for x in w)
    p["stacks"] = ["swift", "ipados"]
    p["ci"] = {"dispatchable": [{"workflow": "ipad-tests.yml", "use_when": "iPad simulator tests"}]}
    assert vp.validate(p)[1] == []


def test_listed_files_must_exist(vp, tmp_path):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["must_read"] = ["README.md", "docs/missing.md"]
    p["project_steward"] = ".claude/skills/x/SKILL.md"
    (tmp_path / "README.md").write_text("x")
    e = errs(vp, p, tmp_path)
    assert any("'docs/missing.md'" in x for x in e)
    assert any("'.claude/skills/x/SKILL.md'" in x for x in e)
    assert not any("'README.md'" in x for x in e)


def test_docs_index_accepted_by_schema(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["index"] = "docs/README.md"
    assert errs(vp, p) == []


def test_docs_index_empty_string_rejected(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["index"] = ""
    assert errs(vp, p)


def test_docs_index_file_must_exist(vp, tmp_path):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["index"] = "docs/README.md"
    (tmp_path / "README.md").write_text("x")
    e = errs(vp, p, tmp_path)
    assert any("'docs/README.md'" in x for x in e)


def test_docs_index_existing_passes(vp, tmp_path):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["index"] = "docs/README.md"
    (tmp_path / "README.md").write_text("x")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("x")
    assert not any("docs/README.md" in x for x in errs(vp, p, tmp_path))


def test_must_read_over_three_with_index_warns(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["index"] = "docs/README.md"
    p["docs"]["must_read"] = ["a.md", "b.md", "c.md", "d.md"]
    w = vp.validate(p)[1]
    assert any("'docs.must_read' lists 4 files while 'docs.index' is set" in x for x in w)
    p["docs"]["must_read"] = ["a.md", "b.md", "c.md"]
    assert not any("'docs.must_read' lists" in x for x in vp.validate(p)[1])


def run_cli(*args):
    return subprocess.run([*tld_cmd("profile", "validate"), *args],
                          capture_output=True, text=True)


def test_cli_missing_profile():
    out = run_cli("/nonexistent/toolkit.yaml")
    assert out.returncode == 1 and "no profile at" in out.stderr


def test_cli_names_missing_key(tmp_path):
    f = tmp_path / "toolkit.yaml"
    bad = copy.deepcopy(MINIMAL)
    del bad["verify"]["fast"]
    f.write_text(yaml.safe_dump(bad))
    out = run_cli(str(f), "--no-file-checks")
    assert out.returncode == 1
    assert "toolkit.yaml: missing required key 'verify.fast'" in out.stderr


def test_cli_bad_yaml(tmp_path):
    f = tmp_path / "toolkit.yaml"
    f.write_text("a: [unclosed")
    assert run_cli(str(f)).returncode == 1


def test_cli_resolved_json(tmp_path):
    f = tmp_path / "toolkit.yaml"
    f.write_text(yaml.safe_dump(MINIMAL))
    out = run_cli(str(f), "--no-file-checks", "--resolved")
    assert out.returncode == 0
    assert json.loads(out.stdout)["docs"]["plan_dir"] == "docs/plans"


def test_privacyfence_profile_is_valid(vp):
    profile = yaml.safe_load((FIXTURES / "privacyfence-toolkit.yaml").read_text())
    e, w, resolved = vp.validate(profile)  # no file checks: PrivacyFence's files are not in this repo
    assert e == [] and w == []
    assert [c if isinstance(c, str) else c["run"] for c in resolved["verify"]["fast"]] == [
        "ruff check .", "python3 -m pytest tests/unit -q"]
    assert len(resolved["ci"]["dispatchable"]) == 7


def test_starter_template_is_valid(vp):
    profile = yaml.safe_load((TLD / "templates" / "toolkit.yaml").read_text())
    assert vp.validate(profile)[0] == []


def test_schema_file_matches_the_validator(vp):
    schema = json.loads(vp.SCHEMA.read_text())
    assert set(schema["required"]) == {"docs", "git", "verify", "stacks"}
    assert schema["additionalProperties"] is False
    for key in ("project", "docs", "git", "verify", "ci", "stacks", "models", "project_steward"):
        assert key in schema["properties"]


def test_toolkit_section_is_rejected_with_a_migration_message(vp):
    p = copy.deepcopy(MINIMAL)
    p["toolkit"] = {"ref": "v1"}
    assert errs(vp, p) == [
        "'toolkit' was removed: the toolkit is delivered only as plugins (docs/guides/delivery.md); "
        "delete the 'toolkit' section"
    ]


def _git(**kw):
    p = copy.deepcopy(MINIMAL)
    p["git"].update(kw)
    return p


def test_identity_keys_in_a_valid_profile(vp):
    e, w, _ = vp.validate(_git(codeowners=["owner"], bot_login="agent"))
    assert e == [] and w == []


def test_bot_in_codeowners_is_an_error(vp):
    assert errs(vp, _git(codeowners=["owner", "agent"], bot_login="agent")) == [
        "'git.codeowners' must not contain 'git.bot_login': the agent cannot be its own code owner"]


def test_codeowners_without_bot_login_is_an_error(vp):
    assert errs(vp, _git(codeowners=["owner"])) == ["'git.codeowners' needs 'git.bot_login'"]


def test_bot_login_without_codeowners_warns(vp):
    e, w, _ = vp.validate(_git(bot_login="agent"))
    assert e == [] and w == ["'git.bot_login' is set without 'git.codeowners': nobody is asked to review"]


def test_empty_codeowners_and_empty_bot_login_are_rejected(vp):
    assert errs(vp, _git(codeowners=[], bot_login="agent"))
    assert errs(vp, _git(bot_login=""))


def _maintenance():
    return yaml.safe_load((FIXTURES / "maintenance-toolkit.yaml").read_text())


def test_maintenance_fixture_is_valid(vp):
    assert errs(vp, _maintenance()) == []


@pytest.mark.parametrize("mutate,message", [
    (lambda p: p["deps"].pop("cooldown_days"), "missing required key 'deps.cooldown_days'"),
    (lambda p: p["deps"].update(cooldown_days=31), "'deps.cooldown_days': must be at most 30"),
    (lambda p: p["upstream"].update(repo="nonsense"), "'upstream.repo': does not match"),
    (lambda p: p["upstream"].update(tag_pattern="(["), "'upstream.tag_pattern': not a valid regular expression"),
    (lambda p: p["land"].update(max_prs=0), "'land.max_prs': must be at least 1"),
    (lambda p: p["deps"].update(bogus=1), "unknown key 'deps.bogus'"),
    (lambda p: p["deps"]["audit"][0].pop("run"), "missing required key 'deps.audit[0].run'"),
])
def test_maintenance_keys_are_checked(vp, mutate, message):
    profile = copy.deepcopy(_maintenance())
    mutate(profile)
    assert any(message in e for e in errs(vp, profile))


def _with_git_ops(**git_ops):
    p = copy.deepcopy(MINIMAL)
    p["git_ops"] = git_ops
    return p


def test_git_ops_section_is_optional_and_stays_absent(vp):
    assert errs(vp, MINIMAL) == []
    assert "git_ops" not in vp.validate(MINIMAL)[2]


def test_git_ops_accepts_repo_and_workflow(vp):
    assert errs(vp, _with_git_ops(repo="tkcs-lab/git-ops")) == []
    assert errs(vp, _with_git_ops(repo="tkcs-lab/git-ops", workflow="tld-git-ops.yml")) == []


def test_git_ops_requires_repo(vp):
    assert any("missing required key 'git_ops.repo'" in e
               for e in errs(vp, _with_git_ops(workflow="tld-git-ops.yml")))


@pytest.mark.parametrize("repo", ["x", "a/b/c", "a b/c", "/c", "a/"])
def test_git_ops_repo_must_be_owner_slash_name(vp, repo):
    assert any("'git_ops.repo'" in e for e in errs(vp, _with_git_ops(repo=repo)))


@pytest.mark.parametrize("workflow,ok", [
    ("ci.yml", True), ("tld-git-ops.yaml", True),
    ("ci", False), ("ci.txt", False), ("../ci.yml", False),
])
def test_git_ops_workflow_must_be_a_workflow_file_name(vp, workflow, ok):
    result = errs(vp, _with_git_ops(repo="a/b", workflow=workflow))
    assert (result == []) is ok
    if not ok:
        assert any("'git_ops.workflow'" in e for e in result)


def test_git_ops_unknown_key_is_rejected(vp):
    assert any("unknown key 'git_ops.extra'" in e for e in errs(vp, _with_git_ops(repo="a/b", extra=1)))


def test_profile_schema_has_no_status_key():
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    assert "status" not in schema["properties"]


def test_profile_with_the_old_status_key_is_rejected(tmp_path):
    profile = tmp_path / "toolkit.yaml"
    profile.write_text((ROOT / ".tld" / "toolkit.yaml").read_text() + "status:\n  board_url: https://example.org/x\n")
    result = subprocess.run([*tld_cmd("profile", "validate"), str(profile), "--no-file-checks"],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "unknown key 'status'" in result.stderr


def _release(version_files=None, **extra):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["changelog"] = {"file": "CHANGELOG.md", "section": "## [Unreleased]"}
    p["release"] = {"workflow": "release.yml",
                    "version_files": version_files or [{"path": "v.txt", "pattern": r'^version = "(\d+\.\d+\.\d+)"$'}],
                    **extra}
    return p


def _release_tree(tmp_path, text='version = "1.0.0"\n'):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "release.yml").write_text("on: workflow_dispatch\n")
    (tmp_path / "v.txt").write_text(text)
    return tmp_path


def test_valid_release_section_passes(vp, tmp_path):
    assert errs(vp, _release()) == []
    assert errs(vp, _release(), _release_tree(tmp_path)) == []


def test_release_pattern_must_compile(vp):
    e = errs(vp, _release([{"path": "v.txt", "pattern": "("}]))
    assert len(e) == 1 and e[0].startswith("'release.version_files[0].pattern': not a valid regular expression (")


@pytest.mark.parametrize("pattern", [r"^version = \d+$", r"^(\d+)\.(\d+)$"])
def test_release_pattern_needs_exactly_one_group(vp, pattern):
    assert errs(vp, _release([{"path": "v.txt", "pattern": pattern}])) == [
        "'release.version_files[0].pattern': needs exactly one capture group, the version"]


def test_release_needs_docs_changelog(vp):
    p = _release()
    del p["docs"]["changelog"]
    assert errs(vp, p) == ["'release' needs 'docs.changelog' (the release skill turns its unreleased section "
                           "into a version heading)"]


def test_release_files_must_exist(vp, tmp_path):
    e = errs(vp, _release(), tmp_path)
    assert f"file not found: '.github/workflows/release.yml' (listed in the profile; checked from {tmp_path})" in e
    assert f"file not found: 'v.txt' (listed in the profile; checked from {tmp_path})" in e


@pytest.mark.parametrize("text,n", [("nothing\n", 0), ('version = "1.0.0"\nversion = "2.0.0"\n', 2)])
def test_release_pattern_must_match_once(vp, tmp_path, text, n):
    e = errs(vp, _release(), _release_tree(tmp_path, text))
    assert e == [f"'release.version_files[0]': the pattern matches {n} times in v.txt (needs exactly 1)"]


def test_release_extra_keys_are_errors(vp):
    assert errs(vp, _release(extra=1))
    p = _release()
    p["release"]["version_files"][0]["x"] = 1
    assert errs(vp, p)


def test_release_workflow_has_no_slash(vp):
    p = _release()
    p["release"]["workflow"] = "../x.yml"
    assert errs(vp, p)


def test_release_version_files_not_empty(vp):
    p = _release()
    p["release"]["version_files"] = []
    assert errs(vp, p)
