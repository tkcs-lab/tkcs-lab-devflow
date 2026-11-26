"""repo_admin.py: what a policy without `extends` reads and finds today.

The literals below were captured by running the code once, never computed from it. Later phases of plan 93
re-run this file and may extend it, never edit it: a policy without `extends` must behave exactly as it does here.
"""
import pytest
import test_repo_admin as base
from test_repo_admin import world

NAMES = ("app", "web")

POLICY = {
    "repo_settings": {"allow_auto_merge": True, "delete_branch_on_merge": True, "allow_squash_merge": False},
    "security": {"vulnerability_alerts": True, "secret_scanning": True},
    "actions": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    "rulesets": {"default_branch": {"required_status_checks": ["test", "lint"], "admin_bypass": True}, "tags": True},
    "agent": {"agent_login": "bot", "branch_policy": "default_branch"},
    "release": {"reviewer_login": "owner", "environment": "tld-release"},
    "config_dirs": {"forbid": [".archon"], "known": [".cursor"], "require": ["SECURITY.md"]},
    "workflow_lint": {"pin_actions": "third_party", "require_permissions": True},
    "workflows": [{"template": "release", "params": {"tag_prefix": "rel-"}}, {"template": "land"}],
}

FINDINGS = [('repo', 'acme/app', 'allow_auto_merge', 'fix'),
     ('repo', 'acme/app', 'allow_squash_merge', 'fix'),
     ('repo', 'acme/web', 'allow_auto_merge', 'fix'),
     ('repo', 'acme/web', 'delete_branch_on_merge', 'fix'),
     ('repo', 'acme/web', 'allow_squash_merge', 'fix'),
     ('security', 'acme/app', 'vulnerability_alerts', 'fix'),
     ('security', 'acme/app', 'secret_scanning', 'unavailable'),
     ('security', 'acme/web', 'vulnerability_alerts', 'fix'),
     ('security', 'acme/web', 'secret_scanning', 'unavailable'),
     ('actions', 'acme/app', 'default_workflow_permissions', 'fix'),
     ('actions', 'acme/web', 'GET /repos/acme/web/actions/permissions/workflow', 'unavailable'),
     ('rulesets', 'acme/app', 'GET /repos/acme/app/rulesets', 'unavailable'),
     ('rulesets', 'acme/web', 'GET /repos/acme/web/rulesets', 'unavailable'),
     ('agent', 'acme/app', 'role:bot', 'warn'),
     ('agent', 'acme/app', 'environment:tld-agent', 'fix'),
     ('agent', 'acme/app', 'environment:tld-agent:branch:main', 'fix'),
     ('agent', 'acme/app', 'GET /repos/acme/app/actions/secrets', 'unavailable'),
     ('agent', 'acme/web', 'role:bot', 'warn'),
     ('agent', 'acme/web', 'environment:tld-agent', 'fix'),
     ('agent', 'acme/web', 'environment:tld-agent:branch:main', 'fix'),
     ('agent', 'acme/web', 'GET /repos/acme/web/actions/secrets', 'unavailable'),
     ('release', 'acme/app', 'environment:tld-release', 'fix'),
     ('release', 'acme/app', 'environment:tld-release:branch:main', 'fix'),
     ('release', 'acme/app', 'GET /repos/acme/app/actions/secrets', 'unavailable'),
     ('release', 'acme/web', 'environment:tld-release', 'fix'),
     ('release', 'acme/web', 'environment:tld-release:branch:main', 'fix'),
     ('release', 'acme/web', 'GET /repos/acme/web/actions/secrets', 'unavailable'),
     ('files', 'acme/web', 'workflow:.github/workflows/tld-release.yml', 'fix'),
     ('files', 'acme/web', 'workflow:.github/workflows/tld-land.yml', 'fix')]

READS = ['/orgs/acme/repos',
     '/repos/acme/app',
     '/repos/acme/web',
     '/repos/acme/app/actions/permissions/workflow',
     '/repos/acme/web/actions/permissions/workflow',
     '/repos/acme/app/rulesets',
     '/repos/acme/web/rulesets',
     '/repos/acme/app/collaborators/bot/permission',
     '/repos/acme/app/environments/tld-agent',
     '/repos/acme/app/actions/secrets',
     '/repos/acme/web/collaborators/bot/permission',
     '/repos/acme/web/environments/tld-agent',
     '/repos/acme/web/actions/secrets',
     '/users/owner',
     '/repos/acme/app/environments/tld-release',
     '/repos/acme/app/actions/secrets',
     '/repos/acme/web/environments/tld-release',
     '/repos/acme/web/actions/secrets',
     '/repos/acme/app/branches/main',
     '/repos/acme/web/branches/main',
     '/repos/acme/web/git/trees/t-web']

