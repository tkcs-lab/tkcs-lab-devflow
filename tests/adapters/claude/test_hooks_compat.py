"""Compatibility: every git / gh operation the existing commands document must pass the hooks.

Three layers:
  1. COMPAT lists, per command, the concrete operations and the phrase in the command file that
     documents each one (the test fails when the file stops saying it, so the table cannot rot).
  2. A sweep takes every `git ...` / `gh ...` code span in the commands and skills, fills in the
     <placeholders>, and runs it through the hooks.
  3. The GitHub MCP tools the commands call, and the files they write.
"""
import re

import pytest

from conftest import CLAUDE
from hooks_helpers import BASH_GUARDS, bash, event, run

COMMANDS = CLAUDE / "commands"

# (concrete command run in a checkout on a feature branch, phrase the command file contains)
COMPAT = {
    "implement": [
        ("git fetch origin plan/foo", "git fetch origin <ref>"),
        ("git show FETCH_HEAD:docs/foo-plan.md", "git show FETCH_HEAD:<path>"),
        ("git checkout -b feature/demo origin/plan/foo", "create it from `<ref>`"),
        ("git merge origin/main", "merge `origin/<main>` into it"),
        ("git push -u origin feature/demo", "git push -u origin <feature_branch>"),
        ("git push origin feature/demo", "push merge commits to it"),
        ("git log --grep='Plan-Phase: foo/p1'", "git log --grep"),
        ("git fetch origin feature/demo--p1 feature/demo", "git fetch origin <phase branch> <feature_branch>"),
        ("git diff abc1234...origin/feature/demo--p1", "git diff <base>...origin/<phase branch>"),
        ("git checkout feature/demo && git merge --no-ff origin/feature/demo--p1 -m 'Merge foo p1: title'",
         "git merge --no-ff origin/<phase branch>"),
        ("git merge --abort", "git merge --abort"),
        ("git revert -m 1 abc1234", "git revert -m 1"),
        ("git revert -m 1 abc1234 && git push origin feature/demo", "revert the merge commit"),
        ("git checkout -b feature/demo--p1-rev1 feature/demo", "<feature_branch>--<phase id>-rev<n>"),
        ("git push -u origin feature/demo--fix-1", "<feature_branch>--fix-<n>"),
        ("git merge origin/main && git push origin feature/demo", "merge `origin/<main>` into the feature branch once more, push"),
        ("git diff origin/main...HEAD", "git diff origin/<main>...HEAD"),
        ("git status --porcelain", "feature branch"),
    ],
    "setup": [
        ("git checkout -b chore/toolkit-profile origin/main", "chore/toolkit-profile"),
        ("git push -u origin chore/toolkit-profile", "git push -u origin chore/toolkit-profile"),
        ("git add .tld/toolkit.yaml", "commit only `.tld/toolkit.yaml`"),
    ],
    "land": [
        ("git fetch origin main", "Fetch `origin/<main>`"),
        ("git checkout -b chore/land-20260101-0101 origin/main", "chore/land-<yyyymmdd-hhmm>"),
        ("git merge --no-ff origin/feature/a", "git merge --no-ff"),
        ("git merge --no-ff origin/feature/b -m 'land #2'", "merge the pull request heads in order"),
        ("git merge --abort", "abort that merge"),
        ("git push -u origin chore/land-20260101-0101", "git push -u origin chore/land-<yyyymmdd-hhmm>"),
        ("git push origin feature/b", "push normally"),
        ("git checkout -b chore/tld-land-workflow origin/main", "chore/tld-land-workflow"),
        ("git push -u origin chore/tld-land-workflow", "commit it on `chore/tld-land-workflow`"),
        ("git add .github/workflows/tld-land.yml && git commit -m 'ci: add the land workflow'", "tld-land.yml"),
    ],
    "deps": [
        ("git checkout dependabot/npm_and_yarn/lodash-4.17.21", "check out its branch"),
        ("git push origin dependabot/npm_and_yarn/lodash-4.17.21", "normal push"),
        ("git checkout -b chore/deps-npm-20260101 origin/main", "chore/deps-<ecosystem>-<yyyymmdd>"),
        ("git push -u origin chore/deps-npm-20260101", "push it and open a pull request"),
        ("git commit -am 'chore(deps): bump lodash'", "commit the fix onto it"),
    ],
    "docs": [
        ("git checkout -b chore/docs-init-20260101 origin/main", "git checkout -b chore/docs-init-<yyyymmdd> origin/<main>"),
        ("git push -u origin chore/docs-init-20260101", "git push -u origin chore/docs-init-<yyyymmdd>"),
        ("git checkout -b chore/docs-tidy-20260101 origin/main", "git checkout -b chore/docs-tidy-<yyyymmdd> origin/<main>"),
        ("git push -u origin chore/docs-tidy-20260101", "git push -u origin chore/docs-tidy-<yyyymmdd>"),
        ("git mv docs/design.md docs/architecture/design.md", "ops docs-index move"),
    ],
    "upstream": [
        ("git ls-remote --tags https://github.com/o/r.git", "git ls-remote --tags"),
        ("git fetch origin main", "git fetch origin <main>"),
        ('"${CLAUDE_PLUGIN_ROOT}/bin/tld" ops upstream-sync plan --upstream-url https://github.com/o/r.git '
         "--version-file UPSTREAM --pattern '^v[0-9.]+$'", "ops upstream-sync plan"),
        ('"${CLAUDE_PLUGIN_ROOT}/bin/tld" ops upstream-sync prepare --upstream-url https://github.com/o/r.git '
         "--version-file UPSTREAM --tag v1.2.3 --branch chore/upstream-v1-2-3 --base origin/main", "ops upstream-sync prepare"),
        ("git commit -m 'Sync o/r v1.2.2 to v1.2.3'", "Sync <upstream.repo> <old> to <new>"),
        ("git push -u origin chore/upstream-v1-2-3", "git push -u origin <branch>"),
        ("git fetch --tags", "Release tags only"),
        ("git describe --tags --abbrev=0", "Release tags only"),
    ],
    "review": [
        ("git fetch origin main", "git fetch origin <main>"),
        ("git log -p --all", "git log -p --all"),
        ("git log -p --all -S 'AKIA'", "secret patterns"),
        ("git push -u origin review/foo", "git push -u origin review/<slug>"),
        ("git fetch origin review/foo", "git fetch origin <ref>"),
        ("git show FETCH_HEAD:docs/foo-review.md", "git show FETCH_HEAD:<path>"),
        ("git add docs/foo-review.md && git commit -m 'review: foo' && git push origin review/foo", "commit and push"),
    ],
    "make-plan": [
        ("git fetch origin review/foo", "git fetch origin <ref>"),
        ("git show FETCH_HEAD:docs/foo-review.md", "git show FETCH_HEAD:<path>"),
        ("git fetch origin main && git checkout -b plan/foo origin/main", "git checkout -b plan/<slug>"),
        ("git push -u origin plan/foo", "git push -u origin plan/<slug>"),
        ("git add docs/foo-plan.md docs/foo-plan-manual-steps.html && git commit -m 'plan: foo' && git push origin plan/foo",
         "Commit, push and hand over"),
    ],
    "dod": [
        ("git diff --stat origin/main...HEAD", "git diff --stat origin/<main>...HEAD"),
        ("git diff --name-only origin/main...HEAD", "any changed file"),
    ],
}


