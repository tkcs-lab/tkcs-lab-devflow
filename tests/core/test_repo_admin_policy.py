"""repo_admin_policy.py: the pure model of an inherited repo-admin policy."""
import copy
import json
import subprocess
import sys

import pytest
import yaml
from conftest import SRC, TLD

from tld.ops import repo_admin_policy as rp

BASE = "base acme/.github/tld/b.yaml@abcdef0"
OVR = "acme/app:.tld/admin-policy.yaml"


def ke(doc, kind="override", where=OVR, public=None):
    return rp.key_errors(doc, kind, where, public)


# --------------------------------------------------------------------------- key errors


@pytest.mark.parametrize("key", rp.ORG_LEVEL)
def test_key_errors_override_org_level(key):
    assert ke({key: {}}) == [f"{OVR}: '{key}' is organisation-level; only the organisation's policy and the files it extends may set it"]


@pytest.mark.parametrize("kind,where", [("override", OVR), ("base", BASE)])
def test_key_errors_override_run_only_keys(kind, where):
    for key in ("org", "repos"):
        assert ke({key: "x"}, kind, where) == [f"{where}: '{key}' is set only in the policy file you run"]
    expected = (f"{where}: sets 'extends'; an extended file cannot extend another" if kind == "base"
                else f"{where}: 'extends' is set only in the policy file you run")
    assert ke({"extends": []}, kind, where) == [expected]


def test_key_errors_override_workflow_entries():
    doc = {"workflows": [{"template": "release", "params": {"a": "b"}, "remove": True}, {"template": "land", "path": "x.yml"},
                         {"template": "land", "dest": "d.yml", "repos": ["a"]}]}
    msg = f"{OVR}: 'workflows[%d]': a repository override may set only template, params and remove"
    assert ke(doc) == [msg % 1, msg % 2]


def test_key_errors_base_per_repo_keys():
    doc = {"rulesets": {"default_branch": {"required_status_checks": ["t"]}}, "config_dirs": {"known": [".x"]}, "workflow_params": {}}
    assert ke(doc, "base", BASE) == [f"{BASE}: '{k}' is per repository; set it in each repository's override file"
                                     for k in ("rulesets.default_branch.required_status_checks", "config_dirs.known", "workflow_params")]
    assert ke({"rulesets": {"tags": True, "default_branch": {"admin_bypass": True}}, "config_dirs": {"forbid": [".a"]}}, "base", BASE) == []
    # an override and the run file may set the per-repository keys
    assert ke({"config_dirs": {"known": [".x"]}, "workflow_params": {"release": {"tag_prefix": "v"}}}) == []
    assert ke(doc, "run", "f") == []


ON = {"secrets.delete_unused": True, "variables.delete_unused": True, "labels.delete_unused": True,
      "labels.delete_unlisted": True, "webhooks.delete": ["hook"], "deploy_keys.delete_unused": True,
      "branches.delete_merged": True, "tokens.fine_grained.max_unused_days": 30, "tokens.fine_grained.revoke_expired": True}
OFF = {"secrets.delete_unused": False, "variables.delete_unused": False, "labels.delete_unused": False,
       "labels.delete_unlisted": False, "webhooks.delete": [], "deploy_keys.delete_unused": False,
       "branches.delete_merged": False, "tokens.fine_grained.revoke_expired": False}


def nest(dotted, value):
    doc, node = {}, None
    parts = dotted.split(".")
    node = doc
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return doc


def test_irreversible_table_matches_the_cases():
    assert set(ON) == set(rp.IRREVERSIBLE) and len(ON) == 9


@pytest.mark.parametrize("key", sorted(ON))
def test_key_errors_base_irreversible(key):
    assert ke(nest(key, ON[key]), "base", BASE) == [f"{BASE}: '{key}' turns on an irreversible change; set it only in the policy file you run"]
    if key in OFF:
        assert ke(nest(key, OFF[key]), "base", BASE) == []
    assert ke({key.split(".")[0]: {}}, "base", BASE) == []
    # the run file may switch it on
    assert ke(nest(key, ON[key]), "run", "f") == []


