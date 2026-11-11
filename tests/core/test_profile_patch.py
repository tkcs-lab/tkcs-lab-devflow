import json
import subprocess
import sys

import pytest
import yaml

from conftest import TLD, tld_cmd, _load

SCRIPT = TLD / "profile" / "patch.py"
SCRIPT_CMD = tld_cmd("profile", "patch")

AGENTS = {"posture": {"security": "critical"},
          "required": [{"role": "security-reviewer", "at": ["implement_final"], "blocking": True}]}
AGENTS2 = {"posture": {"security": "standard"}, "disable": ["website-maintainer"]}
WEBSITE = {"dir": "site", "build": "npm run build", "links": "npm run check-links"}

BASE = """\
# top comment
docs:
  must_read:
    - README.md
  # adr_dir: docs/adr
  # website:
  #   dir: site

git:
  main_branch: main
  branch_pattern: "<type>/<kebab-case>"   # keep me

verify:
  fast: ["echo a"]
  dod: ["echo b"]

stacks: []
"""

WITH_AGENTS = BASE.replace("stacks: []\n", """\
stacks: []

# the roles of this project
roles:
  posture:
    security: low
  # a comment inside the block
  disable: [debugger]

# roles:
#   posture:
#     security: critical
  # indented example
# hooks:
#   x: y
""")


@pytest.fixture(scope="module")
def pp():
    return _load("tld.profile.patch")


def check_valid(vp, text):
    data = yaml.safe_load(text)
    errors = vp.validate(data, None)[0]
    assert errors == [], errors
    return data


def test_replace_keeps_everything_else(pp, vp):
    out = pp.set_block(WITH_AGENTS, "roles", AGENTS)
    old_pre, _, old_post = WITH_AGENTS.partition("roles:\n  posture:\n    security: low\n  # a comment inside the block\n  disable: [debugger]\n")
    assert out.startswith(old_pre)
    assert out.endswith(old_post)
    assert "# the roles of this project\nroles:\n" in out
    assert "# roles:\n#   posture:\n#     security: critical\n  # indented example\n# hooks:" in out
    assert check_valid(vp, out)["roles"] == AGENTS


def test_replace_docs_website_keeps_following_comments(pp, vp):
    text = BASE.replace("  # adr_dir", "  website:\n    dir: old\n    build: x\n  # adr_dir")
    out = pp.set_block(text, "docs.website", WEBSITE)
    assert out.startswith("# top comment\ndocs:\n  must_read:\n    - README.md\n  website:\n    dir: site\n")
    assert out.endswith(BASE.split("  must_read:\n    - README.md\n", 1)[1])
    assert "    build: npm run build\n    links: npm run check-links\n  # adr_dir: docs/adr\n  # website:\n  #   dir: site\n" in out
    assert check_valid(vp, out)["docs"]["website"] == WEBSITE


def test_append_agents_adds_one_blank_line_at_end(pp, vp):
    out = pp.set_block(BASE, "roles", AGENTS2)
    assert out.startswith(BASE + "\nroles:\n")
    assert out.endswith("\n") and not out.endswith("\n\n")
    assert check_valid(vp, out)["roles"] == AGENTS2


def test_append_without_trailing_newline(pp, vp):
    out = pp.set_block(BASE.rstrip("\n"), "roles", AGENTS2)
    assert out.startswith(BASE.rstrip("\n") + "\n\nroles:\n")
    check_valid(vp, out)


def test_website_added_directly_after_docs_block(pp, vp):
    out = pp.set_block(BASE, "docs.website", WEBSITE)
    expected = BASE.replace("    - README.md\n", "    - README.md\n  website:\n    dir: site\n    build: npm run build\n"
                            "    links: npm run check-links\n", 1)
    assert out == expected
    assert check_valid(vp, out)["docs"]["website"] == WEBSITE


def test_website_goes_before_trailing_comments_not_after(pp):
    out = pp.set_block(BASE, "docs.website", WEBSITE)
    assert out.index("  website:\n    dir: site") < out.index("  # adr_dir")


@pytest.mark.parametrize("key,value", [("roles", AGENTS), ("docs.website", WEBSITE)])
@pytest.mark.parametrize("text", [BASE, WITH_AGENTS])
def test_idempotent(pp, vp, key, value, text):
    once = pp.set_block(text, key, value)
    assert pp.set_block(once, key, value) == once
    check_valid(vp, once)


def test_docs_website_without_docs_block(pp):
    with pytest.raises(pp.PatchError, match="^no 'docs' block to add 'website' to$"):
        pp.set_block("git:\n  main_branch: main\n", "docs.website", WEBSITE)


def test_unknown_key(pp):
    with pytest.raises(pp.PatchError):
        pp.set_block(BASE, "git", {})


# ---- diff ------------------------------------------------------------------------------------
def make_repo(tmp_path, profile_text):
    (tmp_path / ".tld").mkdir()
    prof = tmp_path / ".tld" / "toolkit.yaml"
    prof.write_text(profile_text)
    return prof


