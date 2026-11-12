"""tld plan active-run (src/tld/plan/active.py): is another run of make-plan or implement already going."""
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from conftest import ROOT, tld_cmd
from tld.plan import active
from test_contracts import code_texts, strip_placeholders

NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=timezone.utc)
BOT = "agent-bot"
MP_START = "Planning started. Session: abc123."
IM_START = "Implementation started on feature/x. Session: abc123."


def iso(minutes_ago=0, seconds_ago=0, now=NOW):
    return (now - timedelta(minutes=minutes_ago, seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def c(body, minutes_ago=0, seconds_ago=0, author=BOT):
    return {"author": author, "created_at": iso(minutes_ago, seconds_ago), "body": body}


def ev(kind, comments, **kw):
    kw.setdefault("bot", BOT)
    return active.evaluate(kind, comments, now=kw.pop("now", NOW), **kw)


def record(minutes_ago=5, **over):
    data = {"kind": "run", "plan_slug": "demo", "status": "running", "updated_at": iso(minutes_ago),
            "orchestrator_session": "sess1"}
    data.update(over)
    return {"id": "proj", "version": 3, "data": data}


def drop(rec, key):
    del rec["data"][key]
    return rec


# ---- the walk over the comments -------------------------------------------------------------
def test_no_comments_is_none():
    assert ev("make-plan", []) == {"state": "none"}


def test_open_start_by_the_bot_is_active():
    r = ev("make-plan", [c(MP_START, 10)])
    assert r == {"state": "active", "kind": "make-plan", "session": "abc123", "started_at": iso(10),
                 "last_seen": iso(10), "age_minutes": 10, "source": "comment"}


def test_start_by_someone_else_is_ignored():
    assert ev("make-plan", [c(MP_START, 10, author="outsider")]) == {"state": "none"}


@pytest.mark.parametrize("kind, start, final", [
    ("make-plan", MP_START, "Plan ready: https://x/y. Next: implement https://x/y."),
    ("make-plan", MP_START, "Plan ready: single-session prompt (see the issue body)."),
    ("make-plan", MP_START, "Planning stopped: no access."),
    ("implement", IM_START, "PR opened: https://x/pull/1."),
    ("implement", IM_START, "Implementation stopped: owner said no."),
])
def test_final_marker_closes_the_run(kind, start, final):
    assert ev(kind, [c(start, 30), c(final, 10)]) == {"state": "none"}


def test_a_later_start_after_a_final_opens_a_new_run():
    r = ev("make-plan", [c(MP_START, 60), c("Plan ready: u.", 50), c("Planning started. Session: s2.", 5)])
    assert r["state"] == "active" and r["session"] == "s2" and r["started_at"] == iso(5)


def test_later_bot_comment_is_a_sign_of_life():
    r = ev("make-plan", [c(MP_START, 200), c("Waiting for you: Answer the question.", 20)])
    assert r["state"] == "active" and r["started_at"] == iso(200) and r["last_seen"] == iso(20)
    assert r["age_minutes"] == 20


def test_silent_for_longer_than_max_age_is_stale():
    assert ev("make-plan", [c(MP_START, 180)])["state"] == "stale"


def test_exactly_max_age_is_still_active():
    assert ev("make-plan", [c(MP_START, 120)])["state"] == "active"


def test_one_second_over_max_age_is_stale():
    assert ev("make-plan", [c(MP_START, 120, 1)])["state"] == "stale"


def test_state_is_not_derived_from_age_minutes():
    r = ev("make-plan", [c(MP_START, 120, 30)])
    assert r["state"] == "stale" and r["age_minutes"] == 120


def test_future_timestamp_gives_age_zero():
    r = ev("make-plan", [c(MP_START, -30)])
    assert r["state"] == "active" and r["age_minutes"] == 0


def test_final_marker_by_someone_else_does_not_close_the_run():
    r = ev("make-plan", [c(MP_START, 30), c("Planning stopped: x.", 10, author="outsider")])
    assert r["state"] == "active"


def test_comment_by_someone_else_is_no_sign_of_life():
    r = ev("make-plan", [c(MP_START, 300), c("hello", 1, author="outsider")])
    assert r["state"] == "stale" and r["last_seen"] == iso(300)


@pytest.mark.parametrize("author, counts", [
    ("Agent-Bot", True), ("AGENT-BOT", True), ("agent-bot-x", False), ("xagent-bot", False),
    ("agent-bot[bot]", False),
])
def test_bot_login_compare_is_exact_and_case_insensitive(author, counts):
    r = ev("make-plan", [c(MP_START, 10, author=author)], bot="agent-bot")
    assert (r["state"] == "active") is counts


def test_comments_out_of_order_are_sorted():
    r = ev("make-plan", [c("Plan ready: u.", 10), c(MP_START, 30)])
    assert r == {"state": "none"}


def test_same_second_keeps_input_order():
    assert ev("make-plan", [c(MP_START, 5), c("Plan ready: u.", 5)]) == {"state": "none"}


# ---- sessions -------------------------------------------------------------------------------
def test_own_session_is_own_not_active():
    r = ev("make-plan", [c(MP_START, 5)], self_id="abc123")
    assert r["state"] == "own" and r["session"] == "abc123"


def test_other_session_is_not_own():
    assert ev("make-plan", [c(MP_START, 5)], self_id="other")["state"] == "active"


def test_session_is_read_from_the_start_comment():
    assert ev("make-plan", [c("Planning started. Session: s_01:AB-c.", 5)])["session"] == "s_01:AB-c"


@pytest.mark.parametrize("body", [
    "Planning started.", "Planning started. Session: unknown.", "Planning started. Session: make-plan.",
    "Planning started. Session: implement.", "Planning started. Session: ",
])
def test_unknown_or_missing_session_is_never_own(body):
    r = ev("make-plan", [c(body, 5)], self_id="unknown")
    assert r["state"] == "active" and r["session"] is None


def test_command_name_session_is_never_own():
    r = ev("make-plan", [c("Planning started. Session: make-plan.", 5)], self_id="make-plan")
    assert r["state"] == "active"


def test_session_is_read_without_the_trailing_period():
    assert ev("make-plan", [c("Planning started. Session: abc123.", 5)], self_id="abc123")["state"] == "own"
    assert ev("make-plan", [c("Planning started. Session: abc123.", 5)])["session"] == "abc123"
    r = ev("implement", [c("Implementation started on feature/x. Session: s_01.AB.", 5)], self_id="s_01.AB")
    assert r["session"] is None and r["state"] == "active"


# ---- what counts as a marker ----------------------------------------------------------------
@pytest.mark.parametrize("body, expect", [
    ("Note: Plan ready: x", "active"),
    ("Plan ready soon", "active"),
    ("Thanks.\nPlan ready: x", "active"),
    ("Thanks.\nPlanning stopped: x.", "active"),
    ("\n  Plan ready: x", "none"),
    ("   Planning stopped: x.\nmore", "none"),
    ("", "active"),
])
def test_markers_match_on_the_first_line_only(body, expect):
    assert ev("make-plan", [c(MP_START, 20), c(body, 5)])["state"] == expect


@pytest.mark.parametrize("body, expect", [
    ("Note: Plan ready: x", "active"),
    ("Plan ready soon", "active"),
    ("a\nPlan ready: x", "active"),
    ("\n  Plan ready: x", "none"),
])
def test_marker_counts_only_at_the_start_of_the_first_line(body, expect):
    assert ev("make-plan", [c(MP_START, 20), c(body, 5)])["state"] == expect


def test_start_marker_of_the_other_kind_is_not_a_start():
    assert ev("implement", [c("Implementation started.", 5)]) == {"state": "none"}
    assert ev("implement", [c(MP_START, 5)]) == {"state": "none"}
    assert ev("make-plan", [c(IM_START, 5)]) == {"state": "none"}


def test_crlf_body_still_yields_the_session():
    r = ev("make-plan", [c("Planning started. Session: abc123.\r\n\r\nmore text", 5)])
    assert r["session"] == "abc123"


def test_old_start_comment_without_session_matches():
    r = ev("make-plan", [c("Planning started.\n\n---\n_Generated by x_", 5)])
    assert r["state"] == "active" and r["session"] is None


# ---- the board record -----------------------------------------------------------------------
def rec_ev(rec, comments=(), **kw):
    kw.setdefault("plan_slug", "demo")
    return ev(kw.pop("kind", "implement"), list(comments), record=rec, **kw)


def test_record_alone_makes_an_implement_run_active():
    r = rec_ev(record(5))
    assert r == {"state": "active", "kind": "implement", "session": "sess1", "started_at": None,
                 "last_seen": iso(5), "age_minutes": 5, "source": "record"}


@pytest.mark.parametrize("change", [
    {"plan_slug": "other"}, {"kind": "command"}, {"status": "done"}, {"status": "failed"},
    {"status": "pr_open"}, {"updated_at": "yesterday"}, {"updated_at": "2026-11-12T10:00:00"},
])
def test_record_of_another_plan_or_a_finished_run_is_ignored(change):
    assert rec_ev(record(5))["state"] == "active"
    assert rec_ev(record(5, **change)) == {"state": "none"}


def test_record_missing_plan_slug_or_updated_at_is_ignored():
    assert rec_ev(drop(record(5), "plan_slug")) == {"state": "none"}
    assert rec_ev(drop(record(5), "updated_at")) == {"state": "none"}
    assert rec_ev(drop(record(5), "kind")) == {"state": "none"}


def test_record_without_session_gives_null_session():
    r = rec_ev(drop(record(5), "orchestrator_session"))
    assert r["state"] == "active" and r["session"] is None


def test_record_without_plan_slug_argument_is_ignored():
    assert ev("implement", [], record=record(5)) == {"state": "none"}


def test_record_extends_last_seen():
    r = rec_ev(record(5), [c(IM_START, 200)])
    assert r["state"] == "active" and r["last_seen"] == iso(5) and r["source"] == "record"
    assert r["started_at"] == iso(200) and r["session"] == "abc123"


def test_older_record_changes_neither_last_seen_nor_source():
    r = rec_ev(record(100), [c(IM_START, 10)])
    assert r["last_seen"] == iso(10) and r["source"] == "comment"
    r = rec_ev(record(10), [c(IM_START, 10)])
    assert r["source"] == "comment"


def test_record_older_than_the_last_final_comment_is_ignored():
    r = rec_ev(record(50), [c(IM_START, 100), c("PR opened: u.", 20)])
    assert r == {"state": "none"}
    r = rec_ev(record(10), [c(IM_START, 100), c("PR opened: u.", 20)])
    assert r["state"] == "active" and r["source"] == "record"
    assert rec_ev(record(20), [c(IM_START, 100), c("PR opened: u.", 20)]) == {"state": "none"}


def test_record_is_ignored_for_make_plan():
    assert rec_ev(record(5))["state"] == "active"
    assert rec_ev(record(5), kind="make-plan") == {"state": "none"}


def test_record_accepts_envelope_and_bare_data():
    rec = record(5)
    assert rec_ev(rec)["state"] == "active"
    assert rec_ev(rec["data"])["state"] == "active"


def test_record_session_equal_to_self_is_own():
    assert rec_ev(record(5), self_id="sess1")["state"] == "own"
    assert rec_ev(record(5), self_id="sess2")["state"] == "active"


def test_stale_record_alone_is_stale():
    assert rec_ev(record(300))["state"] == "stale"


# ---- the command line -----------------------------------------------------------------------
def run(*args):
    return subprocess.run([*tld_cmd("plan", "active-run", *args)], capture_output=True, text=True)


def write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return str(p)


def cli(tmp_path, comments, *extra, kind="make-plan", now=NOW):
    f = write(tmp_path, "comments.json", comments)
    return run("--kind", kind, "--comments", f, "--bot", BOT, "--now", iso(0, 0, now), *extra)


@pytest.mark.parametrize("state, code, comments, extra", [
    ("none", 0, [], []),
    ("own", 0, [c(MP_START, 5)], ["--self", "abc123"]),
    ("stale", 0, [c(MP_START, 500)], []),
    ("active", 4, [c(MP_START, 5)], []),
])
def test_cli_states_and_exit_codes(tmp_path, state, code, comments, extra):
    r = cli(tmp_path, comments, *extra)
    assert r.returncode == code, r.stderr
    assert len(r.stdout.strip().splitlines()) == 1 and json.loads(r.stdout)["state"] == state


def test_cli_exit_4_only_for_active(tmp_path):
    codes = {cli(tmp_path, [c(MP_START, m)]).returncode for m in (1, 119)}
    assert codes == {4}
    assert cli(tmp_path, [c(MP_START, 500)]).returncode == 0


def test_cli_default_max_age_is_120(tmp_path):
    assert cli(tmp_path, [c(MP_START, 120)]).returncode == 4
    assert cli(tmp_path, [c(MP_START, 121)]).returncode == 0
    assert cli(tmp_path, [c(MP_START, 121)], "--max-age-minutes", "200").returncode == 4


def test_cli_empty_comments_with_record_is_active(tmp_path):
    rf = write(tmp_path, "rec.json", record(5))
    r = cli(tmp_path, [], "--record", rf, "--plan-slug", "demo", kind="implement")
    assert r.returncode == 4 and json.loads(r.stdout)["source"] == "record"


def test_cli_record_with_make_plan_is_accepted_and_ignored(tmp_path):
    rf = write(tmp_path, "rec.json", record(5))
    r = cli(tmp_path, [], "--record", rf, "--plan-slug", "demo")
    assert r.returncode == 0 and json.loads(r.stdout) == {"state": "none"}
    r = cli(tmp_path, [], "--record", rf)  # make-plan: even without --plan-slug
    assert r.returncode == 0


def test_cli_accepts_an_object_with_comments(tmp_path):
    r = cli(tmp_path, {"comments": [c(MP_START, 5)]})
    assert r.returncode == 4


@pytest.mark.parametrize("name, build", [
    ("missing author", lambda t: cli(t, [{"created_at": iso(1), "body": "x"}])),
    ("missing body", lambda t: cli(t, [{"author": BOT, "created_at": iso(1)}])),
    ("body not a string", lambda t: cli(t, [{"author": BOT, "created_at": iso(1), "body": 3}])),
    ("author not a string", lambda t: cli(t, [{"author": None, "created_at": iso(1), "body": "x"}])),
    ("comment not an object", lambda t: cli(t, ["x"])),
    ("bad timestamp", lambda t: cli(t, [{"author": BOT, "created_at": "soon", "body": "x"}])),
    ("not a list", lambda t: cli(t, "42")),
    ("object without comments", lambda t: cli(t, {"other": []})),
    ("not json", lambda t: cli(t, "{nope")),
    ("missing file", lambda t: run("--kind", "make-plan", "--comments", str(t / "nope.json"), "--bot", BOT)),
    ("record without plan slug", lambda t: cli(t, [], "--record", write(t, "r.json", record()), kind="implement")),
    ("record not json", lambda t: cli(t, [], "--record", write(t, "r.json", "{"), "--plan-slug", "d",
                                       kind="implement")),
    ("record not an object", lambda t: cli(t, [], "--record", write(t, "r.json", "[]"), "--plan-slug", "d",
                                            kind="implement")),
    ("record data not an object", lambda t: cli(t, [], "--record", write(t, "r.json", {"data": 3}),
                                                 "--plan-slug", "d", kind="implement")),
    ("record file missing", lambda t: cli(t, [], "--record", str(t / "none.json"), "--plan-slug", "d",
                                           kind="implement")),
    ("max age zero", lambda t: cli(t, [], "--max-age-minutes", "0")),
    ("max age text", lambda t: cli(t, [], "--max-age-minutes", "x")),
])
def test_cli_rejects_bad_input(tmp_path, name, build):
    r = build(tmp_path)
    assert r.returncode == 1, (name, r.stdout, r.stderr)
    assert r.stderr.startswith("plan: ") and "Traceback" not in r.stderr and r.stdout == ""


@pytest.mark.parametrize("stamp", ["2026-11-12T10:00:00", "2026-11-12T10:00:00+00:00", "2026-11-12T10:00:00.123Z"])
def test_cli_rejects_naive_and_offset_timestamps(tmp_path, stamp):
    r = cli(tmp_path, [{"author": BOT, "created_at": stamp, "body": MP_START}])
    assert r.returncode == 1 and r.stderr.startswith("plan: ") and "Traceback" not in r.stderr and r.stdout == ""


def test_cli_rejects_a_bad_now(tmp_path):
    f = write(tmp_path, "c.json", [])
    r = run("--kind", "make-plan", "--comments", f, "--bot", BOT, "--now", "tomorrow")
    assert r.returncode == 1 and r.stderr.startswith("plan: ") and "Traceback" not in r.stderr and r.stdout == ""


def test_cli_bad_kind_and_missing_flags_exit_2(tmp_path):
    f = write(tmp_path, "c.json", [])
    assert run("--kind", "review", "--comments", f, "--bot", BOT).returncode == 2
    assert run("--kind", "make-plan", "--comments", f).returncode == 2


def test_cli_without_now_uses_the_clock(tmp_path):
    f = write(tmp_path, "c.json", [])
    r = run("--kind", "make-plan", "--comments", f, "--bot", BOT)
    assert r.returncode == 0 and json.loads(r.stdout) == {"state": "none"}


def test_cli_help_lists_the_kinds():
    r = subprocess.run([*tld_cmd("plan", "active-run", "--help")], capture_output=True, text=True)
    assert r.returncode == 0 and "{make-plan,implement}" in r.stdout


# ---- the playbooks and the command agree ----------------------------------------------------
SAMPLES = {"id": "sess9", "feature": "feature/x", "url": "https://github.com/o/r/pull/1",
           "plan URL": "https://github.com/o/r/blob/main/p.md", "short cause": "no access"}
MARKER_START = ("Planning started", "Plan ready:", "Planning stopped:", "Implementation started on",
                "Implementation stopped:", "PR opened:")


def sample(text):
    def fill(m):
        return SAMPLES.get(m.group(1), "sample")
    return re.sub(r"<([^<>]*)>", fill, text)


def playbook_markers():
    out = []
    for name, kind in (("make-plan", "make-plan"), ("implement", "implement")):
        for code in code_texts((ROOT / "playbooks" / f"{name}.md").read_text()):
            if code.startswith(MARKER_START):
                out.append((kind, name, sample(code)))
    return out


def test_playbook_markers_are_the_ones_the_command_reads():
    found = playbook_markers()
    assert found
    texts = {(k, t) for k, _, t in found}
    for kind, _, text in found:
        if kind == "make-plan" and text.startswith(("Implementation", "PR opened")):
            continue
        starts = ("Planning started." if kind == "make-plan" else "Implementation started on ")
        finals = ("Plan ready:", "Planning stopped:") if kind == "make-plan" else \
            ("PR opened:", "Implementation stopped:")
        if text.startswith(starts):
            r = ev(kind, [c(text, 5)])
            assert r["state"] == "active" and r["session"] == "sess9", text
        else:
            assert text.startswith(finals), (kind, text)
            assert ev(kind, [c(MP_START if kind == "make-plan" else IM_START, 9), c(text, 5)]) == {"state": "none"}
    # every marker the command reads is written somewhere
    assert any(t.startswith("Planning started. Session: ") for k, t in texts if k == "make-plan")
    assert any(t.startswith("Implementation started on ") and "Session: sess9." in t for k, t in texts)
    for needle in ("Plan ready:", "Planning stopped:"):
        assert any(t.startswith(needle) for _, t in texts)
    for needle in ("PR opened:", "Implementation stopped:"):
        assert any(t.startswith(needle) for _, t in texts)


def playbook_calls():
    out = []
    for name in ("make-plan", "implement"):
        for code in code_texts((ROOT / "playbooks" / f"{name}.md").read_text()):
            if code.startswith("tld plan active-run"):
                out.append((name, code))
    return out


def test_playbook_active_run_calls_run(tmp_path):
    calls = playbook_calls()
    assert {n for n, _ in calls} == {"make-plan", "implement"}
    comments = write(tmp_path, "comments.json", [c(MP_START, 5)])
    rec = write(tmp_path, "record.json", record(5))
    for name, code in calls:
        words = strip_placeholders(code).split()
        args, i = [], 3
        while i < len(words):
            flag, val = words[i], words[i + 1] if i + 1 < len(words) else None
            if flag == "--comments":
                val = comments
            elif flag == "--record":
                val = rec
            elif flag == "--bot":
                val = BOT
            elif flag == "--plan-slug":
                val = "demo"
            elif flag == "--self":
                val = "mine"
            args += [flag, val]
            i += 2
        r = run(*args)
        assert r.returncode in (0, 4), (code, r.stderr)
        assert len(r.stdout.strip().splitlines()) == 1 and "state" in json.loads(r.stdout)


def test_module_runs_as_a_script(tmp_path, monkeypatch):
    import runpy
    import sys
    f = write(tmp_path, "c.json", [])
    monkeypatch.setattr(sys, "argv", ["active", "--kind", "make-plan", "--comments", f, "--bot", BOT])
    sys.modules.pop("tld.plan.active", None)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("tld.plan.active", run_name="__main__")
    assert exc.value.code == 0