def test_key_errors_base_public_private_sections():
    for section in rp.PRIVATE_ONLY:
        got = ke({section: {}}, "base", BASE, public="acme/.github")
        assert got == [(f"{BASE}: '{section}' is organisation-private and acme/.github is public; keep org_settings, members, apps, "
                       "tokens, secrets and variables in a file of a private repository")]
        assert ke({section: {}}, "base", BASE) == []
        assert ke({section: {}}, "base", BASE, public=None) == []
    assert "the repository this file goes into is public" in ke({"apps": {}}, "base", "f.yaml", public="the repository this file goes into")[0]
    # the organisation-level sections that are not private-only stay allowed in a public base
    assert ke({"labels": {}, "profile": {}}, "base", BASE, public="acme/.github") == []


def test_key_errors_null():
    assert ke({"security": None}) == [f"{OVR}: 'security': null is not allowed"]
    assert ke({"security": {"secret_scanning": None}}, "base", BASE) == [f"{BASE}: 'security.secret_scanning': null is not allowed"]
    assert ke({"config_dirs": {"forbid": [None]}}) == [f"{OVR}: 'config_dirs.forbid[0]': null is not allowed"]
    assert ke({"security": None}, "run", "f") == []


def test_key_errors_base_extends():
    assert ke({"extends": ["a/b/c@" + "0" * 40]}, "base", BASE) == [f"{BASE}: sets 'extends'; an extended file cannot extend another"]


def test_key_errors_base_workflow_entries():
    doc = {"workflows": [{"template": "release"}, {"template": "land", "params": {"a": "b"}},
                         {"template": "land", "remove": True}, {"path": "x.yml", "dest": "d.yml", "repos": ["a"]}]}
    assert ke(doc, "base", BASE) == [
        f"{BASE}: 'workflows[1].params' is per repository; use workflow_params in each repository's override file",
        f"{BASE}: 'workflows[2].remove': a base may set only template",
        f"{BASE}: 'workflows[3].path': a base may set only template",
        f"{BASE}: 'workflows[3].dest': a base may set only template",
        f"{BASE}: 'workflows[3].repos': a base may set only template",
    ]
    assert ke({"workflows": [{"template": "release"}, {"template": "land"}]}, "base", BASE) == []


def test_kind_of():
    assert rp.kind_of({"org": "a"}) == "run"
    assert rp.kind_of({"org": "a", "extends": []}) == "run"
    assert rp.kind_of({"security": {}}) == "override"
    assert rp.kind_of({}) == "override"


def test_classes_cover_the_schema():
    schema = set(json.loads((TLD / "schema" / "admin-policy.schema.json").read_text())["properties"])
    classes = [set(rp.RUN_ONLY), set(rp.ORG_LEVEL), set(rp.OVERRIDABLE)]
    classified = set().union(*classes)
    assert schema <= classified, f"unclassified: {sorted(schema - classified)}"
    # plan 93 p4 adds `extends` and `workflow_params` to the schema; the tables already know them
    assert classified - schema <= {"extends", "workflow_params"}
    assert not set(rp.RUN_ONLY) & set(rp.ORG_LEVEL) and not set(rp.ORG_LEVEL) & set(rp.OVERRIDABLE)
    assert not set(rp.RUN_ONLY) & set(rp.OVERRIDABLE)
    assert set(rp.PRIVATE_ONLY) <= set(rp.ORG_LEVEL)
    for dotted in rp.IRREVERSIBLE + rp.GUARDED_KEYS:
        assert dotted.split(".")[0] in schema


# --------------------------------------------------------------------------- merge


