"""repo_admin.py: detected override proposals in the policy check, against a fake GitHub."""
import pytest
import yaml

import test_repo_admin as base
from test_repo_admin_derive import RELEASE_SECTION, TOOLKIT, prof
from test_repo_admin_inherit import OVERRIDE, inherited
from test_repo_admin_policy_check import base_pr_routes

POLICY = {"rulesets": {"default_branch": {"admin_bypass": False}}, "workflows": [{"template": "release"}, {"template": "land"}]}
PULLS = "/repos/acme/app/pulls"
TAGS = "/repos/acme/app/tags"


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def head(n):
    return f"{n:040x}"


def served(prs=3, runs=None, statuses=None, tags=("v1.0.0", "v1.1.0"), unmerged=()):
    """Routes for `prs` merged pull requests (numbers 1..prs) and the check runs / statuses of each head.
    runs / statuses: {number: [(name, conclusion)]}; the default is test and lint green on every one."""
    r = {("GET", PULLS): [{"number": n, "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": head(n)}} for n in range(prs, 0, -1)]
         + [{"number": n, "merged_at": None, "head": {"sha": head(n)}} for n in unmerged],
         ("GET", TAGS): [{"name": t} for t in tags]}
    for n in range(1, prs + 1):
        got = (runs or {}).get(n, [("test", "success"), ("lint", "success")])
        r[("GET", f"/repos/acme/app/commits/{head(n)}/check-runs")] = {"check_runs": [
            {"name": name, "status": "completed" if c else "in_progress", "conclusion": c} for name, c in got]}
        r[("GET", f"/repos/acme/app/commits/{head(n)}/status")] = {"statuses": [
            {"context": name, "state": s} for name, s in (statuses or {}).get(n, [])]}
    return r


def proposals(ra, ctx):
    return [f for f in ra.check_policy(ctx) if f.subject.startswith("override:")]


def content(finding):
    [change] = finding.action.changes
    assert change["op"] == "put" and change["path"] == OVERRIDE and change["mode"] == "100644"
    return yaml.safe_load(change["content"])


def test_proposal_for_a_repository_without_an_override(ra):
    runs = {1: [("test", "success"), ("lint", "success"), ("flaky", "failure"), ("docs", "success"), ("slow", "skipped")],
            2: [("test", "success"), ("lint", "success"), ("flaky", "success"), ("docs", "success"), ("slow", "success"),
                ("retry", "failure"), ("retry", "success")],
            3: [("test", "success"), ("lint", "success"), ("flaky", "success"), ("new", "success")]}
    routes = served(runs=runs, statuses={1: [("ci/x", "success")], 2: [("ci/x", "success")], 3: [("ci/x", "success")]})
    ctx, _ = inherited(ra, POLICY, routes=routes, files={"app": {"README.md": "x", "pyproject.toml": ""}})
    [f] = proposals(ra, ctx)
    assert (f.subject, f.severity, f.scope, f.check) == ("override:propose", "fix", "acme/app", "policy")
    doc = content(f)
    assert doc["rulesets"]["default_branch"]["required_status_checks"] == ["ci/x", "lint", "test"]
    assert doc["workflow_params"] == {"release": {"tag_prefix": "v", "version_style": "pep440"}}  # pyproject.toml: pep440
    note = f.action.note
    assert "required_status_checks: ci/x, lint, test" in note
    assert "excluded: flaky (failed on #1)" in note and "excluded: retry (flaky: success and failure on the same commit in #2)" in note
    assert "excluded: slow (skipped on #1)" in note and "excluded: docs (seen on 2 of 3" in note
    assert "excluded: new (seen on 1 of 3" in note and "release parameters: tag_prefix=v version_style=pep440" in note
    assert ra.validate_policy(doc, kind="override") == []  # a proposal is a valid override


def test_proposal_keeps_what_the_repository_wrote(ra):
    mine = "workflow_params:\n  release:\n    tag_prefix: rel-\n    check_script: scripts/v.sh\nrepo_settings:\n  allow_auto_merge: true\n"
    ctx, _ = inherited(ra, POLICY, routes=served(), files={"app": {OVERRIDE: mine}})
    [f] = proposals(ra, ctx)
    doc = content(f)
    assert doc["workflow_params"] == {"release": {"tag_prefix": "rel-", "check_script": "scripts/v.sh"}}
    assert doc["repo_settings"] == {"allow_auto_merge": True}
    assert doc["rulesets"]["default_branch"]["required_status_checks"] == ["lint", "test"]
    assert "release parameters" not in f.action.note  # the repository has its own: nothing is detected for it


