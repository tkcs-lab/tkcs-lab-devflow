"""tld roles page-note and tld roles change-report: the note line, its check, the block printed after it."""
import ast
import hashlib
import inspect
import os

import pytest

from conftest import _load

page_note = _load("tld.roles.page_note")
reflektor = _load("tld.roles.reflektor")
report_check = _load("tld.board.report_check")
section = _load("tld.roles.section")
cli = _load("tld.cli")

NOTE = "HTML page not stored: "
SENT = " It was sent to the owner as a file instead."
TOKEN = "ghp_" + "a" * 36
BAD = "tld roles: the page note is not a page-note line"
BLOCK = "BEGIN change-report\n### Changes\n- one thing\nEND change-report\n"


def stderr_file(tmp_path, text, name="e.txt"):
    f = tmp_path / name
    f.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return str(f)


def note(argv, capsys):
    assert page_note.main(["note", *argv]) == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1
    return out[:-1]


# --- page-note ---------------------------------------------------------------------------------

def test_note_line_role_and_send():
    assert page_note.note_line("role", "", False) == NOTE + "the reflektor role built no checked page."
    assert page_note.note_line("send", "", False) == NOTE + "the page could not be sent as a file."


def test_note_line_check_with_known_reason():
    err = "tld roles: reflektor: the title tag is missing\n"
    assert page_note.note_line("check", err, False) == NOTE + "the page check refused it (the title tag is missing)."


def test_note_line_check_uses_the_first_reflektor_line_only():
    err = "noise\ntld roles: reflektor: the title tag is missing\ntld roles: reflektor: the title tag is not closed\n"
    assert page_note.note_line("check", err, False).endswith("(the title tag is missing).")
    err = "tld roles: reflektor: " + "invalid payload\ntld roles: reflektor: the title tag is missing\n"
    assert page_note.note_line("check", err, False).endswith("(invalid payload).")


@pytest.mark.parametrize("err", [
    "", "no reflektor line here\n",
    f"tld roles: reflektor: the page holds {TOKEN}\n",
    "tld roles: reflektor: something nobody emits\n",
    "tld roles: reflektor: the title tag is missing and more\n",
])
def test_note_line_check_without_a_known_reason(err):
    assert page_note.note_line("check", err, False) == NOTE + "the page check refused it."


def test_note_line_check_does_not_look_past_an_unknown_first_reason():
    err = "tld roles: reflektor: forged\ntld roles: reflektor: the title tag is missing\n"
    assert page_note.note_line("check", err, False) == NOTE + "the page check refused it."


@pytest.mark.parametrize("status", ["413", "422", "503"])
def test_note_line_board_status(status):
    err = f"board_client: the server answered HTTP {status}\n"
    line = page_note.note_line("board", err, False)
    assert line == NOTE + f"the board answered HTTP {status}."


def test_note_line_board_other_texts():
    assert page_note.note_line("board", "board_client: cannot reach the board (URLError: x)\n", False) \
        == NOTE + "the board cannot be reached."
    assert page_note.note_line("board", "board_client: cannot read the report (larger than 20971520 bytes)\n", False) \
        == NOTE + "the page is too large to upload."
    assert page_note.note_line("board", "something else\n", False) == NOTE + "the board did not accept it."
    assert page_note.note_line("board", "", False) == NOTE + "the board did not accept it."


def test_note_line_board_shows_no_url_or_exception_text():
    err = "board_client: cannot reach the board (URLError: https://secret.example/x?t=abc)\n"
    assert "secret" not in page_note.note_line("board", err, False)
    err = "board_client: the server answered HTTP 5039 https://secret.example\n"
    assert page_note.note_line("board", err, False) == NOTE + "the board did not accept it."


def test_note_line_sent_suffix_on_board_only():
    for err in ("board_client: the server answered HTTP 503\n", "cannot reach the board", "", "larger than"):
        assert page_note.note_line("board", err, True).endswith("." + SENT)
        assert not page_note.note_line("board", err, False).endswith(SENT)
    assert not page_note.note_line("send", "", False).endswith(SENT)


def test_sent_with_another_stage_is_a_usage_error(capsys):
    for stage in ("role", "check", "send"):
        with pytest.raises(SystemExit) as exc:
            page_note.main(["note", "--stage", stage, "--sent"])
        assert exc.value.code == 2


def test_missing_or_unknown_stage_is_a_usage_error():
    for argv in (["note"], ["note", "--stage", "other"], []):
        with pytest.raises(SystemExit) as exc:
            page_note.main(argv)
        assert exc.value.code == 2


