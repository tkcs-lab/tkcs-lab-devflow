"""The playbooks name `tld board record-id` for the status record id; none builds an id by hand."""
from conftest import ROOT

from tld.guard import board_gate

PLAYBOOKS = ROOT / "playbooks"
POLICY = PLAYBOOKS / "policies" / "status-board.md"
WRITERS = ("implement", "make-plan", "review", "migrate", "setup", "land", "deps", "upstream", "ci", "docs")


def _text(path):
    return path.read_text(encoding="utf-8")


def test_no_playbook_hand_builds_a_document_id():
    bad = []
    for base in (PLAYBOOKS, ROOT / "adapters"):
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f == POLICY:
                continue
            try:
                t = _text(f)
            except UnicodeDecodeError:
                continue
            for pat in ("<project>--", "{project}--", "tkcs-lab-devflow--"):
                if pat in t:
                    bad.append(f"{f.relative_to(ROOT)}: {pat}")
    assert not bad, bad


def test_status_board_policy_names_record_id_in_the_table_row():
    rows = [ln for ln in _text(POLICY).splitlines() if ln.startswith("| document id")]
    assert rows and "tld board record-id" in rows[0]


def test_every_record_writer_names_record_id():
    missing = [c for c in WRITERS if "tld board record-id" not in _text(PLAYBOOKS / f"{c}.md")]
    assert not missing, missing


def test_status_board_policy_has_the_fallback_and_resume_rule():
    t = _text(POLICY)
    for needle in ("tld board client set", "Only exit 3", "keeps writing that one", "never a reason to skip"):
        assert needle in t, needle


def test_runtime_map_has_the_fallback():
    assert "tld board client set" in _text(ROOT / "adapters" / "claude" / "skills" / "runtime" / "SKILL.md")


def test_record_commands_match_the_playbooks():
    named = {f.stem for f in PLAYBOOKS.glob("*.md") if "tld board record-id" in _text(f)}
    assert named == set(board_gate.RECORD_COMMANDS)


def test_status_board_policy_names_the_already_running_exception():
    t = " ".join(_text(POLICY).split())
    assert any(("already running" in s or "already being planned" in s) and "no record" in s
               for s in t.split(". ")), "the 'already running' exception to the first-record rule is missing"
    assert "write no record yet" in board_gate.MESSAGE
    for name in ("implement", "make-plan"):
        assert 'status-board.md` "When to write"' in _text(PLAYBOOKS / f"{name}.md")
