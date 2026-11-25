"""The profile resolver (plan 90, sections 3.1 and 3.4): load order, explain, ref, clamp to the default branch, hooks.
Repositories are built in tmp_path (a bare repository is the origin); no network."""
import copy
import json
import os
import subprocess

import pytest
import yaml

from conftest import FIXTURES, tld_cmd
from tld.profile import base as base_mod
from tld.profile import resolve as rs
from tld.profile import validate as pv
from tld.profile.base import BaseRef

MINIMAL = {
    "docs": {"must_read": []},
    "git": {"main_branch": "main", "branch_pattern": "<type>/<kebab-case>"},
    "verify": {"fast": ["make lint"], "dod": ["make test"]},
    "stacks": [],
}
REF_A = BaseRef("acme", "org", "tld/base.yaml", "a" * 40)
REF_B = BaseRef("acme", "org", "tld/base.yaml", "b" * 40)
BASE_A = """\
tld:
  allow_override: [roles.posture.security]
roles:
  posture: {security: critical}
  required:
    - {role: security-reviewer, at: [implement_phase], blocking: true}
git: {bot_login: acme-agent}
"""
BASE_B = "models: {worker: standard}\n"
MAIN = {**MINIMAL,
        "roles": {"posture": {"security": "critical"},
                  "required": [{"role": "security-reviewer", "at": ["implement_phase"], "blocking": True}]},
        "hooks": {"dod_gate": {"enabled": True}, "plan_gate": {"enabled": True}, "board_gate": {"enabled": True}}}