def test_note_command_reads_stderr_file(tmp_path, capsys):
    f = stderr_file(tmp_path, "tld roles: reflektor: invalid payload (not JSON)\n")
    assert note(["--stage", "check", "--stderr", f], capsys) == NOTE + "the page check refused it (invalid payload (not JSON))."
    f = stderr_file(tmp_path, "board_client: the server answered HTTP 422\n", "b.txt")
    assert note(["--stage", "board", "--stderr", f, "--sent"], capsys) == NOTE + "the board answered HTTP 422." + SENT


def test_note_command_credential_looking_reason_gives_the_no_reason_line(tmp_path, capsys):
    f = stderr_file(tmp_path, f"tld roles: reflektor: {TOKEN}\n")
    assert note(["--stage", "check", "--stderr", f], capsys) == NOTE + "the page check refused it."


def test_note_command_unreadable_stderr_counts_as_empty(tmp_path, capsys):
    assert note(["--stage", "check", "--stderr", str(tmp_path / "none")], capsys) == NOTE + "the page check refused it."
    assert note(["--stage", "board", "--stderr", str(tmp_path)], capsys) == NOTE + "the board did not accept it."


def test_note_command_reads_at_most_20000_bytes(tmp_path, capsys):
    f = stderr_file(tmp_path, "x" * 20000 + "\ncannot reach the board\n")
    assert note(["--stage", "board", "--stderr", f], capsys) == NOTE + "the board did not accept it."


def test_note_command_bad_bytes_are_replaced(tmp_path, capsys):
    f = stderr_file(tmp_path, b"\xff\xfe tld\n\x00\ncannot reach the board\n")
    assert note(["--stage", "board", "--stderr", f], capsys) == NOTE + "the board cannot be reached."


# --- the note check ----------------------------------------------------------------------------

CRED2 = "the page holds something that looks like a credential (github-token, high-entropy-assignment)"


@pytest.mark.parametrize("reason", [
    reflektor.REASON_ESCAPED, reflektor.REASON_SPLIT, CRED2, "the page is larger than 20971520 bytes",
    "invalid payload (contains '<')", "the data has a link target under 'url'",
])
def test_check_note_keeps_known_reason(reason):
    line = page_note.note_line("check", f"tld roles: reflektor: {reason}\n", False)
    assert line == f"{NOTE}the page check refused it ({reason})."
    assert page_note.valid_note(line)


def test_every_note_line_is_valid():
    errs = ["", "board_client: the server answered HTTP 413", "cannot reach the board",
            "cannot read the report (larger than 5", "junk"]
    for stage in ("role", "send"):
        assert page_note.valid_note(page_note.note_line(stage, "", False))
    for err in errs:
        for sent in (False, True):
            assert page_note.valid_note(page_note.note_line("board", err, sent))
    for reason in (CRED2, "invalid payload (contains '<')", "the data has a link target under 'avatar'",
                   "the title tag is missing"):
        assert page_note.valid_note(page_note.note_line("check", f"tld roles: reflektor: {reason}\n", False))
    assert page_note.valid_note(page_note.note_line("check", "", False))


@pytest.mark.parametrize("line", [
    "", "hello", NOTE, NOTE + "anything",
    "XTML page not stored: the board cannot be reached.",
    NOTE + "the board cannot be reached.\nsecond line",
    NOTE + "the board cannot be reached.\x1b",
    NOTE + "the board cannot be reached.‮",
    NOTE + "the board answered HTTP 50.",
    NOTE + "the board answered HTTP 5030.",
    NOTE + f"the page check refused it ({TOKEN}).",
    NOTE + "the page check refused it (the title tag is missing)",
    NOTE + "the page check refused it ().",
    NOTE + "the reflektor role built no checked page." + SENT,
    NOTE + "the page check refused it." + SENT,
    NOTE + "the page could not be sent as a file." + SENT,
    NOTE + "the page check refused it (the title tag is missing)." + SENT,
])
def test_invalid_notes(line):
    assert page_note.valid_note(line) is False


def test_valid_notes_with_suffix_and_padding():
    assert page_note.valid_note(NOTE + "the board answered HTTP 503." + SENT)
    assert page_note.valid_note("  " + NOTE + "the board did not accept it.  ")


def _literal(node, samples):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(part.value)
            else:
                out.append(samples[ast.unparse(part.value)])
        return "".join(out)
    return None


