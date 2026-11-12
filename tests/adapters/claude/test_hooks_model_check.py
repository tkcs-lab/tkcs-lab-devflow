"""The Claude adapter of model-check: model names to levels, the transcript, command front matter, the events."""
import json
import os

import hooks_helpers as hh
from hooks_helpers import claude_adapter as ca, make_repo


def _assistant(model):
    return json.dumps({"type": "assistant", "message": {"model": model, "content": []}})


def test_level_of_maps_families():
    assert ca.level_of("x-OPUS-y") == "strong"
    assert ca.level_of("a-sonnet-b") == "standard"
    assert ca.level_of("haiku") == "fast"
    assert ca.level_of("gpt") is None
    assert ca.level_of(None) is None and ca.level_of(5) is None


def test_transcript_level_reads_the_newest_assistant_model(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([_assistant("a-haiku"), json.dumps({"type": "user"}), _assistant("a-opus"),
                            json.dumps({"type": "user"})]) + "\n")
    assert ca.transcript_level(str(f)) == "strong"


def test_transcript_level_drops_the_partial_first_line_of_a_big_file(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(_assistant("a-opus") + "\n" + "x" * 300000 + "\n")
    assert ca.transcript_level(str(f)) is None


def test_transcript_level_is_none_for_a_missing_file_and_bad_json(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n{\n[1]\n")
    for p in (str(tmp_path / "none"), str(bad), str(tmp_path), None, 3, ""):
        assert ca.transcript_level(p) is None


def test_command_level_reads_the_front_matter():
    assert ca.command_level("make-plan") == "strong"
    assert ca.command_level("implement") == "standard"
    assert ca.command_level("ask") == "standard"


def test_session_start_event_becomes_a_session_start_action(tmp_path):
    payload = {"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "SessionStart", "model": "x-sonnet-1"}
    a = ca.to_action(payload, str(tmp_path))
    assert (a.kind, a.session_id, a.session_level) == ("session_start", "s1", "standard")
    assert ca.to_action({**payload, "model": 3}, str(tmp_path)).session_level is None


def test_session_start_never_exits_non_zero(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/x", profile="hooks: [broken\n")
    r = ca.execute("model-check", json.dumps({"session_id": "s1", "cwd": str(repo), "hook_event_name": "SessionStart",
                                              "model": "x-opus-1"}))
    assert r.code == 0
    assert ca.execute("model-check", "not json").code == 1  # no event name known: unchanged behaviour
    assert ca.execute("model-check", json.dumps({"hook_event_name": "SessionStart", "cwd": 5})).code == 0


def test_the_warning_is_a_system_message_only(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/x")
    t = tmp_path / "t.jsonl"
    t.write_text(_assistant("x-opus-1") + "\n")
    r = ca.execute("model-check", json.dumps({"session_id": "s2", "cwd": str(repo), "hook_event_name": "UserPromptSubmit",
                                              "prompt": "/tld:implement x", "transcript_path": str(t)}))
    out = json.loads(r.stdout)
    assert r.code == 0 and "systemMessage" in out and "hookSpecificOutput" not in out


def test_transcript_level_ignores_a_fifo(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert ca.transcript_level(str(fifo)) is None
