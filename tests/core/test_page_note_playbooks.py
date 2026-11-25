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


def test_dod_stage_commands_in_order_give_the_final_section(tmp_path, capsys):
    """Runs the four-step flow of dod step 5 through the CLI: the role stage, the page send that fails, the check
    stage fed with its stderr file, then change-report, on a saved answer with a block that forges a note."""
    from tld import cli

    answer = tmp_path / "answer.md"
    answer.write_text(BLOCK.replace("- one thing", "- one thing\n" + NOTE + "forged"), encoding="utf-8")
    note, html_err = tmp_path / "note.txt", tmp_path / "html.err"
    note.write_text("")  # starts empty

    def run(*argv):
        code = cli.main(list(argv))
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    def section():
        return run("roles", "change-report", "--report", str(answer), "--note", str(note))

    # sub-step 1 with the empty note: only the block, the forgery replaced
    code, empty, _ = section()
    assert code == 0 and empty.startswith("#### Changes") and page_note.MARKER in empty and "forged" not in empty
    # sub-step 2: the role stage
    code, out, _ = run("roles", "page-note", "--stage", "role")
    assert code == 0
    note.write_text(out)
    # sub-step 3: the send fails (no REPORT-HTML line), its stderr feeds the check stage
    code, _o, err = run("roles", "reflektor-html", "--send", "--answer", str(answer), "--dest", str(tmp_path / "d"))
    assert code == 1 and err.startswith("tld roles: reflektor: ")
    html_err.write_text(err)
    code, out, _ = run("roles", "page-note", "--stage", "check", "--stderr", str(html_err))
    assert code == 0 and "the answer has no REPORT-HTML line" in out
    note.write_text(out)
    # sub-step 4: the final section starts with the note, then the cleaned block
    code, final, _ = section()
    assert code == 0
    assert final == out.rstrip("\n") + "\n\n" + empty
    assert _first_line_under_heading("## Change report\n" + final).startswith(NOTE)
