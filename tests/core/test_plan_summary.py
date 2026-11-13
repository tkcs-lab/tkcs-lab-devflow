"""tld plan summary-check (src/tld/plan/summary.py): placement, labels, words and echoed text."""
import os
import subprocess
import sys
import time

import pytest

from conftest import ROOT, tld_cmd
from tld.plan import summary

PLAN_BODY = "**Use it:** a b c\n**Scope:** a b c\n**Review focus:** a b c"
PR_BODY = "**Deviations:** None.\n**Review focus:** a b c"
PLAN_BASE, PR_BASE = 15, 8  # words of the minimal Summary section, heading included


def pad(n):
    return " ".join(["w"] * n)


def padded(body, base, total):
    return f"{body} {pad(total - base)}" if total > base else body


def plan_summary(total=PLAN_BASE, extra=""):
    return f"## Summary\n\n{padded(PLAN_BODY, PLAN_BASE, total)}\n{extra}"


def plan_doc(total=PLAN_BASE, extra=""):
    return "# Title\n\n" + plan_summary(total, extra) + "\n## 1. Goal\n\nmore words here\n"


def issue_doc(total=PLAN_BASE):
    return "## Request\n\nthe ask\n\n" + plan_summary(total) + "\n## Goal\n\nmore\n"


def pr_summary(total=PR_BASE):
    return f"## Summary\n\n{padded(PR_BODY, PR_BASE, total)}\n"


def pr_doc(total=PR_BASE):
    return "Closes #1\n\n" + pr_summary(total) + "\n## Details\n\nmore\n"


DOCS = {"plan": plan_doc, "issue": issue_doc, "pr": pr_doc}
LIMITS = {"plan": 350, "issue": 350, "pr": 175}


def probs(text, kind="plan", deviations=None):
    return summary.check(text, kind, deviations)[0]


def run(tmp_path, capsys, text, *args, kind="plan", raw=None):
    path = tmp_path / "doc.md"
    path.write_bytes(raw if raw is not None else text.encode())
    code = summary.main([str(path), "--kind", kind, *args])
    return code, capsys.readouterr().out, str(path)


# --- constants -------------------------------------------------------------------------------------------------

def test_constants_match_the_design():
    assert summary.KINDS == ("plan", "issue", "pr")
    assert summary.MAX_WORDS == LIMITS
    assert summary.ORDER["plan"] == ("Use it", "Scope", "Security", "Performance", "Review focus")
    assert summary.ORDER["issue"] == summary.ORDER["plan"]
    assert summary.ORDER["pr"] == ("Deviations", "Scope", "Security", "Performance", "Review focus")
    assert summary.REQUIRED["plan"] == ("Use it", "Scope", "Review focus")
    assert summary.REQUIRED["issue"] == summary.REQUIRED["plan"]
    assert summary.REQUIRED["pr"] == ("Deviations", "Review focus")
    assert summary.NONE_OK == ("Deviations", "Security", "Performance")
    assert summary.TEXT_MAX == 80


def test_the_minimal_documents_are_valid_and_have_the_assumed_size():
    assert summary.check(plan_doc(), "plan") == ([], PLAN_BASE)
    assert summary.check(issue_doc(), "issue") == ([], PLAN_BASE)
    assert summary.check(pr_doc(), "pr") == ([], PR_BASE)


# --- words -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", summary.KINDS)
def test_exactly_the_limit_is_ok_and_one_more_fails(kind):
    limit = LIMITS[kind]
    assert summary.check(DOCS[kind](limit), kind) == ([], limit)
    assert summary.check(DOCS[kind](limit + 1), kind) == (
        [f"{limit + 1} words, the limit for {kind} is {limit}"], limit + 1)


def test_the_heading_is_counted():
    # 349 words below the heading plus the heading make 350 and pass; 350 plus the heading make 351 and fail.
    assert summary.check(plan_doc(350), "plan")[1] == 350
    assert probs(plan_doc(351)) == ["351 words, the limit for plan is 350"]
    assert summary.check(plan_doc(PLAN_BASE), "plan")[1] == PLAN_BASE