def test_diff_new_changed_same(pp, tmp_path):
    prof = make_repo(tmp_path, BASE)
    (tmp_path / "README.md").write_text("x")
    proposal = {"stacks": [], "git": {"main_branch": "trunk"}, "docs": {"must_read": ["README.md"], "adr_dir": "docs/adr"},
                "roles": AGENTS}
    result = pp.diff(yaml.safe_load(BASE), proposal, tmp_path)
    assert result["same"] == ["stacks", "docs.must_read"]
    assert result["changed"] == [{"key": "git.main_branch", "from": "main", "to": "trunk"}]
    assert result["new"] == ["docs.adr_dir", "roles"]
    assert prof.exists()


def test_diff_stale_paths_and_globs(pp, tmp_path):
    text = """\
docs:
  must_read: [README.md, MISSING.md]
  adr_bar: CONTRIBUTING.md#bar
git: {main_branch: main, branch_pattern: x}
verify: {fast: [a], dod: [b]}
stacks: []
ci:
  dispatchable:
    - {workflow: gone.yml, use_when: u}
    - {workflow: here.yml, use_when: u}
roles:
  required:
    - {role: ux-reviewer, at: [implement_final], when: ["app/**", "ghost/**", "vendored/**"]}
"""
    make_repo(tmp_path, text)
    (tmp_path / "README.md").write_text("x")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "here.yml").write_text("x")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.swift").write_text("x")
    (tmp_path / "node_modules" / "vendored").mkdir(parents=True)
    (tmp_path / "node_modules" / "vendored" / "f.js").write_text("x")
    (tmp_path / "vendored").mkdir()  # an empty directory is no file
    stale = pp.diff(yaml.safe_load(text), {}, tmp_path)["stale"]
    assert stale == [
        {"key": "docs.must_read[1]", "value": "MISSING.md", "why": "path not found"},
        {"key": "docs.adr_bar", "value": "CONTRIBUTING.md#bar", "why": "path not found"},
        {"key": "ci.dispatchable[0].workflow", "value": "gone.yml", "why": "path not found"},
        {"key": "roles.required[0].when[1]", "value": "ghost/**", "why": "no file matches"},
        {"key": "roles.required[0].when[2]", "value": "vendored/**", "why": "no file matches"},
    ]


def test_diff_file_under_node_modules_does_not_match(pp, tmp_path):
    (tmp_path / "node_modules" / "web").mkdir(parents=True)
    (tmp_path / "node_modules" / "web" / "x.js").write_text("x")
    profile = {"roles": {"required": [{"role": "ux-reviewer", "at": ["dod"], "when": ["**/x.js"]}]}}
    assert pp.diff(profile, {}, tmp_path)["stale"][0]["why"] == "no file matches"


# ---- CLI -------------------------------------------------------------------------------------
def run(*args):
    return subprocess.run([*SCRIPT_CMD, *map(str, args)], capture_output=True, text=True)


def survey(profile):
    return {"root": ".", "evidence": {}, "proposal": {"profile": profile, "rationale": []}}


def test_cli_set_block_shows_a_diff_and_writes_a_new_block(tmp_path, vp):
    prof = make_repo(tmp_path, BASE)
    value = tmp_path / "survey.json"
    value.write_text(json.dumps(survey({"roles": AGENTS, "docs": {"website": WEBSITE}})))
    r = run("set-block", prof, "roles", value)
    assert r.returncode == 0 and r.stderr == ""
    assert prof.read_text() == BASE  # a diff only, the file is untouched
    assert r.stdout.startswith(f"--- {prof}\n+++ {prof} (proposed)\n") and "+roles:\n" in r.stdout
    r = run("set-block", prof, "roles", value, "--write")
    assert r.returncode == 0 and r.stdout.endswith(f"profile_patch: wrote 'roles' to {prof}\n")
    r = run("set-block", prof, "docs.website", value, "--write")
    assert r.returncode == 0
    data = check_valid(vp, prof.read_text())
    assert data["roles"] == AGENTS and data["docs"]["website"] == WEBSITE
    before = prof.read_text()
    r = run("set-block", prof, "roles", value, "--write")
    assert prof.read_text() == before and r.stdout == "profile_patch: 'roles' is unchanged\n"


def test_cli_set_block_never_overwrites_a_hand_tuned_block_silently(tmp_path, vp):
    """C1: a block that differs is shown as a diff and written only with --yes."""
    prof = make_repo(tmp_path, WITH_AGENTS)
    value = tmp_path / "survey.json"
    value.write_text(json.dumps(survey({"roles": AGENTS})))
    r = run("set-block", prof, "roles", value, "--write")
    assert r.returncode == 4
    assert "-    security: low\n" in r.stdout and "+    security: critical\n" in r.stdout
    assert "nothing was written" in r.stderr
    assert prof.read_text() == WITH_AGENTS
    r = run("set-block", prof, "roles", value, "--write", "--yes")
    assert r.returncode == 0
    assert check_valid(vp, prof.read_text())["roles"] == AGENTS