def _emitted(module, functions=None):
    """Every reason text a module can raise or return, with a sample for each formatted value."""
    samples = {"what": "the page", "type(exc).__name__": "OSError", "MAX_HTML": "20971520", "k": "url",
               "', '.join(names)": "github-token, high-entropy-assignment"}
    tree = ast.parse(inspect.getsource(module))
    found = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if functions is not None and fn.name not in functions:
            continue
        for node in ast.walk(fn):
            nodes = []
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("PrepareError", "_Reject"):
                nodes = node.args[-1:]
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.List):
                nodes = node.value.elts
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.ListComp):
                nodes = [node.value.elt]
            for arg in nodes:
                text = _literal(arg, samples)
                if text is not None:
                    found.append(text)
    return found


def test_known_reason_covers_every_emitted_reason():
    mine = _emitted(reflektor, {"_read_regular", "harden_html", "send_copy", "verify_html", "marks_left"})
    theirs = _emitted(report_check)
    assert len(mine) >= 10 and len(theirs) >= 15
    for reason in mine + theirs + [reflektor.REASON_SPLIT, reflektor.REASON_ESCAPED, reflektor.REASON_MARK_RAW]:
        assert reflektor.known_reason(reason), reason


# --- the stderr of a real refusal --------------------------------------------------------------

A = "<!doctype html><head>"
B = "</head><body>"
C = '<script>x</script></body><script id="d" type="application/json">'
D = "</script>"


def _p(s):
    return (len(s), hashlib.sha256(s.encode("utf8")).hexdigest())