def test_the_count_stops_at_the_next_section():
    assert summary.check(plan_doc() + pad(1000), "plan") == ([], PLAN_BASE)


def test_a_200_word_summary_passes_for_plan_and_fails_for_pr():
    assert summary.check(plan_doc(200), "plan") == ([], 200)
    assert summary.check(pr_doc(200), "pr") == (["200 words, the limit for pr is 175"], 200)


def test_marks_without_letters_or_digits_are_not_words():
    extra = "| --- | --- |\n**\n---\n"
    assert summary.check(plan_doc(extra=extra), "plan") == ([], PLAN_BASE)


def test_underscores_and_unicode_letters_are_words():
    assert summary.check(plan_doc(extra="_ é 中\n"), "plan")[1] == PLAN_BASE + 3


# --- fences, quotes, sub-headings -------------------------------------------------------------------------------

def test_a_fenced_summary_heading_is_not_a_duplicate():
    assert summary.check(plan_doc(extra="```\n## Summary\n```\n"), "plan") == ([], PLAN_BASE + 1)
    assert probs("# T\n\n" + plan_summary() + "\n## Goal\n\n```\n## Summary\n```\n") == []


def test_a_fenced_heading_inside_the_summary_does_not_end_it_and_its_words_count():
    assert summary.check(plan_doc(extra="```\n## x one two three\n```\n"), "plan") == ([], PLAN_BASE + 4)


def test_a_sub_heading_stays_inside_the_summary_and_its_words_count():
    assert summary.check(plan_doc(extra="### sub heading words\n"), "plan") == ([], PLAN_BASE + 3)


def test_an_unclosed_fence_runs_to_the_end_of_the_file():
    text = plan_doc(extra="```\nopen\n") + "```\n"
    assert probs(plan_doc() + "```\n## Summary\n") == []
    assert probs(text) == []


@pytest.mark.parametrize("fence", [
    "```\n**Use it:** a b c\n```",
    "~~~\n**Use it:** a b c\n~~~",
    "~~~\n```\n**Use it:** a b c\n~~~",
    "````\n```\n**Use it:** a b c\n````",
    "   ```python\n**Use it:** a b c\n   ```",
])
def test_a_label_inside_a_fence_is_not_a_label(fence):
    text = f"## Summary\n\n**Scope:** a b c\n**Review focus:** a b c\n{fence}\n\n## Goal\n"
    assert probs(text) == ["missing label 'Use it'"]


def test_a_fence_with_four_leading_spaces_is_not_a_fence():
    text = plan_doc(extra="    ```\n**Use it:** a b c\n")
    assert probs(text) == ["duplicate label 'Use it'"]


def test_a_quoted_label_and_a_quoted_heading_are_ignored():
    text = "## Summary\n\n**Scope:** a b c\n**Review focus:** a b c\n> **Use it:** a b c\n  > ## Summary\n"
    assert probs(text) == ["missing label 'Use it'"]


def test_a_quoted_heading_in_the_request_is_ignored():
    text = "## Request\n\n> ## Goal\n> ## Summary\n> fake\n\n" + plan_summary()
    assert summary.check(text, "issue") == ([], PLAN_BASE)


# --- reading ---------------------------------------------------------------------------------------------------

def test_crlf_gives_the_same_result_as_lf():
    lf = plan_doc().replace("# Title", "prose here")
    expected = ["text before '## Summary' is not allowed: 'prose here'"]
    assert probs(lf) == expected
    assert probs(lf.replace("\n", "\r\n")) == expected
    assert summary.check(plan_doc().replace("\n", "\r\n"), "plan") == summary.check(plan_doc(), "plan")


def test_a_bom_before_the_first_heading_is_ignored():
    assert summary.check("﻿" + plan_doc(), "plan") == ([], PLAN_BASE)
    assert summary.check("﻿" + pr_doc(), "pr") == ([], PR_BASE)
    assert summary.check("﻿" + issue_doc(), "issue") == ([], PLAN_BASE)


def test_a_bom_in_a_file_is_ignored(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, "", raw=b"\xef\xbb\xbf" + plan_doc().encode())
    assert (code, out) == (0, f"summary: OK ({PLAN_BASE} words)\n")


