import re

from conftest import DEVFLOW
from test_structure import frontmatter
from test_no_project_words import FORBIDDEN

DOCS = DEVFLOW / "commands" / "docs.md"
SKILL = DEVFLOW / "skills" / "docs-keeper" / "SKILL.md"
TEXT = DOCS.read_text()
FLAT = " ".join(TEXT.split())
SKILL_TEXT = SKILL.read_text()

HEADINGS = ["## Profile", "## Modes", "## check", "## init", "## tidy", "## Never"]
REASONS = ["Review docs tidy PR #<n>", "Decide docs tidy items (issue #<n>)", "Run /docs init",
           "Docs tidy failed: <short cause>"]
PR_HEADINGS = ["## What changed", "## Moved files", "## CLAUDE.md", "## Profile changes", "## Check output"]
SKILL_HEADINGS = ["# Keeping docs cheap to read", "## Structure", "## Reading protocol", "## Writing rules",
                  "## Index row format", "## Maintain", "## Init", "## Tidy", "## Never"]


def section(name):
    return TEXT.split(f"\n## {name}\n")[1].split("\n## ")[0]


def test_front_matter():
    head = TEXT.split("---")[1]
    assert frontmatter(DOCS)["description"].startswith("Check, build or tidy the docs index")
    assert re.search(r"^model: sonnet$", head, re.M)
    assert 'argument-hint: "[check | init | tidy]"' in head


def test_profile_paragraph():
    assert ('Load the `project-profile` skill and follow its "Loading the profile" section. If it reports an '
            "error, show the message verbatim and stop; never substitute a value of your own for a missing key.") in FLAT


def test_headings_in_order():
    positions = [TEXT.index("\n" + h + "\n") for h in HEADINGS]
    assert positions == sorted(positions)


def test_key_words_present():
    for word in ["docs_index.py", "docs-keeper", "kind: maintenance", "command: docs", "<project>--docs",
                 '"scheduled"', "subscribe_pr_activity", "Usage: /docs [check | init | tidy]",
                 "toolkit.yaml: missing required key 'docs.index' (run /docs init)", "docs clean",
                 "chore/docs-init-<yyyymmdd>", "chore/docs-tidy-<yyyymmdd>", "Docs tidy: <n> items to decide"]:
        assert word in TEXT, word


def test_reasons():
    for reason in REASONS:
        assert reason in TEXT, reason


def test_init_pull_request_headings():
    init = section("init")
    for heading in PR_HEADINGS:
        assert heading in init, heading


def test_profile_hooks_only_in_init():
    init = section("init")
    for needle in ('protect_paths.py" --allow-profile', "--end-allow"):
        assert needle in init
        assert TEXT.count(needle) == init.count(needle)


def test_no_bot_command():
    assert not re.search(r"@\w", TEXT)


def test_never_section():
    never = section("Never")
    assert "Merge, approve, enable auto-merge or force-push" in never


def test_no_forbidden_words():
    assert FORBIDDEN.search(TEXT) is None
    assert FORBIDDEN.search(SKILL_TEXT) is None


def test_skill_headings_in_order():
    positions = [SKILL_TEXT.index("\n" + h + "\n") for h in SKILL_HEADINGS]
    assert positions == sorted(positions)
    assert frontmatter(SKILL)["name"] == "docs-keeper"
    assert len(SKILL_TEXT.splitlines()) <= 160


def test_skill_content():
    for word in ["60", "150", "400", "docs-changed:", "AskUserQuestion", "docs_index.py"]:
        assert word in SKILL_TEXT, word
    init = SKILL_TEXT.split("\n## Init\n")[1].split("\n## Tidy\n")[0]
    for n in range(1, 12):
        assert re.search(rf"^{n}\. ", init, re.M), n
