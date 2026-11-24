"""`tld ops deps-body`: the combined dependency pull request body, rendered from validated entries."""
import json
import re
import subprocess

import pytest
from conftest import tld_cmd

from tld.ops.deps_checks import FILE_REASONS, PREPARE_REASONS

CLOSING = re.compile(r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b:?\s+(\S+/\S+)?#\d")


def entry(**kw):
    base = {"ecosystem": "pip", "directory": "/", "pr": 88, "security": False,
            "updates": [{"package": "coverage", "from": "7.17.2", "to": "7.17.3"}],
            "moves": [], "files": [], "state": "included", "reason": None, "file": None}
    base.update(kw)
    return base


def upd(package="coverage", old="1.0.0", new="1.0.1"):
    return {"package": package, "from": old, "to": new}


def body(tmp_path, entries):
    path = tmp_path / "in.json"
    path.write_text(entries if isinstance(entries, str) else json.dumps({"entries": entries}))
    proc = subprocess.run(tld_cmd("ops", "deps-body", str(path)), capture_output=True, text=True)
    return proc, path


def ok(tmp_path, entries):
    proc, path = body(tmp_path, entries)
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "body.md"
    out.write_text(proc.stdout)
    return proc.stdout, out


def summary_check(out):
    return subprocess.run(tld_cmd("plan", "summary-check", str(out), "--kind", "pr"), capture_output=True, text=True)


def rows(text):
    return [line for line in text.split("\n") if line.startswith("| `")]


def test_security_first(tmp_path):
    entries = [
        entry(ecosystem="npm", directory="/a", pr=1, updates=[upd("left-pad")]),
        entry(ecosystem="github-actions", directory="/", pr=2, updates=[upd("actions/x")]),
        entry(ecosystem="zz", directory="/z", pr=900, security=True, updates=[upd("zpkg")]),
        entry(ecosystem="zz", directory="/z", pr=None, security=True, updates=[upd("audit-pkg")]),
    ]
    text, out = ok(tmp_path, entries)
    packages = [re.findall(r"`([^`]+)`", r)[2] for r in rows(text)]
    assert packages == ["audit-pkg", "zpkg", "actions/x", "left-pad"]
    assert "Security updates first: `audit-pkg`, `zpkg`." in text
    assert "| `zz /z` | `audit` | `audit-pkg` | `1.0.0` | `1.0.1` | yes |" in text
    assert summary_check(out).returncode == 0


def test_versions_not_known(tmp_path):
    entries = [entry(updates=[], pr=5), entry(ecosystem="npm", pr=6, updates=[{"package": "new-dep", "from": None, "to": "2.0"}])]
    text, _ = ok(tmp_path, entries)
    assert "| `npm /` | `#6` | `new-dep` | new | `2.0` | no |" in text
    assert "| `pip /` | `#5` | `see #5` | - | - | no |" in text
    assert "The version changes in the Updates table." in text


def test_major_jumps_are_listed(tmp_path):
    entries = [entry(updates=[upd("a", "v1.2", "v2.0"), upd("b", "1.2", "1.3"), upd("c", None, "3.0")])]
    text, _ = ok(tmp_path, entries)
    assert "Major version jumps: `a` `v1.2` to `v2.0`." in text


def test_workflow_files_and_action_moves_named(tmp_path):
    moves = [{"action": f"actions/a{i}", "from": "v1", "to": "v2"} for i in range(7)]
    files = [f".github/workflows/w{i}.yml" for i in range(7)] + ["README.md"]
    entries = [entry(ecosystem="github-actions", pr=81, updates=[], security=True, moves=moves, files=files)]
    text, out = ok(tmp_path, entries)
    sec = next(line for line in text.split("\n") if line.startswith("**Security:**"))
    assert "Workflow files changed: `.github/workflows/w0.yml`" in sec and "`.github/workflows/w4.yml` and 2 more." in sec
    assert "`README.md`" not in sec
    assert "Action moves: `actions/a0` `v1` to `v2`" in sec and "`actions/a4` `v1` to `v2` and 2 more." in sec
    assert "## Action moves" in text and text.count("- `github-actions /` (`#81`): `actions/a") == 7
    assert summary_check(out).returncode == 0


def test_a_left_out_group_is_named(tmp_path):
    entries = [entry(), entry(ecosystem="github-actions", pr=81, state="left_out", reason="verify-red"),
               entry(ecosystem="npm", pr=82, state="left_out", reason="protected-path", file=".env"),
               entry(ecosystem="cargo", pr=None, security=True, state="left_out", reason="time-budget")]
    text, out = ok(tmp_path, entries)
    assert "**Deviations:** Left out 3 updates: `cargo /` (`audit`), `github-actions /` (`#81`), `npm /` (`#82`); see Left out." in text
    assert "- `github-actions /` (`#81`): red after two fix attempts. Its Dependabot pull request stays open." in text
    assert "- `npm /` (`#82`): it changes the protected path `.env`. Its Dependabot pull request stays open." in text
    assert "- `cargo /` (`audit`): not combined: time budget used. It has no Dependabot pull request." in text
    assert summary_check(out).returncode == 0


def test_nothing_left_out(tmp_path):
    text, _ = ok(tmp_path, [entry()])
    assert "**Deviations:** None." in text and "## Left out" not in text and "## Action moves" not in text
    assert "**Security:**" not in text
    assert text.rstrip().endswith("once its update is on the main branch.")


def test_no_closing_keyword(tmp_path):
    entries = [entry(ecosystem="fixes", directory="/resolves", pr=7, updates=[upd("closes")]),
               entry(ecosystem="fixes", directory="/resolves", pr=8, state="left_out", reason="verify-red")]
    text, _ = ok(tmp_path, entries)
    assert CLOSING.search(text) is None


def test_untrusted_values_render_in_code_spans(tmp_path):
    entries = [entry(updates=[upd("@scope/pkg"), upd("@someone")], security=True)]
    text, _ = ok(tmp_path, entries)
    assert "`@scope/pkg`" in text
    assert not re.search(r"@\w", re.sub(r"`[^`]*`", "", text))


def reject(**kw):
    return entry(**kw)


BAD = [
    ("space", reject(updates=[upd("a b")])), ("pipe", reject(updates=[upd("a|b")])),
    ("backtick", reject(updates=[upd("a`b")])), ("newline", reject(updates=[upd("a\nb")])),
    ("version", reject(updates=[upd(new="1$(id)")])), ("dotdot", reject(directory="/a/../b")),
    ("reason", reject(state="left_out", reason="nope")), ("pr0", reject(pr=0)), ("prbool", reject(pr=True)),
    ("prfloat", reject(pr=1.5)), ("secstr", reject(security="yes")),
    ("key", {**entry(), "extra": 1}),
    ("verify-red-file", reject(state="left_out", reason="verify-red", file="a.txt")),
    ("file-form", reject(state="left_out", reason="protected-path", file="/etc/passwd")),
    ("no-updates-no-pr", reject(updates=[], pr=None)),
    ("included-reason", reject(reason="verify-red")),
    ("too-many-moves", reject(moves=[{"action": "a/b", "from": "v1", "to": "v2"}] * 51)),
    ("move-action", reject(moves=[{"action": "a..b/c", "from": "v1", "to": "v2"}])),
    ("many-updates", reject(updates=[upd()] * 51)), ("many-files", reject(files=["a"] * 201)),
    ("long-file", reject(files=["a" * 201])),
]


@pytest.mark.parametrize("name,bad", BAD, ids=[n for n, _ in BAD])
def test_untrusted_values_refused(tmp_path, name, bad):
    proc, _ = body(tmp_path, [entry(), bad])
    assert proc.returncode == 1 and proc.stdout == ""
    assert proc.stderr.startswith("deps: entry 1: ") and proc.stderr.count("\n") == 1


@pytest.mark.parametrize("name,text", [pytest.param(n, t, id=n) for n, t in [
    ("101 entries", json.dumps({"entries": [entry()] * 101})),
    ("no entries", '{"entries": []}'),
    ("no included", json.dumps({"entries": [entry(state="left_out", reason="verify-red")]})),
    ("file over 1000000 bytes", json.dumps({"entries": [entry()], "pad": "x" * 1000000})),
    ("big file", " " * 1000001),
    ("invalid json", "{"), ("array", "[]"), ("bad utf-8", "\xff"),
]])
def test_untrusted_input_refused(tmp_path, name, text):
    proc, _ = body(tmp_path, text)
    assert proc.returncode == 1 and proc.stdout == "" and proc.stderr.startswith("deps: ")
    if name == "no included":
        assert proc.stderr == "deps: no included entry\n"


def test_boundaries_pass(tmp_path):
    ok(tmp_path, [entry(pr=i + 1) for i in range(100)])
    ok(tmp_path, [entry(updates=[upd(f"p{i}") for i in range(50)])])
    ok(tmp_path, [entry(files=[f"f{i}" for i in range(200)])])
    ok(tmp_path, [entry(moves=[{"action": f"a/b{i}", "from": "v1", "to": "v2"} for i in range(50)])])


def test_a_missing_file_is_refused(tmp_path):
    proc = subprocess.run(tld_cmd("ops", "deps-body", str(tmp_path / "none.json")), capture_output=True, text=True)
    assert proc.returncode == 1 and proc.stdout == "" and proc.stderr.startswith("deps: ")


def test_body_passes_summary_check(tmp_path):
    for n in (1, 7, 100):
        _, out = ok(tmp_path, [entry(ecosystem=f"eco{i}", pr=i + 1, security=i % 2 == 0,
                                     updates=[upd(f"pkg{i}", "1.0", "2.0")]) for i in range(n)])
        done = summary_check(out)
        assert done.returncode == 0, (n, done.stdout)
    moves = [{"action": f"actions/a{i}", "from": "v1", "to": "v2"} for i in range(50)]
    big = [entry(ecosystem=f"eco{i}", pr=i + 1, security=True, updates=[], moves=moves,
                 files=[f".github/workflows/w{i}.yml"]) for i in range(100)]
    _, out = ok(tmp_path, big)
    done = summary_check(out)
    assert done.returncode == 0, done.stdout
    left = [{**e, "state": "left_out", "reason": "verify-red"} for e in big[:50]] + big[50:]
    _, out = ok(tmp_path, left)
    assert summary_check(out).returncode == 0


def test_every_prepare_reason_is_accepted_by_body(tmp_path):
    entries = [entry()]
    for i, reason in enumerate(PREPARE_REASONS):
        entries.append(entry(ecosystem=f"e{i}", pr=i + 1, state="left_out", reason=reason,
                             file="a/b.txt" if reason in FILE_REASONS else None))
    text, out = ok(tmp_path, entries)
    assert text.count("\n- `e") == len(PREPARE_REASONS)
    assert summary_check(out).returncode == 0
