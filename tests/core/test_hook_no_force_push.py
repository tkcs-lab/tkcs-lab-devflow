"""no-force-push: no force push, no branch deletion by push."""
import pytest

from hooks_helpers import bash, git, make_repo, make_repo_with_origin, run, run_script

HOOK = "no-force-push"

DENIED = [
    # force flags, every spelling
    "git push --force", "git push -f", "git push origin -f feature/demo", "git push -fu origin feature/demo",
    "git push -uf origin feature/demo", "git push --force origin feature/demo", "git push origin feature/demo --force",
    "git push --force-with-lease", "git push --force-with-lease=feature/demo:abc123 origin feature/demo",
    "git push --force-if-includes", "git push --force-with-lease --force-if-includes origin x",
    "git push --forc", "git push --force-w", "git push -v -f", "git push -o ci.skip -f origin x",
    # a leading + on the refspec
    "git push origin +feature/demo", "git push origin +HEAD:feature/demo", "git push origin x +y:z",
    # deleting a branch by push
    "git push origin :old-branch", "git push origin :refs/heads/old", "git push --delete origin old",
    "git push origin --delete old", "git push -d origin old", "git push --del origin old", "git push --prune origin",
    "git push --mirror", "git push origin --delete feature/demo",
    # indirection and chaining
    "git -C . push -f", "git -c push.default=current push -f", "cd . && git push -f", "echo ok; git push -f",
    "bash -c 'git push -f origin x'", "sh -c \"git push origin +x\"", "(git push -f)", "FOO=1 git push -f",
    "env A=b git push --force", "sudo git push -f", "eval git push -f", "echo $(git push -f)", "git status | git push -f",
    "xargs git push -f", "if true; then git push -f; fi", "true &&\ngit push -f", "/usr/bin/git push -f",
    "git push -f # not a comment for git",
    # the API routes
    "gh api -X DELETE repos/o/r/git/refs/heads/old", "gh api --method DELETE /repos/o/r/git/refs/heads/feature/x",
    "gh pr close 3 --delete-branch", "gh pr close 3 -d", "gh pr close 3 --delete",
]
ALLOWED = [
    "git push", "git push -u origin feature/demo", "git push --set-upstream origin feature/demo", "git push origin HEAD",
    "git push origin feature/demo:feature/other", "git push --dry-run origin x", "git push -n origin x", "git push -v",
    "git push -q", "git push -o ci.skip origin x", "git push -o -f origin x", "git push --push-option=-f origin x",
    "git push --follow-tags", "git push origin --tags", "git push --atomic origin x", "git push --no-verify origin x",
    "git push origin 'feature/force-fix'", "git push origin feature/delete-old-code", "git push origin plan/prune-cache",
    "git push --repo=origin", "git push --signed=if-asked origin x", "git push --recurse-submodules=check",
    "git branch -d old", "git branch -D old", "git fetch --prune", "git remote prune origin", "git merge --abort",
    "git revert -m 1 HEAD", "git merge origin/main", "git reset --hard origin/feature/demo",
    "git log --format=%f", "gh pr close 3", "gh pr merge --help", "gh api repos/o/r/git/refs/heads/x",
    "gh api -X PATCH repos/o/r/pulls/3 -f state=closed", "gh pr view 3 -d",
    "echo 'git push -f'", "git commit -m 'never git push --force'", "grep -rn 'push --force' docs",
    "git commit -m \"$(cat <<'EOF'\nfix: no more git push -f here\nEOF\n)\"", "ls", 'git push origin "$BRANCH"',
]