def test_a_missing_file_is_reported_without_a_traceback(tmp_path, capsys):
    path = str(tmp_path / "nope.md")
    assert summary.main([path, "--kind", "plan"]) == 1
    assert capsys.readouterr().out == f"summary: cannot read '{path}': No such file or directory\n"


def test_a_directory_is_reported_without_a_traceback(tmp_path, capsys):
    assert summary.main([str(tmp_path), "--kind", "plan"]) == 1
    assert capsys.readouterr().out == f"summary: cannot read '{tmp_path}': Is a directory\n"


def test_bytes_that_are_not_utf8_are_reported(tmp_path, capsys):
    code, out, path = run(tmp_path, capsys, "", raw=b"## Summary\n\xff\xfe\n")
    assert (code, out) == (1, f"summary: cannot read '{path}': not valid UTF-8\n")


def test_a_file_over_a_megabyte_is_refused(tmp_path, capsys):
    big = plan_doc().encode() + b"x" * (1000000 - len(plan_doc()) + 1)
    assert len(big) == 1000001
    code, out, path = run(tmp_path, capsys, "", raw=big)
    assert (code, out) == (1, f"summary: cannot read '{path}': larger than 1000000 bytes\n")


def test_a_file_of_exactly_a_megabyte_is_read(tmp_path, capsys):
    text = plan_doc() + "x" * (1000000 - len(plan_doc()))
    assert len(text.encode()) == 1000000
    code, out, _ = run(tmp_path, capsys, text)
    assert (code, out) == (0, f"summary: OK ({PLAN_BASE} words)\n")


def test_an_unreadable_deviations_file_is_reported(tmp_path, capsys):
    gone = str(tmp_path / "gone.md")
    code, out, _ = run(tmp_path, capsys, pr_doc(), "--deviations", gone, kind="pr")
    assert (code, out) == (1, f"summary: cannot read '{gone}': No such file or directory\n")


def test_the_path_in_a_read_error_is_sanitised(tmp_path, capsys):
    assert summary.main([str(tmp_path / "a\x1bb"), "--kind", "plan"]) == 1
    assert capsys.readouterr().out == f"summary: cannot read '{tmp_path}/a?b': No such file or directory\n"


# --- headings --------------------------------------------------------------------------------------------------

def test_no_summary_heading():
    assert probs("# Title\n\n## Goal\n\ntext\n") == ["no '## Summary' section"]
    assert probs("") == ["no '## Summary' section"]


@pytest.mark.parametrize("heading", ["##Summary", "### Summary", "#  Summary", " ## Summary"])
def test_a_line_that_is_not_a_level_two_heading_is_no_heading(heading):
    assert probs(f"{heading}\n\n{PLAN_BODY}\n") == ["no '## Summary' section"]


@pytest.mark.parametrize("heading,found", [
    ("## summary", "summary"), ("## SUMMARY", "SUMMARY"), ("## Summary of x", "Summary of x"),
    ("## Executive summary", "Executive summary"), ("## Summary:", "Summary:"),
])
def test_a_near_miss_heading_is_named_and_stops_the_check(heading, found):
    text = f"{heading}\n\n{PLAN_BODY}\n"
    assert probs(text) == [f"the heading must be exactly '## Summary' (found '{found}')"]


def test_a_near_miss_next_to_an_exact_heading_is_named_and_the_check_goes_on():
    text = plan_doc() + "\n## Summary of changes\n\ntext\n"
    assert probs(text) == ["the heading must be exactly '## Summary' (found 'Summary of changes')"]


def test_the_echoed_heading_text_is_sanitised_and_cut():
    text = "## summary\x1b‮" + "n" * 200 + "\n"
    assert probs(text) == ["the heading must be exactly '## Summary' (found 'summary??" + "n" * 71 + "')"]


def test_trailing_spaces_after_the_heading_are_accepted():
    assert probs(plan_doc().replace("## Summary", "## Summary   ")) == []


def test_two_summary_headings_fail():
    assert probs(plan_doc() + "\n## Summary\n\n" + PLAN_BODY + "\n") == ["2 '## Summary' sections"]
    assert probs(plan_doc() + "\n## Summary\n\na\n\n## Summary\n") == ["3 '## Summary' sections"]


