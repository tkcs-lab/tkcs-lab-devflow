"""repo_admin.py: the policy check, the keep-live rules, the release stand-down and the pull request notes (fake GitHub).
Each test looks only at the findings of the (check, subject) it is about: later phases add findings to inherited runs."""
import pytest

import test_repo_admin as base
from test_repo_admin import by_check, world
from test_repo_admin_inherit import OVERRIDE, inherited
from test_repo_admin_rulesets import RS, served

BIG_POLICY = {"security": {"secret_scanning": True}, "repo_settings": {"allow_auto_merge": True}}


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def subjects(findings, check="policy"):
    return sorted(f.subject for f in by_check(findings, check))


def test_organisation_level_key_in_an_override(ra):
    policy = {"repo_settings": {"allow_auto_merge": True}}
    ctx, _ = inherited(ra, policy, files={"app": {OVERRIDE: "labels:\n  delete_unused: true\n"}}, allow_auto_merge=False)
    found = ra.check_policy(ctx)
    [bad] = [f for f in found if f.subject == "override:invalid"]
    assert (bad.scope, bad.severity) == ("acme/app", "error") and "organisation-level" in bad.message
    assert bad.message.startswith(f"acme/app:{OVERRIDE}: ") and bad.message.count(OVERRIDE) == 1
    [fix] = ra.check_repo(ctx)  # audited with the organisation policy alone
    assert fix.action.body == {"allow_auto_merge": True}


def test_loosening_held(ra):
    routes = {("GET", "/repos/acme/app/vulnerability-alerts"): {}}
    ctx, _ = inherited(ra, {"security": {"secret_scanning": True}}, routes=routes,
                       files={"app": {OVERRIDE: "security:\n  secret_scanning: false\n"}},
                       security_and_analysis={"secret_scanning": {"status": "disabled"}})
    [warn] = [f for f in ra.check_policy(ctx) if f.subject == "loosen:security.secret_scanning"]
    assert warn.severity == "warn" and warn.scope == "acme/app"
    assert "false" in warn.message and "true" in warn.message and "organisation value applies" in warn.message
    [fix] = [f for f in ra.check_security(ctx) if f.subject == "secret_scanning"]
    assert fix.action.body == {"security_and_analysis": {"secret_scanning": {"status": "enabled"}}}


def test_loosening_allowed_by_the_run_file(ra):
    policy = {"security": {"secret_scanning": True}, "repos": {"allow_loosen": {"app": ["security.secret_scanning"]}}}
    ctx, _ = inherited(ra, policy, files={"app": {OVERRIDE: "security:\n  secret_scanning: false\n"}},
                       security_and_analysis={"secret_scanning": {"status": "enabled"}})
    assert not [f for f in ra.check_policy(ctx) if f.subject.startswith("loosen:")]
    assert ctx.pol(ctx.all_repos[0])["security"]["secret_scanning"] is False
    [fix] = [f for f in ra.check_security(ctx) if f.subject == "secret_scanning"]
    assert fix.action.body == {"security_and_analysis": {"secret_scanning": {"status": "disabled"}}}


def test_run_file_loosening_reported(ra):
    ctx, _ = inherited(ra, {"security": {"secret_scanning": False}, "_run_loosenings": [("security.secret_scanning", True, False)]})
    [warn] = [f for f in ra.check_policy(ctx) if f.subject == "loosen:security.secret_scanning"]
    assert (warn.scope, warn.severity) == ("acme", "warn")
    assert "the policy file sets security.secret_scanning to false, looser than its base's true" in warn.message


def test_loosening_text_is_clean_and_bounded(ra):
    ctx, _ = inherited(ra, {"_run_loosenings": [("config_dirs.forbid", ["a"], ["\x1b[31m" + "x" * 500])]})
    [warn] = ra.check_policy(ctx)
    assert len(warn.message) <= 300 and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in warn.message)


