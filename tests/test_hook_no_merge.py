"""no-merge: no PR merge, no approval, no push to the main branch."""
import pytest

from hooks_helpers import bash, event, git, make_repo, run, run_script

HOOK = "no-merge"

DENIED_GH = [
    "gh pr merge 12", "gh pr merge --auto --squash 12", "gh pr merge 12 --admin --delete-branch",
    "gh pr -R o/r merge 5", "gh pr merge -R o/r 5", "/usr/bin/gh pr merge 1",
    "gh pr review 3 --approve", "gh pr review 3 -a", "gh pr review --approve -b ok", "gh pr review 3 --appr",
    "gh api -X PUT repos/o/r/pulls/5/merge", "gh api repos/o/r/pulls/5/merge -X PUT -f merge_method=squash",
    "gh api --method PUT /repos/o/r/pulls/5/merge", "gh api repos/o/r/pulls/5/merge -f commit_title=x",
    "gh api -XPUT repos/o/r/pulls/5/merge", "gh api --method=PUT repos/o/r/pulls/5/merge",
    "gh api https://api.github.com/repos/o/r/pulls/5/merge -X PUT",
    "gh api repos/o/r/pulls/5/reviews -f event=APPROVE", "gh api repos/o/r/pulls/5/reviews -F event=approve",
    "gh api -X POST repos/o/r/pulls/5/reviews/9/events -f event=APPROVE",
    "gh api graphql -f query='mutation{enablePullRequestAutoMerge(input:{pullRequestId:\"x\"}){clientMutationId}}'",
    "gh api graphql -f query='mutation { mergePullRequest(input:{pullRequestId:\"x\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { addPullRequestReview(input:{pullRequestId:\"x\", event: APPROVE}) { clientMutationId } }'",
    "gh api graphql --input -", "gh api graphql --input missing-query.json",
    "gh api -X POST repos/o/r/merges -f base=main -f head=feature/demo",
    "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
    "gh api -X PUT repos/o/r/contents/a.txt -f message=m -f content=eA==",
    "gh api -X PUT repos/o/r/contents/a.txt -f message=m -f branch=main -f content=eA==",
    "gh alias set m 'pr merge'",
    "curl -X PUT https://api.github.com/repos/o/r/pulls/5/merge",
]
DENIED_BYPASS_FORMS = [
    "echo ok && gh pr merge 1", "true; gh pr merge 1", "ls | gh pr merge 1", "(gh pr merge 1)", "{ gh pr merge 1; }",
    "bash -c 'gh pr merge 1'", "sh -c \"git push origin main\"", "FOO=1 gh pr merge 1",
    "env GH_TOKEN=x gh pr merge 1", "sudo gh pr merge 1", "eval \"gh pr merge 1\"", "echo $(gh pr merge 1)",
    "echo `gh pr merge 1`", "xargs gh pr merge < prs", "cd /tmp && gh pr merge 1", "echo hi\ngh pr merge 1",
    "if true; then gh pr merge 1; fi", "git status && git -C . push origin main", "cat <<EOF\n$(gh pr merge 1)\nEOF",
    "gh pr view 1 && git push --force origin main",
]
DENIED_PUSH_ON_FEATURE = [
    "git push origin main", "git push origin HEAD:main", "git push origin feature/demo:main",
    "git push origin HEAD:refs/heads/main", "git push origin refs/heads/x:refs/heads/main",
    "git push -u origin main", "git push --set-upstream origin main", "git push origin +HEAD:main",
    "git push origin :main", "git push --all", "git push origin --all", "git push --mirror", "git push --branches",
    "git push origin 'refs/heads/*:refs/heads/*'", "git push origin feature/demo main",
    "git -C . push origin main", "git --git-dir=.git push origin main", "git -c user.name=x push origin main",
    "git push --repo=origin main", "git push origin $(git rev-parse HEAD):main", "git push origin main --no-verify",
    "git push --force origin main", "GIT_SSH_COMMAND=ssh git push origin main", "git push -o ci.skip origin main",
    "cd . && git push origin main",
]
DENIED_PUSH_ON_MAIN = ["git push", "git push origin", "git push origin HEAD", "git push -u origin HEAD", "git push origin @"]