# --- placement -------------------------------------------------------------------------------------------------

def test_summary_after_another_section_fails_placement():
    text = "# Title\n\n## Goal\n\ntext\n\n" + plan_summary()
    assert probs(text) == ["'## Summary' must be the first '## ' section"]
    assert probs("## Goal\n\n" + pr_summary(), "pr") == ["'## Summary' must be the first '## ' section"]


def test_a_title_a_quote_and_blank_lines_may_come_before_a_plan_summary():
    text = "\n# Title\n\n> Historical record.\n> more\n\n" + plan_summary()
    assert summary.check(text, "plan") == ([], PLAN_BASE)
    assert summary.check(plan_summary(), "plan") == ([], PLAN_BASE)


def test_prose_before_a_plan_summary_fails():
    assert probs("# T\n\nsome prose\n\n" + plan_summary()) == [
        "text before '## Summary' is not allowed: 'some prose'"]


def test_a_second_title_before_a_plan_summary_fails():
    assert probs("# A\n# B\n\n" + plan_summary()) == ["text before '## Summary' is not allowed: '# B'"]


def test_a_fence_before_a_plan_summary_fails():
    assert probs("```\ncode\n```\n" + plan_summary()) == ["text before '## Summary' is not allowed: '```'"]


def test_closes_lines_may_come_before_a_pr_summary():
    text = "Closes #1\n\nfixes #22.\nRESOLVES #3\n  Closes #4  \n\n" + pr_summary()
    assert summary.check(text, "pr") == ([], PR_BASE)
    assert summary.check(pr_summary(), "pr") == ([], PR_BASE)


@pytest.mark.parametrize("line", ["Hello", "Closes #x", "Closes #1 and more", "Closes 1", "# Title", "Closes #1,#2"])
def test_other_text_before_a_pr_summary_fails(line):
    assert probs(f"Closes #1\n{line}\n\n" + pr_summary(), "pr") == [
        f"text before '## Summary' is not allowed: '{line}'"]


def test_an_issue_has_request_then_summary():
    assert summary.check(issue_doc(), "issue") == ([], PLAN_BASE)
    assert summary.check("\n\n" + issue_doc(), "issue") == ([], PLAN_BASE)


@pytest.mark.parametrize("text", [
    "## Request\n\nask\n\n## Goal\n\nx\n\n{S}",
    "{S}",
    "## Goal\n\nx\n\n{S}",
    "## request\n\nask\n\n{S}",
])
def test_an_issue_summary_must_come_right_after_the_request(text):
    assert probs(text.replace("{S}", plan_summary()), "issue") == ["'## Summary' must come right after '## Request'"]


def test_text_before_the_request_of_an_issue_fails():
    assert probs("junk\n" + issue_doc(), "issue") == ["text before '## Summary' is not allowed: 'junk'"]


def test_the_request_exception_is_for_the_issue_kind_only():
    assert probs(issue_doc(), "plan") == ["'## Summary' must be the first '## ' section"]
    assert probs(issue_doc(), "pr")[0] == "'## Summary' must be the first '## ' section"


# --- labels ----------------------------------------------------------------------------------------------------

def test_an_empty_summary_lists_every_missing_required_label():
    assert probs("## Summary\n", "plan") == [
        "missing label 'Use it'", "missing label 'Scope'", "missing label 'Review focus'"]
    assert probs("## Request\n\n## Summary\n", "issue") == probs("## Summary\n", "plan")
    assert probs("## Summary\n", "pr") == ["missing label 'Deviations'", "missing label 'Review focus'"]


def test_a_duplicate_label_is_reported_once():
    text = plan_doc(extra="**Scope:** d e f\n**Scope:** g h i\n")
    assert probs(text) == ["duplicate label 'Scope'"]


def test_a_wrong_case_label_is_unknown_and_the_right_one_is_missing():
    text = plan_doc().replace("**Use it:**", "**use it:**")
    assert probs(text) == ["unknown label 'use it'", "missing label 'Use it'"]


