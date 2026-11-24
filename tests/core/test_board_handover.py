import json
import subprocess

import pytest

from conftest import ROOT, FIXTURES, need_browser, need_tool, tld_cmd

FIXTURE = FIXTURES / "board-records-handover.json"
NOW = "2026-11-09T12:00:00Z"
RULES = ROOT / "src" / "tld" / "board" / "web" / "rules.js"


def docs():
    return json.loads(FIXTURE.read_text())


def node_check(name):
    result = subprocess.run(["node", str(ROOT / "tests" / name)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


@pytest.mark.slow
def test_rules_check():
    need_tool("node")
    node_check("board_handover_rules_check.js")


@pytest.mark.slow
def test_page_check():
    need_browser()
    node_check("board_handover_page_check.js")


def test_each_fixture_record_validates(tmp_path):
    for doc in docs():
        path = tmp_path / "r.json"
        path.write_text(json.dumps(doc["data"]))
        result = subprocess.run(tld_cmd("board", "validate-record", str(path), "--doc-id", doc["id"]),
                                capture_output=True, text=True)
        assert result.returncode == 0, doc["id"] + result.stdout + result.stderr


def test_stale_ids_equal_the_hidden_sections():
    need_tool("node")
    stale = subprocess.run(tld_cmd("board", "stale", str(FIXTURE), "--now", NOW), capture_output=True, text=True)
    assert stale.returncode == 0, stale.stderr
    script = (
        "const r = require(process.argv[1]); const docs = require(process.argv[2]); const now = Date.parse(process.argv[3]);"
        "console.log(JSON.stringify(docs.filter(d => r.section(d.data, now) === 'hidden').map(d => d.id)));"
    )
    node = subprocess.run(["node", "-e", script, str(RULES), str(FIXTURE), NOW], capture_output=True, text=True)
    assert node.returncode == 0, node.stderr
    hidden = set(json.loads(node.stdout))
    assert set(stale.stdout.split()) == hidden
    by_slug = {d["data"].get("handover", {}).get("plan_slug"): d["id"] for d in docs() if d["data"].get("handover")}
    assert by_slug["old-plan"] in hidden
    assert by_slug["demo-plan"] not in hidden and by_slug["issue-12"] not in hidden
    without = [d["id"] for d in docs() if d["data"]["kind"] == "command" and "handover" not in d["data"]]
    assert without and not set(without) & hidden
