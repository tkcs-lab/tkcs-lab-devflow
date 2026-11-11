from conftest import DEVFLOW, ROOT


def read(*parts):
    return (DEVFLOW.joinpath(*parts)).read_text()


def test_implement_stop_text_and_reviewer_request():
    text = read("commands", "implement.md")
    assert ("`get_me returned <login> but git.bot_login is <bot_login>: connect the second GitHub\n"
            "account at claude.ai/connect-github and start a new session.`") in text
    assert "`update_pull_request` with `reviewers`" in text
    assert "`Review PR #<n>`" in text
    assert "Never re-request for the same pushed head" in text
    assert "never approve, merge or enable auto-merge" in text.lower()
    assert "approve or merge the PR yourself" in text


def test_steward_code_owner_bullet():
    text = " ".join(read("skills", "pr-steward", "SKILL.md").split())
    assert "**A review requested from a code owner is waiting on a person.**" in text
    assert "Request the review once per pushed head." in text
    assert "Never approve, merge or enable auto-merge on a PR you opened." in text


def test_make_plan_standing_item():
    text = read("commands", "make-plan.md")
    for line in [
        "id: mb0-second-user",
        "title: Second GitHub user ready",
        "why: The agent opens PRs as git.bot_login and the code owner's review is the gate",
        "done_when: get_me in a new session prints <bot_login> and the main branch requires a Code Owner review",
        "docs/reference/profile-reference.md#second-github-user",
    ]:
        assert line in text, line


def test_reference_has_the_checklist():
    text = (ROOT / "docs" / "reference" / "profile-reference.md").read_text()
    assert "### Second GitHub user" in text
    assert "8. Open a session and ask it to call `get_me`" in text
