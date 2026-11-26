"""The org base profile: parse a pin, fetch it by commit, cache it, check it. A local repository is the origin; no network."""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT
from tld.guard import secret_scan
from tld.profile import base

SOURCE = "acme/.github/tld/profile-base.yaml"
SHA = "a" * 40
PATH = "tld/profile-base.yaml"
GOOD = """\
tld:
  version: ">=1.7,<2"
git:
  bot_login: acme-agent
  codeowners: [alice]
  branch_pattern: "<type>/<kebab-case>"
roles:
  posture: {security: critical}
  required:
    - {role: security-reviewer, at: [implement_phase, implement_final], blocking: true}
    - {role: dependency-auditor, at: [dod], when: [pyproject.toml, "requirements*.txt"]}
hooks:
  dod_gate: {enabled: true, max_attempts: 3}
  plan_gate: {enabled: true}
models: {worker: standard, reviewer: strong}
runtime: {environments: [TLD]}
verify:
  dod_manual:
    - "A user-visible change needs a changelog line."
"""


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k.startswith("GIT_CONFIG_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.test", GIT_TERMINAL_PROMPT="0")
    return env


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args], capture_output=True,
                       text=True, env=_env())
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def commit(repo, text=GOOD, message="base"):
    path = repo / PATH
    if text is None:
        git(repo, "rm", "-q", PATH)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        git(repo, "add", PATH)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def origin(tmp_path):
    repo = tmp_path / "origin"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    return repo


@pytest.fixture
def project(tmp_path, origin, monkeypatch):
    proj = tmp_path / "project"
    proj.mkdir()
    git(proj, "init", "-q", "-b", "main")
    (proj / "README.md").write_text("x\n")
    git(proj, "add", "README.md")
    git(proj, "commit", "-q", "-m", "init")
    monkeypatch.setattr(base, "url_for", lambda ref: str(origin))
    return proj


def ref_for(sha, source=SOURCE):
    return base.parse_extends(f"{source}@{sha}")


# ---- the pin ---------------------------------------------------------------------------------------------------

def test_valid_pin():
    ref = base.parse_extends(f"Acme/.github/{PATH}@{SHA.upper()}")
    assert (ref.owner, ref.repo, ref.path, ref.sha) == ("acme", ".github", PATH, SHA)
    assert ref.source == SOURCE and ref.label == f"{SOURCE}@aaaaaaa"
    assert base.parse_extends(f"a/b/c.yml@{SHA}").path == "c.yml"


def test_not_a_commit():
    with pytest.raises(base.BaseError) as exc:
        base.parse_extends(f"{SOURCE}@v1")
    assert str(exc.value) == ("toolkit.yaml: 'tld.extends': '@v1' is not a commit SHA; pin the base by its full "
                              f"40-hex commit (a tag can move): run tld profile base latest {SOURCE}")
    for ref in ("main", "abc1234", "a" * 39, "a" * 41):
        with pytest.raises(base.BaseError, match="is not a commit SHA"):
            base.parse_extends(f"{SOURCE}@{ref}")


def test_malformed_source():
    bad = [f"{PATH}@{SHA}", f"acme/x@{SHA}", f"acme/.github/{PATH}", f"acme/.github/{PATH}@", f"-acme/r/p.yaml@{SHA}",
           f"acme/r.git/p.yaml@{SHA}", f"acme/../p.yaml@{SHA}", f"acme/r/../p.yaml@{SHA}", f"acme/r/a//b.yaml@{SHA}",
           f"acme/r/a\\b.yaml@{SHA}", f"acme/r/p.txt@{SHA}", f"acme/r/p.yaml/@{SHA}", f"acme/r/p\n.yaml@{SHA}",
           f"acme/r/{'a' * 260}.yaml@{SHA}", 7, None]
    for value in bad:
        with pytest.raises(base.BaseError) as exc:
            base.parse_extends(value)
        assert str(exc.value).startswith("toolkit.yaml: 'tld.extends': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got '"), value
    with pytest.raises(base.BaseError) as exc:
        base.parse_extends(f"acme/x@{SHA}")
    assert str(exc.value) == f"toolkit.yaml: 'tld.extends': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got 'acme/x@{SHA}')"


def test_url_for_builds_github_url():
    assert base.url_for(ref_for(SHA)) == "https://github.com/acme/.github.git"
    assert base.url_for(ref_for(SHA, "Other-Org/Repo.x/a/b.yml")) == "https://github.com/other-org/repo.x.git"