APPLY_LINES = [('Would run: PATCH /repos/acme/app {"allow_auto_merge": true}   [1386c2b718] allow_auto_merge is False, '
     'policy wants True'),
     ('Would run: PATCH /repos/acme/app {"allow_squash_merge": false}   [afafc21592] allow_squash_merge is True, '
     'policy wants False'),
     ('Would run: PATCH /repos/acme/web {"allow_auto_merge": true}   [c6f08bda50] allow_auto_merge is None, '
     'policy wants True'),
     ('Would run: PATCH /repos/acme/web {"delete_branch_on_merge": true}   [e8bd4f75e1] delete_branch_on_merge is '
     'None, policy wants True'),
     ('Would run: PATCH /repos/acme/web {"allow_squash_merge": false}   [f8754cb4c3] allow_squash_merge is None, '
     'policy wants False'),
     ('Would run: PUT /repos/acme/app/vulnerability-alerts   [7c4b51d22e] vulnerability_alerts is off, policy '
     'wants on'),
     ('Would run: PUT /repos/acme/web/vulnerability-alerts   [ae806d32c4] vulnerability_alerts is off, policy '
     'wants on'),
     ('Would run: PUT /repos/acme/app/actions/permissions/workflow {"default_workflow_permissions": "read"}   '
     "[b10e5b2be9] default_workflow_permissions is 'write', policy wants 'read'"),
     ('Would run: PUT /repos/acme/app/environments/tld-agent {"deployment_branch_policy": '
     '{"custom_branch_policies": true, "protected_branches": false}}   [1d9300c82d] environment tld-agent is '
     'missing; policy wants only the default branch'),
     ('Would run: POST /repos/acme/app/environments/tld-agent/deployment-branch-policies {"name": "main", "type": '
     '"branch"}   [991ac2fb70] environment tld-agent does not allow the default branch main'),
     ('Would run: PUT /repos/acme/web/environments/tld-agent {"deployment_branch_policy": '
     '{"custom_branch_policies": true, "protected_branches": false}}   [b00aaf905a] environment tld-agent is '
     'missing; policy wants only the default branch'),
     ('Would run: POST /repos/acme/web/environments/tld-agent/deployment-branch-policies {"name": "main", "type": '
     '"branch"}   [2ee847360f] environment tld-agent does not allow the default branch main'),
     ('Would run: PUT /repos/acme/app/environments/tld-release {"deployment_branch_policy": '
     '{"custom_branch_policies": true, "protected_branches": false}, "reviewers": [{"id": 42, "type": '
     '"User"}]}   [e544ee6806] environment tld-release is missing; policy wants only the default branch and the '
     'owner as the one required reviewer'),
     ('Would run: POST /repos/acme/app/environments/tld-release/deployment-branch-policies {"name": "main", '
     '"type": "branch"}   [ee1e12f51f] environment tld-release does not allow the default branch main'),
     ('Would run: PUT /repos/acme/web/environments/tld-release {"deployment_branch_policy": '
     '{"custom_branch_policies": true, "protected_branches": false}, "reviewers": [{"id": 42, "type": '
     '"User"}]}   [bcb59355bf] environment tld-release is missing; policy wants only the default branch and the '
     'owner as the one required reviewer'),
     ('Would run: POST /repos/acme/web/environments/tld-release/deployment-branch-policies {"name": "main", '
     '"type": "branch"}   [23c04d91ac] environment tld-release does not allow the default branch main'),
     ('Would run: pull request on acme/web: put .github/workflows/tld-release.yml, put '
     '.github/workflows/tld-land.yml   [2b34e3c42f, 079c818b4e]'),
     'Dry run: nothing was changed. Run again with --yes to make these changes.']

PARTIAL_FINDINGS = [('labels', 'acme/app', 'GET /repos/acme/app/labels', 'unavailable'),
     ('labels', 'acme/web', 'GET /repos/acme/web/labels', 'unavailable')]

PARTIAL_READS = ['/orgs/acme/repos', '/repos/acme/app/labels', '/repos/acme/web/labels']


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def test_policy_without_extends_reads_and_finds_the_same(ra):
    routes = {
        ("GET", "/users/owner"): {"login": "owner", "id": 42},
        ("GET", "/repos/acme/app"): base.repo("app", allow_auto_merge=False, delete_branch_on_merge=True, allow_squash_merge=True),
        ("GET", "/repos/acme/app/actions/permissions/workflow"): {"default_workflow_permissions": "write",
                                                                  "can_approve_pull_request_reviews": False},
    }
    files = {"app": {".archon/a": "x", "README.md": "r"}, "web": {"SECURITY.md": "s"}}
    ctx, fake = world(ra, POLICY, names=NAMES, routes=routes, files=files)
    found = ra.run_checks(ctx)
    assert [(f.check, f.scope, f.subject, f.severity) for f in found] == FINDINGS
    assert fake.reads == READS
    lines: list[str] = []
    ra.apply_findings(ctx, found, yes=False, allow_delete=False, out=lines.append)
    assert lines == APPLY_LINES


def test_partial_policy_without_extends_makes_no_new_request(ra):
    ctx, fake = world(ra, {"labels": {"sync": [{"name": "bug", "color": "ff0000"}]}}, names=NAMES)
    found = ra.run_checks(ctx)
    assert [(f.check, f.scope, f.subject, f.severity) for f in found] == PARTIAL_FINDINGS
    assert fake.reads == PARTIAL_READS


def test_unknown_reviewer_without_extends_is_one_org_finding(ra):
    routes = {("GET", "/users/ghost"): base.ApiErr(404, "Not Found", "GET", "/users/ghost")}
    ctx, _ = world(ra, {"release": {"reviewer_login": "ghost"}}, names=NAMES, routes=routes)
    found = ra.run_checks(ctx, ["release"])
    assert [(f.check, f.scope, f.subject, f.severity) for f in found] == [("release", "acme", "GET /users/ghost", "unavailable")]


def test_missing_login_messages_are_pinned(ra):
    assert ra.validate_policy({"org": "a", "agent": {}}) == ["missing required key 'agent.agent_login'"]
    assert ra.validate_policy({"org": "a", "release": {}}) == ["missing required key 'release.reviewer_login'"]
