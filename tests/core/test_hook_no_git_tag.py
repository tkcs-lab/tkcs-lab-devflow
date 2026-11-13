"""no-git-tag: no creating, moving, deleting or pushing tags; reading stays allowed."""
import json
import re
import subprocess
import sys
import time

import pytest

from conftest import BIN
from hooks_helpers import bash, event, git, make_repo, make_repo_with_origin, run, run_script

HOOK = "no-git-tag"

DENIED = [
    # git tag, every way of writing a tag
    "git tag v2", "git tag v2 HEAD", "git tag v2 abc123", "git tag -a v2 -m 'release'", "git tag -am msg v2",
    "git tag -a -m 'msg' v2 HEAD", "git tag -s v2", "git tag -f v1.0", "git tag -fa v1.0 -m x", "git tag -d v1.0",
    "git tag --delete v1.0", "git tag --del v1.0", "git tag -d v1.0 v2", "git tag --annotate v2", "git tag --force v2 HEAD",
    "git tag -F notes.txt v2", "git tag -u keyid v2", "git tag -m 'a message' v2", "git tag --message='a message' v2",
    "git tag --sign v2", "git tag -- v2", "git tag -e v2", "git tag -a v2", "git -C . tag v2", "git -c tag.gpgsign=false tag v2",
    "git tag -d -l v1.0",
    # pushing tags
    "git push --tags", "git push origin --tags", "git push --follow-tags", "git push --tag", "git push origin refs/tags/v2",
    "git push origin v1.0", "git push origin tag v2", "git push origin :refs/tags/v1.0", "git push --delete origin v1.0",
    "git push origin HEAD:refs/tags/v2", "git push origin refs/tags/*:refs/tags/*", "git push origin v1.0:refs/heads/x",
    "git push origin feature/demo v1.0",
    # other ways to write a tag ref
    "git update-ref refs/tags/v2 HEAD", "git update-ref -d refs/tags/v1.0",
    # indirection and chaining
    "echo ok && git tag v2", "git tag v2 || true", "(git tag v2)", "bash -c 'git tag v2'", "sh -c \"git push --tags\"",
    "FOO=1 git tag v2", "sudo git tag v2", "eval git tag v2", "echo $(git tag v2)", "echo `git tag v2`",
    "xargs -n1 git tag -d < list", "if true; then git tag v2; fi", "cd . && git push --tags", "git status\ngit tag v2",
    "/usr/bin/git tag v2",
    # the API and the gh CLI
    "gh release create v2", "gh release create v2 --generate-notes", "gh release delete v1.0", "gh -R o/r release create v2",
    "gh api -X POST repos/o/r/git/refs -f ref=refs/tags/v2 -f sha=abc", "gh api -X DELETE repos/o/r/git/refs/tags/v1.0",
    "gh api -X PATCH repos/o/r/git/refs/tags/v1.0 -f sha=abc", "gh api repos/o/r/git/tags -f tag=v2 -f message=m -f object=abc -f type=commit",
    "gh api repos/o/r/releases -f tag_name=v2",
]
ALLOWED = [
    # reading tags
    "git tag", "git tag -l", "git tag --list", "git tag -l 'v*'", "git tag --list 'v*'", "git tag -n", "git tag -n5 -l",
    "git tag -n v1.0", "git tag --sort=-v:refname", "git tag --sort -version:refname", "git tag --contains HEAD",
    "git tag --points-at HEAD", "git tag --merged main", "git tag --no-merged main", "git tag -v v1.0",
    "git tag --format='%(refname)'", "git tag -l --sort=-creatordate", "git describe", "git describe --tags",
    "git describe --tags --abbrev=0", "git fetch --tags", "git fetch origin --tags", "git fetch origin 'refs/tags/*:refs/tags/*'",
    "git ls-remote --tags origin", "git ls-remote --tags https://github.com/o/r.git", "git ls-remote --tags --refs origin",
    "git show v1.0", "git log v1.0..HEAD", "git rev-list -n1 v1.0", "git checkout v1.0", "git cat-file -t v1.0",
    "git for-each-ref refs/tags", "git show-ref --tags", "git rev-parse v1.0", "git diff v1.0...HEAD", "git merge-base v1.0 HEAD",
    "gh release list", "gh release view v1.0", "gh release download v1.0", "gh api repos/o/r/git/refs/tags/v1.0",
    "gh api repos/o/r/releases/latest", "gh api repos/o/r/git/refs", "gh api repos/o/r/tags",
    # pushes of branches, including names that contain "tag"
    "git push -u origin feature/demo", "git push origin HEAD", "git push", "git push origin feature/tag-fix",
    "git push origin main:feature/y", "git push origin feature/demo:feature/other", "git push origin plan/tags",
    "git push -u origin chore/upstream-v1-2-3", "git push origin 'refs/heads/feature/demo'", 'git push origin "$BRANCH"',
    "git push origin v9.9",  # no such tag here: it is a branch name as far as the repository can tell
    "git update-ref refs/heads/x HEAD", "git branch v2", "git checkout -b v3",
    # mentions
    "echo 'git tag v2'", "git commit -m 'docs: never git tag from a session'", "grep -rn 'git tag' docs",
    "git commit -m \"$(cat <<'EOF'\nnote: do not git tag or git push --tags\nEOF\n)\"", "ls",
    "cli/tld ops upstream-sync plan --upstream-url https://github.com/o/r.git --version-file v.txt --pattern '^v'",
]