# ---- checking a base file --------------------------------------------------------------------------------------

def test_check_a_base_file():
    data, errors = base.check_base_text(GOOD, "x@1234567")
    assert errors == [] and data["roles"]["posture"] == {"security": "critical"}
    data, errors = base.check_base_text(GOOD.encode(), "x@1234567")
    assert errors == [] and data is not None


def test_base_chains_refused():
    data, errors = base.check_base_text(f"tld:\n  extends: {SOURCE}@{SHA}\n", "o/r/p.yaml@1234567")
    assert data is None
    assert errors == ["toolkit.yaml: base o/r/p.yaml@1234567: 'tld.extends': a base cannot extend another profile"]


def test_key_a_base_may_not_set():
    for text, key in (("verify:\n  fast: [make]\n", "verify.fast"), ("roles:\n  extra_context: hi\n", "roles.extra_context"),
                      ("deps: {cooldown_days: 3}\n", "deps"), ("scope: {}\n", "scope"), ("git:\n  main_branch: x\n", "git.main_branch"),
                      ("tld: 5\n", "tld")):
        data, errors = base.check_base_text(text, "l")
        assert data is None
        assert errors == [f"toolkit.yaml: base l: '{key}' cannot be set in a base (a base may set: {base.BASE_KEYS_TEXT})"], text
    assert "hooks.*" in base.BASE_KEYS_TEXT and "verify.dod_manual" in base.BASE_KEYS_TEXT


def _token():
    return "gh" + "p_" + "A1b2C3d4E5" * 4  # built at run time so this file holds no credential-looking line


def test_token_like_text():
    data, errors = base.check_base_text(f"models:\n  worker: {_token()}\n", "l")
    assert data is None and len(errors) == 1 and "refused: line 2 looks like" in errors[0]
    assert "(pattern: github-token)" in errors[0] and errors[0].endswith("A base never holds a credential.")
    marked = f"models:\n  worker: {_token()}  # {secret_scan.ALLOW_MARK}\n"
    data, errors = base.check_base_text(marked, "l")
    assert data is None and errors and "line 2" in errors[0]  # the allow mark never hides a token in a base


def test_token_refusal_does_not_print_the_value():
    token = _token()
    _, errors = base.check_base_text(f"models:\n  worker: {token}\n", "l")
    assert errors and all(token not in e and token[4:20] not in e for e in errors)


def test_secret_like_key_refused_whatever_value():
    data, errors = base.check_base_text("models:\n  api_key: hello\n", "l")
    assert data is None and len(errors) == 1
    assert "line 2 has a key named like a credential" in errors[0] and "hello" not in errors[0] and "api_key" not in errors[0]
    _, errors = base.check_base_text("hooks:\n  deep:\n    - {deploy_token: 1}\n", "l")
    assert errors and "line 3" in errors[0]
    data, errors = base.check_base_text("git:\n  bot_login: acme-agent\n", "l")
    assert errors == [] and data


def test_anchors_and_size():
    pre = "toolkit.yaml: base l: "
    _, errors = base.check_base_text("models: &m {worker: standard}\nruntime: {environments: [a]}\n", "l")
    assert errors == [pre + "uses YAML anchors or aliases; a base must not"]
    _, errors = base.check_base_text("models: &m {worker: standard}\nhooks: {x: *m}\n", "l")
    assert errors == [pre + "uses YAML anchors or aliases; a base must not"]
    _, errors = base.check_base_text("models: {worker: " + "a" * 70000 + "}\n", "l")
    assert errors == [pre + "is larger than 65536 bytes"]
    _, errors = base.check_base_text("﻿models: {}\n", "l")
    assert errors and "byte order mark" in errors[0]
    _, errors = base.check_base_text(b"models: \xff\xfe\n", "l")
    assert errors == [pre + "is not UTF-8"]
    _, errors = base.check_base_text("a: [b\n", "l")
    assert errors and errors[0].startswith(pre + "is not valid YAML")
    _, errors = base.check_base_text("- a\n- b\n", "l")
    assert errors == [pre + "must be a mapping at the top"]
    deep = "hooks: " + "[" * 12 + "]" * 12 + "\n"
    _, errors = base.check_base_text(deep, "l")
    assert errors == [pre + "nests deeper than 8 levels"]
    ok = "hooks: " + "[" * 7 + "]" * 7 + "\n"  # the top mapping plus seven sequences is eight levels
    assert not any("nests deeper" in e for e in base.check_base_text(ok, "l")[1])  # the shape check may object