def test_proposal_for_an_own_release_workflow(ra):
    own = prof("", "release: {workflow: ship.yml, version_files: [{path: VERSION, pattern: '(.*)'}]}\n")
    ctx, _ = inherited(ra, POLICY, routes=served(), files={"app": {TOOLKIT: own}})
    [f] = proposals(ra, ctx)
    doc = content(f)
    assert doc["workflows"] == [{"template": "land"}] and "workflow_params" not in doc
    assert "ship.yml" in f.action.note and "release parameters" not in f.action.note
    ours = prof("", RELEASE_SECTION)  # the template's own file name: parameters are proposed as usual
    ctx, _ = inherited(ra, POLICY, routes=served(), files={"app": {TOOLKIT: ours}})
    [g] = proposals(ra, ctx)
    assert "workflows" not in content(g) and content(g)["workflow_params"]["release"]["tag_prefix"] == "v"


def test_no_proposal_when_nothing_is_missing(ra):
    policy = {"rulesets": {"default_branch": {"admin_bypass": False, "required_status_checks": ["test"]}},
              "workflows": [{"template": "release", "params": {"tag_prefix": "v"}}]}
    ctx, fake = inherited(ra, policy, routes=served(), files={"app": {"README.md": "x"}})
    assert proposals(ra, ctx) == []
    assert [p for p in fake.reads if p.endswith("/pulls") or p.endswith("/tags")] == []  # nothing was gathered
    plain, _ = base.world(ra, {"rulesets": {"default_branch": {"admin_bypass": False}}})
    assert ra.check_policy(plain) == []  # not inherited: no detection


def test_too_few_pull_requests_is_reported_in_the_audit(ra):
    ctx, _ = inherited(ra, POLICY, routes=served(prs=2), files={"app": {"README.md": "x"}})
    [f] = proposals(ra, ctx)
    assert "excluded: (all) (too few merged pull requests (2))" in f.action.note
    doc = content(f)
    assert "rulesets" not in doc and doc["workflow_params"]["release"]["tag_prefix"] == "v"
    only, _ = inherited(ra, {"rulesets": {"default_branch": {"admin_bypass": False}}}, routes=served(prs=2, tags=()),
                        files={"app": {"README.md": "x"}})
    [info] = proposals(ra, only)  # nothing to propose: the audit still says why
    assert (info.severity, info.action) == ("info", None) and "too few merged pull requests (2)" in info.message


def test_convert_and_propose_are_one_finding(ra):
    legacy = "org: acme\nrepo_settings:\n  allow_auto_merge: true\nagent:\n  agent_login: bot\n"
    own = prof(", bot_login: bot")
    ctx, _ = inherited(ra, {**POLICY, "repo_settings": {"allow_auto_merge": False}}, routes=served(),
                       files={"app": {OVERRIDE: legacy, TOOLKIT: own}})
    found = proposals(ra, ctx)
    [f] = found  # one finding, one put of the path
    assert f.subject == "override:convert" and len(f.action.changes) == 1
    doc = content(f)
    assert doc["repo_settings"] == {"allow_auto_merge": True} and doc["rulesets"]["default_branch"]["required_status_checks"]
    assert "agent" not in doc  # the login equals the one derived from the profile
    assert "required_status_checks: lint, test" in f.action.note
    org_login = {**POLICY, "agent": {"agent_login": "bot"}}
    again, _ = inherited(ra, org_login, routes=served(), files={"app": {OVERRIDE: "org: acme\nagent:\n  agent_login: bot2\n", TOOLKIT: prof(", bot_login: bot2")}})
    assert "agent" in content(proposals(ra, again)[0])  # the organisation's own value wins, so the override's stays


def test_detection_skipped(ra):
    ctx, fake = inherited(ra, POLICY, routes=served(), files={"app": {"README.md": "x"}})
    ctx.detect = False
    assert proposals(ra, ctx) == []
    assert not [p for p in fake.reads if "/pulls" in p or "/tags" in p or "/commits/" in p]