@pytest.mark.parametrize("command", DENIED)
def test_denied(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert r.code == 2, command
    assert r.stderr.startswith("tld no-git-tag: blocked")
    assert "release workflow" in r.stderr and "git describe" in r.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert (r.code, r.stderr) == (0, ""), command


def test_pushing_a_bare_name_is_a_tag_push_only_when_a_tag_of_that_name_exists(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    assert run(HOOK, bash("git push origin v1.0", repo)).code == 2
    assert run(HOOK, bash("git push origin v7.7", repo)).code == 0
    git(repo, "tag", "v7.7")
    assert run(HOOK, bash("git push origin v7.7", repo)).code == 2
    assert run(HOOK, bash("git -C . push origin v7.7", repo.parent)).code in (0, 2)  # cwd elsewhere: no crash


def test_alias_is_followed(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    git(repo, "config", "alias.mark", "tag")
    git(repo, "config", "alias.release", "!git tag")
    assert run(HOOK, bash("git mark v9", repo)).code == 2
    assert run(HOOK, bash("git release v9", repo)).code == 2
    assert run(HOOK, bash("git mark -l", repo)).code == 0


def test_unparseable_commands_fail_closed(feature_repo):
    r = run(HOOK, bash("git tag 'v2", feature_repo))
    assert r.code == 2 and "cannot parse" in r.stderr


def test_disable_flag(tmp_path):
    # S1: disable only counts when committed on the remote main branch, not in the working tree.
    repo = make_repo_with_origin(tmp_path / "r", committed="git:\n  main_branch: main\nhooks:\n  disable: [no-git-tag]\n")
    assert run(HOOK, bash("git tag v2", repo)).code == 0


def test_disable_in_working_tree_only_is_ignored(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", committed="git:\n  main_branch: main\n",
                                 working="git:\n  main_branch: main\nhooks:\n  disable: [no-git-tag]\n")
    assert run(HOOK, bash("git tag v2", repo)).code == 2


def test_script_contract(feature_repo):
    denied = run_script(HOOK, bash("git tag v2", feature_repo))
    assert denied.returncode == 2 and denied.stdout == "" and "no-git-tag" in denied.stderr
    ok = run_script(HOOK, bash("git tag -l", feature_repo))
    assert (ok.returncode, ok.stdout, ok.stderr) == (0, "", "")
    assert run_script(HOOK, {}, project=feature_repo, stdin="").returncode == 2, "fail closed"


@pytest.mark.parametrize("command", [
    "git -c push.followTags=true push origin feature",
    "git -c PUSH.FOLLOWTAGS=true push origin feature",
    "git -c remote.origin.push='refs/tags/*:refs/tags/*' push origin",
    "echo 'create refs/tags/v7 HEAD' | git update-ref --stdin",
])
def test_config_driven_tag_pushes_and_update_ref_stdin_denied(feature_repo, command):
    assert run(HOOK, bash(command, feature_repo)).code == 2, command


def test_config_driven_tag_pushes_from_repository_config(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    assert run(HOOK, bash("git push origin feature", repo)).code == 0
    git(repo, "config", "remote.origin.push", "refs/tags/*:refs/tags/*")
    assert run(HOOK, bash("git push origin", repo)).code == 2
    git(repo, "config", "--unset-all", "remote.origin.push")
    git(repo, "config", "push.followTags", "true")
    assert run(HOOK, bash("git push origin feature", repo)).code == 2


def test_plain_push_allowed(feature_repo):
    assert run(HOOK, bash("git push origin feature", feature_repo)).code == 0


RELEASE_DENIED = [
    "gh workflow run tld-release.yml -f dry_run=false -f version=9.9.9", "gh workflow run tld-release",
    "gh workflow run .github/workflows/tld-release.yml",
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches -f ref=main",
    "curl -X POST https://api.github.com/repos/o/r/actions/workflows/tld-release.yml/dispatches",
    "gh release edit v1 --tag v3", "gh release edit v1 --tag=v3",
    "gh api -X PATCH repos/o/r/releases/1 -f tag_name=v2", "gh api -X DELETE repos/o/r/releases/1",
]
RELEASE_ALLOWED = [
    "gh workflow run test.yml",
    "gh workflow run tld-git-ops.yml -R org/central -f repo=org/x -f action=delete-branch -f name=old",
    "gh release view v1", "gh release edit v1 --notes hi",
]


@pytest.mark.parametrize("command", RELEASE_DENIED)
def test_release_dispatch_denied_bash(feature_repo, command):
    assert run(HOOK, bash(command, feature_repo)).code == 2, command


@pytest.mark.parametrize("command", RELEASE_ALLOWED)
def test_release_dispatch_allowed_bash(feature_repo, command):
    assert run(HOOK, bash(command, feature_repo)).code == 0, command


def _mcp(feature_repo, **inp):
    return run(HOOK, event("mcp__github__actions_run_trigger", feature_repo, **inp)).code


def test_release_dispatch_denied(feature_repo):
    for command in RELEASE_DENIED:
        assert run(HOOK, bash(command, feature_repo)).code == 2, command
    assert _mcp(feature_repo, method="run_workflow", workflow_id="tld-release.yml", ref="main") == 2
    assert _mcp(feature_repo, method="run_workflow", workflow_id=123456, ref="main") == 2
    assert _mcp(feature_repo, method="run_workflow", workflow_id="123456", ref="main") == 2
    for command in RELEASE_ALLOWED:
        assert run(HOOK, bash(command, feature_repo)).code == 0, command
    assert _mcp(feature_repo, method="run_workflow", workflow_id="test.yml", ref="main") == 0
    assert _mcp(feature_repo, method="run_workflow", workflow_id="tld-git-ops.yml", ref="main") == 0
    assert _mcp(feature_repo, method="cancel_workflow_run", run_id=5) == 0


# --------------------------------------------------------------------------- the guarded release dispatch


def _tld(repo, *args):
    return subprocess.run([sys.executable, str(BIN), "guard", *args], cwd=repo, capture_output=True, text=True, timeout=60)


def _age(repo, seconds):
    marker = repo / ".git" / "tld" / "release-confirm.json"
    data = json.loads(marker.read_text())
    data["written_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds))
    marker.write_text(json.dumps(data))


def _code(repo, command):
    return run(HOOK, bash(command, repo)).code


RUN = "gh workflow run tld-release.yml"
# (command, denied without the marker, denied with the marker for tld-release.yml)
MATRIX = [
    (RUN, True, False),
    (RUN + " -f dry_run=true", False, False),
    (RUN + " -f dry_run=false", True, False),
    (RUN + " -f dry_run=true -f dry_run=false", True, False),
    (RUN + " -f dry_run=false -f dry_run=true", True, False),
    (RUN + " -f dry_run=true -f skip_checks=false", False, False),
    (RUN + " -f dry_run=false -f skip_checks=true", True, True),
    (RUN + " -f dry_run=false -f skip_checks=True", True, True),
    (RUN + " -f dry_run=false -f skip_checks=YES", True, True),
    (RUN + " -f dry_run=false -f skip_checks=1", True, True),
    (RUN + " -f dry_run=true -f skip_checks=true", True, True),
    (RUN + " -f dry_run=false -f skip_checks=false -f skip_checks=true", True, True),
    (RUN + " -f dry_run=False", True, False),
    (RUN + " -f dry_run=0", True, False),
    (RUN + " -f dry_run=1", True, False),
    (RUN + " -f dry_run=''", True, False),
    ("gh workflow run tld-release -f dry_run=false", True, False),
    ("gh workflow run .github/workflows/tld-release.yml -f dry_run=false", True, False),
    (RUN + " --json", True, True),
    (RUN + " -f dry_run=false -F x=@f", True, True),
    (RUN + " -f dry_run=false --field=x=@f", True, True),
]


@pytest.mark.parametrize("command,denied,denied_with_marker", MATRIX)
def test_release_dispatch_matrix(fresh_repo, command, denied, denied_with_marker):
    assert (_code(fresh_repo, command) == 2) is denied, command
    assert _tld(fresh_repo, "allow-release", "tld-release.yml").returncode == 0
    assert (_code(fresh_repo, command) == 2) is denied_with_marker, command


@pytest.mark.parametrize("marker_for", ["release.yml", "other.yml"])
def test_a_marker_for_another_workflow_does_not_open_this_one(fresh_repo, marker_for):
    _tld(fresh_repo, "allow-release", marker_for)
    assert _code(fresh_repo, RUN + " -f dry_run=false") == 2


def test_an_expired_marker_denies(fresh_repo):
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    _age(fresh_repo, 601)
    assert _code(fresh_repo, RUN + " -f dry_run=false") == 2


def test_the_stem_is_covered_by_a_marker_for_the_file(fresh_repo):
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    assert _code(fresh_repo, "gh workflow run tld-release -f dry_run=false") == 0


def test_the_marker_for_the_stem_covers_the_file(fresh_repo):
    _tld(fresh_repo, "allow-release", "tld-release")
    assert _code(fresh_repo, RUN + " -f dry_run=false") == 0


@pytest.mark.parametrize("command", [
    RUN + " --json", RUN + " -f dry_run=true -F body=@f", RUN + " -f dry_run=true --field body=@f",
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches -f inputs[dry_run]=true -F inputs[skip_checks]=@f",
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches --input missing.json",
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches --input -",
    "curl -X POST https://api.github.com/repos/o/r/actions/workflows/tld-release.yml/dispatches",
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld-release.yml/./dispatches",
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld-release.yml//dispatches",
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld%2Drelease.yml/dispatches",
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld-release.yml/{dispatches}",
    "curl -X POST -d '{\"ref\":\"main\",\"inputs\":{\"dry_run\":\"true\"}}' "
    "https://api.github.com/repos/o/r/actions/workflows/tld-release.yml/dispatches",
])
def test_unreadable_release_inputs_deny_even_with_the_marker(fresh_repo, command):
    assert _code(fresh_repo, command) == 2
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    r = run(HOOK, bash(command, fresh_repo))
    assert r.code == 2 and "cannot be read" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", [
    # a bracket key other than inputs[dry_run] / inputs[skip_checks] is a word the shell decides: under nullglob
    # `inputs[a]=b` vanishes (and with a matching file it becomes another word), so the inputs cannot be read
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches "
    "-f inputs[dry_run]=true -f inputs[a]=b",
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches -f inputs[DRY_RUN]=true",
    RUN + " -f dry_run=true -f inputs[a]=b",
])
def test_a_bracket_key_other_than_the_two_release_inputs_denies(fresh_repo, command):
    assert _code(fresh_repo, command) == 2, command
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    r = run(HOOK, bash(command, fresh_repo))
    assert r.code == 2 and "cannot be read" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", [
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld-rele*.yml/dispatches",
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld-releas?.yml/dispatches",
    "curl -X POST -d x api.github.com/repos/o/r/actions/workflows/tld-rele*.yml/dispatches",
    "curl -X POST -d x api.github.com/repos/o/r/actions/workflows/[t]ld-release.yml/dispatches",
    "curl -X POST -d x https://api.github.com/repos/o/r/actions/workflows/tld-release.yml/dispat*",
])
def test_a_globbed_curl_dispatch_word_denies(fresh_repo, command):
    """A glob the shell expands into the real release dispatch URL: the word cannot be checked, so it is denied."""
    r = run(HOOK, bash(command, fresh_repo))
    assert r.code == 2 and "cannot be read" in r.stderr, (command, r.stderr)


def test_a_curl_query_string_question_mark_is_not_a_glob(fresh_repo):
    assert _code(fresh_repo, "curl https://api.github.com/repos/o/r/actions/runs?per_page=1") == 0


@pytest.mark.parametrize("command", [
    "gh workflow run tld-git-ops.yml -f repo=acme/web -f name=chore/release -f dry_run=false",
    "gh workflow run tld-git-ops.yml -f repo=acme/release -f dry_run=false",
    "gh workflow run tld-git-ops.yml --ref chore/release -f dry_run=false",
    "gh workflow run tld-git-ops.yml -f note=x/tld-release -f dry_run=false",
])
def test_the_release_marker_does_not_open_a_git_ops_run_named_by_a_field_value(fresh_repo, command):
    """The workflow is the positional argument, not any word whose last path segment looks like the release one."""
    assert _code(fresh_repo, command) == 2
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    assert _code(fresh_repo, command) == 2, command


@pytest.mark.parametrize("command", [
    'curl -X POST -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/repos/$REPO/actions/workflows/'
    'tld-release.yml/dispatches -d \'{"inputs":{"dry_run":"false"}}\'',
    'curl -X POST "$U" -d x',
    'curl -X POST https://$HOST/repos/o/r/actions/workflows/tld-release.yml/dispatches -d x',
    'curl -X POST https://api.github.com/repos/o/r/actions/workflows/$WF/dispatches -d x',
    'curl -X POST "$API/repos/o/r/git/refs" -d \'{"ref":"refs/tags/v9","sha":"abc"}\'',
])
def test_a_curl_url_built_from_a_variable_is_denied(fresh_repo, command):
    assert _code(fresh_repo, command) == 2, command
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    assert _code(fresh_repo, command) == 2, command


def test_a_curl_get_or_a_dynamic_header_alone_is_fine(fresh_repo):
    assert _code(fresh_repo, 'curl -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/repos/o/r') == 0
    assert _code(fresh_repo, 'curl -X POST -H "Authorization: Bearer $T" -d "$BODY" https://example.org/x') == 0


API = "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches -f ref=main "


@pytest.mark.parametrize("fields,denied,denied_with_marker", [
    ("", True, False),
    ("-f 'inputs[dry_run]=true'", False, False),
    ("-f 'inputs[dry_run]=false'", True, False),
    ("-f 'inputs[dry_run]=true' -f 'inputs[dry_run]=false'", True, False),
    ("-f 'inputs[dry_run]=false' -f 'inputs[skip_checks]=true'", True, True),
    ("-f 'inputs[dry_run]=true' -f 'inputs[skip_checks]=yes'", True, True),
])
def test_release_dispatch_through_gh_api(fresh_repo, fields, denied, denied_with_marker):
    assert (_code(fresh_repo, API + fields) == 2) is denied, fields
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    assert (_code(fresh_repo, API + fields) == 2) is denied_with_marker, fields


@pytest.mark.parametrize("endpoint", ["https://api.github.com//repos/o/c/actions/workflows/tld-git-ops.yml/dispatches",
                                      "repos/o/c/actions/workflows/./tld-git-ops.yml/dispatches#x"])
def test_git_ops_dispatch_endpoint_forms_are_normalised_too(fresh_repo, endpoint):
    assert _code(fresh_repo, f"gh api -X POST {endpoint} -f 'inputs[dry_run]=false'") == 2


def test_a_body_file_is_never_read_for_a_release_dispatch(fresh_repo):
    base = "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches --input "
    (fresh_repo / "dry.json").write_text(json.dumps({"inputs": {"dry_run": "true"}}))
    for name in ("dry.json", "missing.json", "-"):
        assert _code(fresh_repo, base + name) == 2, name
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    for name in ("dry.json", "missing.json", "-"):
        assert _code(fresh_repo, base + name) == 2, name


@pytest.mark.parametrize("command", [
    RUN + " -f dry_run=true --ref -f -f dry_run=false",
    RUN + " -f dry_run=true -r -f -f dry_run=false",
    RUN + " -f dry_run=true -f skip_checks=false --ref -f -f skip_checks=true",
    API + "-f 'inputs[dry_run]=true' -q -f -f 'inputs[dry_run]=false'",
    API + "-f 'inputs[dry_run]=true' --jq -f -f 'inputs[skip_checks]=true'",
    API + "-f 'inputs[dry_run]=true' --hostname -f -f 'inputs[dry_run]=false'",
    API + "-f 'inputs[dry_run]=true' -H -f -f 'inputs[dry_run]=false'",
    RUN + " -f DRY_RUN=false", RUN + " -f dry_run=true -f Skip_Checks=true",
    RUN + " -f dry_run=true -f skip_checks=t", RUN + " -f 'dry_run= true'", RUN + " -f dry_run=TRUE",
    "gh workflow run -f version=9.yml tld-release.yml -f dry_run=false",
    "gh workflow run --ref tld-git-ops.yml tld-release.yml -f dry_run=false",
    "gh workflow run tld-releas{e..e}.yml -f dry_run=false", "gh workflow run $WF.yml -f dry_run=false",
    "gh workflow run tld-releas?.yml -f dry_run=false", "gh workflow run tld-git-op{s..s}.yml -f dry_run=false",
    RUN + " -f dry_run=true ?? ?????????????", RUN + " -f dry_run=true [-]f [d]ry_run=false",
    API + "-f 'inputs[dry_run]=true' ??",
    RUN + " -f dry_run=true -f $X", RUN + ' -f dry_run=true -f "$X"', RUN + " -f dry_run=true -f $(echo dry_run=false)",
    RUN + " -f dry_run=true -f {dry_run=false,x}",
    API + "-f 'inputs[dry_run]=true' -f \"$X\"",
    "gh api -X POST \"$EP\" -f 'inputs[dry_run]=false'",
    "gh api -X POST https://api.github.com//repos/o/r/actions/workflows/tld-release.yml/dispatches -f 'inputs[dry_run]=false'",
    "gh api -X POST https://api.github.com///repos/o/r/actions/workflows/tld-release.yml/dispatches?x=1 -f 'inputs[dry_run]=false'",
    "gh api 'repos/o/r/actions/workflows/tld-release.yml/dispatches#x' -f 'inputs[dry_run]=false'",
    "gh api 'repos/o/r/actions/workflows/tld-release.yml/dispatches?a=1#x' -f 'inputs[dry_run]=false'",
    "gh api -X POST repos/o/r/actions/workflows/tld%2Drelease.yml/dispatches -f 'inputs[dry_run]=false'",
    "gh workflow run --ref a.yml tld-release.yml -f dry_run=false -f skip_checks=true",
    "gh workflow run -r a.yml tld-release.yml -f dry_run=false",
    "gh api -X POST repos/o/r/actions/workflows/./tld-release.yml/dispatches -f 'inputs[dry_run]=false'",
    "gh api -X POST repos/o/r/actions/workflows/x/../tld-release.yml/dispatches -f 'inputs[dry_run]=false'",
    "gh api -X POST repos/o/r/actions/workflows//tld-release.yml/dispatches -f 'inputs[dry_run]=false'",
    "gh api -X POST repos/o/r/actions/workflows/tld-release.yml/dispatches/ -f 'inputs[dry_run]=false'",
    "gh api -X POST https://ghe.example/api/v3/repos/o/r/actions/workflows/tld-release.yml/dispatches -f 'inputs[dry_run]=false'", RUN + " -f dry_run=1", RUN + " -f dry_run=yes",
    API + "-f 'inputs[dry_run]=true' -f 'inputs[SKIP_CHECKS]=true'",
])
def test_option_values_and_odd_spellings_do_not_hide_inputs(fresh_repo, command):
    assert _code(fresh_repo, command) == 2, command
    _tld(fresh_repo, "allow-release", "tld-release.yml")   # a real run is then allowed, skip_checks never
    assert (_code(fresh_repo, command) == 2) is bool(
        "skip_checks" in command.lower() or re.search(r"[${}?*\[\]]", re.sub(r"inputs\[\w+\]", "", command))), command


@pytest.mark.parametrize("command", [
    RUN + " -f dry_run=true --ref main", RUN + " -f dry_run=true -r main -R o/r",
    API + "-f 'inputs[dry_run]=true' -q .x -H 'Accept: x'",
])
def test_option_values_are_skipped_when_reading_inputs(fresh_repo, command):
    assert _code(fresh_repo, command) == 0, command


def _mcp_release(repo, **extra):
    return _mcp(repo, method="run_workflow", workflow_id="tld-release.yml", ref="main", **extra)


def test_release_dispatch_through_mcp(fresh_repo):
    assert _mcp_release(fresh_repo, inputs={"DRY_RUN": 1}) == 2
    assert _mcp_release(fresh_repo, inputs={"dry_run": True}) == 0
    assert _mcp_release(fresh_repo, inputs={"dry_run": "true"}) == 0
    assert _mcp_release(fresh_repo, inputs='{"dry_run": "true"}') == 0
    assert _mcp_release(fresh_repo, inputs={"dry_run": False}) == 2
    assert _mcp_release(fresh_repo) == 2
    assert _mcp_release(fresh_repo, inputs={}) == 2
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    assert _mcp_release(fresh_repo, inputs={"dry_run": False}) == 0
    assert _mcp_release(fresh_repo, inputs={"dry_run": "false"}) == 0
    assert _mcp_release(fresh_repo, inputs={"dry_run": False, "skip_checks": True}) == 2
    assert _mcp_release(fresh_repo, inputs={"dry_run": True, "skip_checks": "yes"}) == 2
    assert _mcp_release(fresh_repo, inputs=["dry_run"]) == 2
    assert _mcp_release(fresh_repo, inputs={"dry_run": False, "skip_checks": ["true"]}) == 2
    assert _mcp_release(fresh_repo, inputs={"dry_run": False, "SKIP_CHECKS": True}) == 2

    assert _mcp_release(fresh_repo, inputs="[1]") == 2
    assert _mcp_release(fresh_repo, inputs="not json") == 2


def test_numeric_ids_and_reruns_stay_denied_with_the_marker(fresh_repo):
    _tld(fresh_repo, "allow-release", "tld-release.yml")
    assert _mcp(fresh_repo, method="run_workflow", workflow_id=123456, ref="main", inputs={"dry_run": True}) == 2
    assert _mcp(fresh_repo, method="run_workflow", workflow_id="123456", ref="main") == 2
    assert _mcp(fresh_repo, method="rerun_workflow_run", run_id=5) == 2
    assert _mcp(fresh_repo, method="rerun_failed_jobs", run_id=5) == 2
    assert _code(fresh_repo, "gh workflow run 123456 -f dry_run=true") == 2
    assert _code(fresh_repo, "git tag v9") == 2


def test_the_profiles_release_workflow_is_guarded_by_name(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/x")
    profile = repo / ".tld" / "toolkit.yaml"
    profile.write_text(profile.read_text() + "release:\n  workflow: release.yml\n  version_files:\n"
                       "    - {path: pyproject.toml, pattern: '^version = \"(.+)\"$'}\n")
    assert _code(repo, "gh workflow run release.yml -f dry_run=false") == 2
    assert _code(repo, "gh workflow run release -f dry_run=false") == 2
    assert _code(repo, "gh workflow run release.yml -f dry_run=true") == 0
    _tld(repo, "allow-release", "release.yml")
    assert _code(repo, "gh workflow run release.yml -f dry_run=false") == 0
    assert _code(repo, "gh workflow run release.yml -f dry_run=false -f skip_checks=true") == 2
    assert _code(repo, "gh workflow run test.yml") == 0
