import copy
import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone

import pytest

from board_helpers import PASSPHRASE, WRITE, base, running
from conftest import ROOT, TLD, FIXTURES, need_browser

from tld.board import server as board_server  # noqa: E402
from tld.board import build as build_board  # noqa: E402
from tld.board.store import Store  # noqa: E402

pytestmark = pytest.mark.slow  # real servers and subprocesses, seconds per test

PAGE = (TLD / "board" / "web" / "board.html").read_text()


def test_page_has_no_claude_runtime():
    assert "claude.use" not in PAGE
    assert "onSnapshot" not in PAGE


def test_page_polls_the_records_api():
    assert "api/records" in PAGE


def test_page_keeps_the_markers_the_builder_needs():
    assert build_board.build("T", None, None)


def test_page_poll_interval_has_a_floor():
    assert "500" in PAGE and "15000" in PAGE


def test_login_poll_and_answer_an_ask_in_a_browser(tmp_path):
    need_browser()
    with running(tmp_path) as srv:
        docs = json.loads((FIXTURES / "board-records.json").read_text())
        rec = copy.deepcopy(next(d["data"] for d in docs if d["id"] == "f-running-ok"))
        rec["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec["next_check_at"] = None
        srv.store.set("f-running-ok", rec, None)
        result = subprocess.run(["node", str(ROOT / "tests" / "board_poll_check.js"), base(srv), WRITE, PASSPHRASE],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "OK"
