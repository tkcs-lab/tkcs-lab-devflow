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


def test_a_continuing_stop_evaluates_the_next_rule(board):
    prompt(board, "docs")
    assert stop(board, continuing=True).verdict == "deny"
    assert stop(board, continuing=True).verdict == "allow"


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
    first = board_mcp._call_tool(store, "board_set", {"id": "f-running-ok--run--plan-f-running-ok", "data": record()})
    assert result(board, first["content"][0]["text"], op="board_set").verdict == "allow"
    assert state(board)["written"] is True
    prompt(board, "review")
    stale = board_mcp._call_tool(store, "board_set", {"id": "f-running-ok--run--plan-f-running-ok", "data": record(), "if_version": 9})
    assert stale["isError"]
    result(board, stale["content"][0]["text"], op="board_set")
    assert state(board)["written"] is False


# --- ask, timer and dirty rules ---------------------------------------------------------------------------------------

TIMER = "tld board-gate: " + board_gate.TIMER_MESSAGE
DIRTY = "tld board-gate: " + board_gate.DIRTY_MESSAGE.format(command="docs")
FIRST = "tld board-gate: " + board_gate.MESSAGE.format(command="docs")
ASK = '{"id":"a-1f","state":"open"}'


def ask(repo, sid="s1"):
    return result(repo, ASK, op="board_ask", sid=sid)


def timer(repo):
    return result(repo, "{}", op="timer")


def write(repo):
    return result(repo, RECORD, op="board_set")


def reasons(repo, n, continuing=True):
    return [stop(repo, continuing=continuing).reason or None for _ in range(n)]


def test_an_ask_without_a_timer_blocks_once(board):
    prompt(board, "docs")
    write(board)
    ask(board)
    assert state(board)["ask_seq"] == 1
    assert stop(board).reason == TIMER
    assert stop(board).reason != TIMER


def test_an_ask_blocks_with_the_timer_message_without_a_board(repo):
    prompt(repo, "docs")
    ask(repo)
    assert stop(repo).reason == TIMER
    assert stop(repo).verdict == "allow"


def test_ask_timer_ask_blocks_again(board):
    prompt(board, "docs")
    ask(board)
    timer(board)
    ask(board)
    assert state(board)["ask_seq"] == 2
    assert stop(board).reason == TIMER


def test_a_timer_after_the_ask_means_no_timer_message(board):
    prompt(board, "docs")
    ask(board)
    timer(board)
    assert stop(board).reason != TIMER


def test_a_timer_before_the_ask_does_not_count(board):
    prompt(board, "docs")
    timer(board)
    ask(board)
    assert stop(board).reason == TIMER


@pytest.mark.parametrize("command,output,counts", [
    ("tld board ask f.json", "a-9c", True),
    ("tld board ask f.json", "ok\n<!-- tld-ask -->\nx", True),
    ("tld board ask-text f.json", "a-9c", False),
    ("grep 'board ask' x", "x:board ask", False),
    ("tld board ask f.json", "error: no board", False),
    ("tld board ask f.json", "a-", False),
    ("tld board ask f.json", "a-xyz", False),
])
def test_a_shell_ask_is_detected(repo, command, output, counts):
    action = Action("tool_result", str(repo), str(repo), command=command, output=output, session_id="s1")
    assert board_gate.is_ask_post(action) is counts


@pytest.mark.parametrize("body,counts", [
    ("<!-- tld-ask -->\nquestion", True),
    ("text <!-- tld-ask -->", False),
    (" <!-- tld-ask -->", False),
    ("\n<!-- tld-ask -->", False),
    (None, False),
    (5, False),
    (["<!-- tld-ask -->"], False),
])
def test_an_ask_comment_needs_the_marker_first(repo, body, counts):
    action = Action("tool_result", str(repo), str(repo), op="ask_comment", args={"body": body}, output="{}", session_id="s1")
    assert board_gate.is_ask_post(action) is counts


@pytest.mark.parametrize("output", ["not json", "[1]", None, "error: bad", '{"id": 5}', '{"id": "x-1"}', '"a-1"', ""])
def test_is_ask_post_rejects(repo, output):
    action = Action("tool_result", str(repo), str(repo), op="board_ask", output=output, session_id="s1")
    assert board_gate.is_ask_post(action) is False


def test_is_ask_post_ignores_other_kinds(repo):
    assert board_gate.is_ask_post(Action("stop", str(repo), str(repo), session_id="s1", op="board_ask", output=ASK)) is False


def test_a_shell_ask_counts_in_the_state(board):
    prompt(board, "docs")
    result(board, "a-9c\n", command="tld board ask f.json")
    assert state(board)["ask_seq"] == 1
    result(board, "a-9d", command="tld board ask-text f.json")
    result(board, "a-9d", command="ls")
    assert state(board)["ask_seq"] == 1


@pytest.mark.parametrize("op,command", [("worker_start", None), ("worker_stop", None), ("pr_create", None),
                                         (None, "git push origin x"), (None, "gh pr create --fill")])
def test_a_change_after_a_record_blocks_once(board, op, command):
    prompt(board, "docs")
    write(board)
    result(board, "ok", op=op, command=command)
    assert stop(board).reason == DIRTY
    assert stop(board).verdict == "allow"


def test_a_record_write_clears_the_dirty_rule(board):
    prompt(board, "docs")
    write(board)
    result(board, "ok", op="worker_start")
    write(board)
    assert state(board)["write_seq"] == state(board)["dirty_seq"] == 1
    assert stop(board).verdict == "allow"