def test_detection_failure_is_a_failure_finding(ra):
    routes = served()
    routes[("GET", PULLS)] = ra.ApiError(500, "boom", "GET", PULLS)
    ctx, _ = inherited(ra, {**POLICY, "security": {"secret_scanning": True}}, routes=routes,
                       files={"app": {OVERRIDE: "security:\n  secret_scanning: false\n"}})
    found = ra.check_policy(ctx)
    [bad] = [f for f in found if f.severity == "error"]
    assert bad.scope == "acme/app" and PULLS in bad.message and bad.action is None
    assert [f for f in found if f.subject == "loosen:security.secret_scanning"]  # the repository's other findings stay
    routes[("GET", PULLS)] = ra.ApiError(403, "no", "GET", PULLS)
    ctx, _ = inherited(ra, POLICY, routes=routes, files={"app": {"README.md": "x"}})
    assert [f.severity for f in ra.check_policy(ctx)] == ["unavailable"]


def test_gather_maps_runs_and_statuses(ra):
    from tld.ops import repo_admin_detect as detect
    runs = {1: [("a", "success"), ("b", None), ("c", "failure"), ("bad\u202ename", "success"), ("x" * 101, "success")]}
    statuses = {1: [("s1", "success"), ("s2", "error"), ("s3", "failure"), ("s4", "pending")]}
    routes = served(prs=3, runs=runs, statuses=statuses, tags=("v1.0.0", "bad\ntag"), unmerged=(99,))
    routes[("GET", PULLS)] = routes[("GET", PULLS)] + [
        {"number": 7, "merged_at": "x", "head": {"sha": "../x"}}, {"number": True, "merged_at": "x", "head": {"sha": head(1)}}, "junk"]
    files = {"app": {"pyproject.toml": "", "go.mod": "", "src/package.json": "", ".github/workflows/rel.yml":
                     "on:\n  push:\n    tags: ['v*']\njobs:\n  r:\n    steps:\n      - run: gh release create $TAG\n",
                     TOOLKIT: prof("", "release: {workflow: ship.yml, version_files: [{path: V, pattern: '(.*)'}]}\n")}}
    ctx, _ = inherited(ra, POLICY, routes=routes, files=files)
    got = detect.gather(ctx, ctx.all_repos[0])
    assert [s.number for s in got.samples] == [3, 2, 1]  # merged only, a bad head or number is skipped
    one = got.samples[2]
    assert [(r.name, r.conclusion) for r in one.runs] == [
        ("a", "success"), ("b", None), ("c", "failure"), ("s1", "success"), ("s2", "failure"), ("s3", "failure"), ("s4", None)]
    assert got.tags == ("v1.0.0",) and got.manifests == ("go.mod", "pyproject.toml") and got.tag_workflow is True
    assert got.profile_release_workflow == "ship.yml"
    assert detect.gather(ctx, ctx.all_repos[0], want_checks=False).samples == ()


def test_gather_bounds_its_requests(ra):
    from tld.ops import repo_admin_detect as detect
    ctx, fake = inherited(ra, POLICY, routes=served(prs=12), files={"app": {"README.md": "x"}})
    got = detect.gather(ctx, ctx.all_repos[0])
    assert [s.number for s in got.samples] == list(range(12, 2, -1)) and detect.DETECT_PRS == 10
    api = [p for p in fake.reads if "/commits/" in p or p.endswith("/pulls") or p.endswith("/tags")]
    assert len(api) == 1 + 2 * detect.DETECT_PRS + 1  # one list, two reads per sampled head, one page of tags
    assert got.profile_release_workflow is None


def test_the_override_of_a_truncated_tree_is_read_by_its_path(ra):
    files = {"app": {"README.md": "x"}}
    listed = f"/repos/acme/app/contents/{OVERRIDE}"
    ctx, fake = inherited(ra, POLICY, routes={**served(), ("GET", listed): "repo_settings:\n  allow_auto_merge: true\n"},
                          files=files, truncated=True)
    [f] = proposals(ra, ctx)  # the file exists although the tree did not list it: it is kept, not created
    assert content(f)["repo_settings"] == {"allow_auto_merge": True} and listed in fake.reads
    gone, _ = inherited(ra, POLICY, routes=served(), files=files, truncated=True)  # a 404 means absent
    assert [f.subject for f in proposals(ra, gone)] == ["override:propose"] and not gone.override(gone.all_repos[0]).problems
    broken = {**served(), ("GET", listed): ra.ApiError(500, "boom", "GET", listed)}
    bad, _ = inherited(ra, POLICY, routes=broken, files=files, truncated=True)
    [err] = [f for f in ra.check_policy(bad) if f.severity == "error"]  # never proposed as if it were absent
    assert err.subject == "override:invalid" and "too large to list" in err.message
    assert [f for f in ra.check_policy(bad) if f.action] == []