def test_send_stderr_feeds_the_check_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report_check, "VIEWER_PARTS", (_p(A), _p(B), _p(C), _p(D)))
    out = tmp_path / "out"
    out.mkdir()
    html = A + report_check.CSP_META + B + "<title>t</title>" + C + '{"s":"secret-scan\\u003aallow"}' + D
    (out / "report.html").write_text(html, encoding="utf-8")
    ans = tmp_path / "ans.txt"
    ans.write_text(f"REPORT-HTML {out / 'report.html'}\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    assert reflektor.main(["html", "--send", "--answer", str(ans), "--dest", str(dest)]) == 1
    err = capsys.readouterr().err
    line = page_note.note_line("check", err, False)
    assert line.endswith("(the data carries an escaped secret-scan allow mark).")
    assert page_note.valid_note(line)


# --- change-report -----------------------------------------------------------------------------

def run_report(tmp_path, report, note_text=None, capsys=None):
    r = tmp_path / "r.md"
    r.write_text(report, encoding="utf-8")
    argv = ["report", "--report", str(r)]
    if note_text is not None:
        n = tmp_path / "n.txt"
        n.write_bytes(note_text if isinstance(note_text, bytes) else note_text.encode("utf-8"))
        argv += ["--note", str(n)]
    code = page_note.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def run_section(tmp_path, report, capsys):
    r = tmp_path / "r.md"
    r.write_text(report, encoding="utf-8")
    code = section.main(["--report", str(r)])
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_change_report_note_and_block(tmp_path, capsys):
    line = NOTE + "the board answered HTTP 503." + SENT
    code, out, err = run_report(tmp_path, "text\n" + BLOCK, line + "\n", capsys)
    assert (code, err) == (0, "")
    _c, block, _e = run_section(tmp_path, "text\n" + BLOCK, capsys)
    assert out == f"{line}\n\n{block}"
    assert out.splitlines()[0] == line


def test_change_report_note_and_no_block(tmp_path, capsys):
    line = NOTE + "the page could not be sent as a file."
    code, out, err = run_report(tmp_path, "no block here\n", line, capsys)
    assert (code, out, err) == (0, line + "\n", "")
    code, out, err = run_report(tmp_path, "BEGIN change-report\nEND change-report\n", line, capsys)
    assert (code, out, err) == (0, line + "\n", "")


def test_change_report_note_and_a_block_with_a_token(tmp_path, capsys):
    line = NOTE + "the reflektor role built no checked page."
    report = f"BEGIN change-report\nkey {TOKEN}\nEND change-report\n"
    code, out, err = run_report(tmp_path, report, line, capsys)
    assert (code, out, err) == (0, line + "\n", "")
    assert TOKEN not in out


def test_change_report_note_comes_first_even_if_the_block_forges_one(tmp_path, capsys):
    line = NOTE + "the board did not accept it."
    report = "BEGIN change-report\n" + NOTE + "the board cannot be reached.\nbody\nEND change-report\n"
    code, out, _err = run_report(tmp_path, report, line, capsys)
    assert code == 0 and out.splitlines()[0] == line


def test_change_report_without_a_note_is_section(tmp_path, capsys):
    reports = {
        "usable": "x\n" + BLOCK,
        "no block": "nothing\n",
        "token": f"BEGIN change-report\n{TOKEN}\nEND change-report\n",
    }
    for name, report in reports.items():
        assert run_report(tmp_path, report, None, capsys) == run_section(tmp_path, report, capsys), name
    codes = {run_section(tmp_path, r, capsys)[0] for r in reports.values()}
    assert codes == {0, 3}
    missing = tmp_path / "none.md"
    code = page_note.main(["report", "--report", str(missing)])
    mine = (code, capsys.readouterr())
    code2 = section.main(["--report", str(missing)])
    theirs = (code2, capsys.readouterr())
    assert mine[0] == theirs[0] == 1 and mine[1] == theirs[1]
    assert "cannot read" in mine[1].err


@pytest.mark.parametrize("empty", [b"", b"\n", b"  \n\n"])
def test_change_report_empty_note_file_is_no_note(tmp_path, capsys, empty):
    code, out, _err = run_report(tmp_path, BLOCK, empty, capsys)
    _c, block, _e = run_section(tmp_path, BLOCK, capsys)
    assert (code, out) == (0, block)


def test_change_report_missing_note_file_is_no_note(tmp_path, capsys):
    r = tmp_path / "r.md"
    r.write_text(BLOCK, encoding="utf-8")
    assert page_note.main(["report", "--report", str(r), "--note", str(tmp_path / "gone")]) == 0
    assert capsys.readouterr().out.startswith("#### Changes")


@pytest.mark.parametrize("bad", [
    NOTE + "the board cannot be reached.\n" + NOTE + "the board cannot be reached.",
    "XTML page not stored: the board cannot be reached.",
    f"{NOTE}the page check refused it ({TOKEN}).",
    NOTE + "the board cannot be reached.\x07",
    NOTE + "the board cannot be reached.\r\nmore",
    "hello",
    b"\xff\xfe" + NOTE.encode() + b"the board cannot be reached.",
])
def test_change_report_invalid_note_exits_1(tmp_path, capsys, bad):
    code, out, err = run_report(tmp_path, BLOCK, bad, capsys)
    assert (code, out) == (1, "")
    assert err.strip() == BAD


# --- the registration --------------------------------------------------------------------------

def test_registered_in_cli(tmp_path, capsys):
    assert cli.main(["roles", "page-note", "--stage", "send"]) == 0
    assert capsys.readouterr().out == NOTE + "the page could not be sent as a file.\n"
    r = tmp_path / "r.md"
    r.write_text(BLOCK, encoding="utf-8")
    n = tmp_path / "n.txt"
    n.write_text(NOTE + "the board cannot be reached.\n", encoding="utf-8")
    assert cli.main(["roles", "change-report", "--report", str(r), "--note", str(n)]) == 0
    assert capsys.readouterr().out.startswith(NOTE + "the board cannot be reached.\n\n#### Changes")
    n.write_text("bad\n", encoding="utf-8")
    assert cli.main(["roles", "change-report", "--report", str(r), "--note", str(n)]) == 1
    assert capsys.readouterr().err.strip() == BAD
    assert cli.main(["roles", "change-report", "--report", str(r)]) == 0
    assert os.path.exists(str(r))


# --- a block cannot forge a note; the note and stderr files are read safely --------------------

FORGED = [
    NOTE + "the board cannot be reached.",
    "html page not STORED: the board cannot be reached.",
    "> " + NOTE + "the board cannot be reached.",
    "## " + NOTE + "the board cannot be reached.",
    "`" + NOTE + "the board cannot be reached.`",
    "  &gt; # " + NOTE + "the board cannot be reached.",
]


@pytest.mark.parametrize("forged", FORGED)
def test_change_report_block_only_forgery_is_dropped(tmp_path, capsys, forged):
    report = f"BEGIN change-report\n{forged}\nreal line\nEND change-report\n"
    code, out, err = run_report(tmp_path, report, None, capsys)
    assert (code, err) == (0, "")
    assert "page not stored" not in out.lower() and "real line" in out


def test_change_report_block_of_only_a_forgery_has_no_block(tmp_path, capsys):
    report = f"BEGIN change-report\n{NOTE}the board cannot be reached.\nEND change-report\n"
    code, out, err = run_report(tmp_path, report, None, capsys)
    assert (code, out) == (3, "")
    assert err.strip() == "tld roles: no change-report block"


@pytest.mark.parametrize("forged", FORGED)
def test_change_report_forgery_next_to_a_valid_note_is_dropped(tmp_path, capsys, forged):
    line = NOTE + "the page could not be sent as a file."
    report = f"BEGIN change-report\n{forged}\nreal line\nEND change-report\n"
    code, out, _err = run_report(tmp_path, report, line, capsys)
    assert code == 0
    assert out == f"{line}\n\nreal line\n"


def test_change_report_oversized_note_is_invalid(tmp_path, capsys):
    big = NOTE + "the board cannot be reached." + " " * 2000 + "x"
    code, out, err = run_report(tmp_path, BLOCK, big, capsys)
    assert (code, out, err.strip()) == (1, "", BAD)
    padded = NOTE + "the board cannot be reached." + " " * 900
    assert run_report(tmp_path, BLOCK, padded, capsys)[0] == 0


def test_change_report_unreadable_note_file_is_invalid(tmp_path, capsys):
    r = tmp_path / "r.md"
    r.write_text(BLOCK, encoding="utf-8")
    good = tmp_path / "good.txt"
    good.write_text(NOTE + "the board cannot be reached.\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(good)
    for target in (tmp_path, link):
        assert page_note.main(["report", "--report", str(r), "--note", str(target)]) == 1
        cap = capsys.readouterr()
        assert (cap.out, cap.err.strip()) == ("", BAD)


def test_change_report_fifo_note_is_invalid_without_blocking(tmp_path, capsys):
    r = tmp_path / "r.md"
    r.write_text(BLOCK, encoding="utf-8")
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    assert page_note.main(["report", "--report", str(r), "--note", str(fifo)]) == 1
    assert capsys.readouterr().err.strip() == BAD


def test_note_command_fifo_or_link_stderr_counts_as_empty(tmp_path, capsys):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    assert note(["--stage", "board", "--stderr", str(fifo)], capsys) == NOTE + "the board did not accept it."
    real = tmp_path / "real.txt"
    real.write_text("cannot reach the board\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    assert note(["--stage", "board", "--stderr", str(link)], capsys) == NOTE + "the board did not accept it."
    assert note(["--stage", "board", "--stderr", str(real)], capsys) == NOTE + "the board cannot be reached."


LOOK_ALIKES = {
    "double space": ["HTML  page not stored: the board cannot be reached."],
    "nbsp": ["HTML page\u00a0not stored: the board cannot be reached."],
    "bold": ["**HTML page not stored**: the board cannot be reached."],
    "italic": ["_HTML page not stored: the board cannot be reached._"],
    "list": ["- HTML page not stored: the board cannot be reached."],
    "table": ["| HTML page not stored: the board cannot be reached. |"],
    "strike": ["~~HTML page not stored~~: the board cannot be reached."],
    "combining": ["HTML pa\u0301ge not stored: the board cannot be reached."],
    "fullwidth": ["\uff28TML page not stored: the board cannot be reached."],
    "fullwidth phrase": ["\uff28\uff34\uff2d\uff2c \uff50\uff41\uff47\uff45 \uff4e\uff4f\uff54 \uff53\uff54\uff4f\uff52\uff45\uff44: x"],
    "precomposed": ["HTML p\u00e1ge not stored: the board cannot be reached."],
    "cyrillic": ["HTM\u04c0 page not stored: the board cannot be reached."],
    "split": ["HTML page not", "stored: the board cannot be reached."],
}


@pytest.mark.parametrize("name", sorted(LOOK_ALIKES))
def test_change_report_look_alike_forgery_is_dropped(tmp_path, capsys, name):
    forged = "\n".join(LOOK_ALIKES[name])
    report = f"BEGIN change-report\n{forged}\nreal line\nEND change-report\n"
    code, out, err = run_report(tmp_path, report, None, capsys)
    assert (code, err, out) == (0, "", "real line\n")
    line = NOTE + "the page could not be sent as a file."
    code, out, _err = run_report(tmp_path, report, line, capsys)
    assert (code, out) == (0, f"{line}\n\nreal line\n")
    assert out.count("not stored") == 1


def test_change_report_harmless_line_is_kept(tmp_path, capsys):
    report = "BEGIN change-report\nStored pages are 20 MB at most.\nThe page is not large.\nEND change-report\n"
    code, out, _err = run_report(tmp_path, report, None, capsys)
    assert (code, out) == (0, "Stored pages are 20 MB at most.\nThe page is not large.\n")
