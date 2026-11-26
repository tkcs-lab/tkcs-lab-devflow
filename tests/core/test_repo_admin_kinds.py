"""repo_admin.validate_policy: the kinds run, override and base, the new keys and the three starters."""
import re

import pytest
import yaml

from conftest import ROOT, TLD, FORBIDDEN

TEMPLATES = TLD / "templates"
STARTER = TEMPLATES / "admin-policy.yaml"
BASE = TEMPLATES / "admin-policy-base.yaml"
ORG = TEMPLATES / "admin-policy-org.yaml"
PIN = "acme/.github/tld/admin-policy-base.yaml@" + "a" * 40


def has(errors, needle):
    return any(needle in e for e in errors)


def test_organisation_level_key_in_an_override(ra):
    for doc, key in (({"labels": {"keep": ["x"]}}, "labels"), ({"org": "acme"}, "org"),
                     ({"extends": [PIN]}, "extends"), ({"repos": {"exclude": ["x"]}}, "repos")):
        errors = ra.validate_policy(doc, kind="override", where="acme/app:.tld/admin-policy.yaml")
        assert errors and all(e.startswith("acme/app:.tld/admin-policy.yaml: ") for e in errors), errors
        assert has(errors, f"'{key}' is "), errors
    errors = ra.validate_policy({"labels": {"keep": ["x"]}}, kind="override", where="w")
    assert errors == ["w: 'labels' is organisation-level; only the organisation's policy and the files it extends may set it"]
    errors = ra.validate_policy({"workflows": [{"template": "land", "path": "x.yml"}]}, kind="override", where="w")
    assert has(errors, "give exactly one") or has(errors, "a repository override may set only template, params and remove")
    errors = ra.validate_policy({"workflows": [{"template": "land", "dest": ".github/workflows/x.yml"}]}, kind="override", where="w")
    assert errors == ["w: 'workflows[0]': a repository override may set only template, params and remove"]


@pytest.mark.parametrize("doc,key", [
    ({"rulesets": {"default_branch": {"required_status_checks": ["test"]}}}, "rulesets.default_branch.required_status_checks"),
    ({"workflow_params": {"release": {"tag_prefix": "v"}}}, "workflow_params"),
    ({"config_dirs": {"known": [".cursor"]}}, "config_dirs.known"),
])
def test_per_repository_key_in_a_base(ra, doc, key):
    errors = ra.validate_policy(doc, kind="base", where="base a/b/c@1234567")
    assert errors == [f"base a/b/c@1234567: '{key}' is per repository; set it in each repository's override file"]


def test_per_repository_workflow_params_in_a_base(ra):
    errors = ra.validate_policy({"workflows": [{"template": "release", "params": {"tag_prefix": "v"}}]}, kind="base", where="b")
    assert errors == ["b: 'workflows[0].params' is per repository; use workflow_params in each repository's override file"]
    # the same keys are fine in an override and in the file you run
    assert ra.validate_policy({"workflow_params": {"release": {"tag_prefix": "v"}}, "config_dirs": {"known": [".cursor"]},
                               "rulesets": {"default_branch": {"required_status_checks": ["t"]}}}, kind="override") == []
    assert ra.validate_policy({"org": "acme", "config_dirs": {"known": [".cursor"]}}) == []


def test_policy_without_extends(ra):
    assert ra.validate_policy(yaml.safe_load(STARTER.read_text()), STARTER.parent) == []
    real = yaml.safe_load((ROOT / ".tld" / "admin-policy.yaml").read_text())
    assert "extends" not in real
    assert ra.validate_policy(real, ROOT / ".tld") == []
    old = {"org": "a", "agent": {"agent_login": "bot"}, "release": {"reviewer_login": "owner"}}
    assert ra.validate_policy(old) == []
    assert ra.validate_policy({"org": "a", "agent": {}}) == ["missing required key 'agent.agent_login'"]
    assert ra.validate_policy({"org": "a", "release": {}}) == ["missing required key 'release.reviewer_login'"]
    assert ra.validate_policy({"org": "a", "extends": []} | {"agent": {}}) == ["missing required key 'agent.agent_login'"]
    assert ra.validate_policy({}) == ["missing required key 'org'"]


def test_inherited_validation_skips_the_login_rule(ra):
    doc = {"org": "a", "agent": {"branch_policy": "default_branch"}, "release": {"environment": "tld-release"}}
    assert ra.validate_policy(doc, inherited=True) == []
    assert ra.validate_policy(doc | {"extends": [PIN]}) == []
    assert ra.validate_policy(doc | {"extends": PIN}) == []
    assert ra.validate_policy(doc | {"extends": []}) != []
    # a login that is given is still checked, and a trailing newline is not a login
    for login in ("-bad", "bad-", "bot\n", "a b"):
        assert ra.validate_policy({"org": "a", "agent": {"agent_login": login}}, inherited=True), login
        assert ra.validate_policy({"org": "a", "release": {"reviewer_login": login}}, inherited=True), login
    assert ra.validate_policy({"org": "a", "agent": {"agent_login": "bot-1"}}, inherited=True) == []


