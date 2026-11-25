import json
import re
import subprocess

import pytest

from conftest import ROOT, FIXTURES, need_browser, need_tool
from tld.board import record

FIXTURE = FIXTURES / "board-records-issue.json"
RULES = ROOT / "src" / "tld" / "board" / "web" / "rules.js"


def node_check(name):
    result = subprocess.run(["node", str(ROOT / "tests" / name)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


@pytest.mark.slow
def test_issue_link_rules():
    need_tool("node")
    node_check("board_issue_link_check.js")


@pytest.mark.slow
def test_issue_link_page():
    need_browser()
    node_check("board_issue_link_page_check.js")


def test_issue_link_fixture_is_valid():
    docs = json.loads(FIXTURE.read_text())
    assert len(docs) == 5
    for doc in docs:
        assert record.validate(doc["data"], doc["id"]) == [], doc["id"]


def test_issue_link_bounds_match_the_validator():
    text = RULES.read_text()
    match = re.search(r"^var ISSUE_MAX = (\d+);$", text, re.M)
    assert match and "var ISSUE_MAX = 9999999999;" in text
    assert int(match.group(1)) == record.ISSUE_MAX
    repo = re.search(r"^var ISSUE_REPO = /(.*)/;$", text, re.M)
    assert repo and repo.group(1).replace("\\/", "/") == record.REPO.pattern  # a JS literal escapes the slash