def test_deletion_needs_the_flag(ra):
    r = {("GET", "/repos/acme/app/labels"): [{"name": "wontfix", "color": "ededed", "description": None}],
         ("GET", "/repos/acme/app/issues"): lambda p: []}
    ctx, fake = inherited(ra, {"labels": {"sync": [], "delete_unused": True}, "repo_settings": {"allow_auto_merge": True}},
                          routes=r, allow_auto_merge=False)
    found = [f for f in ra.run_checks(ctx, ["repo", "labels"]) if f.action]
    out = []
    assert ra.apply_findings(ctx, found, yes=True, allow_delete=False, out=out.append) == 0
    assert [w[0] for w in fake.writes] == ["PATCH"]
    assert len([line for line in out if line.startswith("Held back (irreversible")]) == 1


def test_absent_value_stands_down(ra):
    wf = {"workflows": [{"template": "release"}]}
    ctx, _ = inherited(ra, wf, files={"app": {"README.md": "x"}})
    found = ra.check_files(ctx)
    assert [(f.subject, f.severity) for f in found] == [("workflow:.github/workflows/tld-release.yml:standdown", "info")]
    assert not any(f.action for f in found) and "no release parameters for this repository yet" in found[0].message
    ctx, _ = inherited(ra, wf, files={"app": {OVERRIDE: "workflow_params:\n  release:\n    tag_prefix: rel-\n"}})
    [f] = ra.check_files(ctx)
    assert f.subject == "workflow:.github/workflows/tld-release.yml" and f.action  # the parameters render it
    plain, _ = world(ra, wf, files={"app": {"README.md": "x"}})
    [g] = ra.check_files(plain)
    assert g.action and g.subject == "workflow:.github/workflows/tld-release.yml"


MAIN_LIVE = {"rulesets": {"default_branch": {"admin_bypass": False}}}


def live_world(ra, policy, override="", get_error=None):
    def weaken(name, have):
        for rule in have["rules"]:
            if rule["type"] == "pull_request":
                rule["parameters"]["required_approving_review_count"] = 0

    routes = served(ra, {"default_branch": {"required_status_checks": ["a", "b"]}}, edit=weaken)
    if get_error:
        routes[("GET", f"{RS}/1")] = get_error
    files = {"app": {OVERRIDE: override} if override else {}}
    return inherited(ra, policy, routes=routes, files=files)


def test_absent_checks_are_kept_in_the_put_body(ra):
    ctx, _ = live_world(ra, MAIN_LIVE)
    [fix] = [f for f in ra.check_rulesets(ctx) if f.subject == "tld-main"]
    assert (fix.action.method, fix.action.path) == ("PUT", f"{RS}/1")
    rules = {r["type"]: r for r in fix.action.body["rules"]}
    assert [c["context"] for c in rules["required_status_checks"]["parameters"]["required_status_checks"]] == ["a", "b"]
    assert rules["pull_request"]["parameters"]["required_approving_review_count"] == 1


def test_explicit_empty_checks_remove_the_rule(ra):
    ctx, _ = live_world(ra, MAIN_LIVE, override="rulesets:\n  default_branch:\n    required_status_checks: []\n")
    [fix] = [f for f in ra.check_rulesets(ctx) if f.subject == "tld-main"]
    assert "required_status_checks" not in {r["type"] for r in fix.action.body["rules"]}


def test_invalid_override_keeps_live_checks(ra):
    ctx, _ = live_world(ra, MAIN_LIVE, override="labels:\n  delete_unused: true\n")
    assert ctx.override(ctx.all_repos[0]).problems
    [err] = [f for f in ra.check_policy(ctx) if f.subject == "override:invalid"]
    assert err.severity == "error"
    [fix] = [f for f in ra.check_rulesets(ctx) if f.subject == "tld-main"]
    rules = {r["type"]: r for r in fix.action.body["rules"]}
    assert [c["context"] for c in rules["required_status_checks"]["parameters"]["required_status_checks"]] == ["a", "b"]


