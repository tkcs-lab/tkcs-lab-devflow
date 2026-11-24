"""tld plan handover (src/tld/plan/handover.py): the hand-over object of a finished plan or issue body."""
import json
import random
import string
import subprocess

import pytest

from conftest import tld_cmd
from tld.board import record

REPO = "tkcs-lab/demo"
BASE = f"https://github.com/{REPO}"
PLAN_URL = f"{BASE}/blob/feature/demo/docs/plans/1/plan.md"
ISSUE_URL = f"{BASE}/issues/12"
SPEC_URL = f"{BASE}/tree/feature/demo/openspec/changes/demo-plan"
BODY = "**Use it:** a b c\n**Scope:** a b c\n**Review focus:** a b c"
UNSAFE_MSG = "handover: 'handover.summary' holds a control, format, surrogate, private-use or separator character\n"


def run(path, *args, kind="plan", slug="demo-plan", repo=REPO):
    argv = tld_cmd("plan", "handover", str(path), "--kind", kind, "--repo", repo, "--plan-slug", slug, *args)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def write(tmp_path, text, name="doc.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def with_extra(extra):
    """The Summary body with `extra` on a line of the Scope label (labels stay in order)."""
    return BODY.replace("**Scope:** a b c", "**Scope:** a b c " + extra)


def plan(summary_lines, pre="# Title\n\n"):
    return pre + "## Summary\n\n" + summary_lines + "\n\n## 1. Goal\n\nmore\n"


def test_handover_printed_word_for_word(tmp_path):
    text = (
        "# Title\n\n## Summary\n\n\n" + BODY + "\n\n```\n## not a heading\n```\n\n## 1. Goal\n\nmore\n"
    )
    r = run(write(tmp_path, text), "--plan-url", PLAN_URL, "--command-prefix", "/tld:implement")
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    assert obj["summary"] == BODY + "\n\n```\n## not a heading\n```"
    assert obj["next_command"] == "/tld:implement " + PLAN_URL
    assert obj["issue_url"] is None and obj["spec_url"] is None
    assert obj["plan_slug"] == "demo-plan"
    assert record.handover_errors(obj, REPO) == []


def test_handover_issue_kind(tmp_path):
    text = "## Request\n\nthe ask\n\n## Summary\n\n" + BODY + " é→ü\n\n## Goal\n\nmore\n"
    r = run(write(tmp_path, text), "--issue-url", ISSUE_URL, kind="issue", slug="issue-12")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "summary": BODY + " é→ü", "plan_slug": "issue-12", "issue_url": ISSUE_URL,
        "plan_url": None, "spec_url": None, "next_command": None,
    }


def test_handover_plan_url_without_prefix(tmp_path):
    r = run(write(tmp_path, plan(BODY)), "--plan-url", PLAN_URL, "--spec-url", SPEC_URL)
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    assert obj["next_command"] is None and obj["plan_url"] == PLAN_URL and obj["spec_url"] == SPEC_URL


def test_handover_summary_unsafe_character(tmp_path):
    r = run(write(tmp_path, plan(with_extra("a b c \u202e"))))
    assert (r.returncode, r.stdout, r.stderr) == (1, "", UNSAFE_MSG)


def test_handover_summary_too_many_characters(tmp_path):
    r = run(write(tmp_path, plan(with_extra("x" * 4000))))
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr == "handover: 'handover.summary' has 4059 characters, at most 4000 are allowed\n"


def test_handover_line_separator_before_secret_is_unsafe(tmp_path):
    secret = "api_key = '" + _secret() + "'"
    r = run(write(tmp_path, plan(with_extra("a b c \u2028" + secret))))
    assert (r.returncode, r.stdout, r.stderr) == (1, "", UNSAFE_MSG)


def test_handover_summary_over_word_limit(tmp_path):
    r = run(write(tmp_path, plan(BODY + " " + " ".join(["w"] * 400))))
    assert r.returncode == 1 and r.stdout == ""
    assert r.stderr.startswith("handover: summary: ")


def _secret():
    rng = random.Random(11)
    chars = [rng.choice(string.ascii_letters + string.digits) for _ in range(40)]
    chars[0], chars[1] = "q", "7"
    return "".join(chars)


def test_handover_secret_in_summary_names_line_not_value(tmp_path):
    value = _secret()
    # the Summary after strip: line 1 label, line 2 blank, line 3 the secret line
    summary = "**Use it:** a b c\n\nsecret_key = '" + value + "'\n**Scope:** a b c\n**Review focus:** a b c"
    text = "# Title\n\n\n## Summary\n\n" + summary + "\n\n## 1. Goal\n\nmore\n"
    r = run(write(tmp_path, text))
    assert r.returncode == 1 and r.stdout == ""
    assert r.stderr == "handover: a secret-like value on line 3 of the Summary\n"
    assert value not in r.stdout + r.stderr


def test_handover_value_fails_record_rules(tmp_path):
    r = run(write(tmp_path, plan(BODY)), "--plan-url", "https://github.com/other/repo/blob/main/plan.md")
    assert r.returncode == 1 and r.stdout == ""
    assert r.stderr.startswith("handover: 'handover.plan_url' must be null or ")


def test_handover_command_prefix_rules(tmp_path):
    path = write(tmp_path, plan(BODY))
    r = run(path, "--command-prefix", "/tld:implement")
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr == "handover: --command-prefix needs --plan-url\n"
    r = run(path, "--plan-url", PLAN_URL, "--command-prefix", "tld implement")
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr.startswith("handover: 'handover.next_command' must be ")


@pytest.mark.parametrize("case", ["missing", "too_large", "not_utf8"])
def test_handover_unreadable_file(tmp_path, case):
    if case == "missing":
        path = tmp_path / "nope.md"
    elif case == "too_large":
        path = tmp_path / "big.md"
        path.write_bytes(b"a" * 1000001)
    else:
        path = tmp_path / "bad.md"
        path.write_bytes(b"\xff")
    r = run(path)
    assert (r.returncode, r.stdout) == (1, "")
    lines = r.stderr.splitlines()
    assert len(lines) == 1 and lines[0].startswith("handover: ")


def test_handover_summary_with_allow_marker(tmp_path):
    line = "api_key = '" + _secret() + "'  # secret-scan:allow"
    r = run(write(tmp_path, plan(with_extra(line))))
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr == "handover: the Summary must not contain 'secret-scan:allow'\n"
    assert _secret() not in r.stderr


def test_handover_token_shaped_link(tmp_path):
    token = "ghp_" + _secret()[:36]
    url = f"{BASE}/blob/{token}/plan.md"
    r = run(write(tmp_path, plan(BODY)), "--plan-url", url, "--command-prefix", "implement")
    assert (r.returncode, r.stdout) == (1, "")
    assert token not in r.stderr and "secret-like value" in r.stderr
    assert "'plan_url' holds a secret-like value" in r.stderr
