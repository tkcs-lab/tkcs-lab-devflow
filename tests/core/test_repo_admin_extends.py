"""repo_admin_extends.py: resolving `extends` through the API against a fake GitHub (no network)."""
import pytest

import test_repo_admin as fake_mod
from test_repo_admin import Fake


@pytest.fixture(autouse=True)
def _bind(ra):
    fake_mod.ApiErr = ra.ApiError


@pytest.fixture
def ext(ra):
    from tld.ops import repo_admin_extends
    return repo_admin_extends


SHA_A, SHA_B = "a" * 40, "b" * 40
BASE_PATH, ORG_PATH = "tld/admin-policy-base.yaml", "tld/admin-policy-org.yaml"
BASE_PIN = f"acme/.github/{BASE_PATH}@{SHA_A}"
ORG_PIN = f"acme/git-ops/{ORG_PATH}@{SHA_B}"
BASE_TEXT = "security: {vulnerability_alerts: true}\nrulesets: {tags: true}\nrelease: {environment: tld-release}\n"
ORG_TEXT = "members: {max_owners: 3}\nrelease: {environment: other}\n"


def serve(routes, repo, path, sha, text, *, private=True, visibility="private", status="behind", default="main"):
    """Routes for one pinned file; the contents answer a missing file for any other ref."""
    base = f"/repos/{repo}"
    routes[("GET", base)] = {"default_branch": default, "private": private, "visibility": visibility}
    routes[("GET", f"{base}/compare/{default}...{sha}")] = {"status": status}

    def answer(params):
        if params.get("ref") != sha:
            return fake_mod.ApiErr(404, "Not Found", "GET", "x")
        return text
    routes[("GET", f"{base}/contents/{path}")] = answer
    return routes


def world(base_text=BASE_TEXT, org_text=ORG_TEXT, **kw):
    routes = {}
    serve(routes, "acme/.github", BASE_PATH, SHA_A, base_text, private=False, visibility="public")
    serve(routes, "acme/git-ops", ORG_PATH, SHA_B, org_text, **kw)
    return Fake(routes)


def run(*pins, **extra):
    return {"org": "acme", "extends": list(pins), **extra}


def test_small_policy_resolves(ra, ext):
    out = ext.resolve(world(), run(BASE_PIN, ORG_PIN))
    assert out.errors == [] and out.policy is not None
    pol = out.policy
    assert pol["org"] == "acme" and pol["members"] == {"max_owners": 3}
    assert pol["security"] == {"vulnerability_alerts": True} and pol["rulesets"] == {"tags": True}
    assert pol["release"] == {"environment": "other"}  # the later layer wins
    assert pol["_inherited"] is True
    assert pol["_extends"] == [f"acme/.github/{BASE_PATH}@aaaaaaa", f"acme/git-ops/{ORG_PATH}@bbbbbbb"] == out.labels
    assert "extends" not in pol
    clean = {k: v for k, v in pol.items() if not k.startswith("_")}
    assert ra.validate_policy(clean, kind="run", inherited=True) == []
    assert out.sources["release.environment"] == f"base acme/git-ops/{ORG_PATH}@bbbbbbb"
    assert out.sources["org"] == "run"


def test_pin_is_not_a_commit(ext):
    out = ext.resolve(world(), run(f"acme/.github/{BASE_PATH}@v1"))
    assert out.policy is None
    assert out.errors == ["'extends[0]': '@v1' is not a commit SHA; pin the base by its full 40-hex commit (a tag can move): "
                          f"run tld ops repo-admin latest-pin acme/.github/{BASE_PATH}"]
    out = ext.resolve(world(), run("nonsense"))
    assert out.errors == ["'extends[0]': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got 'nonsense')"]
    out = ext.resolve(world(), run(*[f"acme/r{i}/x.yaml@{SHA_A}" for i in range(5)]))
    assert out.policy is None and out.errors == ["'extends': at most 4 entries (got 5)"]
    out = ext.resolve(world(), {"org": "acme", "extends": {"a": 1}})
    assert out.errors == ["'extends': must be a string or a list of one to four strings"]


def test_pin_is_not_on_the_default_branch(ext):
    routes = serve({}, "acme/.github", BASE_PATH, SHA_A, BASE_TEXT, status="ahead")
    out = ext.resolve(Fake(routes), run(BASE_PIN))
    assert out.policy is None
    assert out.errors == ["'extends[0]': aaaaaaa is not on the default branch of acme/.github; pin a commit that was merged there"]
    for status in ("diverged", "behind", "identical"):
        routes = serve({}, "acme/.github", BASE_PATH, SHA_A, BASE_TEXT, status=status)
        assert bool(ext.resolve(Fake(routes), run(BASE_PIN)).policy) == (status != "diverged")


