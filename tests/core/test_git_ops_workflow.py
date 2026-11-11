"""The tld-git-ops workflow template: structure, and its scripts run for real against a stub gh."""
import json
import os
import re
import subprocess

import pytest
import yaml

from conftest import TLD, FORBIDDEN
from conftest import FORBIDDEN

TEMPLATE = TLD / "templates" / "tld-git-ops.yml"
ALLOWLIST_TEMPLATE = TLD / "templates" / "git-ops-allowlist.json"

STEP_VALIDATE = "Validate the inputs"
STEP_ALLOWLIST = "Check the allowlist"
STEP_TARGET = "Look at the target"
STEP_BRANCH = "Delete the branch"
STEP_NAMES = [STEP_VALIDATE, STEP_ALLOWLIST, STEP_TARGET, STEP_BRANCH]

SHA = "a" * 40

ALLOW = {
    "owner": "o",
    "repos": ["r", "app-*"],
    "protected_branches": ["main", "master", "develop", "release/*", "gh-pages"],
}

# Stub gh: serves JSON from $STUB_DIR, applies the --jq expression with the real jq, logs every call.
# The env var FAIL holds comma-separated substrings; a call whose arguments contain one of them exits 1.
STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_DIR/calls.log"
args="$*"
if [ -n "${FAIL:-}" ]; then
  IFS=, read -ra bad <<< "$FAIL"
  for b in "${bad[@]}"; do
    [ -n "$b" ] && case "$args" in *"$b"*) exit 1 ;; esac
  done
fi
[ "$1" = api ] || exit 2
jqexpr=""; method=GET; path=""; prev=""
for a in "$@"; do
  case "$prev" in --jq) jqexpr=$a ;; -X) method=$a ;; esac
  case "$a" in repos/*) path=$a ;; esac
  prev=$a
done
emit() { if [ -n "$jqexpr" ]; then jq -r "$jqexpr"; else cat; fi; }
[ "$method" = POST ] && exit 2
if [ "$method" = DELETE ]; then echo '{}'; exit 0; fi
case "$path" in
  */contents/git-ops-allowlist.json*)
    [ -f "$STUB_DIR/allowlist.json" ] || exit 1
    cat "$STUB_DIR/allowlist.json" ;;
  */git/ref/heads/*)
    b=${path#*/git/ref/heads/}
    jq -e --arg b "$b" 'has($b)' "$STUB_DIR/branches.json" > /dev/null || exit 1
    jq -c --arg b "$b" '{object: {sha: .[$b]}}' "$STUB_DIR/branches.json" | emit ;;
  */branches/*)
    b=${path#*/branches/}; prot=false
    case ",${PROTECTED:-}," in *",$b,"*) prot=true ;; esac
    echo "{\"protected\": $prot}" | emit ;;
  */pulls\?*) emit < "$STUB_DIR/pulls.json" ;;
  *)
    [[ $path =~ ^repos/[^/]+/[^/]+$ ]] || exit 2
    emit < "$STUB_DIR/repo.json" ;;