def test_a_change_after_the_record_write_blocks_again(board):
    prompt(board, "docs")
    write(board)
    result(board, "ok", op="worker_start")
    assert stop(board).reason == DIRTY
    write(board)
    result(board, "ok", op="pr_create")
    assert stop(board).reason == DIRTY


def test_a_change_a_first_write_another_change_and_a_second_write(board):
    prompt(board, "docs")
    result(board, "ok", op="worker_start")
    write(board)
    result(board, "ok", op="worker_stop")
    write(board)
    assert stop(board).verdict == "allow"


def test_a_plain_stop_after_the_first_write_is_not_blocked(board):
    prompt(board, "docs")
    write(board)
    assert stop(board).verdict == "allow"


def test_the_ask_makes_the_record_dirty_too(board):
    prompt(board, "docs")
    write(board)
    ask(board)
    timer(board)
    assert stop(board).reason == DIRTY
    write(board)
    assert stop(board).verdict == "allow"


def test_ask_write_timer_stop_gives_no_block(board):
    prompt(board, "docs")
    ask(board)
    write(board)
    timer(board)
    assert stop(board).verdict == "allow"


def test_the_timer_rule_precedes_the_first_record_rule(board):
    prompt(board, "docs")
    ask(board)
    assert reasons(board, 3, continuing=False) == [TIMER, FIRST, None]


def test_without_a_record_the_dirty_rule_never_fires(board):
    prompt(board, "docs")
    ask(board)
    assert reasons(board, 4) == [TIMER, FIRST, None, None]


def test_stop_chain_ends(board):
    prompt(board, "docs")
    ask(board)
    result(board, "ok", op="worker_start")
    assert reasons(board, 3) == [TIMER, FIRST, None]


def test_stop_chain_ends_after_a_record_write(board):
    prompt(board, "docs")
    write(board)
    ask(board)
    result(board, "ok", op="worker_start")
    assert reasons(board, 4) == [TIMER, DIRTY, None, None]


def test_equal_sequence_numbers_do_not_block(board):
    prompt(board, "docs")
    write(board)
    ask(board)
    timer(board)
    s = state(board)
    s["write_seq"] = s["dirty_seq"]
    board_gate.state_file(str(board), "s1").write_text(json.dumps(s))
    assert (s["ask_seq"], s["timer_seq"]) == (1, 1)
    assert stop(board).verdict == "allow"


def test_a_state_one_ahead_blocks(board):
    prompt(board, "docs")
    write(board)
    s = state(board)
    s["ask_seq"], s["timer_seq"], s["dirty_seq"], s["write_seq"] = 2, 1, 1, 1
    board_gate.state_file(str(board), "s1").write_text(json.dumps(s))
    assert stop(board).reason == TIMER


def test_a_state_with_only_the_old_keys_loads_with_zeros(board):
    prompt(board, "docs")
    path = board_gate.state_file(str(board), "s1")
    path.write_text(json.dumps({"command": "docs", "opened_at": board_gate.time.time(), "written": False, "blocked": False}))
    loaded = board_gate._load(path)
    assert all(loaded[k] == 0 for k in board_gate.COUNTERS) and len(loaded) == 10


@pytest.mark.parametrize("bad", [True, -1, "x", 1.5, None])
def test_bad_counter_types_load_as_zero(board, bad):
    prompt(board, "docs")
    path = board_gate.state_file(str(board), "s1")
    s = state(board)
    s.update({k: bad for k in board_gate.COUNTERS})
    path.write_text(json.dumps(s))
    assert all(board_gate._load(path)[k] == 0 for k in board_gate.COUNTERS)


def test_save_round_trips_and_refreshes_opened_at(board, monkeypatch):
    prompt(board, "docs")
    path = board_gate.state_file(str(board), "s1")
    full = {"command": "docs", "opened_at": 1.0, "written": True, "blocked": True,
            **{k: i + 1 for i, k in enumerate(board_gate.COUNTERS)}}
    monkeypatch.setattr(board_gate.time, "time", lambda: 12345.0)
    board_gate._save(path, dict(full))
    loaded = board_gate._load(path)
    assert loaded == {**full, "opened_at": 12345.0} and len(loaded) == 10


def test_a_truncated_state_file_loads_as_none_and_save_leaves_no_tmp(board):
    prompt(board, "docs")
    path = board_gate.state_file(str(board), "s1")
    path.write_text('{"command": "docs", "opened_at": 1')
    assert board_gate._load(path) is None
    board_gate._save(path, {"command": "docs", "opened_at": 0, "written": False, "blocked": False})
    assert not list(path.parent.glob("*.tmp")) and board_gate._load(path)["command"] == "docs"


def test_a_second_prompt_keeps_the_counters(board):
    prompt(board, "docs")
    ask(board)
    prompt(board, "docs")
    assert state(board)["ask_seq"] == 1
    prompt(board, "review")
    assert state(board)["ask_seq"] == 0


def test_the_ttl_counts_from_the_last_save(board, monkeypatch):
    prompt(board, "docs")
    now = board_gate.time.time()
    monkeypatch.setattr(board_gate.time, "time", lambda: now + 24 * 3600 - 60)
    ask(board)
    monkeypatch.setattr(board_gate.time, "time", lambda: now + 2 * 24 * 3600 - 120)
    assert state(board)["ask_seq"] == 1
    assert stop(board).reason == TIMER
    monkeypatch.setattr(board_gate.time, "time", lambda: now + 4 * 24 * 3600)
    assert stop(board).verdict == "allow"


def test_a_timer_without_a_state_creates_none(board):
    timer(board)
    ask(board)
    assert not has_state(board)
