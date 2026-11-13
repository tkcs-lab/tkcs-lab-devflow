import json
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, TLD, CLAUDE, FIXTURES, need_browser, tld_cmd

BUILD = TLD / "board" / "build.py"
BUILD_CMD = tld_cmd("board", "build")
FIXTURE = FIXTURES / "board-records.json"
NOW = "2026-11-09T12:00:00Z"


def build(tmp_path, *extra, title="tld Board"):
    out = tmp_path / "board.html"
    result = subprocess.run([*BUILD_CMD, "--title", title, "--out", str(out), *extra],
                            capture_output=True, text=True)
    return result, out


def test_build_fills_title_and_rules(tmp_path):
    result, out = build(tmp_path)
    assert result.returncode == 0, result.stderr
    page = out.read_text()
    assert "<title>tld Board</title>" in page
    assert "isSilent" in page
    for marker in ("<!--TLD:TITLE-->", "/*TLD:RULES*/"):
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


def test_page_builds_the_dom_from_text_only():
    page = (TLD / "board" / "web" / "board.html").read_text()
    for call in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert call not in page
    # The page writes nothing but answers, cancels, dismissals and the login: no record write path.
    assert 'api("PUT"' not in page and '"DELETE"' not in page


def test_build_injects_the_session_url(tmp_path):
    result, out = build(tmp_path, "--session-url", "https://sessions.example.org/s/")
    assert result.returncode == 0, result.stderr
    assert 'var SESSION_URL = "https://sessions.example.org/s/";' in out.read_text()
    result, out = build(tmp_path)
    assert "var SESSION_URL = /*TLD:SESSION_URL*/null;" in out.read_text()
    result, _ = build(tmp_path, "--session-url", "http://insecure.example.org/")
    assert result.returncode == 1


def test_page_has_no_hard_coded_session_host():
    page = (TLD / "board" / "web" / "board.html").read_text()
    assert "claude.ai" not in page


@pytest.mark.slow
def test_render_check():
    need_browser()
    result = subprocess.run(["node", str(ROOT / "tests" / "board_render_check.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


@pytest.mark.slow
def test_prompt_run_check():
    need_browser()
    result = subprocess.run(["node", str(ROOT / "tests" / "board_prompt_run_check.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


@pytest.mark.slow
def test_fixture_page_has_no_dismiss_or_restore_buttons(tmp_path):
    need_browser()
    result, out = build(tmp_path, "--fixture", str(FIXTURE), "--now", NOW)
    assert result.returncode == 0, result.stderr
    script = (
        "const { chromium } = require('playwright');"
        "(async () => { const b = await chromium.launch(); const p = await b.newPage();"
        "await p.goto('file://' + process.argv[1]); await p.waitForSelector('[data-section]');"
        "const a = await p.locator('[data-action]').count();"
        "const n = await p.locator('[data-section=\"needs_you\"] .row').count();"
        "await b.close(); console.log(JSON.stringify([a, n])); })().catch((e) => { console.error(e); process.exit(1); });"
    )
    run = subprocess.run(["node", "-e", script, str(out)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    actions, needs = json.loads(run.stdout)
    assert actions == 0
    assert needs > 0
