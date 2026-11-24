"""`tld ops deps-prepare`: groups of dependency updates combined onto one branch, with real git and a bare origin."""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import tld_cmd
from hooks_helpers import git, make_repo_with_origin

from tld.guard import trust
from tld.ops import deps_checks, deps_prepare

pytestmark = pytest.mark.slow

SHA_A, SHA_B = "a" * 40, "b" * 40
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
WEB = ("GitHub", "noreply@github.com")
EVE = ("Eve", "eve@example.test")
ME = ("Me", "me@example.test")

HEAD = """\
docs:
  must_read: []
git:
  main_branch: main
  branch_pattern: "<type>/<kebab-case>"
verify:
  fast: ["true"]
  dod: ["true"]
stacks: []
"""
PROFILE = HEAD + """\
deps:
  cooldown_days: 3
  time_budget_minutes: 90
  lock_freshness:
    - when: ["requirements.in"]
      run: "touch ran"
      lockfiles: ["requirements.lock"]
    - when: ["web/package.json"]
      run: "npm install"
      lockfiles: ["web/package-lock.json"]
hooks:
  protect_paths: [".tld/toolkit.yaml", ".env", ".env.*", "*.lock", "secrets/**", ".github/workflows/**"]
"""
REQ_IN = "".join(f"{n}==1.0\n# --\n" for n in ("alpha", "beta", "gamma"))
CI = f"""---
name: ci
jobs:
  t:
    steps:
      - uses: actions/checkout@v4
      - run: echo hi
      - uses: actions/cache@{SHA_A} # v3
      - run: echo bye
"""
BASE_FILES = {
    "requirements.in": REQ_IN, "requirements.lock": "alpha 1.0\nbeta 1.0\n",
    "web/package.json": "{}\n", "web/package-lock.json": "{\"v\": 1}\n",
    "pkg/a.txt": "a1\n", "pkg/b.txt": "b1\n", "pkg/c.txt": "c1\n", "pkg/clean.txt": "v1\n", "pkg/run.sh": "echo\n",
    ".github/workflows/ci.yml": CI, ".github/workflows/other.yml": "name: other\n",
    ".github/workflows/tld-land.yml": CI,
}


class Link(str):
    """A symbolic link to this target."""


