"""repo_admin.py: a repository's resolved profile and the logins derived from it, against a fake GitHub."""
import pytest

import test_repo_admin as base
from test_repo_admin_inherit import OVERRIDE, inherited
from test_repo_admin_profile import BASE_FILE, OLD, profile_text
from test_repo_admin_profile import routes as base_routes
from test_repo_admin_rulesets import ENV, GOOD_ENV, MAIN_ONLY, PERM, RENV, agent_routes, release_env, release_routes

TOOLKIT = ".tld/toolkit.yaml"
RELEASE_SECTION = "release: {workflow: tld-release.yml, version_files: [{path: VERSION, pattern: '(.*)'}]}\n"
POLICY = {"agent": {"branch_policy": "default_branch"}, "release": {"environment": "tld-release"}}


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def prof(git="", extra=""):
    """A complete profile with no base; `git` adds keys to its git section."""
    docs = "{must_read: [], changelog: {file: CHANGELOG.md, section: '## [Unreleased]'}}" if "release:" in extra else "{must_read: []}"
    return ("docs: " + docs + "\ngit: {main_branch: main, branch_pattern: '<type>/<kebab-case>'" + git + "}\n"
            "verify: {fast: [make lint], dod: [make test]}\nstacks: []\n" + extra)


def toolkit_reads(fake):
    return [p for p in fake.reads if p.endswith(TOOLKIT)]


def test_repo_profile_resolves_with_and_without_extends(ra):
    plain = prof(", owner_login: boss")
    pinned = profile_text(pin=f"{BASE_FILE}@{OLD}", extra="")
    ctx, _ = inherited(ra, {}, names=("plain", "pinned"), routes=base_routes(ra, base_text="git:\n  bot_login: basebot\n"),
                       files={"plain": {TOOLKIT: plain}, "pinned": {TOOLKIT: pinned}})
    a, b = ctx.all_repos
    assert ra.repo_admin_profile.repo_profile(ctx, a)["git"]["owner_login"] == "boss"
    resolved = ra.repo_admin_profile.repo_profile(ctx, b)
    assert resolved["git"]["bot_login"] == "basebot" and resolved["tld"]["extends"].startswith(BASE_FILE)


def test_repo_profile_is_none_when_unreadable_or_refused(ra):
    token = "gh" + "p_" + "A1b2C3d4E5" * 4  # built at run time: no credential-looking line in this file
    cases = {
        "none": {},
        "list": {TOOLKIT: "- a\n- b\n"},
        "badpin": {TOOLKIT: profile_text(pin=f"{BASE_FILE}@v1.0")},
        "mixed": {TOOLKIT: profile_text(pin=f"{BASE_FILE}@{'A' * 40}")},
        "token": {TOOLKIT: profile_text(pin=f"{BASE_FILE}@{OLD}")},
        "nores": {TOOLKIT: "docs: {must_read: []}\n"},
        "http500": {TOOLKIT: prof(", owner_login: boss")},
        "good": {TOOLKIT: prof(", owner_login: boss")},
    }
    routes = base_routes(ra, base_text=f"git:\n  bot_login: basebot\n# {token}\n")
    ctx, fake = inherited(ra, {}, names=tuple(cases), routes=routes, files=cases)
    fake.routes[("GET", f"/repos/acme/http500/contents/{TOOLKIT}")] = ra.ApiError(500, "boom", "GET", "x")
    got = {r["name"]: ra.repo_admin_profile.repo_profile(ctx, r) for r in ctx.all_repos}
    assert {name: value is None for name, value in got.items()} == {
        "none": True, "list": True, "badpin": True, "mixed": True, "token": True, "nores": True, "http500": True, "good": False}
    # the profile of "token" is complete without its base: only the refused base makes the result None
    assert ra.repo_admin_profile.repo_profile(ctx, ctx.all_repos[4]) is None
    plain, _ = inherited(ra, {}, files={"app": {TOOLKIT: profile_text(pin=None)}})
    assert ra.repo_admin_profile.repo_profile(plain, plain.all_repos[0]) is not None
    before = len(fake.reads)
    for r in ctx.all_repos:
        ra.repo_admin_profile.repo_profile(ctx, r)
    assert len(fake.reads) == before  # memoised: a second call reads nothing


def test_logins_derived(ra):
    routes = {**agent_routes(env=GOOD_ENV, policies=MAIN_ONLY), **release_routes(env=release_env(42))}
    ctx, fake = inherited(ra, POLICY, routes=routes, files={"app": {TOOLKIT: prof(", owner_login: owner, bot_login: bot")}})
    repo = ctx.all_repos[0]
    lg = ctx.logins(repo)
    assert (lg.agent, lg.reviewer, lg.same) == ("bot", "owner", False)
    assert ra.check_agent(ctx) == [] and ra.check_release(ctx) == []  # the derived logins match the live state
    assert ("GET", PERM) in [("GET", p) for p in fake.reads] and "/users/owner" in fake.reads
    assert len(toolkit_reads(fake)) == 1  # the profile is read once for both checks
    only, _ = inherited(ra, POLICY, files={"app": {TOOLKIT: prof(", bot_login: bot, codeowners: [owner]")}})
    assert only.logins(only.all_repos[0])[:2] == ("bot", "owner")  # exactly one code owner is the reviewer