WEAKER = {**MINIMAL, "roles": {"posture": {"security": "low"}},
          "hooks": {"dod_gate": {"enabled": False}, "plan_gate": {"enabled": False}, "board_gate": {"enabled": False}}}


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k.startswith("GIT_CONFIG_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.test", GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write_profile(repo, profile):
    (repo / ".tld").mkdir(exist_ok=True)
    (repo / ".tld" / "toolkit.yaml").write_text(yaml.safe_dump(profile) if isinstance(profile, dict) else profile)


def commit_all(repo, message="x"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def make_repo(tmp_path, profile, origin=False, name="r"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write_profile(repo, profile)
    (repo / "README.md").write_text("x\n")
    commit_all(repo, "init")
    if origin:
        bare = tmp_path / f"{name}-origin.git"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
        git(repo, "remote", "add", "origin", str(bare))
        git(repo, "push", "-q", "origin", "main")
        git(repo, "checkout", "-q", "-b", "feature/x")
    return repo


def cache_base(repo, ref, text):
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "--stdin"], input=text, capture_output=True,
                          text=True, check=True).stdout.strip()
    base_mod._store(base_mod.common_dir(repo), ref, text.encode(), blob)


def with_extends(profile, ref):
    return {**copy.deepcopy(profile), "tld": {"extends": f"{ref.source}@{ref.sha}"}}


def validate_cli(repo, *args):
    return subprocess.run([*tld_cmd("profile", "validate"), *args], cwd=repo, capture_output=True, text=True)


def errs(raw, **kw):
    return rs.resolve(raw, **kw).errors


# ---------------------------------------------------------------------------------------- the pure resolver

def test_valid_minimal_profile():
    out = rs.resolve(MINIMAL)
    assert out.errors == [] and out.base is None
    assert out.profile["git"]["merge_style"] == "merge-commit" and out.profile["hooks"]["plan_gate"] == {"enabled": True}
    assert out.sources["git.merge_style"] == "default" and out.sources["git.main_branch"] == "repo"


def test_missing_required_key():
    p = copy.deepcopy(MINIMAL)
    del p["verify"]["dod"]
    assert errs(p) == ["missing required key 'verify.dod'"]


def test_unknown_key_and_wrong_type():
    p = copy.deepcopy(MINIMAL)
    p["verfy"] = {}
    p["stacks"] = 3
    found = errs(p)
    assert any("unknown key 'verfy'" in e for e in found) and any("'stacks': must be a list" in e for e in found)
    assert rs.resolve(["x"]).errors == ["the profile must be a YAML mapping"]


def test_no_file_or_bad_yaml(tmp_path):
    out = rs.load(tmp_path / ".tld" / "toolkit.yaml", trusted=False)
    assert out.errors and out.errors[0].startswith("no profile at")
    f = tmp_path / ".tld" / "toolkit.yaml"
    f.parent.mkdir()
    f.write_text("a: [unclosed\n")
    assert rs.load(f, trusted=False).errors[0].startswith("not valid YAML")
    f.write_text("- 1\n")
    assert rs.load(f, trusted=False).errors == ["the profile must be a YAML mapping"]


def test_old_profile_without_extends():
    out = rs.resolve(MINIMAL)
    assert out.base is None and out.warnings == []
    assert not any(s.startswith("base") for s in out.sources.values())


def test_old_profile_without_extends_keeps_every_value():
    for name in ("maintenance-toolkit.yaml", "privacyfence-toolkit.yaml"):
        raw = yaml.safe_load((FIXTURES / name).read_text())
        out = rs.resolve(raw)
        assert out.errors == [], name
        for key, value in rs._leaves(raw):
            node = out.profile
            for part in key.split("."):
                node = node[part]
            assert node == (value.rstrip("/") if key == "docs.plan_dir" else value), (name, key)


def test_repository_sets_allow_override():
    p = {**MINIMAL, "tld": {"allow_override": ["hooks.protect_paths"]}}
    assert errs(p) == ["'tld.allow_override': only a base profile may set it"]


def test_release_version_files_stay_required():
    out = rs.resolve({**MINIMAL, "docs": {"must_read": [], "changelog": {"file": "C.md", "section": "## x"}},
                      "release": {}})
    assert "missing required key 'release.version_files'" in out.errors


def test_merged_bot_as_code_owner():
    p = {**MINIMAL, "git": {**MINIMAL["git"], "codeowners": ["acme-agent"]}}
    out = rs.resolve(with_extends(p, REF_A), base=yaml.safe_load(BASE_A), base_ref=REF_A)
    assert any("'git.codeowners' must not contain 'git.bot_login'" in e for e in out.errors)


def test_base_values_are_merged_and_explained():
    out = rs.resolve(with_extends(MINIMAL, REF_A), base=yaml.safe_load(BASE_A), base_ref=REF_A)
    assert out.errors == [] and out.profile["roles"]["posture"]["security"] == "critical"
    lines = rs.explain_lines(out)
    label = "acme/org/tld/base.yaml@aaaaaaa"
    assert f'roles.posture.security = "critical"  # base {label}' in lines
    assert 'git.main_branch = "main"  # repo' in lines and lines == sorted(lines)
    assert "values from the base " + REF_A.label in rs.note_line(out)


def test_a_repository_cannot_weaken_its_base():
    p = with_extends({**MINIMAL, "roles": {"posture": {"security": "low"}}}, REF_A)
    out = rs.resolve(p, base={"roles": {"posture": {"security": "critical"}}}, base_ref=REF_A)
    assert out.errors and "'roles.posture.security': 'low' is weaker than the base's 'critical'" in out.errors[0]


def test_a_gate_the_base_does_not_write_cannot_be_switched_off():
    """The floor has every gate on, also where the base says nothing about it."""
    p = with_extends({**MINIMAL, "hooks": {"dod_gate": {"enabled": False}}}, REF_B)
    out = rs.resolve(p, base=yaml.safe_load(BASE_B), base_ref=REF_B)
    assert out.errors and out.errors[0].startswith("'hooks.dod_gate.enabled': false switches off a gate the base turns on")


def test_an_invalid_origin_owner_gives_no_git_ops_default():
    from tld.profile.defaults import Env
    out = rs.resolve(MINIMAL, env=Env(origin_owner="../evil"))
    assert "git_ops" not in out.profile and any("origin owner" in w for w in out.warnings)
    assert rs.resolve(MINIMAL, env=Env(origin_owner="acme")).profile["git_ops"]["repo"] == "acme/git-ops"


def test_the_raw_profile_is_shape_checked_before_the_merge():
    out = rs.resolve(with_extends({**MINIMAL, "roles": {"required": "x"}}, REF_A), base=yaml.safe_load(BASE_A),
                     base_ref=REF_A)
    assert out.errors == ["'roles.required': must be a list (got str)"]


def test_missing_main_branch_message():
    p = copy.deepcopy(MINIMAL)
    del p["git"]["main_branch"]
    assert errs(p) == ["missing required key 'git.main_branch' (it could not be detected: no origin/HEAD and no "
                       "remote default branch)"]


# ---------------------------------------------------------------------------------------------- the pin

def test_validate_rejects_a_tag_pin_with_the_commit_message():
    out = pv.validate({**MINIMAL, "tld": {"extends": "acme/org/tld/base.yaml@v1.2"}})
    assert out[0] and "'@v1.2' is not a commit SHA; pin the base by its full 40-hex commit (a tag can move): run " \
                      "tld profile base latest acme/org/tld/base.yaml" in out[0][0]


def test_validate_rejects_a_malformed_source():
    for bad in ("nonsense@" + "a" * 40, "acme/org/base.txt@" + "a" * 40, "acme/org/../x.yaml@" + "a" * 40):
        found = pv.validate({**MINIMAL, "tld": {"extends": bad}})[0]
        assert found and "must be <owner>/<repo>/<path>@<40-hex commit SHA>" in found[0], bad
    short = pv.validate({**MINIMAL, "tld": {"extends": "acme/org/b.yaml@" + "a" * 39}})[0]
    assert short and "is not a commit SHA" in short[0]
    ok = pv.validate({**MINIMAL, "tld": {"extends": "acme/org/b.yaml@" + "a" * 40}}, fetch=False)
    assert ok[0] == [] and "is not cached" in ok[1][0]  # fetch=False: a base that is not cached is a warning


def test_validate_rejects_an_uppercase_hex_pin():
    found = pv.validate({**MINIMAL, "tld": {"extends": "acme/org/b.yaml@" + "A" * 40}}, fetch=False)[0]
    assert found and "lower-case" in found[0]


# --------------------------------------------------------------------------------------- the command line

def test_explained_output(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    (repo / "docs").mkdir()
    (repo / "docs" / "README.md").write_text("index\n")
    out = validate_cli(repo, "--explain")
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert lines == sorted(lines)
    assert 'git.main_branch = "main"  # repo' in lines
    assert 'docs.index = "docs/README.md"  # default (docs/README.md exists)' in lines
    assert 'git.merge_style = "merge-commit"  # default' in lines
    assert "built-in defaults" not in out.stderr  # the note belongs to --resolved


def test_resolved_at_a_ref(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    write_profile(repo, {**MINIMAL, "git": {**MINIMAL["git"], "merge_style": "squash"}})  # not committed
    committed = json.loads(validate_cli(repo, "--ref", "HEAD", "--resolved").stdout)
    working = json.loads(validate_cli(repo, "--resolved").stdout)
    assert committed["git"]["merge_style"] == "merge-commit" and working["git"]["merge_style"] == "squash"
    out = validate_cli(repo, "--ref", "no-such-ref")
    assert out.returncode == 1 and "no profile at 'no-such-ref': it is not a commit of this repository" in out.stderr


def test_a_ref_that_looks_like_an_option_is_refused_and_writes_nothing(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    for ref in ("--output=x", "--output=../x", "-p"):
        out = validate_cli(repo, f"--ref={ref}", "--root", ".")
        assert out.returncode == 1 and "is not a git ref" in out.stderr, ref
    assert not (repo / "x").exists() and not (tmp_path / "x").exists()
    assert not any(p.name.startswith("--") for p in repo.iterdir())


def test_a_ref_resolves_once_and_only_the_sha_reaches_git(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, MINIMAL)
    seen = []
    real = rs._git
    monkeypatch.setattr(rs, "_git", lambda root, *a: (seen.append(a), real(root, *a))[1])
    out = rs.load(repo / ".tld" / "toolkit.yaml", ref="HEAD", root=repo, trusted=False)
    assert out.errors == []
    sha = git(repo, "rev-parse", "HEAD")
    assert ("show", f"{sha}:.tld/toolkit.yaml") in seen and ("ls-tree", "-r", "--name-only", sha) in seen
    assert not any("HEAD" in a and a[0] in ("show", "ls-tree") for a in seen)


def test_a_profile_path_outside_the_repository_at_a_ref_is_a_clean_error(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    outside = tmp_path / "other.yaml"
    outside.write_text("x: 1\n")
    out = validate_cli(repo, str(outside), "--ref", "HEAD", "--root", ".")
    assert out.returncode == 1 and "is outside the repository" in out.stderr and "Traceback" not in out.stderr
    out = validate_cli(repo, "../other.yaml", "--ref", "HEAD", "--root", ".")
    assert out.returncode == 1 and "must be a path inside the repository" in out.stderr
    inside = validate_cli(repo, str(repo / ".tld" / "toolkit.yaml"), "--ref", "HEAD", "--root", ".")
    assert inside.returncode == 0, inside.stderr


def test_a_bad_raw_profile_never_fetches_the_base(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, MINIMAL)
    write_profile(repo, {**with_extends(MINIMAL, REF_A), "tld": {"extends": f"{REF_A.source}@{REF_A.sha}",
                                                                 "allow_override": ["hooks.protect_paths"]}})

    def no_fetch(*a, **kw):
        raise AssertionError("fetched")

    monkeypatch.setattr(base_mod, "fetch", no_fetch)
    out = rs.load(repo / ".tld" / "toolkit.yaml", root=repo, trusted=False)
    assert out.errors == ["'tld.allow_override': only a base profile may set it"]


def test_resolved_output_plan_dir_default(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    out = validate_cli(repo, "--resolved")
    assert out.returncode == 0 and json.loads(out.stdout)["docs"]["plan_dir"] == "docs"
    assert "toolkit.yaml: note: " in out.stderr and "built-in defaults (--explain lists them)" in out.stderr
    (repo / "docs" / "plans").mkdir(parents=True)
    assert json.loads(validate_cli(repo, "--resolved").stdout)["docs"]["plan_dir"] == "docs/plans"
    assert json.loads(validate_cli(repo, "--resolved").stdout)["hooks"]["plan_gate"] == {"enabled": True}


def test_resolved_plan_dir_strips_trailing_slash(tmp_path):
    repo = make_repo(tmp_path, {**MINIMAL, "docs": {"must_read": [], "plan_dir": "plans/"}})
    assert json.loads(validate_cli(repo, "--resolved").stdout)["docs"]["plan_dir"] == "plans"


def test_missing_main_branch_message_on_the_command_line(tmp_path):
    p = copy.deepcopy(MINIMAL)
    del p["git"]["main_branch"]
    out = validate_cli(make_repo(tmp_path, p))
    assert out.returncode == 1 and ("toolkit.yaml: missing required key 'git.main_branch' (it could not be detected: "
                                    "no origin/HEAD and no remote default branch)") in out.stderr


def test_no_origin_warns_no_trusted_copy(tmp_path):
    out = validate_cli(make_repo(tmp_path, MINIMAL))
    assert out.returncode == 0 and out.stdout.startswith("toolkit.yaml: OK")
    assert "toolkit.yaml: warning: no trusted copy of the profile (no origin remote); guarded keys are taken from " \
           "this working tree" in out.stderr


def test_validate_with_unreachable_origin_warns_and_exits_0(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    git(repo, "remote", "add", "origin", str(tmp_path / "gone.git"))
    out = validate_cli(repo)
    assert out.returncode == 0, out.stderr
    assert "warning: no trusted copy of the profile (" in out.stderr and "could not be read" in out.stderr


def test_detected_main_branch_from_the_trusted_copy(tmp_path):
    p = copy.deepcopy(MINIMAL)
    del p["git"]["main_branch"]
    repo = make_repo(tmp_path, {**MINIMAL, "git": {"branch_pattern": "<type>/<kebab-case>", "main_branch": "main"}},
                     origin=True)
    write_profile(repo, p)
    out = validate_cli(repo, "--explain")
    assert out.returncode == 0, out.stderr
    assert 'git.main_branch = "main"  # detected (origin/HEAD)' in out.stdout.splitlines()


# --------------------------------------------------------------------------- the clamp to the default branch

def test_branch_weakening_is_clamped_to_main(tmp_path):
    repo = make_repo(tmp_path, MAIN, origin=True)
    write_profile(repo, WEAKER)
    out = validate_cli(repo, "--resolved")
    assert out.returncode == 0, out.stderr
    resolved = json.loads(out.stdout)
    assert resolved["roles"]["posture"]["security"] == "critical"
    assert [r["role"] for r in resolved["roles"]["required"]] == ["security-reviewer"]
    assert all(resolved["hooks"][g]["enabled"] is True for g in ("dod_gate", "plan_gate", "board_gate"))
    for key in ("roles.posture.security", "hooks.dod_gate.enabled", "roles.required.security-reviewer"):
        assert (f"toolkit.yaml: warning: '{key}' is weaker here than on main (the remote default branch); "
                "the main value applies until this change is merged") in out.stderr
    explained = validate_cli(repo, "--explain").stdout
    assert 'roles.posture.security = "critical"  # main (the remote default branch; this branch\'s value is ' \
           "weaker)" in explained


def test_branch_repointing_extends_is_clamped_to_main_base(tmp_path):
    repo = make_repo(tmp_path, with_extends(MINIMAL, REF_A), origin=True)
    cache_base(repo, REF_A, BASE_A)
    cache_base(repo, REF_B, BASE_B)
    write_profile(repo, with_extends(MINIMAL, REF_B))
    out = validate_cli(repo, "--resolved")
    assert out.returncode == 0, out.stderr
    resolved = json.loads(out.stdout)
    assert resolved["roles"]["posture"]["security"] == "critical"
    assert [r["role"] for r in resolved["roles"]["required"]] == ["security-reviewer"]
    assert "'roles.required.security-reviewer' is weaker here than on main" in out.stderr


def test_branch_removing_extends_is_clamped(tmp_path):
    repo = make_repo(tmp_path, with_extends(MINIMAL, REF_A), origin=True)
    cache_base(repo, REF_A, BASE_A)
    write_profile(repo, MINIMAL)
    out = validate_cli(repo, "--resolved")
    assert out.returncode == 0, out.stderr
    resolved = json.loads(out.stdout)
    assert resolved["roles"]["posture"]["security"] == "critical" and "tld" not in resolved
    assert [r["role"] for r in resolved["roles"]["required"]] == ["security-reviewer"]


def test_trusted_base_not_cached_ignores_allow_override(tmp_path):
    repo = make_repo(tmp_path, with_extends(MINIMAL, REF_A), origin=True)  # main's base is not cached here
    cache_base(repo, REF_B, BASE_B)
    write_profile(repo, with_extends(MINIMAL, REF_B))
    out = validate_cli(repo, "--resolved")
    assert out.returncode == 0, out.stderr
    assert (f"warning: the default branch's base {REF_A.label} is not cached; its values and its tld.allow_override "
            "are not applied") in out.stderr
    raw = yaml.safe_load(yaml.safe_dump(with_extends(MINIMAL, REF_A)))
    _, base, errors, warnings = rs.base_for(raw, repo, False, trusted_copy=True)
    assert base is None and errors == [] and "tld.allow_override" in warnings[0]


# ------------------------------------------------------------------------------------------------- hooks

def test_for_hook_never_runs_git_fetch(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, with_extends(MINIMAL, REF_A))
    calls = []
    real = subprocess.run

    def spy(args, *a, **kw):
        calls.append(list(args))
        return real(args, *a, **kw)

    def no_fetch(*a, **kw):
        raise AssertionError("for_hook fetched")

    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setattr(base_mod, "fetch", no_fetch)
    resolved, notice = rs.for_hook(with_extends(MINIMAL, REF_A), repo)
    assert resolved["hooks"]["plan_gate"] == {"enabled": True}
    assert notice == f"the base {REF_A.label} is not cached here; run tld profile validate to fetch it"
    assert not any("fetch" in c for c in calls)
    cache_base(repo, REF_A, BASE_A)
    resolved, notice = rs.for_hook(with_extends(MINIMAL, REF_A), repo)
    assert notice is None and resolved["roles"]["posture"]["security"] == "critical"


def test_for_hook_does_not_read_the_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "SCHEMA", tmp_path / "no-such-schema.json")
    resolved, notice = rs.for_hook(MINIMAL, tmp_path)
    assert resolved["git"]["main_branch"] == "main" and notice is None


def test_for_hook_reads_files_at_a_commit_only_for_a_real_sha(tmp_path):
    repo = make_repo(tmp_path, MINIMAL)
    (repo / "docs").mkdir()
    (repo / "docs" / "README.md").write_text("i\n")  # in the working tree only
    sha = git(repo, "rev-parse", "HEAD")
    assert "index" not in rs.for_hook(MINIMAL, repo, at_sha=sha)[0]["docs"]
    for bad in ("--output=x", "HEAD", "main", sha[:10], "../x"):
        assert rs.for_hook(MINIMAL, repo, at_sha=bad)[0]["docs"]["index"] == "docs/README.md", bad
    assert not (repo / "x").exists()


def test_for_hook_never_raises(tmp_path, monkeypatch):
    assert rs.for_hook(None, tmp_path) == (None, None) and rs.for_hook("x", tmp_path) == (None, None)
    odd = {"roles": {"required": "x"}, "tld": {"extends": 5}, "hooks": 3, "docs": []}
    resolved, notice = rs.for_hook(odd, tmp_path / "missing")
    assert resolved is None or isinstance(resolved, dict)
    monkeypatch.setattr(rs.defaults, "apply", lambda *a, **k: 1 / 0)
    resolved, notice = rs.for_hook(MINIMAL, tmp_path)
    assert resolved is None and "could not be resolved" in notice