ALLOWED = [
    # the known allowed set
    "git push -u origin feature/demo", "git push -u origin HEAD", "git push", "git push origin feature/demo",
    "git push origin plan/my-plan", "git push -u origin review/my-review", "git push -u origin chore/land-20260101-0101",
    "git push origin chore/devflow-land-workflow", "git push origin feature/x:feature/x", "git push origin main:feature/x",
    "git push origin feature/demo--fix-1", "git push origin feature/demo--p1-rev2", 'git push origin "$BRANCH"',
    "git push origin --tags", "git push --follow-tags",
    "git merge origin/main", "git merge --no-ff origin/feature/demo--p1 -m 'Merge plan p1: title'", "git merge --abort",
    "git merge main", "git revert -m 1 HEAD", "git checkout main", "git pull origin main", "git fetch origin main",
    "git rebase --abort", "git log --oneline main", "git diff origin/main...HEAD",
    # gh reads and non-merge writes
    "gh pr create --title x --body y", "gh pr view 3", "gh pr view 3 --json state", "gh pr review 3 --comment -b hi",
    "gh pr review 3 --request-changes -b x", "gh pr ready 3", "gh pr close 3", "gh pr list", "gh pr checks 3",
    "gh api repos/o/r/pulls/5/merge", "gh api repos/o/r/pulls/5", "gh api -X PUT repos/o/r/pulls/5/update-branch",
    "gh api repos/o/r/pulls -f title=x -f head=feature/demo -f base=main",
    "gh api repos/o/r/pulls/5/reviews -f event=COMMENT", "gh api graphql -f query='query{viewer{login}}'",
    "gh api repos/o/r/contents/a.txt", "gh api -X PATCH repos/o/r/git/refs/heads/feature/demo -f sha=abc",
    "gh api -X POST repos/o/r/merges -f base=feature/demo -f head=feature/other",
    "gh run list", "gh workflow run x.yml --ref feature/demo", "gh auth status",
    "curl https://api.github.com/repos/o/r/pulls/5",
    # words that merely mention the forbidden things
    "echo \"gh pr merge is forbidden\"", "git commit -m 'docs: never git push origin main'",
    "git commit -m \"$(cat <<'EOF'\nstop: do not gh pr merge, do not git push origin main\nEOF\n)\"",
    "grep -rn 'gh pr merge' docs", "echo 'git push origin main' > /dev/null", "ls",
    "python3 scripts/tool.py main", "echo $(git rev-parse HEAD)",
]