def sh(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


def build(tmp_path, profile=PROFILE, files=None, name="repo"):
    """A repo on feature/demo whose origin/main holds BASE_FILES and `profile`."""
    repo = make_repo_with_origin(tmp_path / name, committed=profile)
    git(repo, "checkout", "-q", "main")
    for path, text in {**BASE_FILES, **(files or {})}.items():
        write(repo, path, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-B", "feature/demo", "main")
    return repo


def write(repo, path, text):
    target = Path(repo) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    if isinstance(text, Link):
        os.symlink(str(text), target)
    else:
        target.write_text(text)


def commit(repo, parent, changes, who=BOT, committer=WEB, cacheinfo=(), chmod=(), msg="bump"):
    """A commit on `parent` with `changes` ({path: text, None deletes, Link: symlink}); returns its sha."""
    sh(repo, "checkout", "-q", "--detach", parent)
    for path, text in changes.items():
        if text is None:
            sh(repo, "rm", "-q", "-f", path)
        else:
            write(repo, path, text)
    sh(repo, "add", "-A")
    for mode, sha, path in cacheinfo:
        sh(repo, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
    for path in chmod:
        sh(repo, "update-index", "--chmod=+x", path)
    env = {"GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1],
           "GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1]}
    sh(repo, "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", msg, env=env)
    sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "-f", "feature/demo")
    return sha


def group(repo, name, changes, parent="origin/main", ref=None, **kw):
    """A Dependabot-like remote-tracking branch; returns the ref as given to --group."""
    sha = commit(repo, parent, changes, **kw)
    sh(repo, "update-ref", f"refs/remotes/{ref or 'origin/dependabot/' + name}", sha)
    return ref or f"origin/dependabot/{name}"


def clean(repo, parent="origin/main"):
    return group(repo, "clean", {"pkg/clean.txt": "v2\n"}, parent)


def run(repo, *args, branch="chore/deps-test", base="origin/main"):
    proc = subprocess.run(tld_cmd("ops", "deps-prepare", f"--base={base}", f"--branch={branch}", *args),
                          cwd=repo, capture_output=True, text=True)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc, out


def groups(*refs):
    return [f"--group={r}" for r in refs]


def by_ref(out):
    return {g["ref"]: g for g in out["groups"]}


def branch_files(repo, branch="chore/deps-test", base="origin/main"):
    return set(sh(repo, "diff", "--name-only", base, branch).splitlines())


def assert_left_out(repo, proc, out, ref, reason, file=None, clean_ref="origin/dependabot/clean", leaked=()):
    assert proc.returncode == 0, proc.stderr
    g = by_ref(out)
    assert g[ref]["state"] == "left_out" and g[ref]["reason"] == reason and g[ref]["file"] == file, g[ref]
    assert g[clean_ref]["state"] == "applied"
    assert sh(repo, "rev-list", "--count", "origin/main..chore/deps-test") == "1"
    assert branch_files(repo) == {"pkg/clean.txt"}
    for path in leaked:
        assert path not in branch_files(repo)


def test_groups_applied_lockfiles_left_for_the_lock_command(tmp_path):
    repo = build(tmp_path)
    g1 = group(repo, "web", {"web/package.json": '{"a": 1}\n', "web/package-lock.json": "{\"v\": 2}\n"})
    g2 = group(repo, "pip", {"requirements.in": REQ_IN.replace("alpha==1.0", "alpha==2.0"),
                             "requirements.lock": "alpha 2.0\n"})
    proc, out = run(repo, *groups(g1, g2))
    assert proc.returncode == 0, proc.stderr
    assert [g["state"] for g in out["groups"]] == ["applied", "applied"]
    assert sh(repo, "rev-list", "--count", "origin/main..chore/deps-test") == "2"
    assert sh(repo, "rev-parse", "--abbrev-ref", "HEAD") == "chore/deps-test"
    assert [c["index"] for c in out["lock_commands"]] == [0, 1]       # profile order, each once
    assert out["lock_commands"][0]["run"] == "touch ran"
    assert branch_files(repo) == {"requirements.in", "web/package.json"}
    for lock in ("requirements.lock", "web/package-lock.json"):
        assert sh(repo, "rev-parse", f"chore/deps-test:{lock}") == sh(repo, "rev-parse", f"origin/main:{lock}")
    assert sh(repo, "status", "--porcelain") == ""
    subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"], check=True)
    assert out["base_sha"] == sh(repo, "rev-parse", "origin/main")


@pytest.mark.parametrize("path,old,new", [
    ("package-lock.json", "1\n", "2\n"), ("web/package-lock.json", "1\n", "2\n"), ("go.sum", "1\n", "2\n"),
    ("pnpm-lock.yaml", "1\n", "2\n"), ("npm-shrinkwrap.json", "1\n", "2\n"), ("requirements.txt", "1\n", "2\n"),
    ("go.sum", "1\n", None), ("npm-shrinkwrap.json", None, "2\n"),
], ids=["root-npm", "web-npm", "go-sum", "pnpm", "shrinkwrap", "profile-glob-only", "deleted", "added"])
def test_what_counts_as_a_lockfile(tmp_path, path, old, new):
    entry = ('deps:\n  cooldown_days: 3\n  time_budget_minutes: 90\n  lock_freshness:\n    - when: ["pkg/a.txt"]\n      run: "x"\n'
             '      lockfiles: ["package-lock.json", "go.sum", "pnpm-lock.yaml", "npm-shrinkwrap.json",'
             ' "requirements.txt"]\n')
    repo = build(tmp_path, profile=HEAD + entry,
                 files={path: old} if old is not None else None)
    g = group(repo, "g", {"pkg/a.txt": "a2\n", path: new})
    proc, out = run(repo, *groups(g))
    assert proc.returncode == 0, proc.stderr
    assert out["groups"][0]["state"] == "applied" and path in out["groups"][0]["lockfiles"]
    assert sh(repo, "ls-tree", "chore/deps-test", "--", path) == sh(repo, "ls-tree", "origin/main", "--", path)
    assert "pkg/a.txt" in branch_files(repo)
    assert out["groups"][0]["files"] == sorted(["pkg/a.txt", path])


def test_lock_entries_from_defaults_and_explicit_values_alike(tmp_path, monkeypatch, capsys):
    entry = {"when": ["requirements.in"], "run": "make lock", "lockfiles": ["requirements.lock"]}
    written = {**yaml.safe_load(HEAD), "deps": {"cooldown_days": 3, "time_budget_minutes": 90,
                                                "lock_freshness": [entry]}}
    assert deps_prepare.lock_entries(written) == [entry]
    assert deps_prepare.lock_entries(yaml.safe_load(HEAD)) == []
    monkeypatch.setattr(deps_prepare, "validate", lambda profile, root: ([], [], {"deps": {"lock_freshness": [entry]}}))
    assert deps_prepare.lock_entries(yaml.safe_load(HEAD)) == [entry]
    repo = build(tmp_path, profile=HEAD)
    g = group(repo, "pip", {"requirements.in": REQ_IN.replace("alpha==1.0", "alpha==2.0"),
                            "requirements.lock": "alpha 2.0\n"})
    monkeypatch.chdir(repo)
    assert deps_prepare.main(["--base=origin/main", "--branch=chore/deps-x", f"--group={g}"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["lock_commands"] == [{"index": 0, "run": "make lock", "when": ["requirements.in"],
                                     "lockfiles": ["requirements.lock"]}]
    assert out["groups"][0]["lockfiles"] == ["requirements.lock"]


@pytest.mark.parametrize("case", ["side-branch", "no-trusted-copy"])
def test_the_profile_comes_from_the_remote_default_branch(tmp_path, case):
    repo = build(tmp_path)
    g = group(repo, "g", {"pkg/a.txt": "a2\n"})
    if case == "side-branch":
        sh(repo, "branch", "side", sh(repo, "rev-parse", "origin/main"))
        sh(repo, "checkout", "-q", "side")
        write(repo, "pkg/new.txt", "x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "local only")
        proc, out = run(repo, *groups(g), base="side")
        assert proc.returncode == 1 and out is None
        assert proc.stderr.startswith("deps: --base side is not the remote default branch (")
    else:
        trust.trusted(str(repo))
        sh(repo, "update-ref", "refs/tld/trusted", sh(repo, "rev-parse", g))
        proc, out = run(repo, *groups(g))
        assert proc.returncode == 1 and out is None
        assert proc.stderr.startswith("deps: no trusted copy of the profile (")
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", "refs/heads/chore/deps-test"],
                          capture_output=True).returncode != 0


def test_a_base_that_is_the_current_remote_head_is_accepted(tmp_path):
    repo = build(tmp_path)
    g = group(repo, "g", {"pkg/a.txt": "a2\n"})
    cached = trust.trusted(str(repo))
    assert cached.available and cached.sha == sh(repo, "rev-parse", "origin/main")
    sh(repo, "checkout", "-q", "main")
    write(repo, "pkg/other.txt", "x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main moves on")
    git(repo, "push", "-q", "origin", "main")
    sh(repo, "checkout", "-q", "feature/demo")
    proc, out = run(repo, *groups(g))
    assert proc.returncode == 0, proc.stderr
    assert out["base_sha"] == sh(repo, "rev-parse", "origin/main") != cached.sha
    # a changed profile on the new head: refused
    sh(repo, "checkout", "-q", "main")
    write(repo, ".tld/toolkit.yaml", PROFILE + "# changed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "profile changes")
    git(repo, "push", "-q", "origin", "main")
    sh(repo, "checkout", "-q", "feature/demo")
    proc, out = run(repo, *groups(g), branch="chore/deps-two")
    assert proc.returncode == 1 and out is None
    assert proc.stderr.startswith("deps: the profile changed on the default branch since the trusted copy was read")


def test_local_profile_does_not_choose_lock_commands(tmp_path):
    repo = build(tmp_path)
    evil = (HEAD + 'deps:\n  cooldown_days: 3\n  time_budget_minutes: 90\n  lock_freshness:\n'
            '    - when: ["**"]\n      run: "touch pwned"\n      lockfiles: ["*"]\n')
    write(repo, ".tld/toolkit.yaml", evil)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "evil profile")
    secret = group(repo, "secret", {"secrets/k.txt": "key\n"})
    pip = group(repo, "pip", {"requirements.in": REQ_IN.replace("alpha==1.0", "alpha==2.0"),
                              "requirements.lock": "alpha 2.0\n"})
    proc, out = run(repo, *groups(secret, pip))
    assert proc.returncode == 0, proc.stderr
    g = by_ref(out)
    assert g[secret]["reason"] == "protected-path" and g[secret]["file"] == "secrets/k.txt"
    assert g[pip]["state"] == "applied"
    assert [c["run"] for c in out["lock_commands"]] == ["touch ran"]
    assert not (repo / "pwned").exists()


def test_local_origin_main_moved_is_refused(tmp_path):
    repo = build(tmp_path)
    g = group(repo, "g", {"pkg/a.txt": "a2\n"})
    forged = commit(repo, "origin/main", {".tld/toolkit.yaml": HEAD + "# forged\n"}, who=ME, committer=ME)
    sh(repo, "update-ref", "refs/remotes/origin/main", forged)
    proc, out = run(repo, *groups(g))
    assert proc.returncode == 1 and out is None
    assert "is not the remote default branch" in proc.stderr
    assert sh(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/demo"


def test_a_lockfile_no_entry_covers(tmp_path):
    repo = build(tmp_path, files={"other/Cargo.lock": "1\n"})
    bad = group(repo, "cargo", {"pkg/a.txt": "a2\n", "other/Cargo.lock": "2\n"})
    proc, out = run(repo, *groups(bad, clean(repo)))
    assert_left_out(repo, proc, out, bad, "lock-uncovered", "other/Cargo.lock", leaked=["pkg/a.txt"])
    assert set(by_ref(out)[bad]["lockfiles"]) == {"other/Cargo.lock"}


def test_only_lockfiles_changed(tmp_path):
    repo = build(tmp_path)
    bad = group(repo, "lock", {"requirements.lock": "alpha 9.9\n"})
    proc, out = run(repo, *groups(bad, clean(repo)))
    assert_left_out(repo, proc, out, bad, "lockfile-only", None, leaked=["requirements.lock"])
    assert {g["reason"] for g in out["groups"]} - {None} <= set(deps_checks.PREPARE_REASONS)


@pytest.mark.parametrize("who,committer,ref,expected", [
    (EVE, WEB, "origin/dependabot/x", "not-bot-authored"),
    (BOT, EVE, "origin/dependabot/x", "not-bot-authored"),
    (EVE, WEB, "refs/remotes/origin/dependabot/x", "not-bot-authored"),
    (EVE, EVE, "origin/tld-deps/x", "not-bot-authored"),
    (("dependabot[bot]", "eve@example.test"), WEB, "origin/dependabot/x", "not-bot-authored"),
    (BOT, WEB, "origin/dependabot/x", None),
    (BOT, BOT, "origin/dependabot/x", None),
    (("dependabot[bot]", "dependabot[bot]"), BOT, "origin/dependabot/x", None),
], ids=["foreign-author", "foreign-committer", "full-name", "work-looking-remote-name", "bot-name-foreign-email",
        "github-committed", "bot-committed", "bot-short-email"])
def test_a_ref_without_the_bot_identity(tmp_path, who, committer, ref, expected):
    repo = build(tmp_path)
    given = ref
    sha = commit(repo, "origin/main", {"pkg/a.txt": "a2\n"}, who=who, committer=committer)
    sh(repo, "update-ref", ref if ref.startswith("refs/") else f"refs/remotes/{ref}", sha)
    proc, out = run(repo, *groups(given, clean(repo)))
    if expected:
        assert_left_out(repo, proc, out, given, expected, None, leaked=["pkg/a.txt"])
        assert {g["reason"] for g in out["groups"]} - {None} <= set(deps_checks.PREPARE_REASONS)
    else:
        assert proc.returncode == 0 and by_ref(out)[given]["state"] == "applied"
        assert branch_files(repo) == {"pkg/a.txt", "pkg/clean.txt"}


def bump(text, old, new):
    assert old in text
    return text.replace(old, new)


WF_CASES = {
    "ref-move": (lambda t: bump(t, "actions/checkout@v4", "actions/checkout@v5"), [("actions/checkout", "v4", "v5")]),
    "sha-to-sha": (lambda t: bump(bump(t, SHA_A, SHA_B), "# v3", "# v4"), [("actions/cache", SHA_A, SHA_B)]),
    "run-line": (lambda t: bump(t, "echo hi", "echo pwned"), None),
    "other-action": (lambda t: bump(t, "actions/checkout@v4", "actions/other@v4"), None),
    "local-action": (lambda t: bump(t, "actions/checkout@v4", "./x@y"), None),
    "sha-to-tag": (lambda t: bump(t, f"actions/cache@{SHA_A}", "actions/cache@v4"), None),
    "extra-uses": (lambda t: t + "      - uses: actions/x@v1\n", None),
    "indent": (lambda t: bump(t, "      - uses: actions/checkout@v4", "        - uses: actions/checkout@v5"), None),
    "comment-only": (lambda t: bump(t, "# v3", "# v4"), None),
    "removed-dashes": (lambda t: bump(bump(t, "---\n", ""), "actions/checkout@v4", "actions/checkout@v5"), None),
    "added-plus": (lambda t: bump(bump(t, "echo bye\n", "echo bye\n++x\n"), "actions/checkout@v4",
                                  "actions/checkout@v5"), None),
    "hash-suffix": (lambda t: bump(t, "actions/checkout@v4", "actions/checkout@v5#x"), None),
}


@pytest.mark.parametrize("case", sorted(WF_CASES))
def test_workflow_files_only_as_action_ref_moves(tmp_path, case):
    edit, moves = WF_CASES[case]
    repo = build(tmp_path)
    ci = ".github/workflows/ci.yml"
    g = group(repo, "wf", {ci: edit(CI)})
    proc, out = run(repo, *groups(g, clean(repo)))
    if moves is not None:
        assert proc.returncode == 0, proc.stderr
        assert by_ref(out)[g]["state"] == "applied"
        assert by_ref(out)[g]["workflow_moves"] == [{"action": a, "from": o, "to": n} for a, o, n in moves]
        assert sh(repo, "show", f"chore/deps-test:{ci}") == edit(CI).strip()
    else:
        assert_left_out(repo, proc, out, g, "workflow-not-a-bump", ci, leaked=[ci])


@pytest.mark.parametrize("case", ["added", "deleted"])
def test_workflow_file_added_or_deleted_is_not_a_bump(tmp_path, case):
    repo = build(tmp_path)
    path, change = (".github/workflows/new.yml", "name: new\n") if case == "added" else (
        ".github/workflows/other.yml", None)
    g = group(repo, "wf", {path: change})
    proc, out = run(repo, *groups(g, clean(repo)))
    assert_left_out(repo, proc, out, g, "workflow-not-a-bump", path, leaked=[path])


def test_workflow_from_a_work_branch_needs_a_bot_ref(tmp_path):
    repo = build(tmp_path)
    ci = ".github/workflows/ci.yml"
    bot = group(repo, "wf", {ci: bump(CI, "actions/checkout@v4", "actions/checkout@v5")})
    foreign = group(repo, "foreign", {ci: bump(CI, "actions/checkout@v4", "actions/checkout@v5")}, who=EVE,
                    committer=EVE)
    work_sha = sh(repo, "rev-parse", bot)
    sh(repo, "update-ref", "refs/heads/tld-deps/1", work_sha)
    ok = clean(repo)
    for extra in ([], [f"--bot-ref={foreign}"]):
        proc, out = run(repo, *groups("tld-deps/1", ok), *extra)
        assert_left_out(repo, proc, out, "tld-deps/1", "workflow-not-a-bump", ci, leaked=[ci])
        sh(repo, "checkout", "-q", "feature/demo")
        sh(repo, "branch", "-D", "chore/deps-test")
    proc, out = run(repo, *groups("tld-deps/1", ok), f"--bot-ref={bot}")
    assert proc.returncode == 0, proc.stderr
    assert by_ref(out)["tld-deps/1"]["state"] == "applied"
    assert out["bot_refs"] == [{"ref": bot, "state": "ok"}]
    sh(repo, "checkout", "-q", "feature/demo")
    sh(repo, "branch", "-D", "chore/deps-test")
    # the bot commit plus a fix commit that moves the same action once more: not what Dependabot made
    fixed = commit(repo, work_sha, {ci: bump(CI, "actions/checkout@v4", "actions/checkout@v6")}, who=ME,
                   committer=ME, msg="fix")
    sh(repo, "update-ref", "refs/heads/tld-deps/1", fixed)
    proc, out = run(repo, *groups("tld-deps/1", ok), f"--bot-ref={bot}")
    assert_left_out(repo, proc, out, "tld-deps/1", "workflow-not-a-bump", ci, leaked=[ci])
    assert out["bot_refs"] == [{"ref": bot, "state": "ok"}]


@pytest.mark.parametrize("path,text,applied", [
    (".tld/toolkit.yaml", PROFILE + "# x\n", False), (".env", "K=1\n", False), (".env.production", "K=1\n", False),
    (".mcp.json", "{}\n", False), (".claude/settings.local.json", "{}\n", False), (".claude/hooks/x", "x\n", False),
    ("secrets/k.txt", "k\n", False), (".github/workflows/tld-land.yml", None, False), (".env.example", "K=\n", True),
], ids=["profile", "env", "env-production", "mcp", "claude-settings", "claude-hooks", "custom-entry", "guarded-workflow",
        "env-example"])
def test_other_protected_paths(tmp_path, path, text, applied):
    repo = build(tmp_path)
    if text is None:   # a bot bump of a workflow file the toolkit installs
        text = bump(CI, "actions/checkout@v4", "actions/checkout@v5")
    g = group(repo, "p", {path: text})
    proc, out = run(repo, *groups(g, clean(repo)))
    if applied:
        assert proc.returncode == 0 and by_ref(out)[g]["state"] == "applied"
        assert branch_files(repo) == {path, "pkg/clean.txt"}
    else:
        assert_left_out(repo, proc, out, g, "protected-path", path, leaked=[path])


@pytest.mark.parametrize("kind", ["symlink-added", "gitlink", "mode-change", "file-to-symlink"])
def test_unexpected_kinds_of_change(tmp_path, kind):
    repo = build(tmp_path)
    kw, path = {}, "pkg/link"
    changes = {"pkg/link": Link("../outside")}
    if kind == "gitlink":
        changes, kw = {}, {"cacheinfo": [("160000", "1" * 40, "pkg/sub")]}
        path = "pkg/sub"
    elif kind == "mode-change":
        changes, kw, path = {}, {"chmod": ["pkg/run.sh"]}, "pkg/run.sh"
    elif kind == "file-to-symlink":
        changes, path = {"pkg/a.txt": Link("b.txt")}, "pkg/a.txt"
    g = group(repo, "u", changes, **kw)
    proc, out = run(repo, *groups(g, clean(repo)))
    assert_left_out(repo, proc, out, g, "unexpected-change", path, leaked=[path])


def test_a_group_that_does_not_apply(tmp_path):
    repo = build(tmp_path)
    g1 = group(repo, "g1", {"pkg/a.txt": "one\n"})
    g2 = group(repo, "g2", {"pkg/a.txt": "two\n"})
    g3 = clean(repo)
    proc, out = run(repo, *groups(g1, g2, g3))
    assert proc.returncode == 0, proc.stderr
    g = by_ref(out)
    assert (g[g1]["state"], g[g2]["state"], g[g2]["reason"], g[g2]["file"], g[g3]["state"]) == (
        "applied", "left_out", "does-not-apply", None, "applied")
    assert sh(repo, "rev-list", "--count", "origin/main..chore/deps-test") == "2"
    assert sh(repo, "show", "chore/deps-test:pkg/a.txt") == "one"
    assert {x["reason"] for x in out["groups"]} - {None} <= set(deps_checks.PREPARE_REASONS)


def test_main_moved_with_the_same_lockfile_changed_still_applies(tmp_path):
    repo = build(tmp_path)
    bot = group(repo, "pip", {"requirements.in": REQ_IN.replace("gamma==1.0", "gamma==3.0"),
                              "requirements.lock": "alpha 1.0\nbeta 1.0\ngamma 3.0\n"})
    sh(repo, "checkout", "-q", "main")
    write(repo, "requirements.in", REQ_IN.replace("alpha==1.0", "alpha==2.0"))
    write(repo, "requirements.lock", "alpha 2.0\nbeta 1.0\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main bumps alpha")
    git(repo, "push", "-q", "origin", "main")
    sh(repo, "checkout", "-q", "feature/demo")
    proc, out = run(repo, *groups(bot))
    assert proc.returncode == 0, proc.stderr
    assert out["groups"][0]["state"] == "applied"
    merged = sh(repo, "show", "chore/deps-test:requirements.in")
    assert "alpha==2.0" in merged and "gamma==3.0" in merged
    assert sh(repo, "rev-parse", "chore/deps-test:requirements.lock") == sh(repo, "rev-parse", "origin/main:requirements.lock")
    assert sh(repo, "status", "--porcelain") == ""
    subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"], check=True)


def test_nothing_applied(tmp_path):
    repo = build(tmp_path)
    bad = group(repo, "lock", {"requirements.lock": "alpha 9.9\n"})
    before = (sh(repo, "rev-parse", "HEAD"), sh(repo, "rev-parse", "--abbrev-ref", "HEAD"))
    proc, out = run(repo, *groups(bad))
    assert proc.returncode == 3 and out["groups"][0]["reason"] == "lockfile-only" and out["lock_commands"] == []
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", "refs/heads/chore/deps-test"],
                          capture_output=True).returncode != 0
    assert (sh(repo, "rev-parse", "HEAD"), sh(repo, "rev-parse", "--abbrev-ref", "HEAD")) == before
    assert sh(repo, "status", "--porcelain") == ""


def _snapshot(repo):
    return sh(repo, "rev-parse", "HEAD"), sh(repo, "rev-parse", "--abbrev-ref", "HEAD")


@pytest.mark.parametrize("case", [
    "missing-group", "bad:-x", "bad:a..b", "bad:a@{1}", "bad:x.lock", "bad:a//b", "bad:a/", "bad-ref-and-dirty",
    "dirty", "branch-local", "branch-on-origin", "origin-unreachable", "unknown-ref", "no-trusted-copy",
    "no-profile", "invalid-profile", "base-not-default", "untracked-in-the-way"])
def test_errors(tmp_path, case):
    repo = build(tmp_path, profile={"no-profile": None,
                                    "invalid-profile": HEAD + "deps:\n  cooldown_days: x\n  time_budget_minutes: 90\n"}.get(
                                        case, PROFILE))
    g = group(repo, "g", {"pkg/new.txt": "n\n"})
    args, expect, code = [f"--group={g}"], None, 1
    if case == "missing-group":
        proc = subprocess.run(tld_cmd("ops", "deps-prepare", "--base=origin/main", "--branch=b"), cwd=repo,
                              capture_output=True, text=True)
        assert proc.returncode == 2 and proc.stdout == ""
        return
    if case.startswith("bad:"):
        value = case[4:]
        args, expect = [f"--group={value}"], f"deps: not a plain ref name: {value}"
    elif case == "bad-ref-and-dirty":
        write(repo, "pkg/a.txt", "dirty\n")
        args, expect = ["--group=a..b"], "deps: not a plain ref name: a..b"
    elif case == "dirty":
        write(repo, "pkg/a.txt", "dirty\n")
        expect = "deps: the working tree has uncommitted changes"
    elif case == "branch-local":
        sh(repo, "branch", "chore/deps-test", "origin/main")
        expect = "deps: branch chore/deps-test already exists"
    elif case == "branch-on-origin":
        sh(repo, "push", "-q", "origin", "origin/main:refs/heads/chore/deps-test")
        expect = "deps: branch chore/deps-test already exists"
    elif case == "origin-unreachable":
        sh(repo, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
        expect = "deps: cannot reach origin"
    elif case == "unknown-ref":
        args, expect = ["--group=origin/dependabot/nope"], "deps: unknown ref: origin/dependabot/nope"
    elif case == "no-trusted-copy":
        trust.trusted(str(repo))
        sh(repo, "update-ref", "refs/tld/trusted", sh(repo, "rev-parse", g))
        expect = "deps: no trusted copy of the profile"
    elif case == "no-profile":
        expect = "deps: the remote default branch has no .tld/toolkit.yaml"
    elif case == "invalid-profile":
        expect = "deps: the trusted profile is invalid: "
    elif case == "base-not-default":
        sh(repo, "branch", "side", g)
        expect = "deps: --base side is not the remote default branch ("
    elif case == "untracked-in-the-way":
        write(repo, "pkg/new.txt", "mine\n")
    before = _snapshot(repo)
    base = "side" if case == "base-not-default" else "origin/main"
    proc, out = run(repo, *args, base=base)
    assert proc.stdout == ""
    assert proc.returncode == code, proc.stderr
    if case == "untracked-in-the-way":
        assert proc.stderr.startswith("deps: cannot check out chore/deps-test: ")
        assert (repo / "pkg" / "new.txt").read_text() == "mine\n"
    else:
        assert proc.stderr.startswith(expect), proc.stderr
    if not case.startswith("branch-"):
        assert subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", "refs/heads/chore/deps-test"],
                              capture_output=True).returncode != 0
    assert _snapshot(repo) == before


def test_prepare_leaves_remote_and_group_refs_unchanged(tmp_path):
    repo = build(tmp_path)
    g = group(repo, "pip", {"requirements.in": REQ_IN.replace("alpha==1.0", "alpha==2.0"),
                            "requirements.lock": "alpha 2.0\n"})
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {tmp_path}/hooked\n")
    hook.chmod(0o755)
    trust.trusted(str(repo))   # the cached trusted copy is part of the state, make it before the snapshot
    refs = lambda: sh(repo, "for-each-ref", "--format=%(refname) %(objectname)")  # noqa: E731
    remote = lambda: sh(repo, "ls-remote", "origin")  # noqa: E731
    before_refs, before_remote = refs(), remote()
    proc, out = run(repo, *groups(g))
    assert proc.returncode == 0, proc.stderr
    after = [line for line in refs().splitlines() if "refs/heads/chore/deps-test" not in line]
    assert "\n".join(after) == before_refs
    assert remote() == before_remote
    assert out["lock_commands"][0]["run"] == "touch ran" and not (repo / "ran").exists()
    assert not (tmp_path / "hooked").exists()


def test_commit_order_and_no_change(tmp_path):
    repo = build(tmp_path)
    g1 = group(repo, "one", {"pkg/a.txt": "a2\n"})
    g2 = clean(repo)
    g3 = group(repo, "three", {"pkg/c.txt": "c2\n"})
    sh(repo, "checkout", "-q", "main")
    write(repo, "pkg/c.txt", "c2\n")      # main already has the update of g3
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main took it")
    git(repo, "push", "-q", "origin", "main")
    sh(repo, "checkout", "-q", "feature/demo")
    proc, out = run(repo, *groups(g2, g3, g1))
    assert proc.returncode == 0, proc.stderr
    g = by_ref(out)
    assert (g[g3]["state"], g[g3]["reason"], g[g3]["file"]) == ("left_out", "no-change", None)
    subjects = sh(repo, "log", "--reverse", "--format=%s", "origin/main..chore/deps-test").splitlines()
    assert subjects == [f"chore(deps): apply {g2}", f"chore(deps): apply {g1}"]
    assert [x["sha"] for x in out["groups"] if x["state"] == "applied"] == \
        sh(repo, "log", "--reverse", "--format=%H", "origin/main..chore/deps-test").splitlines()
    assert {x["reason"] for x in out["groups"]} - {None} <= set(deps_checks.PREPARE_REASONS)