def normalise(text):
    return " ".join(text.split())


@pytest.mark.parametrize("command_name", sorted(COMPAT))
def test_documented_operations_pass_every_hook(feature_repo, command_name):
    doc = normalise((COMMANDS / f"{command_name}.md").read_text())
    for operation, phrase in COMPAT[command_name]:
        assert normalise(phrase) in doc, f"{command_name}.md no longer says {phrase!r}: update COMPAT"
        for hook in BASH_GUARDS:
            r = run(hook, bash(operation, feature_repo))
            assert r.code == 0, f"/{command_name}: {operation!r} is blocked by {hook}: {r.stderr}"


def test_every_command_file_is_covered():
    assert set(COMPAT) | {"board"} == {p.stem for p in COMMANDS.glob("*.md")}, "a new command needs COMPAT rows"


def test_the_known_allowed_set(feature_repo):
    """The set the task names explicitly."""
    for op in ("git checkout -b feature/new-thing", "git push -u origin feature/new-thing", "git push origin feature/new-thing",
               "git push -u origin plan/x", "git push -u origin review/x", "git push -u origin chore/x",
               "git merge origin/main", "git merge --no-ff origin/feature/demo--p1", "git revert -m 1 HEAD", "git merge --abort"):
        for hook in BASH_GUARDS:
            assert run(hook, bash(op, feature_repo)).code == 0, (op, hook)