def test_an_unknown_label_is_reported_once_per_name():
    text = plan_doc(extra="**Extra:** a b c\n**Extra:** d e f\n")
    assert probs(text) == ["unknown label 'Extra'"]


def test_dash_labels_are_accepted():
    text = plan_doc().replace("**Use it:**", "- **Use it:**")
    assert probs(text) == []


@pytest.mark.parametrize("line", ["**Use it**: x y z", "  **Use it:** x y z", "* **Use it:** x y z",
                                  "**Use it:x y z", "** :** x y z", "**:** x y z", "**a*b:** x y z",
                                  "**Use it:", "-**Use it:** x y z"])
def test_other_forms_are_not_labels(line):
    text = f"## Summary\n\n{line}\n**Scope:** a b c\n**Review focus:** a b c\n"
    assert probs(text) == ["missing label 'Use it'", "text before the first label"]


def test_a_label_without_a_value_fails():
    text = plan_doc().replace("**Use it:** a b c", "**Use it:**")
    assert probs(text) == ["label 'Use it' needs at least 3 words"]


def test_a_value_may_continue_on_the_following_lines():
    text = plan_doc().replace("**Use it:** a b c", "**Use it:**\nfirst second\nthird")
    assert probs(text) == []
    assert probs(plan_doc().replace("**Use it:** a b c", "**Use it:** a\nb"))== ["label 'Use it' needs at least 3 words"]


def test_deviations_is_not_a_plan_label_and_use_it_is_not_a_pr_label():
    assert probs(plan_doc(extra="**Deviations:** None.\n")) == ["unknown label 'Deviations'"]
    assert probs(pr_doc().replace("**Deviations:** None.", "**Use it:** a b c\n**Deviations:** None."), "pr") == [
        "unknown label 'Use it'"]


def test_security_and_performance_are_accepted_in_plan_issue_and_pr():
    plan = plan_doc().replace("**Review focus:**", "**Security:** None.\n**Performance:** None.\n**Review focus:**")
    assert probs(plan) == []
    issue = issue_doc().replace("**Review focus:**", "**Security:** a b c\n**Performance:** a b c\n**Review focus:**")
    assert probs(issue, "issue") == []
    pr = pr_doc().replace("**Review focus:**", "**Security:** a b c\n**Performance:** None.\n**Review focus:**")
    assert probs(pr, "pr") == []


def test_scope_is_optional_in_a_pr_and_required_in_a_plan():
    assert probs(pr_doc().replace("**Review focus:**", "**Scope:** a b c\n**Review focus:**"), "pr") == []
    assert probs(pr_doc(), "pr") == []
    assert probs(plan_doc().replace("**Scope:** a b c\n", "")) == ["missing label 'Scope'"]


def test_a_pr_label_order_is_deviations_scope_security_performance_review_focus():
    text = ("## Summary\n\n**Deviations:** a b c\n**Scope:** a b c\n**Security:** a b c\n"
            "**Performance:** a b c\n**Review focus:** a b c\n")
    assert probs(text, "pr") == []


def test_a_label_out_of_order_is_named():
    text = plan_doc().replace("**Use it:** a b c\n**Scope:** a b c", "**Scope:** a b c\n**Use it:** a b c")
    assert probs(text) == ["label 'Use it' is out of order"]
    text = "## Summary\n\n**Use it:** a b c\n**Scope:** a b c\n**Review focus:** a b c\n**Security:** a b c\n"
    assert probs(text) == ["label 'Security' is out of order"]


def test_a_one_line_summary_with_labels_in_the_middle_fails_on_the_missing_labels():
    text = "## Summary\n\nintro **Use it:** a b c **Scope:** a b c **Review focus:** a b c\n"
    assert probs(text) == ["missing label 'Use it'", "missing label 'Scope'", "missing label 'Review focus'",
                           "text before the first label"]


def test_text_before_the_first_label_is_reported_once():
    text = plan_doc().replace("## Summary\n\n", "## Summary\n\nintro line\nsecond line\n\n")
    assert probs(text) == ["text before the first label"]
    fenced = plan_doc().replace("## Summary\n\n", "## Summary\n\n```\ncode\n```\n")
    assert probs(fenced) == ["text before the first label"]