# ---- fetch and cache -------------------------------------------------------------------------------------------

def counting(calls):
    def run(args, env, timeout):
        calls.append(args)
        return base._default_runner(args, env, timeout)
    return run


def test_first_fetch_is_cached(project, origin):
    sha = commit(origin)
    ref = ref_for(sha)
    calls = []
    text = base.fetch(project, ref, runner=counting(calls))
    assert text == GOOD and calls
    folder = project / ".git" / "tld" / "base"
    key = base.cache_key(ref)
    assert (folder / f"{key}.yaml").read_bytes() == GOOD.encode()
    meta = json.loads((folder / f"{key}.json").read_text())
    assert meta["source"] == SOURCE and meta["sha"] == sha and meta["size"] == len(GOOD.encode())
    assert {"blob", "sha256", "fetched_at"} <= set(meta) and len(key) == 24
    again = []
    assert base.fetch(project, ref, runner=counting(again)) == GOOD
    assert again == []  # a commit never changes: never fetched twice
    assert not list(folder.glob("*.tmp"))


def test_offline_after_caching(project, origin, monkeypatch):
    ref = ref_for(commit(origin))
    base.fetch(project, ref)
    monkeypatch.setattr(base, "url_for", lambda r: str(origin / "gone"))
    assert base.fetch(project, ref) == GOOD
    assert base.cached(base.common_dir(project), ref) == GOOD


def test_fetch_fails_without_a_cache(project, origin, monkeypatch):
    sha = commit(origin)
    ref = ref_for(sha)
    monkeypatch.setattr(base, "url_for", lambda r: str(origin / "gone"))
    with pytest.raises(base.BaseError) as exc:
        base.fetch(project, ref)
    message = str(exc.value)
    assert message.startswith(f"toolkit.yaml: 'tld.extends': the base {SOURCE}@{sha[:7]} is not cached and could not be fetched (")
    assert message.endswith("); run again with network access") and "\n" not in message
    assert len(message.split("(", 1)[1]) <= 260
    assert base.cached(base.common_dir(project), ref) is None
    monkeypatch.setattr(base, "url_for", lambda r: str(origin))
    with pytest.raises(base.BaseError) as exc:
        base.fetch(project, ref_for(sha, "acme/.github/missing/file.yaml"))
    assert str(exc.value) == f"toolkit.yaml: 'tld.extends': missing/file.yaml does not exist at acme/.github@{sha[:7]}"
    failed = []
    with pytest.raises(base.BaseError, match="timed out"):
        base.fetch(project, ref, runner=lambda a, e, t: failed.append(a) or (124, "", "timed out after 20 s"))
    assert failed


def test_corrupt_cache_entry(project, origin):
    ref = ref_for(commit(origin))
    base.fetch(project, ref)
    git_dir = base.common_dir(project)
    entry = git_dir / "tld" / "base" / f"{base.cache_key(ref)}.yaml"
    entry.write_text(GOOD.replace("critical", "low"))
    assert base.cached(git_dir, ref) is None  # the hash no longer matches: a miss
    assert base.fetch(project, ref) == GOOD and entry.read_text() == GOOD  # and the entry is repaired
    entry.with_suffix(".json").write_text("not json")
    assert base.cached(git_dir, ref) is None
    entry.with_suffix(".json").unlink()
    assert base.cached(git_dir, ref) is None


def test_fetch_leaves_the_project_repository_unshallow(project, origin):
    ref = ref_for(commit(origin))
    commit(origin, GOOD + "# more\n", "second")
    base.fetch(project, ref)
    assert git(project, "rev-parse", "--is-shallow-repository") == "false"
    assert not (project / ".git" / "shallow").exists()
    assert git(project, "rev-list", "--all", "--count") == "1"  # none of the base's objects went into the project


def test_cache_is_shared_by_linked_worktrees(project, origin, tmp_path):
    ref = ref_for(commit(origin))
    linked = tmp_path / "linked"
    git(project, "worktree", "add", "-q", "-b", "other", str(linked))
    assert base.common_dir(linked).resolve() == (project / ".git").resolve()
    base.fetch(linked, ref)
    assert base.cached(base.common_dir(project), ref) == GOOD
    calls = []
    assert base.fetch(project, ref, runner=counting(calls)) == GOOD and calls == []


