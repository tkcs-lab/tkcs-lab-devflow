import copy
import io
import json
import re
import urllib.error

import pytest

from conftest import FIXTURES

from tld.board import ask as board_ask
from tld.board import ask_digest
from tld.board import client as board_client

REPO = "acme/demo-app"
NOW = "2026-02-01T00:00:00Z"
VERIFY_TEXT = "These commands run on this machine after each merge. Run them? 1. pytest tests/core -q"


@pytest.fixture()
def corpus():
    return json.loads((FIXTURES / "ask-digest-corpus.json").read_text(encoding="utf-8"))["asks"]


def run(asks, since=None, vocab=None, repo=REPO):
    return ask_digest.digest(asks, repo, since, NOW, vocab)


def by_qid(result, qid):
    return next(c for c in result["clusters"] if c["qid"] == qid)


def find(asks, number):
    return next(a for a in asks if a["id"] == "a-%016x" % number)


def make_ask(number, text, record=None, state="answered", created="2026-03-01T10:00:00Z", kind="confirm",
             answers=None, title="Other", project="demo-app", repo=REPO, answered_at=None, **question):
    q = {"id": "q", "text": text, "kind": kind}
    q.update(question)
    if kind == "choice" and "options" not in q:
        q["options"] = [{"value": "x"}, {"value": "y"}]
    return {"schema": 1, "kind": "ask", "id": "a-%016x" % number, "project": project, "repo": repo, "title": title,
            "created_by": "demo", "context_url": None, "fallback_issue": None, "record": record, "questions": [q],
            "state": state, "answers": {} if answers is None else answers, "created_at": created,
            "answered_at": answered_at}


def minimal(number):
    return make_ask(number, "word%d" % number, created="2026-03-01T10:00:00Z")


# masking and vocabulary

MASK_CASES = [
    ("See https://example.org/a?b=1 now", "see <url> now"),
    ("Run `pytest -x` in docs/plans/33/plan.md", "run <code> in <path>"),
    ("Mail me@example.org or @some-login", "mail <email> or <login>"),
    ("Host board.example.net is down", "host <host> is down"),
    ("Plan secret-plan-2 of #12 at abcdef1 has 3 steps", "plan <slug> of #<n> at <sha> has <n> steps"),
    ("See `https://x.example/a` then `b` and `c`", "see <code> then <code> and <code>"),
    ("See #12345678", "see #<n>"),
    ("x" * 158 + " https://example.org/z", "x" * 158),
]


@pytest.mark.parametrize(("text", "expected"), MASK_CASES)
def test_mask_pairs(text, expected):
    assert ask_digest.mask(text) == expected


def test_mask_cut_keeps_a_whole_placeholder_after_the_limit():
    assert ask_digest.mask("x" * 150 + " https://example.org/z") == "x" * 150 + " <url>"


@pytest.mark.parametrize(("template", "vocab", "expected"), [
    ("run them zebra <n>", {"run", "them"}, "run them <word> <n>"),
    (ask_digest.mask("Ask Zoë about 客户"), {"ask", "about"}, "ask <word> about <word>"),
    ("ok to rm db?", {"ok", "to"}, "ok to <word> <word>?"),
])
def test_apply_vocab_pairs(template, vocab, expected):
    assert ask_digest.apply_vocab(template, vocab) == expected


def test_apply_vocab_with_an_empty_vocabulary_leaves_no_letter_run():
    for text, _ in MASK_CASES:
        out = ask_digest.apply_vocab(ask_digest.mask(text), set())
        outside = re.sub(r"#?<(?:code|url|email|login|path|host|n|sha|slug|word)>", " ", out)
        assert not re.search(r"[^\W\d_]", outside), out


def test_apply_vocab_does_not_trust_a_typed_placeholder():
    assert ask_digest.apply_vocab("<secret> run", {"run"}) == "<<word>> run"