esac
"""

needs_jq = pytest.mark.usefixtures("jq_installed")  # fails instead of skipping under TLD_REQUIRE_BROWSER=1


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(TEMPLATE.read_text())


def step(doc, name):
    steps = doc["jobs"]["git-ops"]["steps"]
    return next(s for s in steps if s["name"] == name)


# ---------------------------------------------------------------- structure


def test_triggers_and_settings(doc):
    on = doc[True]  # YAML 1.1: the key `on` loads as boolean True
    assert list(on) == ["workflow_dispatch"]
    inputs = on["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["repo", "action", "name", "dry_run"]
    assert inputs["dry_run"]["default"] is True and inputs["dry_run"]["type"] == "boolean"
    assert inputs["action"]["options"] == ["delete-branch"] and inputs["action"]["type"] == "choice"
    for k in ("repo", "action", "name"):
        assert inputs[k]["required"] is True
    assert doc["concurrency"] == {"group": "tld-git-ops-${{ inputs.repo }}", "cancel-in-progress": False}
    assert doc["permissions"] == {"contents": "read"}
    assert doc["name"] == "tld-git-ops"
    job = doc["jobs"]["git-ops"]
    assert list(doc["jobs"]) == ["git-ops"]
    assert job["environment"] == "git-ops"
    assert job["runs-on"] == "ubuntu-latest"
    assert job["if"] == "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
    assert [s["name"] for s in job["steps"]] == STEP_NAMES
    assert step(doc, STEP_BRANCH)["if"] == "inputs.action == 'delete-branch'"
    assert step(doc, STEP_TARGET)["id"] == "target"


def test_no_third_party_action_and_no_expression_in_scripts(doc):
    for s in doc["jobs"]["git-ops"]["steps"]:
        assert "uses" not in s


def test_no_expression_inside_scripts(doc):
    for s in doc["jobs"]["git-ops"]["steps"]:
        assert "${{" not in s["run"], f"{s['name']}: an expression inside a script is a shell injection"


def test_tokens(doc):
    for name in (STEP_TARGET, STEP_BRANCH):
        assert step(doc, name)["env"]["GH_TOKEN"] == "${{ secrets.GIT_OPS_TOKEN }}"
    for name in (STEP_VALIDATE, STEP_ALLOWLIST):
        assert "secrets." not in json.dumps(step(doc, name))
    assert step(doc, STEP_ALLOWLIST)["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "GH_TOKEN" not in step(doc, STEP_VALIDATE)["env"]


def test_inputs_reach_the_scripts_through_env(doc):
    assert step(doc, STEP_VALIDATE)["env"] == {
        "REPO": "${{ inputs.repo }}", "ACTION": "${{ inputs.action }}", "NAME": "${{ inputs.name }}"}
    assert step(doc, STEP_BRANCH)["env"]["DRY_RUN"] == "${{ inputs.dry_run }}"
    assert step(doc, STEP_BRANCH)["env"]["DEFAULT"] == "${{ steps.target.outputs.default_branch }}"


def test_scripts_have_valid_syntax(doc, tmp_path):
    for i, s in enumerate(doc["jobs"]["git-ops"]["steps"]):
        f = tmp_path / f"s{i}.sh"
        f.write_text(s["run"])
        subprocess.run(["bash", "-n", str(f)], check=True)


def test_no_placeholders():
    assert re.search(r"__[A-Z_]+__", TEMPLATE.read_text()) is None


def test_no_forbidden_words():
    assert FORBIDDEN.search(TEMPLATE.read_text()) is None
    assert FORBIDDEN.search(ALLOWLIST_TEMPLATE.read_text()) is None


def test_allowlist_template_matches_the_design():
    data = json.loads(ALLOWLIST_TEMPLATE.read_text())
    assert data["owner"] == "your-org"
    assert data["protected_branches"] == ["main", "master", "develop", "release/*", "gh-pages"]
    assert data["repos"] and all(isinstance(r, str) and r for r in data["repos"])
    assert "tag_pattern" not in data


def test_the_workflow_never_touches_a_tag():
    """D13: one route to a tag, the release workflow. git-ops only deletes branches."""
    text = TEMPLATE.read_text()
    assert "create-tag" not in text and "git/tags" not in text and "refs/tags" not in text
    assert "contents: read" in text


# ---------------------------------------------------------------- harness


def stub_env(tmp_path, allowlist=ALLOW, branches=None, pulls=(), repo_info=None, **extra):
    """allowlist: a dict (JSON), a str (raw text) or None (the file does not exist)."""
    d = tmp_path / "stub"
    d.mkdir(exist_ok=True)
    runner = tmp_path / "runner"
    runner.mkdir(exist_ok=True)
    if allowlist is not None:
        text = allowlist if isinstance(allowlist, str) else json.dumps(allowlist)
        (d / "allowlist.json").write_text(text)
        (runner / "allowlist.json").write_text(text)  # what step 2 leaves for steps 4 and 5
    (d / "branches.json").write_text(json.dumps(branches if branches is not None else {"feat": SHA}))
    (d / "pulls.json").write_text(json.dumps(list(pulls)))
    (d / "repo.json").write_text(json.dumps(repo_info or {"default_branch": "main", "archived": False}))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(STUB)
    gh.chmod(0o755)
    out, summary = tmp_path / "output", tmp_path / "summary"
    out.write_text("")
    summary.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "STUB_DIR": str(d), "GH_TOKEN": "t",
           "REPO": "o/r", "ACTION": "delete-branch", "NAME": "feat", "DRY_RUN": "true",
           "DEFAULT": "main", "SELF": "o/git-ops", "SELF_DEFAULT": "main", "RUNNER_TEMP": str(runner),
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary), "FAIL": "",
           "PROTECTED": "", **extra}
    return env, d, out, summary


def run_step(doc, name, env, tmp_path):
    f = tmp_path / "step.sh"
    f.write_text(step(doc, name)["run"])
    return subprocess.run(["bash", str(f)], env=env, capture_output=True, text=True)


def subdir(tmp_path, name):
    sub = tmp_path / name
    sub.mkdir()
    return sub


def calls(d):
    log = d / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def writes(d):
    return [c for c in calls(d) if " -X POST " in c or " -X DELETE " in c]


def validate(doc, tmp_path, **kw):
    env, *_ = stub_env(tmp_path, **kw)
    return run_step(doc, STEP_VALIDATE, env, tmp_path)


def check_allowlist(doc, tmp_path, **kw):
    env, d, *_ = stub_env(tmp_path, **kw)
    return run_step(doc, STEP_ALLOWLIST, env, tmp_path), d


def look(doc, tmp_path, **kw):
    env, d, out, _ = stub_env(tmp_path, **kw)
    p = run_step(doc, STEP_TARGET, env, tmp_path)
    return p, out.read_text().strip()


def branch(doc, tmp_path, name="feat", dry="true", **kw):
    env, d, _, summary = stub_env(tmp_path, NAME=name, ACTION="delete-branch", DRY_RUN=dry, **kw)
    p = run_step(doc, STEP_BRANCH, env, tmp_path)
    return p, d, summary.read_text()


# ---------------------------------------------------------------- step 1: validate the inputs

ACCEPTED_NAMES = ["v1.2.3", "release-2026.11", "chore/git-ops-test", "feature/a_b.c", "a"]
REJECTED_NAMES = ["", "refs/heads/x", "-x", "/x", ".x", "x/", "x.", "a..b", "a//b", "a/.b", "x.lock", "a.lock/b",
                  "HEAD", "a b", "a;b", "$(id)", "a@{1}", "a~1", "a^", "a:b", "a*", "a?", "a[", "a" * 201, "a\nb"]


@needs_jq
@pytest.mark.parametrize("name", ACCEPTED_NAMES)
def test_good_names_are_accepted(doc, tmp_path, name):
    p = validate(doc, tmp_path, NAME=name)
    assert p.returncode == 0, p.stdout + p.stderr


def test_longest_name_is_accepted(doc, tmp_path):
    assert validate(doc, tmp_path, NAME="a" * 200).returncode == 0


@pytest.mark.parametrize("name", REJECTED_NAMES)
def test_bad_names_are_rejected(doc, tmp_path, name):
    p = validate(doc, tmp_path, NAME=name)
    assert p.returncode == 1
    assert "::error::name is not a valid branch name (got: " in p.stdout


@pytest.mark.parametrize("repo", ["", "x", "a/b/c", "a b/c", "a/b;c", "your-org/..", "your-org/.x", "/r", "o/", "$(id)/r"])
def test_bad_repo_is_rejected(doc, tmp_path, repo):
    p = validate(doc, tmp_path, REPO=repo)
    assert p.returncode == 1 and f"::error::repo must look like owner/name (got: {repo})" in p.stdout


@pytest.mark.parametrize("repo", ["o/r", "your-org/app-web", "a.b/c_d.e-f", "o/r.js"])
def test_good_repo_is_accepted(doc, tmp_path, repo):
    assert validate(doc, tmp_path, REPO=repo).returncode == 0


@pytest.mark.parametrize("action", ["", "delete-tag", "create-tag", "CREATE-TAG", "delete-branch;x", "delete-branch "])
def test_bad_action_is_rejected(doc, tmp_path, action):
    p = validate(doc, tmp_path, ACTION=action)
    assert p.returncode == 1
    assert "::error::action must be delete-branch (tags are cut only by the release workflow)" in p.stdout


@pytest.mark.parametrize("action", ["delete-branch"])
def test_good_action_is_accepted(doc, tmp_path, action):
    assert validate(doc, tmp_path, ACTION=action).returncode == 0



# ---------------------------------------------------------------- step 2: the allowlist


@needs_jq
def test_allowlist_is_read_from_the_default_branch_of_this_repository(doc, tmp_path):
    p, d = check_allowlist(doc, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert calls(d) == ['api -H Accept: application/vnd.github.raw+json repos/o/git-ops/contents/git-ops-allowlist.json?ref=main']


@needs_jq
@pytest.mark.parametrize("allowlist", [
    None, "{not json", "", "[]", "[1]", '"text"',
    {"repos": ["r"]}, {"owner": "", "repos": ["r"]}, {"owner": 5, "repos": ["r"]},
    {"owner": "o"}, {"owner": "o", "repos": []}, {"owner": "o", "repos": [""]}, {"owner": "o", "repos": "r"},
    {"owner": "o", "repos": [1]},
    {"owner": "o", "repos": ["r"], "protected_branches": "main"}, {"owner": "o", "repos": ["r"], "protected_branches": [1]},
])
def test_invalid_allowlist_is_refused(doc, tmp_path, allowlist):
    p, _ = check_allowlist(doc, tmp_path, allowlist=allowlist)
    assert p.returncode == 1
    assert "::error::git-ops-allowlist.json is missing or invalid on main" in p.stdout


@needs_jq
def test_fetch_failure_is_refused(doc, tmp_path):
    p, _ = check_allowlist(doc, tmp_path, FAIL="contents")
    assert p.returncode == 1 and "is missing or invalid" in p.stdout


@needs_jq
def test_optional_keys_may_be_absent(doc, tmp_path):
    p, _ = check_allowlist(doc, tmp_path, allowlist={"owner": "o", "repos": ["r"]})
    assert p.returncode == 0, p.stdout + p.stderr


@needs_jq
@pytest.mark.parametrize("repo", ["x/r", "O/r", "o/other", "o/rr", "o/ap-web", "o/xapp-web"])
def test_repo_outside_the_allowlist_is_refused(doc, tmp_path, repo):
    p, _ = check_allowlist(doc, tmp_path, REPO=repo)
    assert p.returncode == 1 and f"::error::repository {repo} is not allowed by git-ops-allowlist.json" in p.stdout


@needs_jq
@pytest.mark.parametrize("repo", ["o/r", "o/app-web", "o/app-"])
def test_repo_inside_the_allowlist_is_accepted(doc, tmp_path, repo):
    p, _ = check_allowlist(doc, tmp_path, REPO=repo)
    assert p.returncode == 0, p.stdout + p.stderr


@needs_jq
def test_allowlist_is_written_for_the_later_steps(doc, tmp_path):
    env, *_ = stub_env(tmp_path)
    (tmp_path / "runner" / "allowlist.json").unlink()
    assert run_step(doc, STEP_ALLOWLIST, env, tmp_path).returncode == 0
    assert json.loads((tmp_path / "runner" / "allowlist.json").read_text()) == ALLOW


# ---------------------------------------------------------------- step 3: the target


@needs_jq
def test_target_reports_the_default_branch(doc, tmp_path):
    p, out = look(doc, tmp_path, repo_info={"default_branch": "trunk", "archived": False})
    assert p.returncode == 0, p.stdout + p.stderr
    assert out == "default_branch=trunk"


@needs_jq
def test_target_without_a_token_is_refused(doc, tmp_path):
    p, out = look(doc, tmp_path, GH_TOKEN="")
    assert p.returncode == 1 and out == ""
    assert "::error::secret GIT_OPS_TOKEN is not set for the git-ops environment" in p.stdout


@needs_jq
def test_target_the_token_cannot_see_is_refused(doc, tmp_path):
    p, out = look(doc, tmp_path, FAIL="repos/o/r")
    assert p.returncode == 1 and out == "" and "::error::the token cannot see o/r" in p.stdout


@needs_jq
def test_archived_target_is_refused(doc, tmp_path):
    p, out = look(doc, tmp_path, repo_info={"default_branch": "main", "archived": True})
    assert p.returncode == 1 and out == "" and "::error::o/r is archived" in p.stdout


# ---------------------------------------------------------------- dry run


@needs_jq
def test_dry_run_is_the_default(doc, tmp_path):
    assert doc[True]["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True
    p, d, summary = branch(doc, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert writes(d) == []
    assert f"Dry run: would delete branch feat ({SHA}) in o/r" in summary


@needs_jq
@pytest.mark.parametrize("dry", ["", "True", "0", "yes", "FALSE", "false "])
def test_anything_but_false_is_a_dry_run(doc, tmp_path, dry):
    p, d, summary = branch(doc, tmp_path, dry=dry)
    assert p.returncode == 0, p.stdout + p.stderr
    assert writes(d) == [] and "Dry run:" in summary


# ---------------------------------------------------------------- step 5: delete the branch


def pr(number, head, base="main"):
    return {"number": number, "head": {"ref": head}, "base": {"ref": base}}


@needs_jq
def test_default_branch_is_refused(doc, tmp_path):
    p, d, _ = branch(doc, tmp_path, name="trunk", dry="false", DEFAULT="trunk", branches={"trunk": SHA})
    assert p.returncode == 1 and writes(d) == []
    assert "::error::trunk is the default branch" in p.stdout


@needs_jq
@pytest.mark.parametrize("name", ["main", "master", "develop", "gh-pages", "release/1.0", "release/a/b", "release/"])
def test_protected_branch_is_refused(doc, tmp_path, name):
    p, d, _ = branch(doc, tmp_path, name=name, dry="false", DEFAULT="trunk", branches={name: SHA})
    assert p.returncode == 1 and writes(d) == []
    assert f"::error::{name} is protected by git-ops-allowlist.json" in p.stdout


@needs_jq
@pytest.mark.parametrize("name", ["releases/1.0", "xmain", "feat", "mainx", "gh-pages2"])
def test_similar_names_are_not_protected(doc, tmp_path, name):
    p, d, _ = branch(doc, tmp_path, name=name, branches={name: SHA})
    assert p.returncode == 0, p.stdout + p.stderr


@needs_jq
def test_protection_globs_are_not_expanded_against_files(doc, tmp_path):
    work = subdir(tmp_path, "x")
    (work / "feat").write_text("")
    env, d, *_ = stub_env(work, allowlist={**ALLOW, "protected_branches": ["*"]}, NAME="other", branches={"other": SHA})
    env["ACTION"] = "delete-branch"
    p = subprocess.run(["bash", "-c", step(doc, STEP_BRANCH)["run"]], env=env, cwd=work, capture_output=True, text=True)
    assert p.returncode == 1 and "is protected by git-ops-allowlist.json" in p.stdout  # `*` as a glob matches every name


@needs_jq
def test_missing_protected_branches_key_protects_only_the_default(doc, tmp_path):
    p, d, _ = branch(doc, tmp_path, name="develop", branches={"develop": SHA}, allowlist={"owner": "o", "repos": ["r"]})
    assert p.returncode == 0, p.stdout + p.stderr


@needs_jq
def test_missing_branch_is_refused(doc, tmp_path):
    p, d, _ = branch(doc, tmp_path, name="gone", dry="false", branches={"feat": SHA})
    assert p.returncode == 1 and writes(d) == []
    assert "::error::branch gone does not exist" in p.stdout


@needs_jq
def test_branch_protected_on_github_is_refused(doc, tmp_path):
    p, d, _ = branch(doc, tmp_path, dry="false", PROTECTED="feat")
    assert p.returncode == 1 and writes(d) == []
    assert "::error::feat is protected on GitHub" in p.stdout


@needs_jq
@pytest.mark.parametrize("pulls,listed", [
    ([pr(7, "feat")], "#7"),
    ([pr(8, "other", "feat")], "#8"),
    ([pr(3, "x"), pr(9, "feat"), pr(4, "y", "feat")], "#9 #4"),
])
def test_branch_with_an_open_pull_request_is_refused(doc, tmp_path, pulls, listed):
    p, d, _ = branch(doc, tmp_path, dry="false", pulls=pulls)
    assert p.returncode == 1 and writes(d) == []
    assert f"::error::branch feat is used by open pull requests: {listed}" in p.stdout
    assert any("pulls?state=open&per_page=100" in c and "--paginate" in c for c in calls(d))


@needs_jq
def test_unrelated_pull_requests_do_not_block(doc, tmp_path):
    p, d, _ = branch(doc, tmp_path, pulls=[pr(1, "feat2"), pr(2, "x", "feat2")])
    assert p.returncode == 0, p.stdout + p.stderr


@needs_jq
def test_branch_name_with_a_slash(doc, tmp_path):
    p, d, summary = branch(doc, tmp_path, name="chore/git-ops-test", dry="false", branches={"chore/git-ops-test": SHA})
    assert p.returncode == 0, p.stdout + p.stderr
    assert writes(d) == ["api -X DELETE repos/o/r/git/refs/heads/chore/git-ops-test"]


@needs_jq
def test_real_delete_makes_exactly_one_call(doc, tmp_path):
    p, d, _ = branch(doc, tmp_path, dry="false")
    assert p.returncode == 0, p.stdout + p.stderr
    assert writes(d) == ["api -X DELETE repos/o/r/git/refs/heads/feat"]


@needs_jq
def test_delete_summary_has_a_restore_command(doc, tmp_path):
    p, d, summary = branch(doc, tmp_path, dry="false")
    expected = f"Deleted branch feat in o/r. Restore: gh api -X POST repos/o/r/git/refs -f ref=refs/heads/feat -f sha={SHA}"
    assert expected in summary and expected in p.stdout


@needs_jq
def test_failed_delete_fails_the_step(doc, tmp_path):
    p, d, summary = branch(doc, tmp_path, dry="false", FAIL="-X DELETE")
    assert p.returncode != 0 and "Deleted" not in summary
