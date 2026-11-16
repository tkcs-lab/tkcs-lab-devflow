"""The Claude adapter puts the toolkit preamble in front of every worker brief."""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[3] / "adapters/claude/skills/runtime/SKILL.md"


def _text():
    return SKILL.read_text(encoding="utf-8")


def _preamble():
    section = _text().split("### Toolkit preamble", 1)[1]
    match = re.search(r"```\n(.*?)\n```", section, re.S)
    assert match, "no fenced preamble block"
    return match.group(1)


def test_the_start_worker_row_names_the_preamble():
    rows = [line for line in _text().splitlines() if line.startswith("| `start_worker(")]
    assert len(rows) == 1
    assert "Put the toolkit preamble below in front of every brief." in rows[0]


def test_the_preamble_starts_with_the_worker_token_line():
    assert _preamble().splitlines()[0] == "tld-worker: <title>"


def test_the_preamble_says_tld_is_not_on_path_and_checks_it():
    block = _preamble()
    for needle in ("is not on PATH", "test -x", "--version"):
        assert needle in block


def test_the_preamble_names_the_unavailable_line():
    block = _preamble()
    assert "tld: unavailable" in block
    assert "status=blocked" in block


def test_the_preamble_scopes_the_stop_to_the_plan_gate_and_other_guards():
    flat = " ".join(_preamble().split())
    assert ("If the plan-gate or any guard other than protect-paths denies an action, or protect-paths names a path "
            "that the protected-changes flow excludes, stop with status=blocked and say so; any other protected "
            "path is reported as protected-change, see your brief.") in flat


def test_the_prose_names_the_placeholders_in_backticks():
    text = _text()
    for name in ("<tld cli>", "<tld root>", "<tld version>"):
        assert f"`{name}`" in text.split("```\n", 2)[2]