def test_words_ignores_placeholders_and_short_words():
    assert ask_digest.words("run <path> to be ok, then stop") == {"run", "then", "stop"}


# the digest of the corpus

def test_digest_counts_and_cursor(corpus):
    result = run(corpus)
    assert (result["asks"], result["analysed"], result["open_asks"], result["excluded_questions_asks"]) == (12, 9, 0, 1)
    assert result["foreign"] == {"asks": 2, "unmatched_questions": 1}
    assert result["cursor"] == "2026-01-13T10:00:00Z"
    assert result["truncated"] is False
    assert (result["schema"], result["project"], result["since"], result["now"]) == (1, "demo-app", None, NOW)


def test_digest_cursor_counts_excluded_and_ignores_foreign(corpus):
    find(corpus, 9)["created_at"] = "2026-01-14T10:00:00Z"
    find(corpus, 18)["created_at"] = "2026-01-15T10:00:00Z"
    result = run(corpus)
    assert result["cursor"] == "2026-01-14T10:00:00Z"
    assert result["analysed"] == 9


def test_digest_cursor_stops_before_the_oldest_open_ask(corpus):
    ask = find(corpus, 10)
    ask.update(state="open", answers={}, answered_at=None)
    result = run(corpus)
    assert result["cursor"] == "2026-01-13T09:59:59Z"
    assert (result["analysed"], result["open_asks"]) == (8, 1)


def test_digest_cursor_is_null_without_own_asks(corpus):
    result = run([a for a in corpus if a["project"] == "other-app"])
    assert result["cursor"] is None
    assert result["clusters"] == []


def test_digest_groups_the_verify_confirmations(corpus):
    c1 = run(corpus)["clusters"][0]
    assert (c1["source"], c1["kind"], c1["count"], c1["records"], c1["foreign_count"]) == ("run", "confirm", 4, 4, 1)
    assert (c1["recommended_rate"], c1["empty_rate"], c1["median_seconds"]) == (1.0, None, 90)
    assert (c1["first"], c1["last"], c1["candidate"]) == ("2026-01-05T10:00:00Z", "2026-01-13T10:00:00Z", True)
    assert c1["asks"] == [find(corpus, n)["id"] for n in (1, 2, 3, 10)]
    assert c1["fingerprint"] == "fb642a6b0656518f"
    vocab = set(re.findall(r"[a-z]+", ask_digest.mask(VERIFY_TEXT)))
    full = run(corpus, vocab=vocab)["clusters"][0]
    assert full["fingerprint"] == "fb642a6b0656518f"
    stripped = run(corpus, vocab=vocab - {"pytest"})["clusters"][0]
    assert "<word>" in stripped["template"]
    assert stripped["fingerprint"] == "20a20556e8e429d0"
    assert stripped["fingerprint"] != c1["fingerprint"]


def test_digest_clusters_differing_only_in_filtered_words_share_a_fingerprint():
    asks = [make_ask(1, "deploy zebra", created="2026-03-01T10:00:00Z"),
            make_ask(2, "deploy yak", created="2026-03-02T10:00:00Z")]
    unfiltered = run(asks)["clusters"]
    assert len(unfiltered) == 2
    assert unfiltered[0]["fingerprint"] != unfiltered[1]["fingerprint"]
    filtered = run(asks, vocab={"deploy"})["clusters"]
    assert len(filtered) == 2
    assert [c["template"] for c in filtered] == ["deploy <word>"] * 2
    assert [c["fingerprint"] for c in filtered] == ["995aff88465c865c"] * 2


def test_digest_reports_unfilled_optional_text(corpus):
    notes = by_qid(run(corpus), "notes")
    assert (notes["source"], notes["kind"], notes["count"], notes["empty_rate"], notes["records"], notes["candidate"]) \
        == ("make-plan", "text", 3, 1.0, 3, True)


