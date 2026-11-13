"""Structure of the release playbook: the marker is always cleared, skip_checks is never used, the base check runs."""
import re
from pathlib import Path

PLAYBOOK = Path(__file__).resolve().parents[2] / "playbooks" / "release.md"
LINES = PLAYBOOK.read_text().splitlines()


def lines_with(text):
    return [i for i, line in enumerate(LINES) if text in line]


def test_every_allow_release_is_followed_by_an_end_allow():
    allow = lines_with("tld guard allow-release")
    assert allow
    ends = lines_with("tld guard end-allow")
    for i in allow:
        assert any(j > i for j in ends), f"line {i + 1} sets the marker and nothing clears it later"


def test_every_line_naming_skip_checks_says_never():
    named = lines_with("skip_checks")
    assert named
    for i in named:
        assert re.search(r"\bnever\b", LINES[i], re.I), f"line {i + 1} names skip_checks without 'never'"


def test_the_check_runs_with_and_without_a_base():
    checks = [line for line in LINES if "tld ops release-prepare --check" in line]
    with_base = [line for line in checks if "--base" in line]
    assert len(with_base) == 1 and len(checks) - len(with_base) == 1


def test_a_real_dispatch_comes_only_after_the_marker():
    real = [i for i, line in enumerate(LINES) if "workflow_dispatch" in line and 'dry_run: "false"' in line]
    assert real
    first_allow = lines_with("tld guard allow-release")[0]
    assert all(i > first_allow for i in real)


def test_it_writes_no_status_record_and_says_why():
    text = " ".join(PLAYBOOK.read_text().split())
    assert "writes no status record" in text and "short attended flow" in text
