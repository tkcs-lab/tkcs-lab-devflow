import json
import subprocess

from conftest import ROOT, FIXTURES, need_tool

from tld.board import ask as ask_mod
from tld.board import record

FIXTURE = FIXTURES / "board-links.json"


def test_links_in_node():
    need_tool("node")
    result = subprocess.run(["node", str(ROOT / "tests" / "board_links_check.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_links_fixture_is_valid():
    fx = json.loads(FIXTURE.read_text())
    for entry in fx["entries"]:
        assert record.validate(entry["data"], None) == [], entry["id"]  # ids here are free-form: the page check only needs them unique
    for item in fx["asks"]:
        assert ask_mod.validate_stored(item) == [], item["id"]
