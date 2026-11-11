"""protect-paths: edits to paths the profile lists are denied (Write/Edit and visible Bash writes)."""
import os

import pytest

from hooks_helpers import bash, event, make_repo, make_repo_with_origin, run, run_script

HOOK = "protect-paths"
PROTECTED_FILES = [".tld/toolkit.yaml", ".env", ".env.local", ".env.production", "sub/.env", "package-lock.json",
                   "web/package-lock.json", "uv.lock", "deep/er/Cargo.lock", "go.sum", ".github/workflows/ci.yml",
                   ".github/workflows/sub/x.yml", "./.env", "docs/../.env"]
ALLOWED_FILES = ["src/app.py", "README.md", ".env.example", ".env.sample", ".env.template", ".env.dist",
                 ".github/workflows/tld-land.yml", ".github/workflows/tld-release.yml", "docs/lock.md",
                 "lockfile.txt", ".github/CODEOWNERS", ".github/dependabot.yml", "src/tld/templates/toolkit.yaml",
                 "sub/.tld/toolkit.yaml", ".envrc.md", "environment.txt", "go.mod", "package.json"]


@pytest.mark.parametrize("path", PROTECTED_FILES)
@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_file_tools_are_denied(feature_repo, tool, path):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    for form in (path, str(feature_repo / path)):
        r = run(HOOK, event(tool, feature_repo, **{key: form}))
        assert r.code == 2, (tool, form)
        assert "protected path" in r.stderr and "hooks.protect_paths_allow" in r.stderr


@pytest.mark.parametrize("path", ALLOWED_FILES)
def test_file_tools_allowed(feature_repo, path):
    assert run(HOOK, event("Write", feature_repo, file_path=path, content="x")).code == 0


def test_paths_outside_the_project_are_not_this_hooks_business(feature_repo, tmp_path):
    assert run(HOOK, event("Write", feature_repo, file_path=str(tmp_path / "other" / ".env"), content="x")).code == 0


def test_a_symlink_to_a_protected_file_is_followed(fresh_repo):
    (fresh_repo / ".env").write_text("A=1\n")
    os.symlink(".env", fresh_repo / "innocent.txt")
    assert run(HOOK, event("Write", fresh_repo, file_path="innocent.txt", content="x")).code == 2


def test_messages_say_what_to_do_instead(feature_repo):
    expected = {".tld/toolkit.yaml": "changed by people", ".env": ".env.example", "uv.lock": "lock command",
                ".github/workflows/ci.yml": "owner"}
    for path, words in expected.items():
        assert words in run(HOOK, event("Write", feature_repo, file_path=path, content="x")).stderr, path


DENIED_BASH = [
    "echo x > .env", "echo x >> .env.local", "echo x 2> .env", "echo hi &> uv.lock", "echo x >| .env", "cat a | tee .env",
    "tee -a uv.lock < a", "sed -i 's/a/b/' package-lock.json", "sed -i.bak -e 's/a/b/' uv.lock",
    "sed -n -i -e p go.sum", "sed --in-place 's/a/b/' .env", "perl -pi -e 's/a/b/' .env", "perl -i.bak -pe 's/a/b/' uv.lock",
    "cp x .env", "cp -f x .github/workflows/ci.yml", "cp x .github/workflows/", "cp -t .github/workflows x.yml",
    "mv x uv.lock", "mv .env .env.bak", "mv uv.lock /tmp/old.lock", "install -m 600 x .env", "rm .env", "rm -f uv.lock",
    "rm -rf .env package-lock.json", "unlink .env", "touch .env", "truncate -s 0 .env", "dd if=x of=.env", "git rm .env",
    "git mv .env .env.old", "ln -sf x .env", "bash -c 'echo x > .env'", "cd sub && echo x > ../.env", "cd . && rm uv.lock",
    "echo ok; echo x > .github/workflows/ci.yml", "echo $(echo x > .env)", "sudo rm .env", "FOO=1 tee .env",
    "echo x > ./.env", "echo x > docs/../.env",
    "ln .env notes2", "ln -s .env notes && echo B=2 >> notes", "ln -s .github/workflows wf && echo 'on: push' > wf/ci.yml",
    "echo B=2 | tee .{env,tmp}", "git checkout origin/x -- .tld/toolkit.yaml",
    "git restore --source origin/x .tld/toolkit.yaml", "git restore --source=origin/x -S -W .env",
    "git checkout -- .env", "git config alias.p push", "git config remote.origin.push HEAD:main",
    "git config --add include.path ../x", "git config --unset branch.main.remote", "git config -e",
    "git config Alias.p push",
]
ALLOWED_BASH = [
    "cat .env", "grep x .env", "echo x > out.txt", "cp .env /tmp/backup", "cp .env.example /tmp/x",
    "sed -i 's/a/b/' src/app.py", "sed 's/a/b/' .env", "sed -n p .env", "sed -n 's/a/b/p' .env > out.txt",
    "rm -rf build", "touch src/x", "git add .env", "git rm src/x.py", "echo x > /dev/null", "ls 2>&1 | tee out.log",
    "ls > files.txt", "echo \">\" .env", "echo 'x > .env'", "git commit -m 'edit .env > nothing'", "npm install", "uv lock",
    "python3 -m pip install x", "echo x > .env.example", "cp x .github/workflows/tld-land.yml", "diff .env other",
    "mv x y", "cat <<EOF > notes.md\n.env\nEOF", "rm .envrc.md", "ls .github/workflows", "grep -r x .github/workflows",
    "echo $(cat .env)", "bash -c 'cat .env'", "git status", 'echo x > "$OUT"',
    "git config user.name x", "git config --get alias.p", "git config --list", "git config alias.p",
    "git checkout feature", "git restore src/a.py", "git checkout -- src/a.py", "echo x > a.{txt,md}",
]


