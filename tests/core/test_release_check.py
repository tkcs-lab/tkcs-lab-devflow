"""`tld ops release-check`: the one definition of a green commit for a release."""
import json
import subprocess
import sys

import pytest
from conftest import BIN
from release_fixtures import CASES, run

from tld.ops import release_check as rc


def call(tmp_path, capsys, runs, status=None, *extra, raw=None):
    checks = tmp_path / "checks.json"
    checks.write_text(raw if raw is not None else json.dumps(runs))
    argv = ["--checks", str(checks), *extra]
    if status is not None:
        sf = tmp_path / "status.json"
        sf.write_text(json.dumps(status))
        argv += ["--status", str(sf)]
    code = rc.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.mark.parametrize("cid,runs,state,total,selfs,code", CASES)
def test_case_table(tmp_path, capsys, cid, runs, state, total, selfs, code):
    status = None if state is None else {"state": state, "total_count": total}
    argv = [a for n in selfs for a in ("--self", n)]
    got, out, _ = call(tmp_path, capsys, runs, status, *argv)
    assert got == code
    assert out.splitlines()[0].startswith({0: "release-check: green", 3: "release-check: waiting", 1: "release-check: red"}[code])


@pytest.mark.parametrize("concl", ["failure", "cancelled", "timed_out", "action_required", "stale", "startup_failure", None])
def test_every_bad_conclusion_is_red(tmp_path, capsys, concl):
    code, out, _ = call(tmp_path, capsys, [run("t", conclusion=concl)])
    assert code == 1
    assert out.splitlines()[1] == f"red: t: completed {concl or ''}".rstrip()


@pytest.mark.parametrize("status", ["in_progress", "queued"])
def test_not_completed_waits(tmp_path, capsys, status):
    code, out, _ = call(tmp_path, capsys, [run("t", status, None)])
    assert code == 3 and out.splitlines() == ["release-check: waiting", f"waiting: t: {status}"]


def test_red_wins_over_running(tmp_path, capsys):
    code, out, _ = call(tmp_path, capsys, [run("a", "in_progress", None), run("b", conclusion="failure")])
    assert code == 1 and "red: b: completed failure" in out and "waiting: a: in_progress" in out


def test_mixed_good_conclusions_are_green(tmp_path, capsys):
    code, out, _ = call(tmp_path, capsys, [run("a"), run("b", conclusion="skipped"), run("c", conclusion="neutral")])
    assert code == 0 and out.strip() == "release-check: green (3 check(s), commit status not checked)"


def test_green_with_status_does_not_say_not_checked(tmp_path, capsys):
    code, out, _ = call(tmp_path, capsys, [run("a")], {"state": "success", "total_count": 2})
    assert code == 0 and out.strip() == "release-check: green (1 check(s))"


def test_status_lines(tmp_path, capsys):
    assert call(tmp_path, capsys, [], {"state": "failure", "total_count": 1})[1].splitlines()[1] == "red: commit status: failure"
    assert call(tmp_path, capsys, [], {"state": "pending", "total_count": 1})[1].splitlines()[1] == "waiting: commit status: pending"


def test_self_once_and_twice(tmp_path, capsys):
    runs = [run("a", conclusion="failure"), run("b", "in_progress", None), run("c")]
    assert call(tmp_path, capsys, runs, None, "--self", "a")[0] == 3
    code, out, _ = call(tmp_path, capsys, runs, None, "--self", "a", "--self", "b")
    assert code == 0 and "(1 check(s)" in out


@pytest.mark.parametrize("shape", ["object", "list", "concatenated"])
def test_input_shapes(tmp_path, capsys, shape):
    runs = [run("a"), run("b", conclusion="failure")]
    raw = {"object": json.dumps({"check_runs": runs}), "list": json.dumps(runs),
           "concatenated": "\n".join(json.dumps(r, indent=2) for r in runs)}[shape]
    code, out, _ = call(tmp_path, capsys, None, None, raw=raw)
    assert code == 1 and "red: b: completed failure" in out


def test_two_pages_of_the_api(tmp_path, capsys):
    raw = json.dumps({"check_runs": [run("a")]}) + json.dumps({"check_runs": [run("b", conclusion="failure")]})
    assert call(tmp_path, capsys, None, None, raw=raw)[0] == 1


def test_stdin(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([run("a")])))
    assert rc.main(["--checks", "-"]) == 0
    assert capsys.readouterr().out.startswith("release-check: green")


@pytest.mark.parametrize("raw", ["{not json", "", "  \n ", '{"check_runs": null}', "[1, 2]", '"text"'])
def test_unreadable_input_is_exit_2(tmp_path, capsys, raw):
    code, out, err = call(tmp_path, capsys, None, None, raw=raw)
    assert code == 2 and out == "" and err.startswith("release-check: ")


def test_missing_file_and_bad_status(tmp_path, capsys):
    assert rc.main(["--checks", str(tmp_path / "nope.json")]) == 2
    assert "release-check:" in capsys.readouterr().err
    code, _, err = call(tmp_path, capsys, [run("a")], ["not", "an", "object"])
    assert code == 2 and "status is not an object" in err


def test_bad_option_exits_2():
    with pytest.raises(SystemExit) as e:
        rc.main(["--bogus"])
    assert e.value.code == 2


@pytest.mark.parametrize("raw", ["[]", '{"check_runs": []}'])
def test_no_checks_given_as_empty_list_is_green(tmp_path, capsys, raw):
    code, out, _ = call(tmp_path, capsys, None, None, raw=raw)
    assert code == 0 and "(0 check(s" in out.splitlines()[0]


def test_sha_is_echoed(tmp_path, capsys):
    assert call(tmp_path, capsys, [run("a")], None, "--sha", "abc123")[1].startswith("release-check: green abc123 (")
    assert call(tmp_path, capsys, [run("a", conclusion="failure")], None, "--sha", "abc123")[1].startswith("release-check: red abc123\n")


def test_registered_in_the_cli():
    p = subprocess.run([sys.executable, str(BIN), "ops", "release-check", "--sha", "x"], input=json.dumps([run("t", conclusion="failure")]),
                       capture_output=True, text=True)
    assert p.returncode == 1 and p.stdout.splitlines() == ["release-check: red x", "red: t: completed failure"]