def test_unreadable_live_ruleset_is_not_a_drop(ra):
    ctx, _ = live_world(ra, MAIN_LIVE, get_error=ra.ApiError(500, "boom", "GET", f"{RS}/1"))
    found = ra.check_rulesets(ctx)
    assert [f.severity for f in found] == ["error"] and found[0].action is None
    assert not [f for f in found if f.action]


def test_base_forbid_only_proposes_a_pull_request(ra):
    ctx, fake = inherited(ra, {"config_dirs": {"forbid": [".archon"]}}, files={"app": {".archon/a": "x"}})
    [f] = [f for f in ra.check_files(ctx) if f.subject == "forbid:.archon"]
    assert f.action.kind == "files" and f.action.changes == [{"op": "delete", "path": ".archon/a"}] and not f.action.destructive
    out = []
    fake.routes.update(base_pr_routes())
    assert ra.apply_findings(ctx, [f], yes=True, allow_delete=False, out=out.append) == 0
    assert not [w for w in fake.writes if w[0] == "DELETE"]
    assert [w for w in fake.writes if w[1].endswith("/pulls")]


def base_pr_routes():
    return {("POST", "/repos/acme/app/git/trees"): {"sha": "NT"}, ("POST", "/repos/acme/app/git/commits"): {"sha": "NC"},
            ("POST", "/repos/acme/app/git/refs"): {}, ("POST", "/repos/acme/app/pulls"): {"html_url": "https://github.com/acme/app/pull/9"}}


LEGACY = "org: acme\nrepo_settings:\n  allow_auto_merge: true\n  delete_branch_on_merge: true\nlabels:\n  delete_unused: true\n"


def test_convert_finding_replaces_the_file(ra):
    ctx, _ = inherited(ra, {"repo_settings": {"allow_auto_merge": True}}, files={"app": {OVERRIDE: LEGACY}})
    [f] = [f for f in ra.check_policy(ctx) if f.subject == "override:convert"]
    assert (f.severity, f.scope) == ("fix", "acme/app") and f.action.kind == "files"
    [change] = f.action.changes
    assert change["op"] == "put" and change["path"] == OVERRIDE and change["mode"] == "100644"
    assert "delete_branch_on_merge: true" in change["content"] and "labels" not in change["content"] and "org:" not in change["content"]
    assert "dropped organisation-level section 'labels'" in f.action.note


def test_apply_notes_reach_the_pull_request_body(ra):
    ctx, fake = inherited(ra, {"repo_settings": {"allow_auto_merge": True}}, files={"app": {OVERRIDE: LEGACY}})
    fake.routes.update(base_pr_routes())
    found = [f for f in ra.check_policy(ctx) if f.action]
    assert ra.apply_findings(ctx, found, yes=True, allow_delete=False, out=lambda _line: None) == 0
    [pull] = [w for w in fake.writes if w[1].endswith("/pulls")]
    body = pull[2]["body"]
    assert "Detected values (the owner confirms them):" in body and "- dropped organisation-level section" in body
    assert body.index("add or update") < body.index("Detected values") < body.index("never merged")
    ra_note = "x\x1b[31m<script>" + "y" * 800
    fake.writes.clear()
    ra.apply_files(fake, "acme/app", [{"op": "delete", "path": "x"}], "main", "c", "t", ctx.now.date(), [ra_note])
    body = [w for w in fake.writes if w[1].endswith("/pulls")][0][2]["body"]
    assert "\x1b" not in body and "<script>" not in body and len(body) < 1500


def test_pol_warnings_and_the_agent_environment_are_separate_findings(ra):
    policy = {"release": {"reviewer_login": "owner", "environment": "tld-release"}}
    ctx, _ = inherited(ra, policy, files={"app": {OVERRIDE: "release:\n  environment: tld-agent\n"}})
    found = [f for f in ra.check_policy(ctx) if f.subject.startswith("release:")]
    assert [f.subject for f in found] == ["release:environment"] and "agent environment" in found[0].message


