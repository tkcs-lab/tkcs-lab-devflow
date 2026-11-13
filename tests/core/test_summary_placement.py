"""The playbooks call `tld plan summary-check` in the right places, with kinds and limits the command knows."""
import re
import subprocess

import pytest

import test_contracts
from conftest import ROOT, tld_cmd
from test_contracts import tld_calls
from tld.plan import summary

MAKE_PLAN = ROOT / "playbooks" / "make-plan.md"
IMPLEMENT = ROOT / "playbooks" / "implement.md"

PLAN_DOC = """# Title

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Type the command and read the result.

**Scope:** The command is added and nothing else changes.

**Review focus:** Section 3 holds the riskiest decisions.

## Goal

Text.
"""
ISSUE_DOC = """## Request

Please do it.

## Summary

**Use it:** Type the command and read the result.

**Scope:** The command is added and nothing else changes.

**Review focus:** Section 3 holds the riskiest decisions.

## Goal

Text.
"""
PR_DOC = """Closes #36

## Summary

**Deviations:** None.

**Review focus:** Read the changed playbooks first.

## Phases

- p1-summary-check: merged abc1234

**Acceptance:**

- [x] The check passes.

**Final review:** approve. Non-blocking findings: none.

## Scope

Text.

## Deviations

DEVIATIONS_BODY

## Manual verification

- [ ] Nothing to do.
"""
DEVIATIONS = "# Deviations\n\n- None.\n"
FIXTURES = {"plan": PLAN_DOC, "issue": ISSUE_DOC, "pr": PR_DOC.replace("DEVIATIONS_BODY", "- None.")}


def summary_calls(path):
    """The `tld plan summary-check` calls of a playbook, each with its `--kind` value (None when it has none)."""
    out = []
    for _, group, command, rest in tld_calls(path):
        if group == "plan" and command == "summary-check":
            m = re.search(r"--kind (\S+)", rest)
            out.append((m.group(1) if m else None, rest))
    return out


def section(text, heading):
    """The text from a `## ` heading line starting with `heading` to the next `## ` line."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def check_kinds(path):
    """Every kind in a playbook's calls, each one a kind the command knows."""
    kinds = [k for k, _ in summary_calls(path)]
    assert None not in kinds, f"{path}: a summary-check call has no --kind"
    unknown = sorted(set(kinds) - set(summary.KINDS))
    assert not unknown, f"{path}: unknown kind {unknown}"
    return set(kinds)


def test_make_plan_calls_the_check_for_plan_issue_and_pr():
    assert check_kinds(MAKE_PLAN) == {"plan", "issue", "pr"}


def test_implement_calls_the_check_once_for_pr_with_deviations():
    calls = summary_calls(IMPLEMENT)
    assert [k for k, _ in calls] == ["pr"]
    assert "--deviations" in calls[0][1]


def test_the_helper_rejects_an_unknown_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(test_contracts, "ROOT", tmp_path)
    bad = tmp_path / "bad.md"
    bad.write_text("Run `tld plan summary-check <body file> --kind prr` first.\n")
    with pytest.raises(AssertionError, match="unknown kind"):
        check_kinds(bad)


@pytest.mark.parametrize("path", [MAKE_PLAN, IMPLEMENT], ids=lambda p: p.name)
def test_every_call_passes_on_a_valid_fixture(path, tmp_path):
    calls = summary_calls(path)
    assert calls
    for n, (kind, rest) in enumerate(calls):
        doc = tmp_path / f"doc{n}.md"
        doc.write_text(FIXTURES[kind])
        dev = tmp_path / f"dev{n}.md"
        dev.write_text(DEVIATIONS)
        files = iter([str(doc), str(dev)])
        argv = [re.sub(r"^X$", lambda _: next(files), tok) for tok in rest.split()]
        r = subprocess.run(tld_cmd("plan", "summary-check", *argv), capture_output=True, text=True, timeout=60)
        assert (r.returncode, r.stdout.startswith("summary: OK")) == (0, True), r.stdout + r.stderr


def test_implement_checks_before_the_pull_request_is_created():
    text = section(IMPLEMENT.read_text(), "## 6. Finishing")
    assert 0 <= text.index("summary-check") < text.index("github.pr_create")


def test_make_plan_checks_the_plan_before_validate_manifest():
    text = section(MAKE_PLAN.read_text(), "## 4. Review before you push")
    review = text.index("run_helper(")
    check = text.index("tld plan summary-check")
    assert "--kind plan" in text[check:check + 80]
    assert review < check < text.index("tld plan validate-manifest <plan file> --profile")


def test_make_plan_checks_the_issue_body_before_it_is_updated():
    text = section(MAKE_PLAN.read_text(), "## 5. Commit, push and hand over")
    check = text.index("tld plan summary-check")
    assert "--kind issue" in text[check:check + 80]
    assert check < text.index("github.issue_update")


def test_small_scope_checks_the_issue_body_and_the_pull_request_body():
    text = section(MAKE_PLAN.read_text(), "## Small scope")
    issue = text.index("summary-check <issue body file> --kind issue")
    assert issue < text.index("github.issue_update")
    assert text.index("summary-check <body file> --kind pr") < text.index("github.pr_create")


def test_the_playbooks_state_the_limits_and_labels_of_the_command():
    make_plan, implement = MAKE_PLAN.read_text(), IMPLEMENT.read_text()
    for label in {*summary.ORDER["plan"], *summary.ORDER["pr"]}:
        assert f"**{label}:**" in make_plan, label
    assert str(summary.MAX_WORDS["plan"]) in make_plan
    assert str(summary.MAX_WORDS["pr"]) in make_plan
    assert re.search(r"\b175\b[^\n]*Summary|Summary[^\n]*\b175\b", implement)


REAL_DOC = PR_DOC.replace("**Deviations:** None.", "**Deviations:** The summary check was reworked after a retry, and the final review found two placement problems in the body steps.")


def demote(text):
    """The deviations file as step 6.3 pastes it: `#`/`##` headings become `###`/`####`."""
    return re.sub(r"^(#{1,2}) ", lambda m: "##" + m.group(1) + " ", text, flags=re.M)


def test_implement_says_to_demote_the_pasted_deviations_headings():
    text = section(IMPLEMENT.read_text(), "## 6. Finishing")
    assert "###" in text and "####" in text


def test_implement_gives_the_phase_list_its_own_heading():
    assert "`## Phases`" in section(IMPLEMENT.read_text(), "## 6. Finishing")


def test_the_real_deviations_file_pasted_as_step_6_3_says_passes(tmp_path):
    dev = ROOT / "docs" / "plans" / "36" / "deviations.md"
    body = tmp_path / "body.md"
    body.write_text(REAL_DOC.replace("DEVIATIONS_BODY", demote(dev.read_text())))
    r = subprocess.run(tld_cmd("plan", "summary-check", str(body), "--kind", "pr", "--deviations", str(dev)),
                       capture_output=True, text=True, timeout=60)
    assert (r.returncode, r.stdout.startswith("summary: OK")) == (0, True), r.stdout + r.stderr


def test_the_same_file_pasted_without_demoting_fails(tmp_path):
    dev = ROOT / "docs" / "plans" / "36" / "deviations.md"
    body = tmp_path / "body.md"
    body.write_text(REAL_DOC.replace("DEVIATIONS_BODY", dev.read_text()))
    r = subprocess.run(tld_cmd("plan", "summary-check", str(body), "--kind", "pr", "--deviations", str(dev)),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