@pytest.mark.parametrize("command", DENIED)
def test_denied(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert r.code == 2, command
    assert r.stderr.startswith("tld no-force-push: blocked")
    assert "Push normally" in r.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert (r.code, r.stderr) == (0, ""), command


def test_alias_is_followed(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    git(repo, "config", "alias.yolo", "push --force")
    git(repo, "config", "alias.shove", "!git push -f")
    assert run(HOOK, bash("git yolo origin x", repo)).code == 2
    assert run(HOOK, bash("git shove origin x", repo)).code == 2
    assert run(HOOK, bash("git -c alias.p='push -f' p", repo)).code == 2
    git(repo, "config", "alias.safe", "push -u origin")
    assert run(HOOK, bash("git safe feature/demo", repo)).code == 0


def test_unparseable_commands_fail_closed(feature_repo):
    r = run(HOOK, bash("git push -f 'origin", feature_repo))
    assert r.code == 2 and "cannot parse" in r.stderr


def test_disable_flag(tmp_path):
    # S1: disable only counts when committed on the remote main branch, not in the working tree.
    repo = make_repo_with_origin(tmp_path / "r", committed="git:\n  main_branch: main\nhooks:\n  disable: [no-force-push]\n")
    assert run(HOOK, bash("git push -f", repo)).code == 0


def test_disable_in_working_tree_only_is_ignored(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", committed="git:\n  main_branch: main\n",
                                 working="git:\n  main_branch: main\nhooks:\n  disable: [no-force-push]\n")
    assert run(HOOK, bash("git push -f", repo)).code == 2


def test_needs_no_profile(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", profile=None)
    assert run(HOOK, bash("git push -f", repo), project=repo).code == 2
    assert run(HOOK, bash("git push -u origin feature/demo", repo), project=repo).code == 0


def test_script_contract(feature_repo):
    denied = run_script(HOOK, bash("git push --force origin feature/demo", feature_repo))
    assert denied.returncode == 2 and denied.stdout == "" and "no-force-push" in denied.stderr
    ok = run_script(HOOK, bash("git push -u origin feature/demo", feature_repo))
    assert (ok.returncode, ok.stdout, ok.stderr) == (0, "", "")
    assert run_script(HOOK, {}, project=feature_repo, stdin="{").returncode == 2, "fail closed"


@pytest.mark.parametrize("command", [
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p -f origin HEAD:main",
    "P=push git --config-env alias.p=P p -f origin HEAD:main",
    "git send-pack --force ../remote.git HEAD:refs/heads/main",
])
def test_env_config_aliases_and_send_pack_denied(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert r.code == 2, command
    assert r.stderr.startswith("tld no-force-push: blocked")
    if "send-pack" not in command:
        r = run("no-merge", bash(command.replace(" -f", ""), feature_repo))
        assert r.code == 2, command


def test_dynamic_word_in_push_option_position_denied(feature_repo):
    r = run(HOOK, bash("git push $(echo --force) origin feature", feature_repo))
    assert r.code == 2
    assert "only known at run time" in r.stderr
    r = run(HOOK, bash("git push origin $(git branch --show-current)", feature_repo))
    assert (r.code, r.stderr) == (0, "")


def test_slow_git_config_still_denies(tmp_path):
    """SEC-H14: a config include that blocks (a FIFO) must not turn a lookup timeout into an allow."""
    import os
    import time

    fifo = tmp_path / "blocker"
    os.mkfifo(fifo)
    try:
        feature = make_repo(tmp_path / "feat", "feature/demo")
        with open(feature / ".git" / "config", "a") as f:
            f.write(f"[alias]\n\tpf = push -f\n[include]\n\tpath = {fifo}\n")
        start = time.monotonic()
        r = run_script(HOOK, bash("git pf origin feature", feature))
        assert r.returncode == 2 and time.monotonic() - start < 18, r.stderr
        on_main = make_repo(tmp_path / "main", "main")
        with open(on_main / ".git" / "config", "a") as f:
            f.write(f"[include]\n\tpath = {fifo}\n")
        start = time.monotonic()
        r = run_script("no-merge", bash("git push", on_main))
        assert r.returncode == 2 and time.monotonic() - start < 18, r.stderr
    finally:
        fifo.unlink()
