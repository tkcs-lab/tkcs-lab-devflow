"""board-gate (UserPromptSubmit, PostToolUse, Stop): a record-writing command's session writes its record once."""
import json
import socket

import pytest

from hooks_helpers import PROFILE, make_repo_with_origin
from tld.board import mcp as board_mcp
from tld.board.store import Store
from tld.guard import _common, board_gate
from tld.guard.action import Action

ON = PROFILE + "hooks:\n  board_gate:\n    enabled: true\n"
RECORD = '{"id":"x","version":3}'


@pytest.fixture(autouse=True)
def no_board_env(monkeypatch):
    monkeypatch.delenv("TLD_BOARD_URL", raising=False)
    monkeypatch.delenv("TLD_BOARD_TOKEN", raising=False)


@pytest.fixture()
def repo(tmp_path):
    return make_repo_with_origin(tmp_path / "repo", "feature/demo", ON)


@pytest.fixture()
def board(repo, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    return repo


def decide(action):
    return _common.run_guard("board-gate", board_gate.evaluate, False, action)


def prompt(repo, invoked, sid="s1", text=None):
    text = text or f"/tld:{invoked} {'init ' if invoked == 'docs' else ''}x"  # docs writes a record only in init and tidy
    return decide(Action("prompt", str(repo), str(repo), prompt=text, invoked=invoked,
                         session_id=sid))


def stop(repo, sid="s1", continuing=False):
    return decide(Action("stop", str(repo), str(repo), session_id=sid, continuing=continuing))


def result(repo, output, op=None, command=None, sid="s1"):
    return decide(Action("tool_result", str(repo), str(repo), op=op, command=command, output=output, session_id=sid))


def state(repo, sid="s1"):
    return json.loads(board_gate.state_file(str(repo), sid).read_text())


def has_state(repo, sid="s1"):
    return board_gate.state_file(str(repo), sid).exists()


def test_a_command_prompt_opens_the_state(repo):
    assert prompt(repo, "docs").verdict == "allow"
    s = state(repo)
    assert (s["command"], s["written"], s["blocked"]) == ("docs", False, False) and s["opened_at"] > 0


@pytest.mark.parametrize("text", ["/tld:docs", "/tld:docs check", "/tld:docs bogus", "/docs", "  /tld:docs check x",
                                  "/tld:docs checkinit", "/tld:docs x init"])
def test_docs_without_a_record_mode_neither_opens_the_state_nor_blocks(board, text):
    assert prompt(board, "docs", text=text).verdict == "allow"
    assert not has_state(board)
    assert stop(board).verdict == "allow"


@pytest.mark.parametrize("text", ["/tld:docs init", "/tld:docs tidy", "/docs tidy", "  /tld:docs init x", "/tld:docs\ttidy",
                                  "<system-reminder>r</system-reminder>\n/tld:docs tidy",
                                  "<command-message>docs</command-message><command-name>/tld:docs</command-name>"
                                  "<command-args>init</command-args>"])
def test_docs_init_and_tidy_open_the_state_and_block_once_without_a_write(board, text):
    prompt(board, "docs", text=text)
    assert state(board)["command"] == "docs"
    assert stop(board).verdict == "deny"
    assert stop(board).verdict == "allow"


def test_a_plain_prompt_does_not_open_the_state(repo):
    prompt(repo, None, text="hello")
    assert not has_state(repo)


@pytest.mark.parametrize("name", ["board", "repo-admin"])
def test_prompts_of_commands_that_write_no_record_do_not_open_the_state(repo, name):
    prompt(repo, name)
    assert not has_state(repo)


def test_a_stop_without_a_write_blocks_with_the_message(board):
    prompt(board, "docs")
    d = stop(board)
    assert d.verdict == "deny" and "/tld:docs" in d.reason and "\n" not in d.reason
    assert d.reason == "tld board-gate: " + board_gate.MESSAGE.format(command="docs")
    assert d.reason.startswith("tld board-gate: this session was started by /tld:docs and has not written")
    assert "If the playbook says to write no record yet, say so and stop. This check blocks only once." in d.reason
    assert d.reason.count("This check blocks only once.") == 1 and 'tld board client set <id> - ' in d.reason


def test_a_second_stop_does_not_block(board):
    prompt(board, "docs")
    assert stop(board).verdict == "deny"
    assert stop(board).verdict == "allow"


def test_a_continuing_stop_does_not_block(board):
    prompt(board, "docs")
    assert stop(board, continuing=True).verdict == "allow"
    assert stop(board).verdict == "deny"


def test_a_reprompt_of_the_same_command_keeps_written(board):
    prompt(board, "docs")
    result(board, '{"id": "x", "version": 2}', op="board_set")
    prompt(board, "docs")
    assert state(board)["written"] is True


def test_a_prompt_of_a_different_command_reopens_the_state(board):
    prompt(board, "docs")
    result(board, '{"id": "x", "version": 2}', op="board_set")
    prompt(board, "review")
    s = state(board)
    assert (s["command"], s["written"]) == ("review", False)


def test_a_board_set_result_sets_written_and_the_stop_is_allowed(board):
    prompt(board, "docs")
    assert result(board, '{"id": "x", "version": 2}', op="board_set").verdict == "allow"
    assert state(board)["written"] is True
    assert stop(board).verdict == "allow"


def test_a_board_set_error_result_is_not_a_write(board):
    prompt(board, "docs")
    result(board, '{"error": "invalid"}', op="board_set")
    assert state(board)["written"] is False
    assert stop(board).verdict == "deny"


def test_a_client_set_with_a_record_line_sets_written(board):
    prompt(board, "docs")
    result(board, f"note\n{RECORD}\n", command="tld board client set x - --if-version 1")
    assert state(board)["written"] is True


def test_a_client_get_is_not_a_write(board):
    prompt(board, "docs")
    result(board, RECORD, command="tld board client get x && echo reset")
    assert state(board)["written"] is False


def test_a_client_set_version_conflict_is_not_a_write(board):
    prompt(board, "docs")
    out = '{"error":"version_conflict","current":{"id":"x","version":3}}'
    result(board, out, command="tld board client set x - --if-version 1")
    assert state(board)["written"] is False


def test_a_result_without_a_state_creates_none(board):
    result(board, RECORD, op="board_set")
    assert not has_state(board)


def test_no_board_url_never_blocks(repo, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    prompt(repo, "docs")
    assert stop(repo).verdict == "allow"


def test_no_token_never_blocks(repo, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    prompt(repo, "docs")
    assert stop(repo).verdict == "allow"


def test_a_bad_board_url_never_blocks(repo, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "ftp://x")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    prompt(repo, "docs")
    assert stop(repo).verdict == "allow"


def test_no_session_id_writes_nothing_and_never_blocks(board):
    assert prompt(board, "docs", sid=None).verdict == "allow"
    assert stop(board, sid=None).verdict == "allow"
    assert not (board_gate.state_file(str(board), "s1").parent).exists()


def test_a_state_older_than_the_ttl_never_blocks(board, monkeypatch):
    prompt(board, "docs")
    now = board_gate.time.time()
    monkeypatch.setattr(board_gate.time, "time", lambda: now + board_gate.SESSION_TTL_SECONDS + 1)
    assert stop(board).verdict == "allow"


def test_a_state_just_inside_the_ttl_blocks(board, monkeypatch):
    prompt(board, "docs")
    now = board_gate.time.time()
    monkeypatch.setattr(board_gate.time, "time", lambda: now + board_gate.SESSION_TTL_SECONDS - 5)
    assert stop(board).verdict == "deny"


def test_a_prompt_after_the_ttl_reopens_the_state(board, monkeypatch):
    prompt(board, "docs")
    result(board, RECORD, op="board_set")
    now = board_gate.time.time()
    monkeypatch.setattr(board_gate.time, "time", lambda: now + board_gate.SESSION_TTL_SECONDS + 1)
    prompt(board, "docs")
    assert state(board)["written"] is False


def test_the_hook_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    repo = make_repo_with_origin(tmp_path / "r", "feature/demo", PROFILE)
    prompt(repo, "docs")
    assert not has_state(repo) and stop(repo).verdict == "allow"


def test_enabled_false_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    repo = make_repo_with_origin(tmp_path / "r", "feature/demo", PROFILE + "hooks:\n  board_gate:\n    enabled: false\n")
    prompt(repo, "docs")
    assert not has_state(repo) and stop(repo).verdict == "allow"


def test_hooks_disable_in_the_committed_profile_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    repo = make_repo_with_origin(tmp_path / "r", "feature/demo", ON + "  disable: [board-gate]\n")
    prompt(repo, "docs")
    assert stop(repo).verdict == "allow"


def test_a_malformed_board_gate_section_notes_and_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    repo = make_repo_with_origin(tmp_path / "r", "feature/demo", PROFILE + "hooks:\n  board_gate:\n    enabled: yes please\n")
    d = stop(repo)
    assert d.verdict == "allow" and "hooks.board_gate.enabled" in (d.notice or "")


def test_an_invalid_json_state_file_never_blocks(board):
    prompt(board, "docs")
    board_gate.state_file(str(board), "s1").write_text("{not json")
    assert stop(board).verdict == "allow"


def test_a_directory_as_state_file_never_blocks(board):
    path = board_gate.state_file(str(board), "s1")
    path.mkdir(parents=True)
    assert prompt(board, "docs").verdict == "allow"
    assert stop(board).verdict == "allow"


def test_board_gate_stop_makes_no_network_call(board, monkeypatch):
    prompt(board, "docs")

    def no_socket(*args, **kwargs):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", no_socket)
    d = stop(board)
    assert d.verdict == "deny" and "has not written its status record" in d.reason


def test_real_mcp_board_set_result_is_a_record_write(board, tmp_path):
    from test_board_mcp import record
    store = Store(str(tmp_path / "b.db"))
    prompt(board, "docs")
    first = board_mcp._call_tool(store, "board_set", {"id": "f-running-ok", "data": record()})
    assert result(board, first["content"][0]["text"], op="board_set").verdict == "allow"
    assert state(board)["written"] is True
    prompt(board, "review")
    stale = board_mcp._call_tool(store, "board_set", {"id": "f-running-ok", "data": record(), "if_version": 9})
    assert stale["isError"]
    result(board, stale["content"][0]["text"], op="board_set")
    assert state(board)["written"] is False