def test_commit_only_a_pull_request_holds_is_refused(project, origin):
    commit(origin)
    git(origin, "checkout", "-q", "-b", "side")
    stray = commit(origin, GOOD.replace("critical", "low"), "a pull request head")
    git(origin, "update-ref", "refs/pull/1/head", stray)
    git(origin, "checkout", "-q", "main")
    git(origin, "branch", "-q", "-D", "side")
    ref = ref_for(stray)
    with pytest.raises(base.BaseError) as exc:
        base.fetch(project, ref)
    assert str(exc.value) == (f"toolkit.yaml: 'tld.extends': the commit {stray[:7]} is not on a tag or the default "
                              f"branch of acme/.github")
    assert base.cached(base.common_dir(project), ref) is None


def test_tagged_commit_off_the_default_branch_is_accepted(project, origin):
    commit(origin)
    git(origin, "checkout", "-q", "-b", "release")
    tagged = commit(origin, GOOD + "# release\n", "release")
    git(origin, "tag", "-a", "-m", "v3", "v3")
    git(origin, "checkout", "-q", "main")
    git(origin, "branch", "-q", "-D", "release")
    assert base.fetch(project, ref_for(tagged)) == GOOD + "# release\n"


def test_a_refused_base_is_not_cached(project, origin):
    sha = commit(origin, GOOD + f"# {_token()}\n")
    ref = ref_for(sha)
    with pytest.raises(base.BaseError, match="refused: line"):
        base.fetch(project, ref)
    assert base.cached(base.common_dir(project), ref) is None
    assert not list((base.common_dir(project) / "tld" / "base").glob("*.yaml"))


def test_cache_entry_must_match_its_blob_id(project, origin):
    ref = ref_for(commit(origin))
    base.fetch(project, ref)
    git_dir = base.common_dir(project)
    meta_path = git_dir / "tld" / "base" / f"{base.cache_key(ref)}.json"
    meta = json.loads(meta_path.read_text())
    meta["blob"] = "0" * 40
    meta_path.write_text(json.dumps(meta))
    assert base.cached(git_dir, ref) is None


def test_tags_are_ascii_and_short():
    for tag in ("v1", "1.2.3", "v10.0", "v1.2.3.4.5.6"):
        assert base.TAG_RE.match(tag), tag
    for tag in ("v1.2.3.4.5.6.7", "v" + "1" * 10, "v\u0661", "v1.", "x1", "v1.\u0662"):
        assert not base.TAG_RE.match(tag), tag


def test_fetch_outside_a_repository(tmp_path):
    with pytest.raises(base.BaseError, match="not a git repository"):
        base.fetch(tmp_path / "nowhere", ref_for(SHA))


# ---- the newest pin --------------------------------------------------------------------------------------------

def test_latest_pin(origin):
    first = commit(origin)
    git(origin, "tag", "v1")
    second = commit(origin, GOOD + "# two\n", "two")
    git(origin, "tag", "-a", "-m", "v2", "v2")  # an annotated tag: the commit it points at counts
    commit(origin, GOOD + "# three\n", "three")
    git(origin, "tag", "not-a-version")
    sha, tag = base.latest_pin(SOURCE)
    assert (sha, tag) == (second, "v2") and sha != first


def test_latest_without_tags(origin):
    commit(origin)
    head = commit(origin, GOOD + "# two\n", "two")
    assert base.latest_pin(SOURCE) == (head, None)


def test_latest_pin_skips_newest_tag_without_file(origin):
    first = commit(origin)
    git(origin, "tag", "v1")
    commit(origin, None, "remove the file")
    (origin / "other.txt").write_text("x")
    git(origin, "add", "other.txt")
    git(origin, "commit", "-q", "-m", "other")
    git(origin, "tag", "v2")
    assert base.latest_pin(SOURCE) == (first, "v1")
    with pytest.raises(base.BaseError, match="does not exist"):
        base.latest_pin("acme/.github/nothing/here.yaml")


def test_latest_pin_sorts_numerically(origin):
    commit(origin)
    git(origin, "tag", "v9")
    ten = commit(origin, GOOD + "# ten\n", "ten")
    git(origin, "tag", "v10")
    git(origin, "tag", "v1.2.3")
    git(origin, "tag", "v2")
    assert base.latest_pin(SOURCE) == (ten, "v10")


