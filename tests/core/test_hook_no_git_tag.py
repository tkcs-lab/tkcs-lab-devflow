"""no-git-tag: no creating, moving, deleting or pushing tags; reading stays allowed."""
import pytest

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
    "bin/tld ops upstream-sync plan --upstream-url https://github.com/o/r.git --version-file v.txt --pattern '^v'",
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
    "gh release edit v1 --tag v3", "gh release edit v1 --tag=v3",
    "gh api -X PATCH repos/o/r/releases/1 -f tag_name=v2", "gh api -X DELETE repos/o/r/releases/1",
]
RELEASE_ALLOWED = [
    "gh workflow run test.yml",
    "gh workflow run tld-git-ops.yml -R org/central -f repo=org/x -f action=create-tag -f name=v1.0.0",
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