def test_a_proposal_that_fails_validation_is_dropped(ra, monkeypatch):
    from tld.ops import repo_admin_detect as detect
    monkeypatch.setattr(detect, "detected_override", lambda *a: {"labels": {"delete_unused": True}})
    ctx, _ = inherited(ra, POLICY, routes=served(), files={"app": {"README.md": "x"}})
    found = ra.check_policy(ctx)
    [drop] = [f for f in found if f.subject == "override:propose:invalid"]
    assert drop.severity == "warn" and "dropped" in drop.message and not [f for f in found if f.action]


def test_unsafe_release_parameters_are_not_proposed(ra):
    ctx, _ = inherited(ra, POLICY, routes=served(tags=("rel+1.0.0", "rel+1.1.0")), files={"app": {"README.md": "x"}})
    [f] = proposals(ra, ctx)
    doc = content(f)
    assert "workflow_params" not in doc and "tag_prefix was detected" in f.action.note and "no release parameters are proposed" in f.action.note


def test_version_tags_are_matched_whole():
    from tld.ops import repo_admin_detect as detect
    assert detect.release_params(["v1.0.0\n"], [], False)[1] == ["no version-like tags"]
    params, _ = detect.release_params(["v1.0.0-rc1\n", "v1.0.0-rc1"], [], False)
    assert params == {"tag_prefix": "v", "version_style": "semver"}
    assert detect.release_params(["v1.0.0a1\n"], [], False)[0] == {}


def test_detected_text_reaches_the_pull_request_only_through_the_cell(ra):
    runs = {n: [("ok", "success"), ("x #12 @bob <b> | `t`", "failure")] for n in (1, 2, 3)}
    routes = {**served(runs=runs), **base_pr_routes()}
    ctx, fake = inherited(ra, POLICY, routes=routes, files={"app": {"README.md": "x"}})
    [f] = proposals(ra, ctx)
    assert ra.apply_findings(ctx, [f], yes=True, allow_delete=False, out=lambda _line: None) == 0
    [pull] = [w for w in fake.writes if w[1].endswith("/pulls")]
    body = pull[2]["body"]
    assert "@bob" not in body and "#12" not in body and "<b>" not in body
    assert "@\u200bbob" in body and "#\u200b12" in body and "\\<b\\>" in body
    [tree] = [w for w in fake.writes if w[1].endswith("/git/trees")]
    [entry] = tree[2]["tree"]
    assert "x #12" not in yaml.safe_load(entry["content"]).get("rulesets", {}).get("default_branch", {}).get("required_status_checks", [])


def test_cell_defuses_the_hash_like_the_at_sign(ra):
    assert ra._cell("#1 @a") == "\\#\u200b1 @\u200ba"


def test_own_release_workflow_keeps_the_organisations_repos_scoping(ra):
    policy = {**POLICY, "workflows": [{"template": "release"}, {"template": "land", "repos": ["other-*"]}, {"template": "land"}]}
    own = prof("", "release: {workflow: ship.yml, version_files: [{path: VERSION, pattern: '(.*)'}]}\n")
    ctx, _ = inherited(ra, policy, routes=served(), files={"app": {TOOLKIT: own}})
    [f] = proposals(ra, ctx)
    assert content(f)["workflows"] == [{"template": "land"}]  # the entry scoped to other-* is not proposed for app
    scoped = {**POLICY, "workflows": [{"template": "release"}, {"template": "land", "repos": ["other-*"]}]}
    ctx, _ = inherited(ra, scoped, routes=served(), files={"app": {TOOLKIT: own}})
    assert content(proposals(ra, ctx)[0])["workflows"] == []


def test_notes_are_separate_lines_with_the_release_line_first(ra):
    runs = {n: [("test", "success")] + [(f"flaky{i}", "failure") for i in range(30)] for n in (1, 2, 3)}
    ctx, fake = inherited(ra, POLICY, routes={**served(runs=runs), **base_pr_routes()}, files={"app": {"README.md": "x"}})
    [f] = proposals(ra, ctx)
    lines = f.action.note.split("\n")
    assert lines[0].startswith("release parameters:") and lines[1].startswith("required_status_checks:") and len(lines) > 30
    assert ra.apply_findings(ctx, [f], yes=True, allow_delete=False, out=lambda _l: None) == 0
    body = [w for w in fake.writes if w[1].endswith("/pulls")][0][2]["body"]
    assert body.index("release parameters") < body.index("required_status_checks") < body.index("flaky29")
    assert body.count("\n- ") >= 30  # one bullet per line, each cut on its own