def test_deep_merge_lists_replace():
    a = {"x": {"l": [1, 2], "k": 1, "n": {"a": 1}}, "y": 1}
    b = {"x": {"l": [3], "n": {"b": 2}}, "z": 2}
    before = copy.deepcopy((a, b))
    out = rp.deep_merge(a, b)
    assert out == {"x": {"l": [3], "k": 1, "n": {"a": 1, "b": 2}}, "y": 1, "z": 2}
    assert (a, b) == before
    out["x"]["n"]["a"] = 9
    out["z"] = 0
    assert (a, b) == before
    assert rp.deep_merge({"a": {"b": 1}}, {"a": 5}) == {"a": 5}


def test_merge_layers_sources():
    layers = [("base A", {"security": {"secret_scanning": True, "vulnerability_alerts": True}, "workflows": [{"template": "release"}]}),
              ("run", {"security": {"secret_scanning": False}, "config_dirs": {"forbid": [".a"]}}),
              ("override app", {"workflows": [{"template": "land"}], "rulesets": {"tags": True}})]
    merged, src = rp.merge_layers(layers)
    assert merged["security"] == {"secret_scanning": False, "vulnerability_alerts": True}
    assert src == {"security.secret_scanning": "run", "security.vulnerability_alerts": "base A", "config_dirs.forbid": "run",
                   "workflows": "override app", "rulesets.tags": "override app"}
    # a scalar replaced by a mapping drops the stale source
    merged, src = rp.merge_layers([("a", {"x": 5}), ("b", {"x": {"y": 1}})])
    assert src == {"x.y": "b"}


def test_clamp_irreversible():
    base_tokens = {"tokens": {"fine_grained": {"max_unused_days": 90}}}
    assert rp.clamp_irreversible(base_tokens, {"org": "a"})["tokens"]["fine_grained"] == {"max_unused_days": 90, "revoke_expired": False}
    # the run file has its own tokens.fine_grained: unchanged
    run = {"org": "a", "tokens": {"fine_grained": {"max_unused_days": 90}}}
    assert rp.clamp_irreversible(base_tokens, run) == base_tokens
    # an explicit value in the merge is kept
    explicit = {"tokens": {"fine_grained": {"revoke_expired": True}}}
    assert rp.clamp_irreversible(explicit, {"org": "a"}) == explicit
    # no tokens.fine_grained at all: nothing is added
    assert rp.clamp_irreversible({"security": {}}, {"org": "a"}) == {"security": {}}
    assert base_tokens == {"tokens": {"fine_grained": {"max_unused_days": 90}}}


ORG = {"workflows": [{"template": "release"}, {"template": "land"}], "security": {"secret_scanning": True}}


def test_apply_override_workflow_params():
    over = {"workflow_params": {"release": {"tag_prefix": "rel-", "version_style": "pep440"}}}
    eff = rp.apply_override(ORG, over)
    assert eff["workflows"] == [{"template": "release", "params": {"tag_prefix": "rel-", "version_style": "pep440"}}, {"template": "land"}]
    assert eff["workflow_params"] == over["workflow_params"]
    assert ORG["workflows"][0] == {"template": "release"}, "the organisation policy is not changed"
    # entry params first, workflow_params wins
    org = {"workflows": [{"template": "release", "params": {"tag_prefix": "v", "check_script": "x.sh"}}]}
    eff = rp.apply_override(org, {"workflow_params": {"release": {"tag_prefix": "r-"}}})
    assert eff["workflows"][0]["params"] == {"tag_prefix": "r-", "check_script": "x.sh"}
    # a template that is not in the list is left alone
    assert rp.apply_override(org, {"workflow_params": {"land": {"x": "y"}}})["workflows"] == org["workflows"]
    # no workflow_params at all: no key, an empty organisation one is dropped
    assert "workflow_params" not in rp.apply_override({**ORG, "workflow_params": {}}, {"security": {"secret_scanning": False}})


def test_apply_override_workflows_replace():
    eff = rp.apply_override(ORG, {"workflows": [{"template": "land"}], "security": {"vulnerability_alerts": True}})
    assert eff["workflows"] == [{"template": "land"}]
    assert eff["security"] == {"secret_scanning": True, "vulnerability_alerts": True}


