"""The fix-round policy, implement's hook-in and the policy's reach."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "playbooks/policies/findings-fix.md"
IMPLEMENT = ROOT / "playbooks/implement.md"


def flat(path):
    """The text with every whitespace run as one space: implement.md wraps its lines."""
    return " ".join(path.read_text().split())


def test_the_policy_exists_and_links_untrusted_text():
    assert POLICY.is_file()
    assert "untrusted-text.md" in POLICY.read_text()


def test_implement_links_the_policy_and_hooks_in():
    text = flat(IMPLEMENT)
    assert "policies/findings-fix.md" in text
    assert "1b." in text
    assert "--findings <N>" in text
    assert "open non-blocking findings" not in text


def test_implement_orders_the_finishing_parts_and_the_body():
    text = flat(IMPLEMENT)
    text = text[text.index("## 6. Finishing"):]
    assert text.index("1a.") < text.index("1b.") < text.index("Then settle the scope drift")
    body = text[text.index("**The body.**"):]
    assert body.index("## Phases") < body.index("## Non-blocking findings")


def test_the_policy_names_its_markers():
    text = flat(POLICY)
    for needle in ("Fixes-Finding:", "FIX-REPORT", "## Non-blocking findings",
                   "declined: fix round did not complete", "Exactly one fix worker per run"):
        assert needle in text


def test_make_plan_and_dod_do_not_link_the_policy():
    for name in ("make-plan.md", "dod.md"):
        assert "findings-fix.md" not in (ROOT / "playbooks" / name).read_text()