def test_token_like_text(ext):
    secret = "ghp_" + "a" * 36
    out = ext.resolve(world(base_text=f"security: {{vulnerability_alerts: true}}\n# {secret}\n"), run(BASE_PIN))
    assert out.policy is None and len(out.errors) == 1
    assert "line 2 looks like a GitHub token" in out.errors[0] and secret not in out.errors[0]
    assert out.errors[0].startswith(f"base acme/.github/{BASE_PATH}@aaaaaaa: refused:")
    out = ext.resolve(world(base_text="labels:\n  password: hello\n"), run(BASE_PIN))
    assert out.policy is None and any("key named like a credential" in e and "hello" not in e for e in out.errors)
    # an allow mark does not exempt a line
    out = ext.resolve(world(base_text=f"# {secret}  # tld-allow-secret\n"), run(BASE_PIN))
    assert out.policy is None and any("looks like a GitHub token" in e for e in out.errors)


def test_organisation_private_section_in_a_public_repository(ext):
    private_text = "members: {max_owners: 3}\n"
    for private, visibility, refused in ((False, "public", True), (True, "private", False), (True, "internal", True),
                                         (False, "private", True), (None, None, True)):
        routes = serve({}, "acme/shared", ORG_PATH, SHA_B, private_text, private=private, visibility=visibility)
        out = ext.resolve(Fake(routes), run(f"acme/shared/{ORG_PATH}@{SHA_B}"))
        if refused:
            assert out.policy is None
            assert any("'members' is organisation-private and acme/shared is public" in e for e in out.errors), out.errors
        else:
            assert out.errors == [] and out.policy["members"] == {"max_owners": 3}
    # a public file without private sections is fine
    assert ext.resolve(world(), run(BASE_PIN)).errors == []


def test_irreversible_switch_in_an_inherited_file(ext):
    out = ext.resolve(world(org_text="branches: {delete_merged: true}\n"), run(BASE_PIN, ORG_PIN))
    assert out.policy is None
    assert any("'branches.delete_merged' turns on an irreversible change; set it only in the policy file you run" in e
               for e in out.errors)
    # an off value is fine
    assert ext.resolve(world(org_text="branches: {delete_merged: false}\n"), run(BASE_PIN, ORG_PIN)).errors == []
    # a base that supplies tokens.fine_grained leaves revoke_expired off for a run file without it
    tokens = "tokens: {fine_grained: {}}\n"
    out = ext.resolve(world(org_text=tokens), run(BASE_PIN, ORG_PIN))
    assert out.errors == []
    assert out.policy["tokens"]["fine_grained"]["revoke_expired"] is False
    own = run(BASE_PIN, ORG_PIN, tokens={"fine_grained": {"revoke_expired": True}})
    assert ext.resolve(world(org_text=tokens), own).policy["tokens"]["fine_grained"]["revoke_expired"] is True


def test_chained_extends(ext):
    out = ext.resolve(world(base_text=f"extends: ['{ORG_PIN}']\n"), run(BASE_PIN))
    assert out.policy is None
    assert any(f"base acme/.github/{BASE_PATH}@aaaaaaa: sets 'extends'; an extended file cannot extend another" in e
               for e in out.errors)


def test_base_with_an_unknown_key_is_refused(ext):
    out = ext.resolve(world(base_text="no_such_section: {a: 1}\n"), run(BASE_PIN))
    assert out.policy is None and out.errors
    assert all(e.startswith(f"base acme/.github/{BASE_PATH}@aaaaaaa: ") for e in out.errors)
    assert any("no_such_section" in e for e in out.errors)
    out = ext.resolve(world(base_text="security: {vulnerability_alerts: 3}\n"), run(BASE_PIN))
    assert out.policy is None and out.errors
    out = ext.resolve(world(base_text="org: acme\n"), run(BASE_PIN))
    assert any("'org' is set only in the policy file you run" in e for e in out.errors)
    out = ext.resolve(world(base_text="*alias\n"), run(BASE_PIN))
    assert out.policy is None and out.errors


def test_two_layers_later_wins(ext):
    first = "actions: {default_workflow_permissions: read}\nconfig_dirs: {forbid: ['.one', '.two']}\n"
    second = "config_dirs: {forbid: ['.three']}\n"
    out = ext.resolve(world(base_text=first, org_text=second), run(BASE_PIN, ORG_PIN))
    assert out.policy["config_dirs"]["forbid"] == [".three"]  # lists replace
    assert out.policy["actions"] == {"default_workflow_permissions": "read"}
    out = ext.resolve(world(base_text=first, org_text=second), run(ORG_PIN, BASE_PIN))
    assert out.policy["config_dirs"]["forbid"] == [".one", ".two"]
    # the run file is last
    own = run(BASE_PIN, ORG_PIN, config_dirs={"forbid": [".mine"]})
    out = ext.resolve(world(base_text=first, org_text=second), own)
    assert out.policy["config_dirs"]["forbid"] == [".mine"] and out.sources["config_dirs.forbid"] == "run"


def test_duplicate_entry(ext):
    out = ext.resolve(world(), run(BASE_PIN, f"ACME/.github/{BASE_PATH}@{SHA_B}"))
    assert out.policy is None
    assert out.errors == [f"'extends': acme/.github/{BASE_PATH} is listed twice"]