def test_digest_flags_cancelled_and_reposted(corpus):
    review = by_qid(run(corpus), "d1")
    assert (review["count"], review["cancelled"], review["reposted"], review["records"]) == (2, 1, 1, 1)
    assert (review["recommended_rate"], review["median_seconds"], review["candidate"]) == (1.0, 40, False)


def test_digest_orders_clusters_by_count(corpus):
    clusters = run(corpus)["clusters"]
    assert [c["qid"] for c in clusters] == ["verify", "notes", "d1", "limits", "scope"]
    assert [c["count"] for c in clusters] == [4, 3, 2, 1, 1]
    assert [c["id"] for c in clusters] == ["c1", "c2", "c3", "c4", "c5"]
    assert (by_qid(run(corpus), "limits")["recommended_rate"], by_qid(run(corpus), "scope")["recommended_rate"]) == (1.0, 0.0)


def test_digest_since_drops_older_asks(corpus):
    result = run(corpus, since="2026-01-09T10:00:00Z")
    assert (result["asks"], result["analysed"], result["open_asks"]) == (6, 4, 0)
    assert result["foreign"] == {"asks": 1, "unmatched_questions": 1}
    assert result["clusters"][0]["qid"] == "d1" and result["clusters"][0]["source"] == "review"
    verify, notes = by_qid(result, "verify"), by_qid(result, "notes")
    assert (verify["count"], verify["foreign_count"], verify["median_seconds"]) == (1, 0, 20)
    assert notes["count"] == 1
    assert all(find(corpus, 5)["id"] not in c["asks"] for c in result["clusters"])


def test_digest_emits_nothing_of_foreign_asks(corpus):
    text = json.dumps(run(corpus))
    for forbidden in ("other-app", "acme/other-app", "a-0000000000000011", "a-0000000000000012",
                      "2026-01-06T11:00:00Z", "2026-01-06T11:00:30Z", "2026-01-09T11:00:00Z", "2026-01-09T11:00:30Z",
                      "other-app--run--zeta", "other-app--run--eta", "unrelated", "make test", "cloud", "database"):
        assert forbidden not in text, forbidden
    own = {a["id"] for a in corpus if a["project"] == "demo-app"}
    assert set(re.findall(r"a-[0-9a-f]{16}", text)) <= own


def test_digest_emits_no_answer_text(corpus):
    find(corpus, 6)["answers"] = {"notes": "SECRET-ANSWER"}
    result = run(corpus)
    assert "SECRET-ANSWER" not in json.dumps(result)
    assert by_qid(result, "notes")["empty_rate"] == 0.67


def test_digest_template_uses_the_vocabulary(corpus):
    vocab = set(re.findall(r"[a-z]+", ask_digest.mask(VERIFY_TEXT))) - {"pytest"}
    template = run(corpus, vocab=vocab)["clusters"][0]["template"]
    assert "<word>" in template and "pytest" not in template


def test_foreign_question_counts_in_the_first_matching_cluster():
    asks = [
        make_ask(1, "alpha beta gamma delta", "demo-app--deps--a", created="2026-03-01T10:00:00Z"),
        make_ask(2, "gamma delta epsilon zeta", "demo-app--deps--b", created="2026-03-02T10:00:00Z"),
        make_ask(3, "alpha beta gamma delta epsilon zeta", "other-app--deps--c", project="other-app", repo="acme/other-app"),
    ]
    first, second = run(asks)["clusters"]
    assert (first["foreign_count"], second["foreign_count"]) == (1, 0)


def test_ask_with_the_same_slug_and_another_repository_is_foreign(corpus):
    find(corpus, 1)["repo"] = "other/demo-app"
    result = run(corpus)
    assert result["foreign"]["asks"] == 3
    assert result["analysed"] == 8


@pytest.mark.parametrize(("record", "title", "expected"), [
    (None, "Start x", "run"), (None, "Phase p1 blocked", "run"), (None, "Plan #3: y", "make-plan"),
    (None, "Other", None), ("demo-app--deps--a", "Other", "deps"), ("demo-app--zzz--a", "Start x", None),
    ("demo-app--run--p", "Other", "run"),
])
def test_source_of(record, title, expected):
    assert ask_digest.source_of({"record": record, "title": title}) == expected