# --- values ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["None.", "none", "NONE.", " None. ", "None"])
def test_none_is_accepted_for_deviations_security_and_performance(value):
    assert probs(pr_doc().replace("**Deviations:** None.", f"**Deviations:** {value}"), "pr") == []
    for name in ("Security", "Performance"):
        assert probs(plan_doc().replace("**Review focus:**", f"**{name}:** {value}\n**Review focus:**")) == []
        assert probs(pr_doc().replace("**Review focus:**", f"**{name}:** {value}\n**Review focus:**"), "pr") == []


def test_none_is_rejected_for_the_other_labels():
    scope = plan_doc().replace("**Scope:** a b c", "**Scope:** None.")
    assert probs(scope) == ["label 'Scope' needs at least 3 words", "label 'Scope' cannot be 'None.'"]
    use = plan_doc().replace("**Use it:** a b c", "**Use it:** none")
    assert probs(use) == ["label 'Use it' needs at least 3 words", "label 'Use it' cannot be 'None.'"]
    focus = pr_doc().replace("**Review focus:** a b c", "**Review focus:** None.")
    assert probs(focus, "pr") == ["label 'Review focus' needs at least 3 words",
                                  "label 'Review focus' cannot be 'None.'"]


def test_none_with_more_words_is_just_text():
    text = pr_doc().replace("**Deviations:** None.", "**Deviations:** None. but a b")
    assert probs(text, "pr") == []
    short = pr_doc().replace("**Deviations:** None.", "**Deviations:** Nothing")
    assert probs(short, "pr") == ["label 'Deviations' needs at least 3 words"]


@pytest.mark.parametrize("value", ["TBD", "tbd.", "TODO", "n/a", "N/A.", "see below", "See Below.", "...", "<x>",
                                   "<fill this in later>"])
def test_placeholders_are_rejected_with_one_line(value):
    text = plan_doc().replace("**Scope:** a b c", f"**Scope:** {value}")
    assert probs(text) == ["label 'Scope' is a placeholder"]


def test_a_placeholder_for_a_label_that_allows_none_is_still_a_placeholder():
    text = pr_doc().replace("**Deviations:** None.", "**Deviations:** TBD")
    assert probs(text, "pr") == ["label 'Deviations' is a placeholder"]


@pytest.mark.parametrize("value", ["<a> <b> <c>", "<a b c", "a <b> c", "<a>b> c d", "tbd now ok"])
def test_values_that_only_look_like_placeholders_are_text(value):
    text = plan_doc().replace("**Scope:** a b c", f"**Scope:** {value}")
    assert probs(text) == []


@pytest.mark.parametrize("markup", ["<!-- hidden -->", "<details>", "<DETAILS open>", "<Details>"])
def test_hidden_markup_is_rejected(markup):
    for where in ("**Review focus:** a b c " + markup, "**Review focus:** a b c\n" + markup,
                  "**Review focus:** a b c\n```\n" + markup + "\n```", "**Review focus:** a b c\n> " + markup):
        text = plan_doc().replace("**Review focus:** a b c", where)
        assert probs(text) == ["the Summary holds hidden markup (an HTML comment or a details block)"], where


def test_hidden_markup_after_the_summary_is_not_in_the_summary():
    assert probs(plan_doc() + "\n<!-- note -->\n<details>\n") == []


# --- deviations file -------------------------------------------------------------------------------------------

BULLETS = "# Deviations: x\n\n## p1\n\n- worker: did a thing\n\n## Final review\n\n- pending\n"


def test_none_over_a_non_empty_deviations_file_fails():
    assert probs(pr_doc(), "pr", BULLETS) == [
        "Deviations says None. but the deviations file records 1 deviations"]
    two = BULLETS + "- review: second\n- None.\n"
    assert probs(pr_doc(), "pr", two) == ["Deviations says None. but the deviations file records 2 deviations"]


def test_none_over_a_deviations_file_with_only_none_and_pending_passes():
    assert probs(pr_doc(), "pr", "## p1\n\n- None.\n\n## Final review\n\n- pending\n") == []
    assert probs(pr_doc(), "pr", "") == []
    assert probs(pr_doc(), "pr", "-not a bullet\nnote - x\n  - indented\n") == []


