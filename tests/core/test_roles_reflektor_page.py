"""tld roles reflektor-check and reflektor-html: the page check, the hardening, the send copy. No network, no Node."""
import hashlib
import json
import os
import subprocess

import pytest

from conftest import BIN, _load

reflektor = _load("tld.roles.reflektor")
report_check = _load("tld.board.report_check")
PrepareError = reflektor.PrepareError

A = "<!doctype html><head>"
B = "</head><body>"
C = '<script>x</script></body><script id="d" type="application/json">'
D = "</script>"
KEY = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"


def _p(s):
    return (len(s), hashlib.sha256(s.encode("utf8")).hexdigest())


PARTS = (_p(A), _p(B), _p(C), _p(D))


@pytest.fixture(autouse=True)
def fake_viewer(monkeypatch):
    monkeypatch.setattr(report_check, "VIEWER_PARTS", PARTS)


def page(payload='{"a":1}', title="t", a=A, b=B, c=C, d=D, csp=None):
    return a + (report_check.CSP_META if csp is None else csp) + b + f"<title>{title}</title>" + c + payload + d


def reasons(text):
    return report_check.check(text)


def test_valid_page_is_clean():
    assert reasons(page()) == []
    assert reflektor.verify_html(page()) == []


@pytest.mark.parametrize("which,needle", [
    ("a", "part 1"), ("b", "part 2"), ("c", "part 3"), ("d", "part 4")])
def test_each_pinned_part_is_checked(which, needle):
    parts = {"a": A, "b": B, "c": C, "d": D}
    parts[which] = parts[which][:-1] + ("Z" if parts[which][-1] != "Z" else "Y")
    got = reasons(page(**parts))
    assert len(got) == 1 and needle in got[0]


def test_missing_csp():
    got = reasons(page(csp=""))
    assert got and "Content-Security-Policy" in got[0]


def test_title_with_angle_bracket():
    got = reasons(page(title="a<b"))
    assert got == ["the title is not plain one-line text"]


def test_title_with_newline():
    assert reasons(page(title="a\nb")) == ["the title is not plain one-line text"]


@pytest.mark.parametrize("payload,needle", [
    ('{"a":"<b>"}', "contains '<'"),
    ("not json", "not JSON"),
    ('{"a":\n1}', "not one line"),
    ('{"a":NaN}', "NaN or Infinity"),
    ('{"a":Infinity}', "NaN or Infinity"),
    ('{"a":1,"a":2}', "duplicate key"),
])
def test_payload_rules(payload, needle):
    got = reasons(page(payload))
    assert len(got) == 1 and needle in got[0]


@pytest.mark.parametrize("payload,label", [
    ('{"url":"x"}', "url"), ('{"x":{"ownerUrl":"x"}}', "ownerUrl"), ('{"href":"x"}', "href"),
    ('{"notesUrl":"x"}', "notesUrl"),
    ('{"repo":{"web":"x"}}', "web"), ('{"screenshots":[1]}', "screenshots"),
    ('{"projectChecks":{}}', "projectChecks"), ('{"coverage":1}', "coverage"), ('{"agent":{"resume":"x"}}', "agent"),
    ('{"branch":{"pr":{"n":1}}}', "branch.pr"), ('{"avatar":{"image":"x"}}', "avatar.image"),
    ('{"a":[{"b":{"href":"x"}}]}', "href"),
])
def test_link_targets_must_be_null(payload, label):
    got = reasons(page(payload))
    assert got == [f"the data has a link target under '{label}'"]


def test_null_link_targets_pass():
    assert reasons(page('{"url":null,"web":null,"branch":{"pr":null},"avatar":{"image":null},"pr":5,"image":1}')) == []


def test_deep_array_is_a_reason_not_an_exception():
    got = reasons(page("[" * 5000 + "]" * 5000))
    assert got and got[0].startswith("invalid payload")