@pytest.mark.parametrize("command", DENIED_GH + DENIED_BYPASS_FORMS + DENIED_PUSH_ON_FEATURE)
def test_denied(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert r.code == 2, command
    assert r.stderr.startswith("devflow no-merge: blocked")
    assert "human" in r.stderr or "rewrite" in r.stderr.lower() or "pass the query" in r.stderr


@pytest.mark.parametrize("command", DENIED_PUSH_ON_MAIN)
def test_push_of_the_current_branch_is_denied_on_main(main_repo, feature_repo, command):
    assert run(HOOK, bash(command, main_repo)).code == 2
    assert run(HOOK, bash(command, feature_repo)).code == 0, "same command is fine on a feature branch"


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert (r.code, r.stderr) == (0, ""), command


def test_graphql_query_in_a_readable_input_file_is_scanned(feature_repo):
    (feature_repo / "q.json").write_text('{"query": "mutation { mergePullRequest(input: {}) { clientMutationId } }"}')
    assert run(HOOK, bash("gh api graphql --input q.json", feature_repo)).code == 2
    (feature_repo / "ok.json").write_text('{"query": "query { viewer { login } }"}')
    assert run(HOOK, bash("gh api graphql --input ok.json", feature_repo)).code == 0


def test_other_branches_are_allowed_when_the_pushed_ref_is_explicit(main_repo):
    assert run(HOOK, bash("git push -u origin feature/x", main_repo)).code == 0


def test_a_different_main_branch_name(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", "git:\n  main_branch: trunk\n")
    assert run(HOOK, bash("git push origin trunk", repo)).code == 2
    assert run(HOOK, bash("git push origin main", repo)).code == 0


def test_unparseable_commands_fail_closed(feature_repo):
    r = run(HOOK, bash("echo \"unterminated", feature_repo))
    assert r.code == 2 and "cannot parse" in r.stderr


def test_alias_to_a_push_of_main_is_followed(feature_repo):
    git(feature_repo, "config", "alias.ship", "push origin main")
    assert run(HOOK, bash("git ship", feature_repo)).code == 2
    assert run(HOOK, bash("git -c alias.go='push origin main' go", feature_repo)).code == 2
    git(feature_repo, "config", "alias.mergeit", "!gh pr merge")
    assert run(HOOK, bash("git mergeit 3", feature_repo)).code == 2
    git(feature_repo, "config", "--unset", "alias.ship")
    git(feature_repo, "config", "--unset", "alias.mergeit")


# ---- the missing-key rule ------------------------------------------------------------------------
def test_push_without_a_profile_fails_loudly(tmp_path):
    repo = make_repo(tmp_path / "noprofile", "feature/demo", profile=None)
    r = run(HOOK, bash("git push origin feature/demo", repo), project=repo)
    assert r.code == 2
    assert "toolkit.yaml: missing required key 'git.main_branch'" in r.stderr
    assert "no .claude/toolkit.yaml found" in r.stderr


def test_push_with_a_profile_missing_the_key_fails_loudly(tmp_path):
    repo = make_repo(tmp_path / "nokey", "feature/demo", "stacks: []\n")
    assert "missing required key 'git.main_branch'" in run(HOOK, bash("git push", repo)).stderr


def test_broken_yaml_is_reported(tmp_path):
    repo = make_repo(tmp_path / "bad", "feature/demo", "git: [unclosed\n")
    r = run(HOOK, bash("git push", repo))
    assert r.code == 2 and "not valid YAML" in r.stderr


def test_commands_that_need_no_project_fact_work_without_a_profile(tmp_path):
    repo = make_repo(tmp_path / "noprofile2", "feature/demo", profile=None)
    assert run(HOOK, bash("ls && git status", repo), project=repo).code == 0
    assert run(HOOK, bash("gh pr merge 1", repo), project=repo).code == 2


def test_disable_flag(tmp_path):
    repo = make_repo(tmp_path / "off", "feature/demo", "git:\n  main_branch: main\nhooks:\n  disable: [no-merge]\n")
    assert run(HOOK, bash("gh pr merge 1", repo)).code == 0
    assert run("no-force-push", bash("git push -f", repo)).code == 2, "other hooks stay on"


# ---- GitHub MCP tools ----------------------------------------------------------------------------
@pytest.mark.parametrize("tool, args", [
    ("mcp__github__merge_pull_request", {"pullNumber": 3}),
    ("mcp__github__enable_pr_auto_merge", {"pullNumber": 3}),
    ("mcp__plugin_x_github__merge_pull_request", {"pullNumber": 3}),
    ("mcp__github__pull_request_review_write", {"method": "create", "event": "APPROVE"}),
    ("mcp__github__pull_request_review_write", {"method": "submit_pending", "event": "approve"}),
    ("mcp__github__push_files", {"branch": "main", "files": []}),
    ("mcp__github__create_or_update_file", {"branch": "main", "path": "a"}),
    ("mcp__github__delete_file", {"branch": "main", "path": "a"}),
])
def test_mcp_denied(feature_repo, tool, args):
    assert run(HOOK, event(tool, feature_repo, **args)).code == 2


@pytest.mark.parametrize("tool, args", [
    ("mcp__github__create_branch", {"branch": "feature/demo", "from_branch": "main"}),
    ("mcp__github__create_pull_request", {"base": "main", "head": "feature/demo"}),
    ("mcp__github__update_pull_request", {"pullNumber": 3, "reviewers": ["x"]}),
    ("mcp__github__update_pull_request_branch", {"pullNumber": 3}),
    ("mcp__github__actions_run_trigger", {"method": "run_workflow"}),
    ("mcp__github__add_issue_comment", {"issue_number": 3}),
    ("mcp__github__pull_request_review_write", {"method": "create", "event": "COMMENT"}),
    ("mcp__github__push_files", {"branch": "feature/demo", "files": []}),
    ("mcp__github__create_or_update_file", {"branch": "plan/x", "path": "a"}),
    ("Read", {"file_path": "x"}),
])
def test_mcp_and_other_tools_allowed(feature_repo, tool, args):
    assert run(HOOK, event(tool, feature_repo, **args)).code == 0


# ---- the exit-code contract on the real script ---------------------------------------------------
def test_script_contract(feature_repo):
    denied = run_script(HOOK, bash("gh pr merge 1", feature_repo))
    assert denied.returncode == 2 and denied.stdout == ""
    assert "devflow no-merge: blocked" in denied.stderr
    allowed = run_script(HOOK, bash("git push -u origin feature/demo", feature_repo))
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, "", "")
    assert run_script(HOOK, {}, project=feature_repo, stdin="not json").returncode == 2, "fail closed"
    assert run_script(HOOK, {}, project=feature_repo, stdin="[]").returncode == 2


# ---- destination of a push without a refspec (SEC-H1), GraphQL -F @file (SEC-H7) ------------------
def _with_origin(tmp_path, branch):
    """A repo on `branch`, cut from origin/main, with a real bare origin that has main (and `feature`)."""
    repo = make_repo(tmp_path / "w", branch)
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "push", "-q", "origin", f"{branch}:feature")
    git(repo, "fetch", "-q", "origin")
    return repo


