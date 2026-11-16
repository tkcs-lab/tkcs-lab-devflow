"""implement and make-plan use the preamble, the fallback and the protected-change flow."""
from pathlib import Path

from tld.guard import plan_gate

ROOT = Path(__file__).resolve().parents[2]


def slice_of(path, start, end):
    text = (ROOT / path).read_text()
    a = text.index(start)
    return text[a:text.index(end, a)]


IMPLEMENT = "playbooks/implement.md"


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