def test_a_crlf_deviations_file_is_read_like_lf():
    assert probs(pr_doc(), "pr", BULLETS.replace("\n", "\r\n")) == [
        "Deviations says None. but the deviations file records 1 deviations"]
    assert probs(pr_doc(), "pr", "- None.\r\n- pending\r\n") == []


def test_deviations_with_text_over_a_deviations_file_passes():
    text = pr_doc().replace("**Deviations:** None.", "**Deviations:** the design changed here")
    assert probs(text, "pr", BULLETS) == []


def test_the_deviations_file_is_not_looked_at_without_the_option():
    assert probs(pr_doc(), "pr") == []


def test_the_deviations_line_comes_after_the_word_count():
    problems = probs(pr_doc(200), "pr", BULLETS)
    assert problems == ["200 words, the limit for pr is 175",
                        "Deviations says None. but the deviations file records 1 deviations"]


def test_main_checks_the_deviations_file(tmp_path, capsys):
    dev = tmp_path / "dev.md"
    dev.write_text(BULLETS)
    code, out, _ = run(tmp_path, capsys, pr_doc(), "--deviations", str(dev), kind="pr")
    assert (code, out) == (1, "summary: Deviations says None. but the deviations file records 1 deviations\n")
    dev.write_text("- None.\n")
    code, out, _ = run(tmp_path, capsys, pr_doc(), "--deviations", str(dev), kind="pr")
    assert (code, out) == (0, f"summary: OK ({PR_BASE} words)\n")


@pytest.mark.parametrize("kind", ["plan", "issue"])
def test_deviations_is_only_for_the_pr_kind(tmp_path, capsys, kind):
    path = tmp_path / "doc.md"
    path.write_text(plan_doc())
    with pytest.raises(SystemExit) as exc:
        summary.main([str(path), "--kind", kind, "--deviations", str(path)])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


# --- sanitising and speed --------------------------------------------------------------------------------------

def test_clean_replaces_control_format_surrogate_private_and_separator_characters():
    assert summary.clean("a\x1b\x85‮​  \ud800z") == "a" + "?" * 8 + "z"
    assert summary.clean("é 中 – x") == "é 中 – x"
    assert summary.clean("x" * 500) == "x" * 80


def test_an_echoed_unknown_label_is_sanitised():
    text = plan_doc(extra="**Bad\x1b\x85‮​:** x y z\n")
    assert probs(text) == ["unknown label 'Bad????'"]


def test_a_long_unknown_label_is_echoed_at_text_max():
    text = plan_doc(extra="**" + "N" * 2000 + ":** x y z\n")
    assert probs(text) == ["unknown label '" + "N" * summary.TEXT_MAX + "'"]


def test_an_offending_line_is_sanitised_and_cut():
    text = "pro\x1bse " + "p" * 300 + "\n\n" + plan_summary()
    assert probs(text) == ["text before '## Summary' is not allowed: 'pro?se " + "p" * 73 + "'"]


@pytest.mark.parametrize("line", ["x" * 200000, "`" * 200000, "*" * 200000, "**" + "a" * 200000, "> " * 100000,
                                  " " * 200000 + "x", "- " * 100000, "~" * 200000 + " tail",
                                  "Closes #" + "1" * 200000, "#" * 200000, "## " + "s" * 200000,
                                  "**" + "a" * 100000 + ":**" * 30000])
@pytest.mark.parametrize("where", ["before", "inside"])
def test_a_very_long_line_is_checked_quickly(line, where):
    text = line + "\n" + plan_doc() if where == "before" else plan_doc(extra=line + "\n")
    start = time.monotonic()
    summary.check(text, "plan")
    summary.check(text, "pr")
    summary.check(text, "issue")
    assert time.monotonic() - start < 5


# --- the order of the problems ---------------------------------------------------------------------------------