UP_MAIN = ("origin/main", "git push")
CFG_DENIED = [
    ("origin/main", ["push.default=upstream"], "git push"),
    ("origin/main", [], "git -c push.default=upstream push"),
    ("origin/main", [], "git -c remote.origin.push=HEAD:refs/heads/main push origin"),
    ("origin/main", [], "git -c remote.origin.mirror=true push origin"),
    ("origin/main", [], "git -c REMOTE.origin.push=refs/heads/x:refs/heads/main push"),
    ("origin/main", ["remote.origin.push=HEAD:refs/heads/main"], "git push"),
    ("origin/main", ["remote.origin.mirror=true"], "git push"),
    ("origin/main", ["push.default=matching"], "git push"),
    ("origin/main", ["push.default=tracking"], "git push"),
]
CFG_ALLOWED = [
    ("origin/main", ["push.default=simple"], "git push -u origin feature"),
    ("origin/main", ["push.default=simple"], "git push"),
    ("origin/feature", ["push.default=upstream"], "git push"),
    ("origin/main", ["push.default=current"], "git push"),
    ("origin/main", ["push.default=nothing"], "git push"),
    ("origin/main", ["remote.origin.push=HEAD:refs/heads/feature"], "git push"),
]


@pytest.mark.parametrize("upstream, config, command", CFG_DENIED + CFG_ALLOWED,
                         ids=[f"{'deny' if r in CFG_DENIED else 'allow'}-{i}" for i, r in
                              enumerate(CFG_DENIED + CFG_ALLOWED)])
def test_upstream_and_config_refspec_to_main_denied(tmp_path, upstream, config, command):
    repo = _with_origin(tmp_path, "feature/demo")
    git(repo, "branch", f"--set-upstream-to={upstream}")
    for item in config:
        key, _, value = item.partition("=")
        git(repo, "config", "--add", key, value)
    expected = 2 if (upstream, config, command) in CFG_DENIED else 0
    assert run(HOOK, bash(command, repo)).code == expected, command


def test_graphql_field_file_is_scanned(feature_repo):
    (feature_repo / "q.graphql").write_text("mutation { mergePullRequest(input: {}) { clientMutationId } }")
    (feature_repo / "ok.graphql").write_text("query { viewer { login } }")
    assert run(HOOK, bash("gh api graphql -F query=@q.graphql", feature_repo)).code == 2
    assert run(HOOK, bash("gh api graphql --field query=@q.graphql", feature_repo)).code == 2
    assert run(HOOK, bash("gh api graphql -F query=@-", feature_repo)).code == 2
    assert run(HOOK, bash("gh api graphql -F query=@missing.graphql", feature_repo)).code == 2
    assert run(HOOK, bash("gh api graphql -F query=@ok.graphql", feature_repo)).code == 0
    assert run(HOOK, bash("gh api graphql -f query=@x", feature_repo)).code == 0, "-f is raw text"


@pytest.mark.parametrize("tool, args", [
    ("mcp__github__create_or_update_file", {"path": "a"}),
    ("mcp__github__create_or_update_file", {"path": "a", "branch": ""}),
    ("mcp__github__create_or_update_file", {"path": "a", "branch": "refs/heads/main"}),
    ("mcp__github__create_or_update_file", {"path": "a", "branch": "heads/main"}),
    ("mcp__github__push_files", {"files": []}),
    ("mcp__github__delete_file", {"path": "a"}),
])
def test_mcp_denied_without_or_with_qualified_main_branch(feature_repo, tool, args):
    assert run(HOOK, event(tool, feature_repo, **args)).code == 2


@pytest.mark.parametrize("command", [
    "gh api -X POST repos/o/r/merge-upstream -f branch=main",
    "gh api -X POST repos/o/r/merge-upstream",
    "gh api -X POST repos/o/r/branches/main/rename -f new_name=old",
    "gh api repos/o/r/branches/main/rename -X PUT -f new_name=old",
    "gh repo sync o/r --branch main --force",
    "gh repo sync o/r -b main",
    "gh repo sync o/r --force",
])
def test_gh_routes_to_main_denied(feature_repo, command):
    assert run(HOOK, bash(command, feature_repo)).code == 2, command


@pytest.mark.parametrize("command", [
    "gh api -X POST repos/o/r/merge-upstream -f branch=feature/demo",
    "gh api -X POST repos/o/r/branches/feature/rename -f new_name=x",
    "gh repo sync o/r --branch feature/demo", "gh repo sync o/r",
])
def test_gh_routes_allowed(feature_repo, command):
    assert run(HOOK, bash(command, feature_repo)).code == 0, command
