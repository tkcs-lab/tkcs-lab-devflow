"""Profile keys `agents` and `docs.website`: schema, semantic errors, starter copy."""
import copy

import pytest
import yaml

from conftest import TLD, FIXTURES
from test_validate_profile import MINIMAL


def load_fixture():
    return yaml.safe_load((FIXTURES / "roles-toolkit.yaml").read_text())


def errs(vp, profile):
    return vp.validate(profile, None)[0]


def with_agents(agents, website=True):
    p = copy.deepcopy(MINIMAL)
    if website:
        p["docs"]["website"] = {"dir": "site", "build": "npm run build"}
    p["roles"] = agents
    return p


def test_fixture_validates(vp):
    errors, _, resolved = vp.validate(load_fixture(), None)
    assert errors == []
    assert resolved["docs"]["website"]["dir"] == "site"
    assert resolved["roles"]["posture"] == {"security": "critical"}


def test_profile_without_the_keys_resolves_without_them(vp):
    errors, _, resolved = vp.validate(copy.deepcopy(MINIMAL), None)
    assert errors == []
    assert "roles" not in resolved
    assert "website" not in resolved["docs"]


def test_privacyfence_fixture_still_validates(vp):
    profile = yaml.safe_load((FIXTURES / "privacyfence-toolkit.yaml").read_text())
    assert vp.validate(profile, None)[0] == []


def test_disabled_and_required(vp):
    p = with_agents({"disable": ["tech-writer"], "required": [{"role": "tech-writer", "at": ["dod"]}]})
    assert errs(vp, p) == ["'roles.required[0]': 'tech-writer' is listed in 'roles.disable'"]


def test_website_maintainer_needs_docs_website(vp):
    p = with_agents({"required": [{"role": "website-maintainer", "at": ["dod"]}]}, website=False)
    assert errs(vp, p) == ["'roles.required[0]': 'website-maintainer' needs 'docs.website'"]


def test_website_maintainer_with_docs_website_is_valid(vp):
    p = with_agents({"required": [{"role": "website-maintainer", "at": ["dod", "review"]}]})
    assert errs(vp, p) == []


def test_when_needs_a_diff_point(vp):
    p = with_agents({"required": [{"role": "tech-writer", "at": ["make_plan", "review"], "when": ["docs/**"]}]})
    assert errs(vp, p) == [
        "'roles.required[0].when': needs a diff, but 'at' has no point with a diff "
        "(only 'make_plan' and 'review' have none)"
    ]


def test_agent_that_cannot_run_at_review(vp):
    p = with_agents({"required": [{"role": "ux-reviewer", "at": ["review"]}]})
    assert errs(vp, p) == [
        "'roles.required[0]': 'ux-reviewer' cannot run at 'review' (it has no review dimension; allowed: "
        "security-reviewer, dependency-auditor, test-architect, tech-writer, website-maintainer)"
    ]


@pytest.mark.parametrize("agents, message", [
    ({"disable": ["no-such-agent"]}, "'roles.disable[0]': must be one of"),
    ({"required": [{"role": "no-such-agent", "at": ["dod"]}]}, "'roles.required[0].role': must be one of"),
    ({"required": [{"role": "debugger", "at": ["later"]}]}, "'roles.required[0].at[0]': must be one of"),
    ({"required": [{"role": "debugger", "at": []}]}, "'roles.required[0].at': needs at least 1 item(s)"),
    ({"required": [{"role": "debugger", "at": ["dod"], "blocking": "yes"}]},
     "'roles.required[0].blocking': must be true/false"),
    ({"posture": {"security": "paranoid"}}, "'roles.posture.security': must be one of"),
    ({"required": [{"role": "debugger", "at": ["dod"], "when": []}]},
     "'roles.required[0].when': needs at least 1 item(s)"),
    ({"required": [{"role": "debugger", "at": ["dod"], "extra": 1}]}, "unknown key 'roles.required[0].extra'"),
    ({"extra_context": [""]}, "'roles.extra_context[0]': must not be empty"),
    ({"unknown": 1}, "unknown key 'roles.unknown'"),
])
def test_invalid_agents_are_rejected(vp, agents, message):
    assert any(message in e for e in errs(vp, with_agents(agents))), errs(vp, with_agents(agents))


@pytest.mark.parametrize("website, message", [
    ({"build": "x"}, "missing required key 'docs.website.dir'"),
    ({"dir": "site"}, "missing required key 'docs.website.build'"),
    ({"dir": "site", "build": "x", "other": 1}, "unknown key 'docs.website.other'"),
])
def test_invalid_website_is_rejected(vp, website, message):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["website"] = website
    assert any(message in e for e in errs(vp, p))


def test_schema_has_no_defaults_for_the_new_keys():
    import json
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    assert "default" not in json.dumps(schema["properties"]["roles"])
    assert "default" not in json.dumps(schema["properties"]["docs"]["properties"]["website"])