def test_placement_label_and_word_problems_come_in_the_order_of_the_design():
    text = ("## Goal\n\n## Summary\n\n**Use it:** a b\n**Bogus:** x\n**Scope:** " + pad(343) + " <!--\n")
    assert summary.check(text, "plan") == ([
        "'## Summary' must be the first '## ' section",
        "unknown label 'Bogus'",
        "missing label 'Review focus'",
        "label 'Use it' needs at least 3 words",
        "the Summary holds hidden markup (an HTML comment or a details block)",
        "351 words, the limit for plan is 350",
    ], 351)


def test_labels_order_is_unknown_duplicate_missing_then_out_of_order():
    text = ("## Summary\n\n**Scope:** a b c\n**Zed:** a b c\n**Scope:** a b c\n**Use it:** a b c\n")
    assert probs(text) == ["unknown label 'Zed'", "duplicate label 'Scope'", "missing label 'Review focus'",
                           "label 'Use it' is out of order"]


# --- the command -----------------------------------------------------------------------------------------------

def test_cli_a_valid_file_prints_ok(tmp_path):
    path = tmp_path / "plan.md"
    path.write_text(plan_doc())
    r = subprocess.run(tld_cmd("plan", "summary-check", str(path), "--kind", "plan"), capture_output=True, text=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, f"summary: OK ({PLAN_BASE} words)\n", "")


def test_cli_an_invalid_file_prints_every_problem(tmp_path):
    path = tmp_path / "pr.md"
    path.write_text("Hello\n\n" + pr_summary(201).replace("**Review focus:**", "**Bad:**"))
    r = subprocess.run(tld_cmd("plan", "summary-check", str(path), "--kind", "pr"), capture_output=True, text=True)
    assert r.returncode == 1
    assert r.stdout == ("summary: text before '## Summary' is not allowed: 'Hello'\n"
                        "summary: unknown label 'Bad'\n"
                        "summary: missing label 'Review focus'\n"
                        "summary: 200 words, the limit for pr is 175\n")
    assert r.stderr == ""


def test_cli_deviations_through_the_script(tmp_path):
    path, dev = tmp_path / "pr.md", tmp_path / "dev.md"
    path.write_text(pr_doc())
    dev.write_text(BULLETS)
    r = subprocess.run(tld_cmd("plan", "summary-check", str(path), "--kind", "pr", "--deviations", str(dev)),
                       capture_output=True, text=True)
    assert (r.returncode, r.stdout) == (1, "summary: Deviations says None. but the deviations file records 1 deviations\n")


def test_cli_a_missing_file_and_bad_bytes_give_one_line_and_no_traceback(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe")
    for path, reason in ((tmp_path / "gone.md", "No such file or directory"), (bad, "not valid UTF-8")):
        r = subprocess.run(tld_cmd("plan", "summary-check", str(path), "--kind", "plan"), capture_output=True, text=True)
        assert (r.returncode, r.stdout) == (1, f"summary: cannot read '{path}': {reason}\n")
        assert "Traceback" not in r.stderr


@pytest.mark.parametrize("args", [["{f}"], ["{f}", "--kind", "prr"], ["--kind", "plan"], []])
def test_cli_usage_errors_exit_2(tmp_path, args):
    path = tmp_path / "plan.md"
    path.write_text(plan_doc())
    argv = [a.replace("{f}", str(path)) for a in args]
    r = subprocess.run(tld_cmd("plan", "summary-check", *argv), capture_output=True, text=True)
    assert r.returncode == 2 and r.stdout == "" and "Traceback" not in r.stderr


def test_cli_help_lists_the_options():
    r = subprocess.run(tld_cmd("plan", "summary-check", "--help"), capture_output=True, text=True)
    assert r.returncode == 0
    assert "--kind" in r.stdout and "{plan,issue,pr}" in r.stdout and "--deviations" in r.stdout


def test_the_command_is_registered_in_the_cli():
    from tld import cli
    assert cli.COMMANDS[("plan", "summary-check")][0] == "tld.plan.summary"


def test_the_script_runs_as_a_module(tmp_path):
    path = tmp_path / "plan.md"
    path.write_text(plan_doc())
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])}
    r = subprocess.run([sys.executable, "-m", "tld.plan.summary", str(path), "--kind", "plan"],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    assert (r.returncode, r.stdout) == (0, f"summary: OK ({PLAN_BASE} words)\n"), r.stderr