def test_explicit_login_wins(ra):
    policy = {"agent": {"agent_login": "bot"}, "release": {"environment": "tld-release", "reviewer_login": "owner"}}
    routes = {**agent_routes(env=GOOD_ENV, policies=MAIN_ONLY), **release_routes(env=release_env(42))}
    ctx, fake = inherited(ra, policy, routes=routes, files={"app": {TOOLKIT: prof(", owner_login: other, bot_login: robot")}})
    assert ra.check_agent(ctx) == [] and ra.check_release(ctx) == []
    assert toolkit_reads(fake) == [] and "/users/other" not in fake.reads  # no route for the profile is read
    override = {"app": {OVERRIDE: "agent:\n  agent_login: bot\n"}}
    mixed, fake = inherited(ra, {"agent": {}, "release": {"reviewer_login": "owner"}}, files=override)
    assert mixed.logins(mixed.all_repos[0])[:2] == ("bot", "owner") and toolkit_reads(fake) == []


def test_login_not_derivable(ra):
    ctx, fake = inherited(ra, POLICY, routes=release_routes(env=release_env(42)) | agent_routes(),
                          files={"app": {TOOLKIT: prof("")}})
    found = ra.check_agent(ctx)
    [warn] = [f for f in found if f.subject == "login:agent"]
    assert warn.severity == "warn" and warn.scope == "acme/app" and warn.message.startswith(
        "agent.agent_login is not set and cannot be derived (") and "bot_login" in warn.message
    assert "git.bot_login" in warn.manual
    assert [f.subject for f in found if f.subject.startswith("environment:")]  # the environment part still runs
    assert not [f for f in found if f.subject.startswith("role:")] and f"/repos/acme/app/collaborators/bot/permission" not in fake.reads
    found = ra.check_release(ctx)
    assert [(f.subject, f.severity) for f in found] == [("login:reviewer", "warn")]
    assert found[0].message.startswith("release.reviewer_login is not set and cannot be derived (")
    assert not [p for p in fake.reads if p.startswith("/users/")] and fake.writes == []


@pytest.mark.parametrize("policy,git", [
    (POLICY, ", owner_login: Bot, bot_login: bot"),  # both derived, equal without case
    ({**POLICY, "agent": {"agent_login": "BOT", "branch_policy": "default_branch"}}, ", owner_login: bot"),  # explicit and derived
    ({**POLICY, "release": {"environment": "tld-release", "reviewer_login": "bot"}}, ", bot_login: Bot"),  # derived and explicit
])
def test_equal_effective_logins_stand_down(ra, policy, git):
    ctx, fake = inherited(ra, policy, routes=agent_routes() | release_routes(), files={"app": {TOOLKIT: prof(git)}})
    lg = ctx.logins(ctx.all_repos[0])
    assert lg.same and lg.reviewer is None and lg.agent
    agent = ra.check_agent(ctx)
    [same] = [f for f in agent if f.subject == "login:same"]
    assert same.severity == "warn" and "equals the agent login" in same.message and "release check stands down" in same.message
    assert not [f for f in agent if f.subject.startswith("role:")] and [f for f in agent if f.subject.startswith("environment:")]
    release = ra.check_release(ctx)
    assert [(f.subject, f.severity) for f in release] == [("login:same", "warn")]
    assert not [p for p in fake.reads if p.startswith("/users/") or p.endswith("/permission")] and fake.writes == []


def test_release_template_stands_down_without_a_release_section(ra):
    policy = {"workflows": [{"template": "release", "params": {"tag_prefix": "v"}}]}
    ctx, _ = inherited(ra, policy, files={"app": {TOOLKIT: prof("")}})
    [f] = ra.check_files(ctx)
    assert (f.subject, f.severity, f.action) == ("workflow:.github/workflows/tld-release.yml:standdown", "info", None)
    assert "profile has no release section" in f.message
    ctx, _ = inherited(ra, policy, files={"app": {TOOLKIT: prof("", RELEASE_SECTION)}})
    assert ra.repo_admin_profile.repo_profile(ctx, ctx.all_repos[0])["release"]["workflow"] == "tld-release.yml"
    [g] = ra.check_files(ctx)
    assert g.subject == "workflow:.github/workflows/tld-release.yml" and g.action  # a release section: it is installed
    ctx, _ = inherited(ra, policy, files={"app": {"README.md": "x"}})
    [h] = ra.check_files(ctx)
    assert h.action  # no profile at all: nothing says it has no release section
    plain, _ = base.world(ra, dict(policy), files={"app": {TOOLKIT: prof("")}})
    [i] = ra.check_files(plain)
    assert i.action  # without inheritance the profile is not read
