"""The tracking-issue flow (design D16) is spelled out in the two command files."""

from conftest import CLAUDE

MAKE_PLAN = (CLAUDE / "commands" / "make-plan.md").read_text()
IMPLEMENT = (CLAUDE / "commands" / "implement.md").read_text()

HEADINGS = [
    "## Request",
    "## Goal",
    "## What changes",
    "## Order",
    "## Before you start",
    "## After the last merge",
    "## Risks",
    "## Machine-readable plan",
]


def test_make_plan_comment_texts():
    assert "`Planning started.`" in MAKE_PLAN
    assert "`Plan ready: <plan URL>. Next: /implement <plan URL>.`" in MAKE_PLAN
    assert "`Implementation started.`" in MAKE_PLAN
    assert "`PR opened: <url>.`" in MAKE_PLAN


def test_implement_comment_texts():
    for text in (
        "Implementation started on <feature_branch>.",
        "Phase <phase id> merged.",
        "Waiting for you: <needs_you_reason>.",
        "Phase <phase id> failed after retry: <short cause>.",
        "Final review: approve.",
        "Final review: changes (<n> blocking).",
        "PR opened: <url>.",
    ):
        assert f"`{text}`" in IMPLEMENT, text


def test_make_plan_issue_headings_in_order():
    pos = -1
    for h in HEADINGS:
        nxt = MAKE_PLAN.find(f"`{h}`", pos + 1)
        assert nxt > pos, h
        pos = nxt


def test_make_plan_issue_body_has_no_yaml():
    assert "no YAML" in MAKE_PLAN
    assert "tracking_issue: <n>" in MAKE_PLAN and "closes: [<n>]" in MAKE_PLAN


def test_implement_closes_lines():
    assert "Closes #<tracking_issue>" in IMPLEMENT
    assert "Closes #<n>" in IMPLEMENT
