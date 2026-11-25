"""The playbook text of the page note: the dod commands, the row, and the first line of the PR body section."""
import re

import pytest

from conftest import ROOT, _load

page_note = _load("tld.roles.page_note")

PLAYBOOKS = ROOT / "playbooks"
BLOCK = "BEGIN change-report\n### Changes\n- one thing\nEND change-report\n"
STAGES = ("role", "check", "board", "send")
NOTE = "HTML page not stored: "


def test_dod_names_exactly_the_four_stages():
    dod = (PLAYBOOKS / "dod.md").read_text()
    assert set(re.findall(r"--stage (\w+)", dod)) == set(STAGES)


def test_dod_names_the_row_text():
    dod = (PLAYBOOKS / "dod.md").read_text()
    assert "needs attention (<blocking> + <non-blocking>; HTML page not stored)" in dod


def _pr_body(tmp_path, capsys, note_text):
    answer = tmp_path / "answer.md"
    answer.write_text(BLOCK)
    note_file = tmp_path / "note.txt"
    note_file.write_text(note_text)
    assert page_note.main(["report", "--report", str(answer), "--note", str(note_file)]) == 0
    return "## Change report\n" + capsys.readouterr().out


def _first_line_under_heading(body):
    after = body.split("## Change report\n", 1)[1]
    return next(line for line in after.splitlines() if line.strip())


@pytest.mark.parametrize("stage", STAGES)
def test_note_is_the_first_line_of_the_change_report_section(tmp_path, capsys, stage):
    note = page_note.note_line(stage, "", False)
    first = _first_line_under_heading(_pr_body(tmp_path, capsys, note + "\n"))
    assert first == note and first.startswith(NOTE)


def test_empty_note_leaves_the_block_first(tmp_path, capsys):
    first = _first_line_under_heading(_pr_body(tmp_path, capsys, ""))
    assert first == "#### Changes"  # the first line of the block, headings demoted, markers dropped
    assert not first.startswith(NOTE)


def test_implement_forbids_removing_rewording_or_moving_the_line():
    implement = (PLAYBOOKS / "implement.md").read_text()
    assert "its first line is `HTML page not stored: <reason>`" in implement
    assert "never remove, shorten, reword or move it" in implement
    assert "never edit, rebuild or re-send the page" in implement