@pytest.mark.parametrize("command", DENIED_BASH)
def test_bash_writes_denied(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert r.code == 2, command
    assert "protected path" in r.stderr


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_bash_allowed(feature_repo, command):
    r = run(HOOK, bash(command, feature_repo))
    assert (r.code, r.stderr) == (0, ""), command


def test_globs_expand_against_the_file_system(fresh_repo):
    (fresh_repo / ".env").write_text("A=1\n")
    assert run(HOOK, bash("rm .env*", fresh_repo)).code == 2
    assert run(HOOK, bash("rm nothing-*", fresh_repo)).code == 0


def test_profile_can_replace_the_list_and_add_exceptions(tmp_path):
    # S1: the protect lists are read from the remote main branch (the trusted copy), so commit them there.
    repo = make_repo_with_origin(tmp_path / "r",
                                 committed="git:\n  main_branch: main\nhooks:\n  protect_paths: ['secrets/**', 'Makefile']\n"
                                 "  protect_paths_allow: ['secrets/public.txt']\n")
    ev = lambda p: event("Write", repo, file_path=p, content="x")  # noqa: E731
    assert run(HOOK, ev("secrets/a/b.txt")).code == 2
    assert run(HOOK, ev("Makefile")).code == 2
    assert run(HOOK, ev("secrets/public.txt")).code == 0
    assert run(HOOK, ev(".env")).code == 0, "a list in the profile replaces the default list"


def test_exceptions_extend_the_default(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r",
                                 committed="git:\n  main_branch: main\nhooks:\n  protect_paths_allow: ['uv.lock']\n")
    assert run(HOOK, event("Write", repo, file_path="uv.lock", content="x")).code == 0
    assert run(HOOK, event("Write", repo, file_path=".env", content="x")).code == 2


def test_working_tree_cannot_widen_the_allow_list(tmp_path):
    # Without a trusted copy an allow list from the working tree is ignored (it never weakens protection).
    repo = make_repo(tmp_path / "r", "feature/demo",
                     "git:\n  main_branch: main\nhooks:\n  protect_paths_allow: ['.env']\n")
    assert run(HOOK, event("Write", repo, file_path=".env", content="x")).code == 2


def test_a_malformed_hooks_section_is_reported(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", "git:\n  main_branch: main\nhooks:\n  protect_paths: nope\n")
    r = run(HOOK, event("Write", repo, file_path="a", content="x"))
    assert r.code == 2 and "'hooks.protect_paths' must be a list" in r.stderr


def test_works_without_a_profile_using_the_defaults(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", profile=None)
    assert run(HOOK, event("Write", repo, file_path=".env", content="x"), project=repo).code == 2
    assert run(HOOK, event("Write", repo, file_path="a.py", content="x"), project=repo).code == 0


def test_disable_flag(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", committed="git:\n  main_branch: main\nhooks:\n  disable: [protect-paths]\n")
    assert run(HOOK, event("Write", repo, file_path=".env", content="x")).code == 0


def test_script_contract(feature_repo):
    denied = run_script(HOOK, event("Write", feature_repo, file_path=".env", content="x"))
    assert denied.returncode == 2 and denied.stdout == "" and "tld protect-paths: blocked" in denied.stderr
    assert run_script(HOOK, bash("echo x > .env", feature_repo)).returncode == 2
    ok = run_script(HOOK, event("Write", feature_repo, file_path="a.py", content="x"))
    assert (ok.returncode, ok.stdout, ok.stderr) == (0, "", "")
    assert run_script(HOOK, {}, project=feature_repo, stdin="oops").returncode == 1


@pytest.mark.parametrize("path", [".git/config", ".claude/settings.json", ".claude/settings.local.json",
                                  ".git/hooks/pre-push"])
def test_guardrail_files_are_always_protected(tmp_path, monkeypatch, path):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    repo = make_repo(tmp_path / "r", "feature/demo",
                     "git:\n  main_branch: main\nhooks:\n  protect_paths: []\n  protect_paths_allow: ['**']\n")
    assert run(HOOK, event("Write", repo, file_path=path, content="x")).code == 2
    assert run(HOOK, bash(f"echo x > {path}", repo)).code == 2
    assert run(HOOK, event("Write", repo, file_path="a.py", content="x")).code == 0


def test_the_plugin_root_is_protected(feature_repo, tmp_path, monkeypatch):
    root = tmp_path / "plugin"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    assert run(HOOK, event("Write", feature_repo, file_path=str(root / "hooks" / "x.py"), content="x")).code == 2
    assert run(HOOK, bash(f"echo x > {root}/hooks/x.py", feature_repo)).code == 2
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "")
    assert run(HOOK, event("Write", feature_repo, file_path=str(root / "x.py"), content="x")).code == 0


def test_a_hard_link_made_earlier_is_recognised_by_inode(fresh_repo):
    (fresh_repo / ".env").write_text("A=1\n")
    os.link(fresh_repo / ".env", fresh_repo / "notes2")
    assert run(HOOK, bash("echo C=3 >> notes2", fresh_repo)).code == 2
    (fresh_repo / "plain.txt").write_text("x")
    assert run(HOOK, bash("echo C=3 >> plain.txt", fresh_repo)).code == 0


def test_matcher_units():
    from tld.guard.protect_paths import matches
    assert matches("**/secret.txt", "secret.txt")
    assert matches("a/**/b", "a/b")
    assert matches("?.env", "x.env")
    assert not matches("?.env", "xy.env")


def test_unparseable_commands_are_allowed(feature_repo):
    assert run(HOOK, bash("echo 'unterminated > .env", feature_repo)).code == 0