def test_wrong_part_never_parses_json(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("json.loads was called")
    monkeypatch.setattr(report_check.json, "loads", boom)
    assert reasons(page(a="<!doctype html><head >"))
    assert reasons(page(csp=""))
    assert reasons(page(title="<"))


def test_any_exception_becomes_invalid_payload(monkeypatch):
    def boom(*a, **k):
        raise KeyError("x")
    monkeypatch.setattr(report_check.json, "loads", boom)
    assert reasons(page()) == ["invalid payload"]


def test_trailing_text_after_part_4():
    got = reasons(page() + "tail")
    assert len(got) == 1 and "part 4" in got[0]


def test_secret_in_payload():
    got = reflektor.verify_html(page(json.dumps({"a": KEY})))
    assert len(got) == 1 and "credential" in got[0] and "private-key" in got[0] and KEY not in got[0]


def test_secret_behind_json_escape_is_found_in_decoded_strings():
    payload = '{"a":"\\u002d\\u002d\\u002d\\u002d\\u002d' + KEY[5:] + '"}'
    assert KEY not in payload and reasons(page(payload)) == []
    got = reflektor.verify_html(page(payload))
    assert len(got) == 1 and "credential" in got[0]


def test_secret_in_a_key_is_found():
    got = reflektor.verify_html(page(json.dumps({KEY: 1})))
    assert len(got) == 1 and "credential" in got[0]


def test_verify_html_passes_check_reasons_through():
    assert reflektor.verify_html(page(csp="")) == reasons(page(csp=""))


# ---- harden_html

def hardless(payload='{"a":1}', head_twice=False):
    text = A + B + "<title>t</title>" + C + payload + D
    return text


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_harden_inserts_csp(tmp_path):
    f = write(tmp_path / "r.html", hardless())
    assert reflektor.harden_html(f) == f
    assert f.read_text(encoding="utf-8") == page()


def test_harden_twice_is_refused(tmp_path):
    f = write(tmp_path / "r.html", hardless())
    reflektor.harden_html(f)
    before = f.read_bytes()
    with pytest.raises(PrepareError) as e:
        reflektor.harden_html(f)
    assert e.value.code == 1 and e.value.message == "already hardened"
    assert f.read_bytes() == before


def test_harden_refuses_two_heads_and_leaves_file(tmp_path):
    f = write(tmp_path / "r.html", hardless().replace("<title>", "<head><title>", 1))
    before = f.read_bytes()
    with pytest.raises(PrepareError) as e:
        reflektor.harden_html(f)
    assert "one <head>" in e.value.message
    assert f.read_bytes() == before


def test_harden_refuses_a_page_that_fails_the_check(tmp_path):
    f = write(tmp_path / "r.html", hardless('{"url":"x"}'))
    before = f.read_bytes()
    with pytest.raises(PrepareError) as e:
        reflektor.harden_html(f)
    assert "link target" in e.value.message
    assert f.read_bytes() == before


def test_harden_refuses_symlink_directory_big_and_non_utf8(tmp_path, monkeypatch):
    real = write(tmp_path / "real.html", hardless())
    link = tmp_path / "link.html"
    link.symlink_to(real)
    with pytest.raises(PrepareError):
        reflektor.harden_html(link)
    with pytest.raises(PrepareError):
        reflektor.harden_html(tmp_path)
    monkeypatch.setattr(reflektor, "MAX_HTML", 10)
    with pytest.raises(PrepareError) as e:
        reflektor.harden_html(real)
    assert "larger" in e.value.message
    monkeypatch.undo()
    monkeypatch.setattr(report_check, "VIEWER_PARTS", PARTS)
    bad = tmp_path / "bad.html"
    bad.write_bytes(b"\xff\xfe<head>")
    with pytest.raises(PrepareError) as e:
        reflektor.harden_html(bad)
    assert "UTF-8" in e.value.message
    assert real.read_text(encoding="utf-8") == hardless()


# ---- send_copy

def make_answer(tmp_path, lines, html=None, name="a"):
    out = tmp_path / name / "out"
    out.mkdir(parents=True)
    h = out / "report.html"
    h.write_text(page() if html is None else html, encoding="utf-8")
    ans = tmp_path / f"{name}.txt"
    ans.write_text("\n".join(l.replace("@H@", str(h)) for l in lines) + "\n", encoding="utf-8")
    return ans, h


def test_send_copy_success(tmp_path):
    ans, h = make_answer(tmp_path, ["text", "REPORT-HTML @H@", "AGENT-REPORT x"])
    dest = tmp_path / "d"
    dest.mkdir()
    got = reflektor.send_copy(ans, dest)
    assert got == dest / "report.html" and got.read_text(encoding="utf-8") == page()


def test_send_copy_uses_the_last_line(tmp_path):
    ans, h = make_answer(tmp_path, ["REPORT-HTML /nope/out/report.html", "REPORT-HTML @H@"])
    dest = tmp_path / "d"
    dest.mkdir()
    assert reflektor.send_copy(ans, dest).exists()


@pytest.mark.parametrize("bad", [
    "/tmp/$(x)/out/report.html", "/tmp/a b/out/report.html", "/tmp/../x/out/report.html", "tmp/out/report.html",
    "/tmp/x/report.html", "/tmp/x/out/report.htm", "/tmp/x/out/report.html/", "/tmp/x;y/out/report.html",
    "/tmp/x\\y/out/report.html",
])
def test_send_copy_refuses_bad_paths(tmp_path, bad):
    ans = tmp_path / "a.txt"
    ans.write_text(f"REPORT-HTML {bad}\n", encoding="utf-8")
    dest = tmp_path / "d"
    dest.mkdir()
    with pytest.raises(PrepareError) as e:
        reflektor.send_copy(ans, dest)
    assert e.value.code == 1
    assert list(dest.iterdir()) == []


def test_send_copy_refuses_answer_without_line_and_symlink_page(tmp_path):
    dest = tmp_path / "d"
    dest.mkdir()
    ans = tmp_path / "a.txt"
    ans.write_text("no line here\n", encoding="utf-8")
    with pytest.raises(PrepareError) as e:
        reflektor.send_copy(ans, dest)
    assert "no REPORT-HTML" in e.value.message
    ans2, h = make_answer(tmp_path, ["REPORT-HTML @H@"], name="b")
    real = tmp_path / "real.html"
    real.write_text(page(), encoding="utf-8")
    h.unlink()
    h.symlink_to(real)
    with pytest.raises(PrepareError):
        reflektor.send_copy(ans2, dest)
    assert list(dest.iterdir()) == []


def test_send_copy_refuses_a_bad_page_and_writes_nothing(tmp_path):
    ans, h = make_answer(tmp_path, ["REPORT-HTML @H@"], html=page(csp=""))
    dest = tmp_path / "d"
    dest.mkdir()
    with pytest.raises(PrepareError) as e:
        reflektor.send_copy(ans, dest)
    assert "Content-Security-Policy" in e.value.message
    assert list(dest.iterdir()) == []


def test_send_copy_refuses_a_secret_page(tmp_path):
    ans, h = make_answer(tmp_path, ["REPORT-HTML @H@"], html=page(json.dumps({"a": KEY})))
    dest = tmp_path / "d"
    dest.mkdir()
    with pytest.raises(PrepareError):
        reflektor.send_copy(ans, dest)
    assert list(dest.iterdir()) == []


# ---- check_report

@pytest.fixture
def clone(tmp_path):
    root = tmp_path / "clone"
    (root / "src").mkdir(parents=True)
    (root / "src" / "math.js").write_text("x")
    (root / "a").mkdir()
    (root / "a" / "b.txt").write_text("x")
    return root


def rep(**kw):
    return json.dumps({"sections": [{"files": [kw]}]})


def test_check_report_accepts_plain_paths(clone):
    assert reflektor.check_report(rep(path="src/math.js"), clone) == []
    assert reflektor.check_report(rep(path="a/b.txt") + "\n", clone) == []
    assert reflektor.check_report(rep(path="not/yet/there.txt"), clone) == []


@pytest.mark.parametrize("path", ["../x", "/etc/passwd", "~/x", "a\\b", "a//b", "a/./b", "", "a/../b", "a\x00b", 5, None, ["x"]])
def test_check_report_refuses_bad_paths(clone, path):
    got = reflektor.check_report(json.dumps({"sections": [{"files": [{"path": path}]}]}), clone)
    assert len(got) == 1


def test_check_report_refuses_nested_path_key(clone):
    assert reflektor.check_report(json.dumps({"ref": {"path": "../x"}}), clone)
    deep = {"a": [{"b": [{"c": {"path": "../x"}}]}]}
    assert reflektor.check_report(json.dumps(deep), clone)


def test_check_report_refuses_symlink_out_of_clone(clone, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (clone / "evil").symlink_to(outside)
    assert reflektor.check_report(rep(path="evil/secret"), clone) == ["path 'evil/secret' leaves the clone"]
    (clone / "file-link").symlink_to(outside / "f")
    assert reflektor.check_report(rep(path="file-link"), clone)


def test_check_report_shape(clone):
    assert reflektor.check_report("{}\n{}\n", clone)
    assert reflektor.check_report("{}\n\n", clone)
    assert reflektor.check_report("[]", clone) == ["the report is not a JSON object"]
    assert reflektor.check_report("nope", clone) == ["the report is not valid JSON"]
    assert reflektor.check_report("[" * 100000, clone)
    deep = '{"a":' * 300 + '{"path":"../x"}' + "}" * 300
    assert reflektor.check_report(deep, clone) == ["the report is nested too deeply"]
    assert reflektor.check_report("{}", clone) == []
    assert reflektor.check_report("{}\n", clone) == []


# ---- main and the real cli

def test_main_check(tmp_path, clone, capsys):
    good = tmp_path / "g.json"
    good.write_text(rep(path="a/b.txt") + "\n")
    bad = tmp_path / "b.json"
    bad.write_text(rep(path="../x"))
    assert reflektor.main(["check", "--report", str(good), "--root", str(clone)]) == 0
    assert reflektor.main(["check", "--report", str(bad), "--root", str(clone)]) == 1
    assert capsys.readouterr().err.startswith("tld roles: reflektor: ")
    assert reflektor.main(["check", "--report", str(tmp_path / "none"), "--root", str(clone)]) == 1


def test_main_html_file_and_send(tmp_path, capsys):
    f = write(tmp_path / "r.html", hardless())
    assert reflektor.main(["html", "--file", str(f)]) == 0
    assert reflektor.main(["html", "--file", str(f)]) == 1
    assert "tld roles: reflektor: already hardened" in capsys.readouterr().err
    ans, h = make_answer(tmp_path, ["REPORT-HTML @H@"])
    dest = tmp_path / "d"
    assert reflektor.main(["html", "--send", "--answer", str(ans), "--dest", str(dest)]) == 0
    assert capsys.readouterr().out.strip() == str(dest / "report.html")
    h.write_text(page(csp=""), encoding="utf-8")
    assert reflektor.main(["html", "--send", "--answer", str(ans), "--dest", str(tmp_path / "e")]) == 1
    assert capsys.readouterr().err.startswith("tld roles: reflektor: ")
    with pytest.raises(SystemExit):
        reflektor.main(["html"])
    with pytest.raises(SystemExit):
        reflektor.main(["html", "--send", "--answer", str(ans)])
    with pytest.raises(SystemExit):
        reflektor.main(["html", "--file", str(f), "--send", "--answer", "x", "--dest", "y"])


def _tld(*args):
    return subprocess.run([str(BIN), *args], capture_output=True, text=True, timeout=60)


def test_cli_check_missing_file(tmp_path):
    done = _tld("roles", "reflektor-check", "--report", str(tmp_path / "none"), "--root", str(tmp_path))
    assert done.returncode == 1 and "Traceback" not in done.stderr
    assert done.stderr.startswith("tld roles: reflektor: ")


def test_cli_html_send_missing_file(tmp_path):
    done = _tld("roles", "reflektor-html", "--send", "--answer", str(tmp_path / "none"), "--dest", str(tmp_path / "d"))
    assert done.returncode == 1 and "Traceback" not in done.stderr
    assert done.stderr.startswith("tld roles: reflektor: ")
    done = _tld("roles", "reflektor-html", "--file", str(tmp_path / "none"))
    assert done.returncode == 1 and "Traceback" not in done.stderr


def test_report_check_imports_nothing_from_tld():
    import re
    src = open(report_check.__file__, encoding="utf-8").read()
    assert not re.search(r"^\s*(from|import)\s+tld", src, re.M)
    assert len(report_check.VIEWER_PARTS) == 4