def test_workflow_params_for_a_template_that_is_not_listed(ra):
    ctx, _ = inherited(ra, {"workflows": [{"template": "land"}]},
                       files={"app": {OVERRIDE: "workflow_params:\n  release:\n    tag_prefix: v\n"}})
    [warn] = [f for f in ra.check_policy(ctx) if f.subject == "workflow_params:release"]
    assert warn.severity == "warn"


def test_policy_check_is_silent_without_inheritance(ra):
    ctx, fake = world(ra, BIG_POLICY)
    assert ra.check_policy(ctx) == [] and not [p for p in fake.reads if p.endswith(OVERRIDE)]
    assert "policy" in ra.CHECKS


def test_kept_live_checks_keep_their_integration_id(ra):
    ctx, _ = live_world(ra, MAIN_LIVE)
    [fix] = [f for f in ra.check_rulesets(ctx) if f.subject == "tld-main"]
    rules = {r["type"]: r for r in fix.action.body["rules"]}
    assert rules["required_status_checks"]["parameters"]["required_status_checks"] == [
        {"context": "a", "integration_id": 15368}, {"context": "b", "integration_id": 15368}]
    # a live check that lost its integration no longer matches the kept, bound one
    want = {"strict_required_status_checks_policy": False, "required_status_checks": [{"context": "a", "integration_id": 7}]}
    have = {"strict_required_status_checks_policy": False, "required_status_checks": [{"context": "a"}]}
    assert ra._param_diffs("required_status_checks", want, have) == ["required_status_checks"]
    plain = {"strict_required_status_checks_policy": False, "required_status_checks": [{"context": "a"}]}
    assert ra._param_diffs("required_status_checks", plain, {**have, "required_status_checks": [{"context": "a", "integration_id": 7}]}) == []


def test_equal_organisation_logins_stand_the_release_check_down(ra):
    org = {"org": "a", "agent": {"agent_login": "bot"}, "release": {"reviewer_login": "BOT"}}
    eff, _loose, warns = ra.effective_policy(org, {}, "app")
    assert "reviewer_login" not in eff["release"] and eff["agent"]["agent_login"] == "bot"
    [msg] = [m for s, m in warns if s == "login:same"]
    assert "stands down" in msg and "release.reviewer_login" in msg and "organisation's logins apply" not in msg
    ctx, _ = inherited(ra, {"agent": {"agent_login": "bot"}, "release": {"reviewer_login": "BOT"}})
    assert ra.check_release(ctx) == []
    subjects = [f.subject for f in ra.check_agent(ctx)]
    assert "login:same" in subjects and "login:agent" not in subjects  # the agent's role is not checked either


def test_cell_defuses_references_and_entities(ra):
    cell = ra._cell("see #12 and &amp; @someone")
    assert "\\#\u200b12" in cell and "#12" not in cell and "\\&amp;" in cell and "@someone" not in cell


def test_explicit_empty_checks_ignore_live_checks_in_the_body(ra):
    bodies = {b["name"]: b for b in ra.ruleset_bodies({"default_branch": {"required_status_checks": []}}, ["x"])}
    assert "required_status_checks" not in {r["type"] for r in bodies["tld-main"]["rules"]}


def test_cell_breaks_bare_urls(ra):
    cell = ra._cell("check https://evil.example/x and www.evil.example")
    assert "://" not in cell and "www.evil" not in cell


def test_key_the_organisation_omits(ra):
    org = {"org": "a", "security": {"secret_scanning": True}}
    eff, loose, _warns = ra.effective_policy(org, {"security": {"secret_push_protection": False}}, "app")
    assert eff["security"]["secret_push_protection"] is False and loose == []
