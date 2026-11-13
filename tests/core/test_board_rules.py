import json
import subprocess
import sys

import pytest

from conftest import ROOT, TLD, FIXTURES, need_tool, tld_cmd

FIXTURE = FIXTURES / "board-records.json"
NOW = "2026-11-09T12:00:00Z"
VALIDATOR = TLD / "board" / "record.py"
VALIDATOR_CMD = tld_cmd("board", "validate-record")
STALE = TLD / "board" / "stale.py"
STALE_CMD = tld_cmd("board", "stale")


def docs():
    return json.loads(FIXTURE.read_text())


def test_rules_in_node():
    need_tool("node")
    result = subprocess.run(["node", str(ROOT / "tests" / "board_rules_check.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_fixture_has_14_valid_records():
    entries = docs()
    assert len(entries) == 14
    for entry in entries:
        result = subprocess.run([*VALIDATOR_CMD, "-", "--doc-id", entry["id"]],
                                input=json.dumps(entry["data"]), capture_output=True, text=True)
        assert result.returncode == 0, f"{entry['id']}: {result.stdout}"


def test_board_stale_prints_the_hidden_ids():
    result = subprocess.run([*STALE_CMD, str(FIXTURE), "--now", NOW], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    ids = result.stdout.split()
    assert sorted(ids) == ["f-done-old--run--plan-f-done-old", "f-stale-quiet--run--plan-f-stale-quiet"]
    needs = {e["id"] for e in docs() if e["data"]["needs_you"]}
    assert not needs & set(ids)  # a record that needs the owner is never listed by age alone


def test_board_stale_reads_stdin():
    result = subprocess.run([*STALE_CMD, "-", "--now", NOW], input=FIXTURE.read_text(),
                            capture_output=True, text=True)
    assert sorted(result.stdout.split()) == ["f-done-old--run--plan-f-done-old",
                                             "f-stale-quiet--run--plan-f-stale-quiet"]