def test_login_pattern_rejects_a_trailing_newline(ra):
    for section, key in (("agent", "agent_login"), ("release", "reviewer_login")):
        errors = ra.validate_policy({"org": "a", section: {key: "owner\n"}})
        assert has(errors, f"'{section}.{key}': does not match"), errors
    assert ra.validate_policy({"org": "a", "agent": {"agent_login": "bot"}, "release": {"reviewer_login": "owner"}}) == []


def test_override_and_base_need_no_org(ra):
    assert ra.validate_policy({"security": {"secret_scanning": True}}, kind="override") == []
    assert ra.validate_policy({"security": {"secret_scanning": True}}, kind="base") == []
    assert ra.validate_policy({"agent": {"branch_policy": "default_branch"}}, kind="override") == []
    assert ra.validate_policy({"release": {"environment": "tld-release"}}, kind="base") == []
    # the schema still rejects an unknown key and a wrong value in every kind
    assert has(ra.validate_policy({"secuurity": {}}, kind="override"), "unknown key 'secuurity'")
    assert has(ra.validate_policy({"actions": {"default_workflow_permissions": "x"}}, kind="base"), "must be one of")
    assert ra.validate_policy([], kind="base") == ["the policy must be a YAML mapping"]


def test_run_policy_still_needs_org(ra):
    assert ra.validate_policy({}) == ["missing required key 'org'"]
    assert ra.validate_policy({}, kind="run") == ["missing required key 'org'"]
    assert ra.validate_policy({"security": {}}, inherited=True) == ["missing required key 'org'"]


def test_override_path_and_allow_loosen_checked(ra):
    ok = {"org": "a", "repos": {"override_path": ".tld/admin-policy.yaml",
                                "allow_loosen": {"legacy-*": ["security.secret_scanning", "actions.default_workflow_permissions"]}}}
    assert ra.validate_policy(ok) == []
    for path in ("/etc/x.yaml", "../x.yaml", "a/../../x.yaml"):
        errors = ra.validate_policy({"org": "a", "repos": {"override_path": path}})
        assert errors == ["'repos.override_path': must be a path below the repository root (no absolute path, no '..')"], path
    errors = ra.validate_policy({"org": "a", "repos": {"allow_loosen": {"x": ["security.nope", "security.secret_scanning"]}}})
    assert errors == ["'repos.allow_loosen': 'security.nope' is not a guarded key"]
    assert has(ra.validate_policy({"org": "a", "repos": {"allow_loosen": {"x": "security.secret_scanning"}}}), "'repos.allow_loosen.x'")
    assert has(ra.validate_policy({"org": "a", "repos": {"allow_loosen": ["x"]}}), "'repos.allow_loosen'")
    assert has(ra.validate_policy({"org": "a", "repos": {"override_path": 3}}), "'repos.override_path'")


def test_workflow_params_values_are_checked(ra):
    assert ra.validate_policy({"org": "a", "workflow_params": {"release": {"version_style": "pep440", "create_release": "false",
                                                                          "check_script": "scripts/x.py", "tag_prefix": "v"}}}) == []
    errors = ra.validate_policy({"org": "a", "workflow_params": {"release": {"tag_prefix": "v;rm", "version_style": "calver",
                                                                             "check_script": "../x"}}})
    assert "'workflow_params.release.tag_prefix': must be a string of letters, digits and . _ / - only" in errors
    assert "'workflow_params.release.version_style': must be one of semver, pep440" in errors
    assert "'workflow_params.release.check_script': must be a path inside the repository" in errors
    assert has(ra.validate_policy({"workflow_params": {"release": {"check_script": "/x"}}}, kind="override"),
               "'workflow_params.release.check_script'")
    assert has(ra.validate_policy({"org": "a", "workflow_params": {"land": {}}}), "unknown key 'workflow_params.land'")
    assert has(ra.validate_policy({"org": "a", "workflow_params": {"release": {"x": 3}}}), "'workflow_params.release.x'")


def test_extends_shape_in_the_schema(ra):
    assert ra.validate_policy({"org": "a", "extends": [PIN, PIN.replace("base", "org")]}) == []
    assert has(ra.validate_policy({"org": "a", "extends": 3}), "'extends'")
    # the schema checker has no maxItems: the limit of four is parse_list's rule (plan 93, p3)
    assert has(ra.validate_policy({"org": "a", "extends": [1]}), "'extends[0]'")