# ---- the sweep ----------------------------------------------------------------------------------
PLACEHOLDERS = {
    "<path>": "docs/foo-plan.md", "<ref>": "plan/foo", "<main>": "main", "<slug>": "foo", "<feature_branch>": "feature/demo",
    "<branch>": "feature/demo", "<phase branch>": "feature/demo--p1", "<base>": "abc1234",
    "<yyyymmdd-hhmm>": "20260101-0101", "<yyyymmdd>": "20260101", "<owner>/<repo>": "o/r",
}
SPAN = re.compile(r"`((?:git|gh) [^`]+)`")


def spans():
    out = []
    for path in sorted(list(COMMANDS.glob("*.md")) + list(CLAUDE.glob("skills/*/SKILL.md"))):
        for m in SPAN.finditer(path.read_text()):
            text = m.group(1)
            for key, value in PLACEHOLDERS.items():
                text = text.replace(key, value)
            assert "<" not in text, f"{path.name}: unfilled placeholder in {text!r}: extend PLACEHOLDERS"
            out.append((path.name, text))
    return out


def test_the_sweep_finds_the_spans():
    found = {t for _, t in spans()}
    assert "git push -u origin feature/demo" in found and "git merge --abort" in found and len(found) >= 15


@pytest.mark.parametrize("source, operation", spans())
def test_every_code_span_in_the_commands_and_skills_is_allowed(feature_repo, source, operation):
    for hook in BASH_GUARDS:
        r = run(hook, bash(operation, feature_repo))
        assert r.code == 0, f"{source}: `{operation}` is blocked by {hook}: {r.stderr}"


# ---- MCP tools and files the commands use ---------------------------------------------------------
MCP = [
    ("mcp__github__create_branch", "create_branch", {"branch": "feature/demo", "from_branch": "plan/foo"}),
    ("mcp__github__create_pull_request", "Open **one** pull request", {"head": "feature/demo", "base": "main"}),
    ("mcp__github__update_pull_request", "update_pull_request", {"pullNumber": 4, "reviewers": ["owner"]}),
    ("mcp__github__update_pull_request_branch", "update_pull_request_branch", {"pullNumber": 4}),
    ("mcp__github__actions_run_trigger", "actions_run_trigger", {"method": "run_workflow", "ref": "feature/demo"}),
    ("mcp__github__add_issue_comment", "tracking_issue", {"issue_number": 3, "body": "Phase p1 merged."}),
]


@pytest.mark.parametrize("tool, phrase, args", MCP)
def test_github_mcp_calls_the_commands_make_are_allowed(feature_repo, tool, phrase, args):
    docs = normalise(" ".join(p.read_text() for p in COMMANDS.glob("*.md")))
    assert phrase in docs, phrase
    assert run("no-merge", event(tool, feature_repo, **args)).code == 0


def test_files_the_commands_write_are_allowed(feature_repo):
    for path in ("docs/foo-plan.md", "docs/foo-plan-manual-steps.html", "docs/foo-review.md", "docs/foo-review-decisions.html",
                 "CHANGELOG.md"):
        for hook in ("protect-paths", "secret-scan"):
            r = run(hook, event("Write", feature_repo, file_path=path, content="plain text\n"))
            assert r.code == 0, (path, hook, r.stderr)


def test_the_land_install_step_writes_its_workflow_only_with_the_marker(fresh_repo):
    """S13: /land step 4 runs `tld guard allow-workflow-install tld-land.yml` before it writes the file."""
    import subprocess
    import sys
    from conftest import BIN
    text = " ".join((COMMANDS / "land.md").read_text().split())
    assert '"${CLAUDE_PLUGIN_ROOT}/bin/tld" guard allow-workflow-install tld-land.yml' in text
    assert '"${CLAUDE_PLUGIN_ROOT}/bin/tld" guard end-allow' in text
    path = ".github/workflows/tld-land.yml"
    assert run("protect-paths", event("Write", fresh_repo, file_path=path, content="x\n")).code == 2
    subprocess.run([sys.executable, str(BIN), "guard", "allow-workflow-install", "tld-land.yml"], cwd=fresh_repo, check=True,
                   capture_output=True)
    assert run("protect-paths", event("Write", fresh_repo, file_path=path, content="x\n")).code == 0
    assert run("protect-paths", event("Write", fresh_repo, file_path=".github/workflows/tld-release.yml", content="x\n")).code == 2
    subprocess.run([sys.executable, str(BIN), "guard", "end-allow"], cwd=fresh_repo, check=True, capture_output=True)
    assert run("protect-paths", event("Write", fresh_repo, file_path=path, content="x\n")).code == 2
