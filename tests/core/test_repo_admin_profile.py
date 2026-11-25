"""repo_admin_profile.py: the base pin, the guarded overrides and the merge style, against a fake GitHub."""
import difflib
import subprocess

import pytest
import yaml

import test_repo_admin as base
from conftest import TLD
from test_repo_admin import STARTER, by_check, world

BASE_FILE = "acme/.github/tld/profile-base.yaml"
OLD, MID, NEW = "a" * 40, "b" * 40, "c" * 40
BASE_TEXT = """\
tld:
  allow_override: [roles.posture.security]
roles:
  posture: {security: critical}
"""
POLICY = {"profile": {"base": BASE_FILE}}


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def profile_text(pin=f"{BASE_FILE}@{OLD}  # v1.0", extra=""):
    head = f"tld:\n  extends: {pin}\n" if pin else ""
    return (head + "docs: {must_read: []}\ngit: {main_branch: main, branch_pattern: '<type>/<kebab-case>'}\n"
            "verify: {fast: [make lint], dod: [make test]}\nstacks: []\n" + extra)


def routes(ra, tags=(("v1.0", OLD), ("v1.1", MID), ("v1.10", NEW)), base_text=BASE_TEXT):
    r = {("GET", "/repos/acme/.github/tags"): [{"name": n, "commit": {"sha": s}} for n, s in tags]}

    def contents(params):
        if params.get("ref") not in {s for _, s in tags}:
            return ra.ApiError(404, "Not Found", "GET", "x")
        return base_text

    r[("GET", "/repos/acme/.github/contents/tld/profile-base.yaml")] = contents
    return r


def audit(ra, text, policy=POLICY, **kw):
    ctx, fake = world(ra, policy, files={"app": {".tld/toolkit.yaml": text}} if text is not None else {},
                      routes=routes(ra), **kw)
    return ra.run_checks(ctx, ["profile"]), fake


def test_repository_without_a_base(ra):
    found, _ = audit(ra, profile_text(pin=None))
    (one,) = by_check(found, "profile-no-extends")
    assert one.severity == "warn" and BASE_FILE in one.message and f"@{NEW}" in one.manual
    found, _ = audit(ra, profile_text(pin=f"{BASE_FILE}@v1.0"))
    (bad,) = by_check(found, "profile-invalid-extends")
    assert bad.severity == "warn" and "not a commit SHA" in bad.message
    assert by_check(found, "profile-no-extends") == []
    found, _ = audit(ra, profile_text(pin=f"other/base/x.yaml@{NEW}"))
    assert "policy's base" in by_check(found, "profile-invalid-extends")[0].message
    assert audit(ra, None)[0] == []  # no profile: nothing to say


def test_out_of_date_pin(ra):
    found, _ = audit(ra, profile_text())
    (old,) = by_check(found, "profile-pin-old")
    assert old.severity == "fix" and "chore: bump the tld base to v1.10" in old.message
    assert old.action.kind == "files" and old.action.repo == "acme/app"
    assert [c["path"] for c in old.action.changes] == [".tld/toolkit.yaml"]
    assert by_check(audit(ra, profile_text(pin=f"{BASE_FILE}@{NEW}  # v1.10"))[0], "profile-pin-old") == []
    found, _ = audit(ra, profile_text(), policy={"profile": {"base": BASE_FILE, "pin": MID}})
    assert f"{MID[:7]}" in by_check(found, "profile-pin-old")[0].message and "v1.1" in by_check(found, "profile-pin-old")[0].message


def test_pin_bump_changes_only_the_extends_line(ra):
    text = profile_text(extra="# a comment\nrelease: {version_files: [x]}\n")
    found, _ = audit(ra, text)
    new = by_check(found, "profile-pin-old")[0].action.changes[0]["content"]
    diff = [d for d in difflib.unified_diff(text.splitlines(), new.splitlines(), lineterm="", n=0) if d[:1] in "+-" and d[:3] not in ("+++", "---")]
    assert diff == [f"-  extends: {BASE_FILE}@{OLD}  # v1.0", f"+  extends: {BASE_FILE}@{NEW}  # v1.10"]
    assert new.endswith("\n") and new.count("\n") == text.count("\n")
    assert ra_bump(None, "x: 1\n") is None
    assert ra_bump("v2", f"tld:\n  extends: {BASE_FILE}@{OLD}\n").endswith(f"@{NEW}  # v2\n")
    assert ra_bump(None, f"tld:\n  extends: {BASE_FILE}@{OLD}  # v1.0\n").endswith(f"@{NEW}\n")
    assert ra_bump(None, f"tld:\n  extends: a\n  extends: b\n") is None