def test_templates_validate(ra):
    assert ra.validate_policy(yaml.safe_load(STARTER.read_text()), STARTER.parent) == []
    base = yaml.safe_load(BASE.read_text())
    assert ra.validate_policy(base, kind="base", where="base", public="acme/.github") == []
    lines = ORG.read_text().splitlines()
    example = "\n".join(line[2:] for line in lines if line.startswith("# "))  # prose lines start with ##
    org = yaml.safe_load(example)
    assert set(org) == {"org_settings", "members", "apps", "tokens", "secrets", "variables", "profile", "git_ops"}
    assert ra.validate_policy(org, kind="base", where="base") == []
    # the file as shipped holds only comments: nothing is managed until the owner uncomments a section
    assert yaml.safe_load(ORG.read_text()) is None
    starter = yaml.safe_load(STARTER.read_text())
    assert starter["extends"] == [] and starter["workflow_params"] == {}


def test_base_template_has_no_private_section(ra):
    base = yaml.safe_load(BASE.read_text())
    from tld.ops import repo_admin_policy as pol
    assert not set(base) & set(pol.ORG_LEVEL)
    assert not set(base) & set(pol.RUN_ONLY)
    assert "workflow_params" not in base
    assert base["workflows"] == [{"template": "release"}, {"template": "land"}]
    assert base["rulesets"] == {"default_branch": {"admin_bypass": True}, "tags": True}
    assert ra.validate_policy(base, kind="base", where="b", public="acme/.github") == []
    for key in pol.IRREVERSIBLE:
        node = base
        for part in key.split("."):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        assert node == {}, key
    text = BASE.read_text()
    assert "tld ops repo-admin validate-policy --kind base --public" in text and "public" in text
    # no irreversible switch and no private section in the org example either
    example = "\n".join(line[2:] for line in ORG.read_text().splitlines() if line.startswith("# "))
    assert not re.search(r"delete_unused|delete_unlisted|delete_merged|max_unused_days|revoke_expired|^webhooks", example, re.M)
    for path in (BASE, ORG, STARTER):
        assert FORBIDDEN.search(path.read_text()) is None, path


def test_workflow_params_release_takes_only_the_four_keys(ra):
    for key in ("main_branch", "release_environment", "environment", "dest"):
        for kind in ("override", "run"):
            doc = {"workflow_params": {"release": {key: "x"}}} | ({"org": "a"} if kind == "run" else {})
            errors = ra.validate_policy(doc, kind=kind)
            assert has(errors, f"unknown key 'workflow_params.release.{key}'"), (key, kind, errors)
    four = {"tag_prefix": "v", "version_style": "semver", "check_script": "s.py", "create_release": "true"}
    assert ra.validate_policy({"workflow_params": {"release": four}}, kind="override") == []


def test_override_workflow_params_are_limited_to_the_four_keys(ra):
    where = "acme/app:.tld/admin-policy.yaml"
    for key in ("main_branch", "release_environment", "environment"):
        errors = ra.validate_policy({"workflows": [{"template": "release", "params": {key: "x"}}]}, kind="override", where=where)
        assert errors == [f"{where}: 'workflows[0].params.{key}': a repository override may set only "
                          "tag_prefix, version_style, check_script, create_release"], errors
    ok = {"workflows": [{"template": "release", "params": {"tag_prefix": "v", "version_style": "pep440"}}, {"template": "land"}]}
    assert ra.validate_policy(ok, kind="override", where=where) == []
    # the file you run and a base are unchanged: main_branch stays allowed in the run file
    run = {"org": "a", "workflows": [{"template": "release", "params": {"main_branch": "trunk", "tag_prefix": "v"}}]}
    assert ra.validate_policy(run) == []


def test_a_trailing_newline_is_not_a_safe_value(ra):
    assert ra.SAFE_PARAM.fullmatch("v") and not ra.SAFE_PARAM.fullmatch("v\n")
    errors = ra.validate_policy({"org": "a", "workflows": [{"template": "release", "params": {"tag_prefix": "v\n"}}]})
    assert errors == ["'workflows[0].params.tag_prefix': must be a string of letters, digits and . _ / - only"]
    errors = ra.validate_policy({"workflow_params": {"release": {"tag_prefix": "v\n"}}}, kind="override")
    assert errors == ["'workflow_params.release.tag_prefix': must be a string of letters, digits and . _ / - only"]
    for doc in ({"org": "acme\n"}, {"org": "a", "release": {"environment": "tld-release\n"}},
                {"org": "a", "workflows": [{"template": "land", "dest": ".github/workflows/x.yml\n"}]}):
        assert ra.validate_policy(doc), doc


def test_an_unknown_kind_raises(ra):
    for kind in ("", "legacy", "Run", None):
        with pytest.raises(ValueError):
            ra.validate_policy({"org": "a"}, kind=kind)
    assert ra.validate_policy({"org": "a"}, kind="run") == []


def test_the_schema_patterns_avoid_the_python_only_end_anchor():
    import json
    text = (TLD / "schema" / "admin-policy.schema.json").read_text()
    assert "\\\\Z" not in text
    for login in ("agent", "release"):
        key = "agent_login" if login == "agent" else "reviewer_login"
        pattern = json.loads(text)["properties"][login]["properties"][key]["pattern"]
        assert pattern.endswith("(?![\\s\\S])")
