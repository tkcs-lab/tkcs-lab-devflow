"""The ask model, `tld board ask | answers | cancel`, the issue fallback and the client's redirect handling."""
import json
import os
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from board_helpers import WRITE, ask_doc, base, running
from conftest import ROOT, tld_cmd

from tld.board import ask as ask_model
from tld.board import inbox
from tld.net import SameHostRedirects, same_origin


def env_for(url=None, token=WRITE):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_")}
    if url:
        env["TLD_BOARD_URL"] = url
    if token:
        env["TLD_BOARD_TOKEN"] = token
    return env


def tld(*args, env=None, stdin=None, cwd=None):
    return subprocess.run([*tld_cmd("board", *args)], env=env or env_for(), input=stdin, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


@pytest.fixture
def server(tmp_path):
    with running(tmp_path) as srv:
        yield srv


# ---- the ask model --------------------------------------------------------------------------------

def test_schema_and_validator_agree_on_the_fields():
    schema = json.loads((ROOT / "src" / "tld" / "schema" / "ask.schema.json").read_text())
    assert tuple(schema["properties"]) == ask_model.FIELDS
    assert tuple(schema["required"]) == ask_model.REQUIRED
    q = schema["properties"]["questions"]
    assert q["maxItems"] == ask_model.MAX_QUESTIONS
    assert q["items"]["properties"]["text"]["maxLength"] == ask_model.MAX_TEXT
    assert q["items"]["properties"]["options"]["maxItems"] == ask_model.MAX_OPTIONS


def test_a_good_ask_is_valid():
    assert ask_model.validate_new(ask_doc()) == []
    assert tld("validate-ask", "-", stdin=json.dumps(ask_doc())).stdout.strip() == "ask: OK"


@pytest.mark.parametrize("changes,needle", [
    ({"kind": "run"}, "'kind'"),
    ({"schema": 2}, "'schema'"),
    ({"project": "other"}, "slug of the repository"),
    ({"repo": "nope"}, "owner/name"),
    ({"title": "two\nlines"}, "one line"),
    ({"title": "x" * 121}, "at most 120"),
    ({"created_by": "has space"}, "'created_by'"),
    ({"context_url": "http://example.com"}, "https://"),
    ({"context_url": "javascript:alert(1)"}, "https://"),
    ({"fallback_issue": "not an issue"}, "'fallback_issue'"),
    ({"questions": []}, "1 to 30"),
    ({"questions": [{"id": "q", "text": "t", "kind": "text"}] * 31}, "1 to 30"),
    ({"id": "a-0123456789abcdef"}, "set by the board"),
    ({"state": "answered"}, "'state'"),
    ({"answers": {"q": "x"}}, "'answers'"),
    ({"extra": 1}, "not a known field"),
])
def test_bad_asks_are_refused(changes, needle):
    errors = ask_model.validate_new(ask_doc(**changes))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("question,needle", [
    ({"id": "q", "text": "t", "kind": "choice"}, "2 to 10 options"),
    ({"id": "q", "text": "t", "kind": "choice", "options": [{"value": "a"}]}, "2 to 10 options"),
    ({"id": "q", "text": "t", "kind": "choice", "options": [{"value": "a"}, {"value": "A"}]}, "used twice"),
    ({"id": "q", "text": "t", "kind": "choice", "options": [{"value": "a b"}, {"value": "c"}]}, "'value'"),
    ({"id": "q", "text": "t", "kind": "choice", "options": ["a", "b"]}, "must be an object"),
    ({"id": "q", "text": "t", "kind": "confirm", "options": [{"value": "a"}, {"value": "b"}]}, "only allowed"),
    ({"id": "q", "text": "t", "kind": "slider"}, "'kind'"),
    ({"id": "bad id", "text": "t", "kind": "text"}, "'id'"),
    ({"id": "q", "text": "x" * 2001, "kind": "text"}, "at most 2000"),
    ({"id": "q", "text": "bell\x07", "kind": "text"}, "control characters"),
    ({"id": "q", "text": "rtl‮", "kind": "text"}, "control characters"),
    ({"id": "q", "text": "t", "kind": "text", "required": "yes"}, "'required'"),
    ({"id": "q", "text": "t", "kind": "text", "html": "<b>"}, "unknown field"),
])
def test_bad_questions_are_refused(question, needle):
    errors = ask_model.validate_new(ask_doc(questions=[question]))
    assert any(needle in e for e in errors), errors


def test_duplicate_question_ids_are_refused():
    q = {"id": "q", "text": "t", "kind": "text"}
    assert any("used twice" in e for e in ask_model.validate_new(ask_doc(questions=[q, q])))


def test_an_oversized_ask_is_refused():
    options = [{"value": f"o{m}", "label": "z" * 200} for m in range(10)]
    questions = [{"id": f"q{n}", "text": "y" * 2000, "kind": "choice", "options": options} for n in range(30)]
    assert any("larger than" in e for e in ask_model.validate_new(ask_doc(questions=questions)))


# ---- tld board ask / answers / cancel ---------------------------------------------------------------

def test_ask_posts_and_prints_the_id(server, tmp_path):
    path = tmp_path / "ask.json"
    path.write_text(json.dumps(ask_doc()))
    result = tld("ask", str(path), env=env_for(base(server)))
    assert result.returncode == 0, result.stderr
    ask_id = result.stdout.strip()
    assert server.store.get_ask(ask_id)["state"] == "open"


def test_ask_refuses_an_invalid_ask_before_posting(server):
    result = tld("ask", "-", env=env_for(base(server)), stdin=json.dumps(ask_doc(questions=[])))
    assert result.returncode == 1 and "ask: 'questions'" in result.stdout
    assert server.store.list_asks() == []


def test_ask_without_a_board_is_exit_3():
    result = tld("ask", "-", env=env_for(None, None), stdin=json.dumps(ask_doc()))
    assert result.returncode == 3 and "no board configured" in result.stderr


def test_answers_exit_codes(server):
    ask = server.store.create_ask(ask_doc())
    env = env_for(base(server))
    started = time.monotonic()
    result = tld("answers", ask["id"], "--wait", "1.5", "--interval", "1", env=env)
    assert result.returncode == 3 and result.stdout == "" and "still open" in result.stderr
    assert time.monotonic() - started >= 1.4
    server.store.answer_ask(ask["id"], {"SEC-1": "drop", "go": True, "notes": "fine"})
    result = tld("answers", ask["id"], env=env)
    assert result.returncode == 0 and json.loads(result.stdout) == {"SEC-1": "drop", "go": True, "notes": "fine"}
    other = server.store.create_ask(ask_doc())
    server.store.cancel_ask(other["id"])
    assert tld("answers", other["id"], env=env).returncode == 4
    assert tld("answers", "a-ffffffffffffffff", env=env).returncode == 1
    assert tld("answers", ask["id"], env=env_for(None, None)).returncode == 1


def test_answers_wait_returns_as_soon_as_the_owner_answers(server):
    ask = server.store.create_ask(ask_doc())
    timer = threading.Timer(1.0, server.store.answer_ask, (ask["id"], {"SEC-1": "plan", "go": False}))
    timer.start()
    try:
        started = time.monotonic()
        result = tld("answers", ask["id"], "--wait", "30", "--interval", "1", env=env_for(base(server)))
    finally:
        timer.cancel()
    assert result.returncode == 0 and json.loads(result.stdout) == {"SEC-1": "plan", "go": False}
    assert time.monotonic() - started < 20


def test_cancel(server):
    ask = server.store.create_ask(ask_doc())
    env = env_for(base(server))
    result = tld("cancel", ask["id"], env=env)
    assert result.returncode == 0 and json.loads(result.stdout) == {"id": ask["id"], "state": "cancelled"}
    answered = server.store.create_ask(ask_doc())
    server.store.answer_ask(answered["id"], {"SEC-1": "plan", "go": True})
    result = tld("cancel", answered["id"], env=env)
    assert result.returncode == 1 and "already answered" in result.stderr


# ---- the issue fallback -----------------------------------------------------------------------------

def test_fallback_prints_the_comment_and_exits_5_without_a_board(tmp_path):
    result = tld("ask", "-", "--fallback-issue", "example/example-project#7", "--mention", "the-owner",
                 env=env_for(None, None), stdin=json.dumps(ask_doc()))
    assert result.returncode == 5, result.stderr
    body = result.stdout
    assert body.startswith(inbox.MARKER + "\n@the-owner a tld session (session_example) needs your answers:")
    assert "1. `SEC-1` (choice, required): Token in logs.\n   Fix it?" in body
    assert "   Options: `plan` (plan (recommended)), `issue`, `drop`" in body
    assert "2. `go` (confirm, required): Run the commands?\n   Answer `yes` or `no`." in body
    assert "3. `notes` (text, optional)" in body
    assert "```\nSEC-1: plan\ngo: yes\nnotes: <your answer on one line>\n```" in body
    assert "Context: https://example.com/review.md" in body
    assert "example/example-project#7" in result.stderr


def test_fallback_when_the_board_cannot_be_reached():
    env = env_for("http://127.0.0.1:9")  # nothing listens on the discard port
    result = tld("ask", "-", "--fallback-issue", "example/example-project", env=env, stdin=json.dumps(ask_doc()))
    assert result.returncode == 5 and result.stdout.startswith(inbox.MARKER)
    assert "@example a tld session" in result.stdout  # default: the repository owner
    without = tld("ask", "-", env=env, stdin=json.dumps(ask_doc()))
    assert without.returncode == 1 and "cannot reach" in without.stderr


def test_fallback_mentions_the_profile_owner_login(tmp_path):
    (tmp_path / ".tld").mkdir()
    (tmp_path / ".tld" / "toolkit.yaml").write_text("git:\n  owner_login: profile-owner\n")
    result = tld("ask", "-", "--fallback-issue", "example/example-project#1", env=env_for(None, None),
                 stdin=json.dumps(ask_doc()), cwd=tmp_path)
    assert result.returncode == 5 and "@profile-owner a tld session" in result.stdout


def test_fallback_body_mentions_nobody_else():
    body = inbox.fallback_comment(ask_doc(title="ping @someone", questions=[
        {"id": "q", "text": "cc @other-person", "kind": "text"}]), "owner")
    assert body.count("@") == 3 and "@​someone" in body and "@​other-person" in body


def test_the_fallback_ref_and_mention_are_checked():
    assert tld("ask", "-", "--fallback-issue", "nope", stdin=json.dumps(ask_doc())).returncode == 2
    assert tld("ask", "-", "--fallback-issue", "a/b#1", "--mention", "bad login!",
               stdin=json.dumps(ask_doc())).returncode == 2


def _comments(*items):
    return [{"author": a, "permission": p, "body": b} for a, p, b in items]


def test_answers_from_issue_counts_only_owners_and_collaborators(tmp_path):
    ask_file = tmp_path / "ask.json"
    ask_file.write_text(json.dumps(ask_doc()))
    comments = _comments(
        ("agent-bot", "write", inbox.fallback_comment(ask_doc(), "owner")),  # the question itself
        ("stranger", "read", "SEC-1: drop\ngo: no"),                        # not a collaborator
        ("drive-by", "none", "SEC-1: drop"),
        ("agent-bot", "write", "SEC-1: drop"),                              # the session's own login
        ("the-owner", "admin", "Thanks!\nSEC-1: Issue\ngo: yes\n> notes: quoted, ignored"),
        ("helper", "maintain", "notes: please link #12\nSEC-1: not-an-option"),
    )
    path = tmp_path / "comments.json"
    path.write_text(json.dumps(comments))
    result = tld("answers", "--from-issue", str(path), "--ask", str(ask_file), "--ignore-author", "agent-bot")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"SEC-1": "issue", "go": True, "notes": "please link #12"}