def test_empty_extends_is_not_inherited(ext):
    for doc in ({"org": "acme"}, {"org": "acme", "extends": []}, {"org": "acme", "extends": None}):
        fake = Fake({})
        out = ext.resolve(fake, doc)
        assert out.policy is doc and out.errors == [] and "_inherited" not in out.policy and fake.reads == []
    out = ext.resolve(world(), {"org": "acme", "extends": BASE_PIN})  # a string is one entry
    assert out.errors == [] and out.policy["_inherited"] is True


def test_cannot_read_a_private_file(ra, ext):
    routes = serve({}, "acme/git-ops", ORG_PATH, SHA_B, ORG_TEXT)
    routes[("GET", f"/repos/acme/git-ops/contents/{ORG_PATH}")] = ra.ApiError(404, "Not Found", "GET", "x")
    out = ext.resolve(Fake(routes), run(ORG_PIN))
    assert out.policy is None
    assert out.errors == [f"'extends[0]': cannot read acme/git-ops/{ORG_PATH}@bbbbbbb (HTTP 404: Not Found); a private file "
                          "needs a token that can read it (GH_TOKEN, GITHUB_TOKEN or gh auth login)"]
    out = ext.resolve(Fake({}), run(ORG_PIN))  # the repository itself is unreadable
    assert out.policy is None and "cannot read" in out.errors[0] and "HTTP 404" in out.errors[0]
    # every file is tried: two failures give two errors
    out = ext.resolve(Fake({}), run(BASE_PIN, ORG_PIN))
    assert len(out.errors) == 2


def test_run_file_loosening_is_recorded(ext):
    strict = "security: {secret_scanning: true}\nactions: {default_workflow_permissions: read}\n"
    own = run(BASE_PIN, security={"secret_scanning": False}, actions={"default_workflow_permissions": "write"})
    out = ext.resolve(world(base_text=strict), own)
    assert out.errors == []
    assert sorted(out.policy["_run_loosenings"]) == [("actions.default_workflow_permissions", "read", "write"),
                                                     ("security.secret_scanning", True, False)]
    # it is reported, not clamped: the run file is the owner's
    assert out.policy["security"]["secret_scanning"] is False
    assert ext.resolve(world(base_text=strict), run(BASE_PIN)).policy["_run_loosenings"] == []


def tag_world(tags, with_file, head_has_file=True, default="main"):
    routes = {("GET", "/repos/acme/.github/tags"): [{"name": n, "commit": {"sha": s}} for n, s in tags]}
    routes[("GET", "/repos/acme/.github")] = {"default_branch": default}
    routes[("GET", f"/repos/acme/.github/branches/{default}")] = {"commit": {"sha": "c" * 40}}
    has = set(with_file) | ({"c" * 40} if head_has_file else set())

    def contents(params):
        return {"name": "x"} if params.get("ref") in has else fake_mod.ApiErr(404, "Not Found", "GET", "x")
    routes[("GET", f"/repos/acme/.github/contents/{BASE_PATH}")] = contents
    return Fake(routes)


def test_latest_pin_picks_the_newest_tag_with_the_file(ext):
    tags = [("v1", "1" * 40), ("v10", "a" * 40), ("v9", "9" * 40), ("v2.1", "2" * 40), ("nightly", "f" * 40), ("v11", "b" * 40)]
    fake = tag_world(tags, with_file=["a" * 40, "9" * 40, "1" * 40])
    assert ext.latest_pin(fake, f"acme/.github/{BASE_PATH}") == ("a" * 40, "v10")  # v11 lacks the file, v10 after v9 by number


def test_latest_pin_without_tags(ext):
    fake = tag_world([("nightly", "f" * 40)], with_file=[])
    assert ext.latest_pin(fake, f"acme/.github/{BASE_PATH}") == ("c" * 40, None)
    fake = tag_world([], with_file=[])
    assert ext.latest_pin(fake, f"acme/.github/{BASE_PATH}") == ("c" * 40, None)
    with pytest.raises(ValueError, match=r"^latest-pin: 'nonsense' must be <owner>/<repo>/<path>$"):
        ext.latest_pin(fake, "nonsense")


def test_latest_pin_missing_file(ext):
    fake = tag_world([("v1", "1" * 40)], with_file=[], head_has_file=False)
    with pytest.raises(LookupError, match=rf"^latest-pin: {BASE_PATH} does not exist in acme/.github$"):
        ext.latest_pin(fake, f"acme/.github/{BASE_PATH}")
    # at most 20 tags are tried
    many = [(f"v{i}", f"{i:040x}") for i in range(1, 30)]
    fake = tag_world(many, with_file=[], head_has_file=False)
    with pytest.raises(LookupError):
        ext.latest_pin(fake, f"acme/.github/{BASE_PATH}")
    tried = [p for p in fake.reads if p.endswith(BASE_PATH)]
    assert len(tried) == 21  # twenty tags and the default branch head

