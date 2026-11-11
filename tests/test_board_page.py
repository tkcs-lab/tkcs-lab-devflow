import copy
import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone

import pytest

from conftest import DEVFLOW, FIXTURES, ROOT

sys.path.insert(0, str(DEVFLOW / "scripts"))
import board_server  # noqa: E402
import build_board  # noqa: E402
from board_store import Store  # noqa: E402

PAGE = (DEVFLOW / "board" / "board.html").read_text()


def test_page_has_no_claude_runtime():
    assert "claude.use" not in PAGE
    assert "onSnapshot" not in PAGE


def test_page_polls_the_records_api():
    assert "api/records" in PAGE


def test_page_keeps_the_markers_the_builder_needs():
    assert build_board.build("T", None, None)


def test_page_poll_interval_has_a_floor():
    assert "500" in PAGE and "15000" in PAGE


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_poll_in_a_browser(tmp_path):
    probe = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("playwright cannot be required")
    token = "w" * 24
    srv = board_server.make_server(Store(str(tmp_path / "b.sqlite3")), board_server.Tokens(token), "T",
                                   "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        docs = json.loads((FIXTURES / "board-records.json").read_text())
        rec = copy.deepcopy(next(d["data"] for d in docs if d["id"] == "f-running-ok"))
        rec["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec["next_check_at"] = None
        srv.store.set("f-running-ok", rec, None)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        result = subprocess.run(["node", str(ROOT / "tests" / "board_poll_check.js"), base, token],
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "OK"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(5)
