from conftest import DEVFLOW


def flat(*parts):
    return " ".join((DEVFLOW.joinpath(*parts)).read_text().split())


MAKE_PLAN = flat("commands", "make-plan.md")
IMPLEMENT = flat("commands", "implement.md")
DOD = flat("commands", "dod.md")
DISPATCH = flat("skills", "agent-dispatch", "SKILL.md")
DOCS_REVIEW = flat("skills", "docs-review", "SKILL.md")
CHECK = "docs_index.py check --profile .claude/toolkit.yaml"


def test_e1_index_parts_bullet_in_make_plan():
    assert '"index parts" apply only when the profile has `docs.index`' in MAKE_PLAN
    assert 'follow its "Reading protocol"' in MAKE_PLAN


def test_e2_reading_through_the_index():
    assert "Index parts: then open the docs index (`docs.index`) and read only the rows that match the change" in MAKE_PLAN
    assert "Without `docs.index`: read the ADR index and every ADR" in MAKE_PLAN


def test_e2b_architect_gets_routed_paths():
    assert "(index parts: and the paths of the docs you read through the index)" in MAKE_PLAN


def test_e3_read_first_line():
    assert "Read first: <paths>" in MAKE_PLAN


def test_e4_retirement_phase_owns_the_index():
    assert "the retirement phase also updates the docs index" in MAKE_PLAN
    assert "No other phase edits the index or `CLAUDE.md`" in MAKE_PLAN
    assert "`docs-changed:` line" in MAKE_PLAN


def test_e5_final_check_in_manifest_example():
    assert "`python3 <devflow root>/scripts/" + CHECK + "` exits 0> # index parts only" in MAKE_PLAN


def test_e6_reviewer_checks_index_rows_and_read_first():
    assert "gives a brief no `Read first:` line (index parts)" in MAKE_PLAN


def test_e7_no_index_hint():
    assert "No docs index: run /docs init to build one" in MAKE_PLAN


def test_e8_small_scope_items():
    assert "and the docs the index routes to (index parts)" in MAKE_PLAN
    assert "the docs-index rows the change needs (index parts)" in MAKE_PLAN


def test_e9_implement_profile_bullet():
    assert '"index parts" apply only when the profile has it' in IMPLEMENT


def test_e10_child_brief_rule():
    assert "Read the docs your brief's `Read first:` line names" in IMPLEMENT
    assert "docs-changed: <added|moved|deleted> <path>" in IMPLEMENT


def test_e11_ledger_list_docs_changed():
    assert "Collect each `docs-changed:` line of the report into the ledger list `Docs changed`" in IMPLEMENT


def test_e12_retirement_brief_gets_the_list():
    assert "update the docs index for each" in IMPLEMENT


def test_e13_finishing_runs_check():
    assert CHECK in IMPLEMENT


def test_e14_final_review_checks_index():
    assert "`CLAUDE.md` is still at most 60 lines" in IMPLEMENT


def test_scripts_named_in_all_three_commands():
    for text in (MAKE_PLAN, IMPLEMENT, DOD):
        assert CHECK in text


def test_e15_dod_row_is_non_blocking():
    assert "Docs index (only when the profile has `docs.index`)" in DOD
    assert "n/a (docs_index.py not in this devflow version)" in DOD
    assert "never FAIL and never part of the verdict" in DOD


def test_e16_agents_do_not_get_the_index():
    assert "Never hand an agent the index" in DISPATCH


def test_e17_docs_review_checks_index():
    assert "Docs index (only when the profile has" in DOCS_REVIEW
    assert "a `CLAUDE.md` over 60 lines" in DOCS_REVIEW