# --------------------------------------------------------------------------- guarded settings


def test_loosened_each_group():
    def one(key, org_value, value):
        return rp.loosened(nest(key, org_value), nest(key, value))

    for key in rp.TRUE_KEYS:
        assert one(key, True, False) == [rp.Loosening(key, True, False)]
        assert one(key, True, True) == [] and one(key, False, True) == []
    for key in rp.FALSE_KEYS:
        assert one(key, False, True) == [rp.Loosening(key, False, True)]
        assert one(key, False, False) == [] and one(key, True, False) == []
    # ordered: stricter last
    assert one("workflow_lint.pin_actions", "third_party", "all") == []
    assert one("workflow_lint.pin_actions", "all", "third_party") == [rp.Loosening("workflow_lint.pin_actions", "all", "third_party")]
    assert one("actions.default_workflow_permissions", "read", "write") == [
        rp.Loosening("actions.default_workflow_permissions", "read", "write")]
    assert one("actions.default_workflow_permissions", "write", "read") == []
    assert one("agent.branch_policy", "default_branch", "protected_branches") != []
    assert one("agent.branch_policy", "protected_branches", "default_branch") == []
    # equal keys: any difference
    for key in rp.EQUAL_KEYS:
        assert one(key, True, False) != [] and one(key, False, True) != [] and one(key, True, True) == []
    # lists may not shrink, may grow
    assert one("config_dirs.forbid", [".a", ".b"], [".a"]) == [rp.Loosening("config_dirs.forbid", [".a", ".b"], [".a"])]
    assert one("config_dirs.require", ["A"], ["A", "B"]) == []
    # only keys the organisation sets are compared
    assert rp.loosened({}, {"security": {"secret_scanning": False}}) == []
    assert rp.loosened({"security": {"secret_scanning": True}}, {"rulesets": {"tags": False}}) == []
    assert len(rp.GUARDED_KEYS) == len(set(rp.GUARDED_KEYS)) == 8 + 2 + 3 + 3 + 2 and list(rp.GUARDED_KEYS) == sorted(rp.GUARDED_KEYS)


def test_clamp_guarded_restores_and_allows():
    org = {"security": {"secret_scanning": True}, "actions": {"default_workflow_permissions": "read"},
           "config_dirs": {"forbid": [".a", ".b", ".c"]}, "repo_settings": {"allow_squash_merge": False}}
    eff = {"security": {"secret_scanning": False}, "actions": {"default_workflow_permissions": "write"},
           "config_dirs": {"forbid": [".b", ".new"]}, "repo_settings": {"allow_squash_merge": True, "has_wiki": False}}
    before = copy.deepcopy(eff)
    out, found = rp.clamp_guarded(org, eff, set())
    assert eff == before
    assert out["security"]["secret_scanning"] is True and out["actions"]["default_workflow_permissions"] == "read"
    assert out["config_dirs"]["forbid"] == [".b", ".new", ".a", ".c"], "the dropped entries come back after the kept ones"
    assert out["repo_settings"] == {"allow_squash_merge": False, "has_wiki": False}
    assert [f.key for f in found] == ["actions.default_workflow_permissions", "config_dirs.forbid", "repo_settings.allow_squash_merge",
                                      "security.secret_scanning"]
    # an allowed key is neither reported nor clamped
    out, found = rp.clamp_guarded(org, eff, {"security.secret_scanning", "config_dirs.forbid"})
    assert out["security"]["secret_scanning"] is False and out["config_dirs"]["forbid"] == [".b", ".new"]
    assert [f.key for f in found] == ["actions.default_workflow_permissions", "repo_settings.allow_squash_merge"]
    # nothing loosened: nothing changes
    assert rp.clamp_guarded(org, org, set()) == (org, [])


