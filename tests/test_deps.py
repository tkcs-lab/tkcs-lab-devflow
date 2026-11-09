import re

from conftest import DEVFLOW
from test_structure import frontmatter
from test_no_project_words import FORBIDDEN

DEPS = DEVFLOW / "commands" / "deps.md"
TEXT = DEPS.read_text()
FLAT = " ".join(TEXT.split())

HEADINGS = ["## Profile", "## Rules", "## 1. Pre-check", "## 2. Group and decide", "## 3. Fix one group",
            "## 4. Verify and record", "## Never"]
REASONS = ["Review deps PR #<n> (CI red)", "Run /deps again: time budget used",
           "Set Dependabot cooldown for <ecosystem>", "Check deps group <ecosystem>: <short cause>"]


def test_front_matter():
    head = TEXT.split("---")[1]
    assert frontmatter(DEPS)["description"].startswith("Weekly unattended dependency update")
    assert re.search(r"^description: \"Weekly unattended dependency update", head, re.M)
    assert re.search(r"^model: sonnet$", head, re.M)


def test_profile_paragraph():
    assert ('Load the `project-profile` skill and follow its "Loading the profile" section. If it reports an '
            "error, show the message verbatim and stop; never substitute a value of your own for a missing key.") in FLAT


def test_headings_in_order():
    positions = [TEXT.index("\n" + h + "\n") for h in HEADINGS]
    assert positions == sorted(positions)


def test_key_words_present():
    for word in ["cooldown_days", "time_budget_minutes", "untrusted", "deps.audit", "cooldown",
                 "cannot be read", "GraphQL", "status-board", "kind: maintenance", "command: deps",
                 "<project>--deps", '"scheduled"']:
        assert word in TEXT, word
    assert TEXT.count("deps.audit") >= 2


def test_reasons():
    for reason in REASONS:
        assert reason in TEXT, reason


def test_no_bot_command():
    assert "@dependabot" not in TEXT


def test_never_section():
    never = TEXT.split("\n## Never\n")[1]
    assert "Never merge, approve, enable auto-merge or force-push" in never


def test_no_forbidden_words():
    assert FORBIDDEN.search(TEXT) is None


def test_steward_points_to_deps():
    steward = (DEVFLOW / "skills" / "pr-steward" / "SKILL.md").read_text()
    assert ("decision for a person. The `/deps` command is that request: it triages dependency-bot PRs "
            "under its own rules.") in " ".join(steward.split())