def test_answers_from_issue_later_overrides_and_incomplete_is_exit_3(tmp_path):
    ask_file = tmp_path / "ask.json"
    ask_file.write_text(json.dumps(ask_doc()))
    path = tmp_path / "comments.json"
    path.write_text(json.dumps(_comments(("o", "admin", "SEC-1: plan"), ("o", "write", "`SEC-1`: drop"))))
    result = tld("answers", "--from-issue", str(path), "--ask", str(ask_file))
    assert result.returncode == 3 and "go" in result.stderr and result.stdout == ""
    path.write_text(json.dumps(_comments(("o", "admin", "SEC-1: plan"), ("o", "write", "`SEC-1`: drop\ngo: n"))))
    result = tld("answers", "--from-issue", str(path), "--ask", str(ask_file))
    assert result.returncode == 0 and json.loads(result.stdout) == {"SEC-1": "drop", "go": False}


def test_answers_from_issue_ignores_fenced_examples():
    found = inbox.answers_from_comments(ask_doc(), _comments(("o", "admin", "```\nSEC-1: plan\ngo: yes\n```")))
    assert found == {}


def test_answers_from_issue_needs_the_ask(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("[]")
    assert tld("answers", "--from-issue", str(path)).returncode == 2
    (tmp_path / "a.json").write_text(json.dumps(ask_doc()))
    path.write_text("{}")
    assert tld("answers", "--from-issue", str(path), "--ask", str(tmp_path / "a.json")).returncode == 1


# ---- redirects keep the token on the same origin (S18) ----------------------------------------------

def test_same_host_redirects_drop_authorization_elsewhere():
    handler = SameHostRedirects()
    req = urllib.request.Request("https://board.example.org/api/asks", headers={"Authorization": "Bearer t"})
    same = handler.redirect_request(req, None, 302, "Found", {}, "https://board.example.org/api/asks/")
    other = handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/x")
    downgrade = handler.redirect_request(req, None, 302, "Found", {}, "http://board.example.org/x")
    port = handler.redirect_request(req, None, 302, "Found", {}, "https://board.example.org:8443/x")
    assert same.get_header("Authorization") == "Bearer t"
    for new in (other, downgrade, port):
        assert new.get_header("Authorization") is None
    assert same_origin("https://A.example.org/x", "https://a.example.org/y")


def test_repo_admin_uses_the_shared_handler(ra):
    assert ra._SameHostRedirects is SameHostRedirects


class _Hop(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        _Hop.seen.append((self.server.server_address[1], self.path, self.headers.get("Authorization")))
        target = getattr(self.server, "target", None)
        if target:
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b'{"records": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_board_client_does_not_send_the_token_to_another_host():
    """A board that redirects to another host (here: another port) gets no token there."""
    other = ThreadingHTTPServer(("127.0.0.1", 0), _Hop)
    board = ThreadingHTTPServer(("127.0.0.1", 0), _Hop)
    board.target = f"http://127.0.0.1:{other.server_address[1]}/elsewhere"
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (other, board)]
    for t in threads:
        t.start()
    try:
        _Hop.seen = []
        result = subprocess.run([*tld_cmd("board", "client"), "list"], capture_output=True, text=True, timeout=30,
                                env=env_for(f"http://127.0.0.1:{board.server_address[1]}"))
        assert result.returncode == 0, result.stderr
        assert _Hop.seen[0] == (board.server_address[1], "/api/records", f"Bearer {WRITE}")
        assert _Hop.seen[1] == (other.server_address[1], "/elsewhere", None)
    finally:
        for s in (other, board):
            s.shutdown()
            s.server_close()