def test_allowed_for_globs():
    run = {"org": "a", "repos": {"allow_loosen": {"app-*": ["security.secret_scanning"], "app-legacy": ["rulesets.tags"], "*": ["config_dirs.forbid"]}}}
    assert rp.allowed_for(run, "app-legacy") == {"security.secret_scanning", "rulesets.tags", "config_dirs.forbid"}
    assert rp.allowed_for(run, "app-x") == {"security.secret_scanning", "config_dirs.forbid"}
    assert rp.allowed_for(run, "App-x") == {"config_dirs.forbid"}, "case sensitive"
    assert rp.allowed_for({"org": "a"}, "app") == set()
    assert rp.allowed_for({"org": "a", "repos": {}}, "app") == set()


# --------------------------------------------------------------------------- logins


def test_derive_logins():
    assert rp.derive_logins(None) == (None, None, ["no profile"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "owner_login": "own"}}) == ("bot", "own", [])
    assert rp.derive_logins({"git": {"bot_login": "bot", "codeowners": ["boss"]}}) == ("bot", "boss", [])
    assert rp.derive_logins({"git": {"owner_login": "own"}}) == (None, "own", ["no git.bot_login"])
    assert rp.derive_logins({"git": {"bot_login": "bot"}}) == ("bot", None, ["no git.owner_login and not exactly one git.codeowners entry"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "codeowners": ["a", "b"]}})[2] == [
        "no git.owner_login and not exactly one git.codeowners entry"]
    for bad in ("acme/team", "@x", "-x", ""):
        assert rp.derive_logins({"git": {"bot_login": "bot", "codeowners": [bad]}}) == ("bot", None, ["git.codeowners entry is not a plain login"])
    # the reviewer is never the agent, whatever the case (GitHub logins are case-insensitive)
    assert rp.derive_logins({"git": {"bot_login": "bot", "codeowners": ["BoT"]}}) == ("bot", None, ["reviewer equals the agent login"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "codeowners": ["bot"]}}) == ("bot", None, ["reviewer equals the agent login"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "owner_login": "bot"}}) == ("bot", None, ["reviewer equals the agent login"])
    assert rp.derive_logins({"git": {"bot_login": "Bot", "owner_login": "bOT"}}) == ("Bot", None, ["reviewer equals the agent login"])
    # an invalid login is no login
    assert rp.derive_logins({"git": {"bot_login": "bo/t", "owner_login": "own"}}) == (None, "own", ["git.bot_login is not a plain login"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "owner_login": "o wn"}}) == ("bot", None, ["git.owner_login is not a plain login"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "owner_login": "acme/team"}})[1] is None
    # a trailing newline (a YAML block scalar) is not a plain login
    assert rp.derive_logins({"git": {"bot_login": "bot\n", "owner_login": "own"}}) == (None, "own", ["git.bot_login is not a plain login"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "owner_login": "bot\n"}}) == ("bot", None, ["git.owner_login is not a plain login"])
    assert rp.derive_logins({"git": {"bot_login": "bot", "codeowners": ["bot\n"]}}) == ("bot", None, ["git.codeowners entry is not a plain login"])
    assert rp.derive_logins({}) == (None, None, ["no git.bot_login", "no git.owner_login and not exactly one git.codeowners entry"])
    # owner_login wins over codeowners
    assert rp.derive_logins({"git": {"bot_login": "bot", "owner_login": "own", "codeowners": ["x"]}})[1] == "own"


def test_drop_derived():
    doc = {"agent": {"agent_login": "bot", "branch_policy": "default_branch"}, "release": {"reviewer_login": "own"}}
    before = copy.deepcopy(doc)
    assert rp.drop_derived(doc, "bot", "own") == {"agent": {"branch_policy": "default_branch"}}
    assert doc == before
    assert rp.drop_derived(doc, "other", "other") == doc
    assert rp.drop_derived(doc, None, None) == doc
    assert rp.drop_derived({"security": {}}, "bot", "own") == {"security": {}}


# --------------------------------------------------------------------------- converting and rendering


