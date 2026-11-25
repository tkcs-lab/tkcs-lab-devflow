"""implement and make-plan use the preamble, the fallback and the protected-change flow."""
import re
from pathlib import Path

from tld.guard import plan_gate

ROOT = Path(__file__).resolve().parents[2]


def slice_of(path, start, end):
    text = (ROOT / path).read_text()
    a = text.index(start)
    return text[a:text.index(end, a)]


IMPLEMENT = "playbooks/implement.md"
ALLOW_SENTENCE = (
    "`BUILTIN_PROTECT_ALLOW` and the main profile's `hooks.protect_paths_allow` are subtracted only from the "
    "effective list and from the `.env*` and lockfile parts of the excluded set; they never remove a path of "
    "any workflow `guarded_workflows` returns (the land and release workflows, `tld-git-ops.yml` and the profile's `release.workflow` and `git_ops.workflow`), `ALWAYS_PROTECTED`, `.git/**` or the adapter's protected paths, even when an allow "
    "pattern matches them.")


def test_the_worker_brief_names_the_protected_change_report():
    s = slice_of(IMPLEMENT, "> You are implementing **one phase**", "**Level fallback.**")
    assert "protected-change:" in s and "tld: unavailable" in s


def test_merge_step_three_names_the_unavailable_fallback():
    s = slice_of(IMPLEMENT, "3. **Required roles.**", "4. **Scope check")
    for needle in ("tld: unavailable", "run_role", "review", "tld roles verify"):
        assert needle in s


def test_merge_step_two_names_the_protected_change_line():
    s = slice_of(IMPLEMENT, "2. Review the diff", "3. **Required roles.**")
    assert "protected-change:" in s and "--no-renames" in s


def test_the_final_reviewer_brief_makes_a_protected_diff_blocking():
    s = slice_of(IMPLEMENT, "> You are the final reviewer", "at least one blocking finding.")
    assert "protected path" in s and "allow-plan" not in s


def test_the_preamble_first_line_matches_the_worker_token():
    text = (ROOT / "adapters/claude/skills/runtime/SKILL.md").read_text()
    block = text[text.index("### Toolkit preamble"):].split("```")[1]
    line = block.strip("\n").splitlines()[0].replace("<title>", "demo p1")
    assert plan_gate.WORKER_TOKEN.search(line)


def test_make_plan_links_the_policy():
    text = (ROOT / "playbooks/make-plan.md").read_text()
    assert "policies/protected-changes.md" in text.split("## Setup")[0]
    assert "protected path" in slice_of("playbooks/make-plan.md", "### Sizing", "worker_level: strong")


def test_merge_step_two_and_the_final_reviewer_share_the_allow_and_lockfile_rule():
    merge = slice_of(IMPLEMENT, "2. Review the diff", "3. **Required roles.**")
    final = slice_of(IMPLEMENT, "> You are the final reviewer", "at least one blocking finding.")
    for s in (merge, final):
        flat = " ".join(s.split())
        assert ALLOW_SENTENCE in flat
        assert "lockfile changes are made outside implement (the deps playbook or by the owner)" in flat
        assert "lock command" not in flat and "not blocking" not in flat
    assert "A lockfile in a phase diff is sent back whoever produced it" in " ".join(merge.split())
    assert "A lockfile in the diff is a blocking finding whoever produced it" in " ".join(final.split())


def test_merge_step_three_starts_with_the_unavailable_exception():
    s = slice_of(IMPLEMENT, "3. **Required roles.**", "4. **Scope check")
    assert s.startswith("3. **Required roles.** Unless the report has the line `tld: unavailable`")


def test_rule_zero_keeps_allow_plan():
    assert (ROOT / IMPLEMENT).read_text().count("allow-plan") >= 2


def test_implement_pr_step_passes_changed():
    text = " ".join((ROOT / IMPLEMENT).read_text().split())
    assert "git diff --name-only --no-renames origin/<main>...HEAD" in text
    assert re.search(r"tld plan summary-check <body file> --kind pr --deviations <deviations path> --findings <N> --changed <changed list>", text)
    final = " ".join(slice_of(IMPLEMENT, "> You are the final reviewer", "at least one blocking finding.").split())
    assert "trust-boundary change" in final and "pull_request_target" in final and "permissions: write" in final
