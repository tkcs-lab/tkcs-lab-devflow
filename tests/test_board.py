import shutil
import subprocess
import sys

import pytest

from conftest import DEVFLOW, FIXTURES, ROOT

BUILD = DEVFLOW / "scripts" / "build_board.py"
FIXTURE = FIXTURES / "board-records.json"
NOW = "2026-11-09T12:00:00Z"


def build(tmp_path, *extra, title="Devflow Board"):
    out = tmp_path / "board.html"
    result = subprocess.run([sys.executable, str(BUILD), "--title", title, "--out", str(out), *extra],
                            capture_output=True, text=True)
    return result, out


def test_build_fills_title_and_rules(tmp_path):
    result, out = build(tmp_path)
    assert result.returncode == 0, result.stderr
    page = out.read_text()
    assert "<title>Devflow Board</title>" in page
    assert "isSilent" in page
    for marker in ("<!--DEVFLOW:TITLE-->", "/*DEVFLOW:RULES*/"):
        assert marker not in page


def test_build_escapes_the_title(tmp_path):
    result, out = build(tmp_path, title="A <b>&</b>")
    assert result.returncode == 0, result.stderr
    assert "<title>A &lt;b&gt;&amp;&lt;/b&gt;</title>" in out.read_text()


def test_build_embeds_fixture_and_clock(tmp_path):
    result, out = build(tmp_path, "--fixture", str(FIXTURE), "--now", NOW)
    assert result.returncode == 0, result.stderr
    page = out.read_text()
    assert "f-running-silent" in page
    assert "var FIXED_NOW = 1794225600000;" in page


def test_build_rejects_a_bad_fixture(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    result, _ = build(tmp_path, "--fixture", str(bad))
    assert result.returncode == 1
    assert result.stderr.startswith("build_board: ")


def test_board_command_names_its_keys():
    text = (DEVFLOW / "commands" / "board.md").read_text()
    for needle in (
        "board_client.py health", "board_stale.py", "board_delete", "board_list",
        "DEVFLOW_BOARD_URL", "DEVFLOW_BOARD_TOKEN", "docs/guides/board-server.md",
    ):
        assert needle in text


def test_page_has_no_write_calls():
    page = (DEVFLOW / "board" / "board.html").read_text()
    for call in (".set(", ".update(", ".delete(", "<button"):
        assert call not in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_render_check():
    probe = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("playwright cannot be required")
    result = subprocess.run(["node", str(ROOT / "tests" / "board_render_check.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"