def test_legacy_to_override_minimal():
    org = {"security": {"secret_scanning": True, "vulnerability_alerts": True},
           "workflows": [{"template": "release"}, {"template": "land"}], "config_dirs": {"forbid": [".a"]}}
    legacy = {"org": "acme", "repos": {"exclude": ["x"]}, "_dir": "/p", "labels": {"sync": []}, "members": {"two_factor": True},
              "security": {"secret_scanning": True, "vulnerability_alerts": False},
              "workflows": [{"template": "release", "params": {"tag_prefix": "rel-"}}, {"template": "land"}],
              "config_dirs": {"forbid": [".a"], "known": [".cursor"]},
              "rulesets": {"default_branch": {"required_status_checks": ["t"]}}}
    over, notes = rp.legacy_to_override(legacy, org)
    assert over == {"security": {"vulnerability_alerts": False},
                    "workflows": [{"template": "release", "params": {"tag_prefix": "rel-"}}, {"template": "land"}],
                    "config_dirs": {"known": [".cursor"]}, "rulesets": {"default_branch": {"required_status_checks": ["t"]}}}
    assert notes == ["dropped organisation-level section 'labels'", "dropped organisation-level section 'members'"]
    # identical workflows (compared as a whole list) vanish
    same, _ = rp.legacy_to_override({"org": "a", "workflows": org["workflows"]}, org)
    assert same == {}
    assert rp.legacy_to_override({"org": "a"}, {}) == ({}, [])


def test_propose_override_keeps_existing():
    detected = {"rulesets": {"default_branch": {"required_status_checks": ["a", "b"]}}, "workflow_params": {"release": {"tag_prefix": "v"}}}
    existing = {"rulesets": {"default_branch": {"required_status_checks": ["mine"], "admin_bypass": False}}}
    out = rp.propose_override(existing, detected)
    assert out["rulesets"]["default_branch"] == {"required_status_checks": ["mine"], "admin_bypass": False}
    assert out["workflow_params"] == {"release": {"tag_prefix": "v"}}
    assert rp.propose_override(None, detected) == detected
    assert existing["rulesets"]["default_branch"]["required_status_checks"] == ["mine"]


def test_render_override_header():
    text = rp.render_override({"rulesets": {"default_branch": {"required_status_checks": ["b", "a"]}}, "security": {"secret_scanning": True}})
    lines = text.splitlines()
    assert lines[0] == "# Repository override of the organisation's repo-admin policy (docs/guides/admin.md)."
    assert lines[1] == "# Only what differs from the organisation policy belongs here."
    assert yaml.safe_load(text) == {"rulesets": {"default_branch": {"required_status_checks": ["b", "a"]}}, "security": {"secret_scanning": True}}
    assert text.index("rulesets:") < text.index("security:"), "key order is kept"
    # a hostile name stays data
    nasty = rp.render_override({"rulesets": {"default_branch": {"required_status_checks": ["a: b\n- x", "{{c}}"]}}})
    assert yaml.safe_load(nasty)["rulesets"]["default_branch"]["required_status_checks"] == ["a: b\n- x", "{{c}}"]


def test_explain_lines():
    merged = {"security": {"secret_scanning": True}, "workflows": [{"template": "release"}], "config_dirs": {"forbid": [".a"]}, "agent": {}}
    sources = {"security.secret_scanning": "base x@abc1234", "workflows": "override app", "config_dirs.forbid": "run"}
    assert rp.explain_lines(merged, sources) == [
        "agent = {}  # ",
        'config_dirs.forbid = [".a"]  # run',
        "security.secret_scanning = true  # base x@abc1234",
        'workflows = [{"template":"release"}]  # override app',
    ]


def test_policy_module_does_not_import_repo_admin():
    code = (f"import sys; sys.path.insert(0, {str(SRC)!r}); import tld.ops.repo_admin_policy; "
            "assert 'tld.ops.repo_admin' not in sys.modules")
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