@pytest.fixture(autouse=True)
def _origin_for_latest(request, monkeypatch):
    """latest_pin has no project: point url_for at the origin fixture whenever a test asks for it."""
    if "origin" in request.fixturenames and "project" not in request.fixturenames:
        origin = request.getfixturevalue("origin")
        monkeypatch.setattr(base, "url_for", lambda ref: str(origin))


# ---- command line ----------------------------------------------------------------------------------------------

def test_base_check_cli_prints_ok(tmp_path, capsys):
    good = tmp_path / "profile-base.yaml"
    good.write_text(GOOD)
    assert base.main(["check", str(good)]) == 0
    assert capsys.readouterr().out == "base: OK\n"
    r = subprocess.run([sys.executable, str(ROOT / "cli" / "tld"), "profile", "base", "check", str(good)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "base: OK\n", r.stderr
    bad = tmp_path / "bad.yaml"
    bad.write_text("verify:\n  fast: [x]\n")
    assert base.main(["check", str(bad)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "'verify.fast' cannot be set in a base" in captured.err
    assert base.main(["check", str(tmp_path / "missing.yaml")]) == 1
    help_run = subprocess.run([sys.executable, str(ROOT / "cli" / "tld"), "profile", "base", "--help"],
                              capture_output=True, text=True)
    assert help_run.returncode == 0 and all(w in help_run.stdout for w in ("check", "fetch", "latest"))


def test_fetch_and_latest_commands(project, origin, capsys):
    sha = commit(origin)
    git(origin, "tag", "v1")
    profile = project / ".tld" / "toolkit.yaml"
    profile.parent.mkdir()
    profile.write_text("stacks: []\n")
    assert base.main(["fetch", str(profile)]) == 0 and capsys.readouterr().out == "no base\n"
    profile.write_text(f"tld:\n  extends: {SOURCE}@{sha}\n")
    assert base.main(["fetch", str(profile)]) == 0
    assert capsys.readouterr().out == f"{SOURCE}@{sha[:7]} (fetched)\n"
    assert base.main(["fetch", str(profile)]) == 0
    assert capsys.readouterr().out == f"{SOURCE}@{sha[:7]} (cached)\n"
    profile.write_text(f"tld:\n  extends: {SOURCE}@v1\n")
    assert base.main(["fetch", str(profile)]) == 1 and "is not a commit SHA" in capsys.readouterr().err
    assert base.main(["latest", SOURCE]) == 0
    assert json.loads(capsys.readouterr().out) == {"sha": sha, "tag": "v1"}
    assert base.main(["latest", "nonsense"]) == 1 and "must be <owner>/<repo>/<path>" in capsys.readouterr().err
    assert base.main(["fetch", str(project / "absent.yaml")]) == 1


@pytest.mark.parametrize("path", ["tld/$(id).yaml", "tld/`id`.yaml", "tld/a;b.yaml", "tld/a b.yaml", "tld/a|b.yaml",
                                  "tld/a&b.yaml", "tld/a'b.yaml", 'tld/a"b.yaml', "tld/a\nb.yaml", "tld/${HOME}.yaml"])
def test_shell_metacharacters_are_refused_in_the_path(path):
    """The source is pasted into commands by playbooks: a path never carries a shell metacharacter."""
    with pytest.raises(base.BaseError):
        base.parse_source(f"acme/.github/{path}")
    with pytest.raises(base.BaseError):
        base.parse_extends(f"acme/.github/{path}@{SHA}")


def test_a_trailing_newline_is_refused_in_a_source_or_a_pin():
    with pytest.raises(base.BaseError):
        base.parse_extends(f"{SOURCE}@{SHA}\n")
    with pytest.raises(base.BaseError):
        base.parse_source(SOURCE + "\n")


def test_check_base_text_refuses_a_key_of_the_wrong_type():
    data, errors = base.check_base_text("roles:\n  posture: x\n", "o/r@abcdef1")
    assert data is None and errors and "roles.posture" in errors[0]
    data, errors = base.check_base_text("roles:\n  posture:\n    security: critical\n", "o/r@abcdef1")
    assert errors == [] and data["roles"]["posture"]["security"] == "critical"


# The spec scenario "Pin held only by a pull request" (plan 3.13 names the test after it).
test_pin_held_only_by_a_pull_request = test_commit_only_a_pull_request_holds_is_refused