def test_cli_set_block_merges_the_answers(tmp_path, vp):
    """C1: the human's answers are merged over the proposal, entries of `required` by role."""
    prof = make_repo(tmp_path, BASE)
    value = tmp_path / "survey.json"
    proposal = {"posture": {"security": "standard"},
                "required": [{"role": "security-reviewer", "at": ["implement_final"], "blocking": True},
                             {"role": "test-architect", "at": ["make_plan"], "blocking": False}]}
    value.write_text(json.dumps(survey({"roles": proposal})))
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"roles": {
        "posture": {"security": "critical"},
        "required": [{"role": "security-reviewer", "blocking": False},
                     {"role": "test-architect", "drop": True},
                     {"role": "tech-writer", "at": ["dod"]}]}}))
    r = run("set-block", prof, "roles", value, "--answers", answers, "--write")
    assert r.returncode == 0, r.stderr
    assert check_valid(vp, prof.read_text())["roles"] == {
        "posture": {"security": "critical"},
        "required": [{"role": "security-reviewer", "at": ["implement_final"], "blocking": False},
                     {"role": "tech-writer", "at": ["dod"]}]}


def test_merge_answers_need_a_role(pp):
    with pytest.raises(pp.PatchError, match="needs a 'role'"):
        pp.merge({"required": []}, {"required": [{"blocking": True}]})


def test_cli_set_block_plain_value_file(tmp_path):
    prof = make_repo(tmp_path, BASE)
    value = tmp_path / "v.json"
    value.write_text(json.dumps(WEBSITE))
    r = run("set-block", prof, "docs.website", value)
    assert r.returncode == 0
    assert "+  website:\n+    dir: site\n" in r.stdout


def test_cli_absent_block_is_a_no_op(tmp_path):
    """C1: a survey that found no website (or no roles) changes nothing and exits 0."""
    prof = make_repo(tmp_path, BASE)
    value = tmp_path / "survey.json"
    value.write_text(json.dumps(survey({"stacks": []})))
    for key in ("roles", "docs.website"):
        r = run("set-block", prof, key, value, "--write")
        assert r.returncode == 0 and r.stdout == ""
        assert r.stderr == f"profile_patch: neither the proposal nor the answers have '{key}': nothing to change\n"
    assert prof.read_text() == BASE
    value.write_text(json.dumps({"proposal": None}))
    assert run("set-block", prof, "roles", value).returncode == 0


def test_cli_website_without_docs_exits_1(tmp_path):
    prof = make_repo(tmp_path, "git:\n  main_branch: main\n")
    value = tmp_path / "v.json"
    value.write_text(json.dumps(WEBSITE))
    r = run("set-block", prof, "docs.website", value)
    assert r.returncode == 1
    assert r.stderr == "profile_patch: no 'docs' block to add 'website' to\n"


def test_cli_missing_profile_exits_1(tmp_path):
    value = tmp_path / "v.json"
    value.write_text("{}")
    r = run("set-block", tmp_path / "nope.yaml", "roles", value)
    assert r.returncode == 1 and r.stderr.startswith("profile_patch: cannot read")


def test_cli_diff_with_survey_and_root(tmp_path):
    prof = make_repo(tmp_path, BASE)
    (tmp_path / "README.md").write_text("x")
    proposal = tmp_path / "survey.json"
    proposal.write_text(json.dumps(survey({"stacks": [], "roles": AGENTS})))
    r = run("diff", prof, proposal)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["same"] == ["stacks"] and out["new"] == ["roles"] and out["changed"] == []
    assert out["stale"] == []
    r = run("diff", prof, proposal, "--root", tmp_path / "elsewhere")
    assert json.loads(r.stdout)["stale"][0]["key"] == "docs.must_read[0]"
    # the profile object itself is accepted as well
    proposal.write_text(json.dumps({"roles": AGENTS}))
    assert json.loads(run("diff", prof, proposal).stdout)["new"] == ["roles"]


def test_survey_then_set_block_validates(tmp_path):
    from evals.fixtures import setup_repos
    repo = tmp_path / "repo"
    setup_repos.build(repo, repo="security_heavy", with_profile=True)
    survey_out = subprocess.run([*tld_cmd("profile", "survey"), str(repo)], capture_output=True, text=True)
    assert survey_out.returncode == 0, survey_out.stderr
    survey_file = tmp_path / "survey.json"
    survey_file.write_text(survey_out.stdout)
    assert "roles" in json.loads(survey_out.stdout)["proposal"]["profile"]
    profile = repo / ".tld" / "toolkit.yaml"
    patched = subprocess.run([*SCRIPT_CMD, "set-block", str(profile), "roles", str(survey_file), "--write"],
                             capture_output=True, text=True)
    assert patched.returncode == 0, patched.stderr
    assert "roles:" in profile.read_text()
    check = subprocess.run([*tld_cmd("profile", "validate"), str(profile), "--no-file-checks"],
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
