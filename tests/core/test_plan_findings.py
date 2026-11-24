"""The findings checker (src/tld/plan/findings.py): the rows of the `## Non-blocking findings` section."""
import pytest

from tld.plan import findings

SHA = "abc1234"


def row(k=1, source="final-review", loc="a.py:1", text="a b c d", status=f"fixed {SHA}"):
    return f"- F{k} · {source} · {loc} · {text} · {status}"


def check(lines, n=None):
    return findings.check(lines, n)


def has(problems, part):
    return any(part in p for p in problems)


def test_an_empty_section_is_a_problem():
    assert has(check([]), "the section is empty")
    assert has(check(["", "  "]), "the section is empty")


def test_none_without_n_is_accepted():
    assert check(["", "None.", ""]) == []


def test_none_is_accepted_with_n_zero_and_rejected_with_n_three():
    assert check(["None."], 0) == []
    assert check(["None."], 3) == ["says None. but 3 findings were counted"]


def test_a_row_missing_its_status_is_a_problem():
    assert has(check(["- F1 · final-review · a.py:1 · a b c d"]), "row 1: 4 fields")


def test_a_declined_row_with_a_two_word_reason_is_a_problem():
    assert has(check([row(status="declined: no way")[:-6] + "no way"]), "row 1")
    assert has(check([row(status="declined: no way")]), "at least 3 words")


@pytest.mark.parametrize("reason", ["none", "None.", "tbd", "todo", "n/a", "<reason>"])
def test_a_declined_reason_none_or_a_placeholder_is_a_problem(reason):
    assert has(check([row(status=f"declined: {reason}")]), "placeholder or none")


def test_a_declined_row_with_a_real_reason_is_accepted():
    assert check([row(status="declined: it is out of scope")]) == []


@pytest.mark.parametrize("sha", ["abcdef", "xyz1234", "a" * 41])
def test_a_bad_sha_is_a_problem(sha):
    assert has(check([row(status=f"fixed {sha}")]), "the status must be")


def test_a_forty_character_sha_is_accepted():
    assert check([row(status="fixed " + "a" * 40)]) == []


def test_a_duplicate_id_is_a_problem():
    assert has(check([row(1), row(1)]), "ids must run F1..F2 in order")


def test_a_gap_in_ids_is_a_problem():
    assert has(check([row(1), row(3)]), "ids must run F1..F2 in order")


def test_ids_out_of_order_are_a_problem():
    assert has(check([row(2), row(1)]), "ids must run F1..F2 in order")


def test_n_with_a_different_row_count_is_a_problem():
    assert check([row(1), row(2), row(3)], 2) == ["3 rows, expected 2"]


def test_n_zero_with_a_row_is_a_problem():
    assert check([row(1)], 0) == ["rows but no findings were counted"]


def test_a_html_comment_in_a_row_is_a_problem():
    assert has(check([row(text="a b <!-- c d")]), "hidden markup")
    assert has(check([row(text="a b <DETAILS> c")]), "hidden markup")


def test_a_control_character_in_a_row_is_a_problem():
    assert has(check([row(text="a b\x07 c d")]), "hidden markup")
    assert has(check([row(text="a b ‮ c d")]), "hidden markup")


def test_a_mention_is_a_problem():
    assert has(check([row(text="ask @someone about it")]), "a mention")


def test_a_role_source_is_accepted():
    assert check([row(source="code-reviewer@dod")]) == []
    assert check([row(source="code-reviewer@implement_final")]) == []


@pytest.mark.parametrize("kw", [{"source": "random"}, {"loc": "a b.py"}, {"text": "two words"}])
def test_a_bad_field_is_a_problem(kw):
    assert has(check([row(**kw)]), "row 1")


def test_a_two_word_text_is_a_problem():
    assert check([row(text="two words")]) == ["row 1: the text needs at least 3 words"]


def test_a_bad_id_is_a_problem():
    assert has(check([row()[:2] + "G1" + row()[4:]]), "the id must be F<digits>")


def test_a_text_with_the_separator_is_accepted():
    assert check([row(text="a b · c d")]) == []


def test_a_line_without_the_dash_is_a_problem():
    assert has(check(["F1 · final-review · a.py:1 · a b c · fixed abc1234"]), "starts with '- '")


def test_one_valid_section_of_two_rows():
    assert check([row(1), "", row(2, status="declined: not worth the risk")], 2) == []
