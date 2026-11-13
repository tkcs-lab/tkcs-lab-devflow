import subprocess

import pytest

from board_helpers import PASSPHRASE, WRITE, base, running
from conftest import ROOT, TLD, need_browser, need_tool

PAGE = (TLD / "board" / "web" / "board.html").read_text()
NOW = 1794570000


def test_usage_rules_in_node():
    need_tool("node")
    result = subprocess.run(["node", str(ROOT / "tests" / "board_usage_check.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_page_has_the_usage_link_and_the_plan_null_text():
    assert "usage-link" in PAGE
    assert "Usage is off. Set TLD_BOARD_PLAN=max (or standard) on the board host and restart it." in PAGE
    assert "innerHTML" not in PAGE


@pytest.mark.slow
def test_usage_page_shows_two_bars_in_a_browser(tmp_path):
    need_browser()
    with running(tmp_path, usage_plan=("max", 5.0), clock=lambda: NOW) as srv:
        result = subprocess.run(["node", str(ROOT / "tests" / "board_usage_page_check.js"), base(srv), WRITE, PASSPHRASE],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "OK"