def test_truncated_flag():
    assert run([minimal(n) for n in range(199)])["truncated"] is False
    assert run([minimal(n) for n in range(200)])["truncated"] is True
    assert run([minimal(n) for n in range(1000)])["truncated"] is True


def test_cluster_and_ask_caps():
    letters = "abcdefghijklmnopqrstuvwxyz"
    distinct = [make_ask(n, " ".join(letters[(n // 26 ** i) % 26] * 4 + str(i) for i in range(3)).replace("0", "a")
                         .replace("1", "b").replace("2", "c"), created="2026-03-01T10:00:%02dZ" % (n % 60))
                for n in range(61)]
    for n, ask in enumerate(distinct):
        ask["questions"][0]["text"] = f"{letters[n // 26]}{letters[n % 26]}aaa {letters[n % 26]}{letters[n // 26]}bbb"
    assert len(run(distinct)["clusters"]) == 60
    same = [make_ask(n, "same words here", created="2026-03-01T10:00:%02dZ" % n) for n in range(21)]
    clusters = run(same)["clusters"]
    assert len(clusters) == 1 and clusters[0]["count"] == 21
    assert clusters[0]["asks"] == sorted(a["id"] for a in same)[:20] and len(clusters[0]["asks"]) == 20


def _records(count, records):
    return [make_ask(n, "same words here", f"demo-app--deps--r{n % records}", created=f"2026-03-01T10:00:{n:02d}Z")
            for n in range(count)]


@pytest.mark.parametrize(("count", "records", "expected"), [(2, 2, False), (3, 2, True), (3, 1, False), (4, 1, False)])
def test_candidate_boundaries_count_and_records(count, records, expected):
    assert run(_records(count, records))["clusters"][0]["candidate"] is expected


def _text_asks(empty, total):
    asks = []
    for n in range(total):
        answers = {} if n < empty else {"q": "something"}
        asks.append(make_ask(n, "anything else?", "demo-app--deps--r", kind="text", required=False,
                             answers=answers, answered_at="2026-03-01T10:01:00Z"))
    return asks


@pytest.mark.parametrize(("empty", "total", "rate", "expected"), [(79, 100, 0.79, False), (4, 5, 0.8, True)])
def test_candidate_boundaries_empty_rate(empty, total, rate, expected):
    cluster = run(_text_asks(empty, total))["clusters"][0]
    assert (cluster["empty_rate"], cluster["candidate"]) == (rate, expected)


def test_candidate_needs_three_asks_for_the_empty_rate():
    assert run(_text_asks(2, 2))["clusters"][0]["candidate"] is False


@pytest.mark.parametrize(("cancelled", "expected"), [(2, False), (3, True)])
def test_candidate_boundaries_cancelled(cancelled, expected):
    asks = [make_ask(n, "same words here", "demo-app--deps--r%d" % n, state="cancelled",
                     created=f"2026-03-0{n + 1}T10:00:00Z") for n in range(cancelled)]
    cluster = run(asks)["clusters"][0]
    assert (cluster["cancelled"], cluster["candidate"]) == (cancelled, expected)


@pytest.mark.parametrize(("reposted", "expected"), [(1, False), (2, True)])
def test_candidate_boundaries_reposted(reposted, expected):
    asks = []
    for n in range(reposted):
        record = f"demo-app--deps--r{n}"
        asks.append(make_ask(2 * n, "same words here", record, state="cancelled", created=f"2026-03-0{n + 1}T10:00:00Z"))
        asks.append(make_ask(2 * n + 1, "same words here", record, created=f"2026-03-0{n + 1}T10:05:00Z"))
    cluster = run(asks)["clusters"][0]
    assert (cluster["reposted"], cluster["candidate"]) == (reposted, expected)


def test_a_repost_after_the_window_is_not_a_repost():
    asks = [make_ask(1, "same words here", "demo-app--deps--r", state="cancelled", created="2026-03-01T10:00:00Z"),
            make_ask(2, "same words here", "demo-app--deps--r", created="2026-03-01T10:31:00Z")]
    assert run(asks)["clusters"][0]["reposted"] == 0


def test_corpus_asks_are_valid_stored_asks(corpus):
    assert len(corpus) == 12
    for ask in corpus:
        assert board_ask.validate_stored(ask) == [], ask["id"]


def test_hostile_ask_fields_never_reach_the_output(corpus):
    hostile = make_ask(40, "hello there")
    hostile.update(id="TOP-SECRET-ID")
    odd = make_ask(41, "hello there", record=["x"], answers=None, kind="hunter2 password")
    weird = make_ask(42, "hello there", record={"a": 1}, id="q")
    weird["questions"][0]["id"] = ["list"]
    named = make_ask(43, "hello there")
    named["questions"][0]["id"] = "my secret token"
    result = run(corpus + [hostile, odd, weird, named])
    text = json.dumps(result)
    for leak in ("TOP-SECRET-ID", "hunter2", "my secret token", "list"):
        assert leak not in text
    assert result["asks"] == 12 + 3  # the ask with a bad id is dropped; the others are read


def test_main_exits_1_when_the_digest_cannot_be_built(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ask_digest, "digest", lambda *a, **k: (_ for _ in ()).throw(TypeError("x")))
    path = tmp_path / "a.json"
    path.write_text("[]", encoding="utf-8")
    code, _, err = run_main(["--repo", REPO, "--file", str(path)], capsys)
    assert code == 1 and err.startswith("tld board: ")


def test_mask_is_fast_on_hostile_text():
    import time
    start = time.monotonic()
    for text in ("a@" * 20000, "a-" * 20000, "a" * 50000, "a.b" * 20000):
        ask_digest.mask(text)
    assert time.monotonic() - start < 2


def test_mask_hides_windows_paths_and_apply_vocab_drops_symbols():
    assert ask_digest.mask("open C:\\Users\\bob\\x.txt now") == "open <path> now"
    assert ask_digest.apply_vocab("hello \u24d7\u24e4 hello", {"hello"}) == "hello    hello"


# the command line

def run_main(argv, capsys):
    code = ask_digest.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_main_file_prints_one_json_line_and_exit_0(capsys):
    code, out, err = run_main(["--repo", REPO, "--file", str(FIXTURES / "ask-digest-corpus.json"), "--now", NOW], capsys)
    assert (code, err) == (0, "")
    assert out.count("\n") == 1 and " " not in out.split('"template"')[0]
    assert json.loads(out)["clusters"][0]["count"] == 4


def test_main_reads_a_bare_list_from_stdin_and_a_vocabulary(monkeypatch, capsys, tmp_path, corpus):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(corpus)))
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("run\nthem\n\n", encoding="utf-8")
    code, out, _ = run_main(["--repo", REPO, "--file", "-", "--vocab", str(vocab)], capsys)
    assert code == 0
    assert "<word>" in json.loads(out)["clusters"][0]["template"]


def test_main_without_board_exits_3(monkeypatch, capsys):
    monkeypatch.delenv("TLD_BOARD_URL", raising=False)
    monkeypatch.delenv("TLD_BOARD_TOKEN", raising=False)
    assert run_main(["--repo", REPO], capsys)[0] == 3
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example.net")
    code, _, err = run_main(["--repo", REPO], capsys)
    assert code == 3 and err.startswith("tld board: ")


def test_main_bad_url_exits_1(monkeypatch, capsys):
    monkeypatch.setenv("TLD_BOARD_URL", "ftp://x")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    code, _, err = run_main(["--repo", REPO], capsys)
    assert code == 1 and err.startswith("tld board: ")


def test_main_unreadable_file_and_vocab_exit_1(tmp_path, capsys):
    missing = str(tmp_path / "missing.json")
    assert run_main(["--repo", REPO, "--file", missing], capsys)[0] == 1
    assert run_main(["--repo", REPO, "--file", str(FIXTURES / "ask-digest-corpus.json"), "--vocab", missing], capsys)[0] == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    code, _, err = run_main(["--repo", REPO, "--file", str(bad)], capsys)
    assert code == 1 and err.startswith("tld board: ")
    bad.write_text('{"asks": 3}', encoding="utf-8")
    assert run_main(["--repo", REPO, "--file", str(bad)], capsys)[0] == 1


def test_main_usage_errors_exit_2(capsys):
    for argv in ([], ["--repo", REPO, "--since", "yesterday"], ["--repo", REPO, "--now", "2026-01-01"]):
        with pytest.raises(SystemExit) as exc:
            ask_digest.main(argv)
        assert exc.value.code == 2
        capsys.readouterr()


@pytest.fixture()
def board(monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example.net")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")


def test_main_board_error_exits_1(board, monkeypatch, capsys):
    monkeypatch.setattr(board_client, "call", lambda *a, **k: (500, None))
    code, _, err = run_main(["--repo", REPO], capsys)
    assert code == 1 and err.startswith("tld board: ") and "HTTP 500" in err

    def unreachable(*a, **k):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(board_client, "call", unreachable)
    assert run_main(["--repo", REPO], capsys)[0] == 1
    monkeypatch.setattr(board_client, "call", lambda *a, **k: (200, {"asks": "x"}))
    assert run_main(["--repo", REPO], capsys)[0] == 1


def test_main_reads_the_board(board, monkeypatch, capsys, corpus):
    monkeypatch.setattr(board_client, "call", lambda *a, **k: (200, {"asks": corpus}))
    code, out, _ = run_main(["--repo", REPO, "--now", NOW], capsys)
    assert code == 0 and json.loads(out)["analysed"] == 9


def test_fetch_passes_since_limit_and_order(monkeypatch):
    paths = []

    def fake(config, method, path, *rest, **kw):
        paths.append((method, path))
        return 200, {"asks": []}
    monkeypatch.setattr(board_client, "call", fake)
    config = board_client.Config("https://board.example.net", "t")
    assert ask_digest.fetch(config, "2026-01-02T03:04:05Z") == []
    assert ask_digest.fetch(config, None) == []
    assert paths == [("GET", "/api/asks?limit=1000&order=asc&since=2026-01-02T03:04:05Z"),
                     ("GET", "/api/asks?limit=1000&order=asc")]


def test_digest_does_not_change_its_input(corpus):
    before = copy.deepcopy(corpus)
    run(corpus)
    assert corpus == before


def test_an_id_with_a_trailing_newline_is_not_valid():
    ask = make_ask(50, "hello there")
    ask["id"] = "a-0123456789abcdef\n"
    other = make_ask(51, "hello there")
    other["questions"][0]["id"] = "q1\n"
    result = run([ask, other])
    assert result["asks"] == 1 and result["clusters"][0]["qid"] == "q0"


def test_similar_with_two_empty_word_sets_needs_equal_templates():
    empty = frozenset()
    assert ask_digest._similar(empty, "<n>", empty, "<n>") is True
    assert ask_digest._similar(empty, "<n>", empty, "<path>") is False


def test_empty_is_false_for_an_ask_that_was_not_answered():
    ask = make_ask(1, "anything else?", kind="text", required=False, state="open")
    assert ask_digest._empty(ask, ask["questions"][0]) is False
    answered = make_ask(2, "anything else?", kind="text", required=False, answers={}, answered_at="2026-03-01T10:01:00Z")
    assert ask_digest._empty(answered, answered["questions"][0]) is True