def ra_bump(tag, text):
    from tld.ops import repo_admin_profile as mod
    return mod.bump_extends(text, BASE_FILE, NEW, tag)


def test_override_listed(ra):
    text = profile_text(pin=f"{BASE_FILE}@{NEW}  # v1.10", extra="roles: {posture: {security: low}}\n")
    found, _ = audit(ra, text)
    (info,) = by_check(found, "profile-guarded-override")
    assert info.severity == "info" and "roles.posture.security" in info.message
    quiet = audit(ra, text, policy={"profile": {"base": BASE_FILE, "guarded_overrides": "ignore"}})[0]
    assert by_check(quiet, "profile-guarded-override") == []
    plain = profile_text(pin=f"{BASE_FILE}@{NEW}  # v1.10")
    assert by_check(audit(ra, plain)[0], "profile-guarded-override") == []


def test_guarded_override_resolves_remote_profile_offline(ra, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the audit must not run git or the network")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    from tld.profile import base as base_mod
    monkeypatch.setattr(base_mod, "fetch", refuse)
    text = profile_text(pin=f"{BASE_FILE}@{NEW}  # v1.10", extra="roles: {posture: {security: low}}\n")
    found, fake = audit(ra, text)
    assert [f.check for f in found] == ["profile-guarded-override"]
    assert "/repos/acme/.github/contents/tld/profile-base.yaml" in fake.reads  # the base text came from the client
    assert not fake.writes
    # a posture the base does not allow to change is a resolve error, shown as an invalid profile
    strict = routes(ra, base_text="roles:\n  posture: {security: critical}\n")
    ctx, _ = world(ra, POLICY, files={"app": {".tld/toolkit.yaml": text}}, routes=strict)
    (bad,) = by_check(ra.run_checks(ctx, ["profile"]), "profile-invalid-extends")
    assert "roles.posture.security" in bad.message


def test_merge_settings(ra):
    starter = yaml.safe_load(STARTER.read_text())["repo_settings"]
    assert (starter["allow_merge_commit"], starter["allow_squash_merge"], starter["allow_rebase_merge"]) == (True, False, False)
    text = profile_text(pin=f"{BASE_FILE}@{NEW}  # v1.10")
    assert by_check(audit(ra, text, allow_merge_commit=True)[0], "profile-merge-style") == []
    (one,) = by_check(audit(ra, text, allow_merge_commit=False)[0], "profile-merge-style")
    assert one.severity == "warn" and "allow_merge_commit" in one.message and "merge-commit" in one.message
    squash = profile_text(pin=f"{BASE_FILE}@{NEW}  # v1.10").replace("branch_pattern: '<type>/<kebab-case>'", "branch_pattern: '<type>/<kebab-case>', merge_style: squash")
    (sq,) = by_check(audit(ra, squash, allow_squash_merge=False)[0], "profile-merge-style")
    assert "allow_squash_merge" in sq.message


def test_policy_with_profile_and_git_ops_sections_validates(ra):
    policy = {"org": "acme", "profile": {"base": BASE_FILE, "pin": NEW, "guarded_overrides": "report"},
              "git_ops": {"repo": "acme/git-ops", "workflow": "tld-git-ops.yml", "allowlist": "allowlist.yml"}}
    assert ra.validate_policy(policy) == []
    assert ra.validate_policy({"org": "acme", "profile": {"base": BASE_FILE, "pin": "latest-tag"}}) == []
    assert any("profile" in e for e in ra.validate_policy({"org": "acme", "profile": {"pin": "latest-tag"}}))
    assert any("guarded_overrides" in e for e in ra.validate_policy({"org": "acme", "profile": {"base": BASE_FILE, "guarded_overrides": "all"}}))
    assert any("git_ops" in e for e in ra.validate_policy({"org": "acme", "git_ops": {"repository": "x"}}))
    lines = (TLD / "templates" / "admin-policy.yaml").read_text().splitlines()
    block = lines[next(i for i, l in enumerate(lines) if l.startswith("# profile:")):next(i for i, l in enumerate(lines) if l.startswith("secrets:"))]
    example = {k: v for k, v in yaml.safe_load("\n".join(l[2:] if l.startswith("# ") else l for l in block)).items()}
    assert set(example) == {"profile", "git_ops"}
    assert ra.validate_policy({"org": "acme", **example}) == []


@pytest.mark.parametrize("pin", ["v1.2.0", "main", "latest", "ABCDEF" * 6 + "abcd", "a" * 39, "a" * 41])
def test_policy_pin_tag_rejected(ra, pin):
    errors = ra.validate_policy({"org": "acme", "profile": {"base": BASE_FILE, "pin": pin}})
    assert errors and "profile.pin" in errors[0]
