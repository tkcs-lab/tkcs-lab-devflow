from pathlib import Path
from conftest import CLAUDE



def test_skill_alerts_strings():
    text = (CLAUDE / "skills" / "status-board" / "SKILL.md").read_text()
    assert "\n## Alerts\n" in text
    assert "[NEEDS YOU] <project> · <reason>" in text
    assert "<project>: <reason>" in text
    assert "190 characters" in text
    assert "| record has `kind: maintenance` | push only |" in text
    assert "All of it is best effort." in text
    assert "`get_session`" in text


def test_implement_alerts_paragraph_and_reasons():
    text = (CLAUDE / "commands" / "implement.md").read_text()
    assert "When `needs_you` changes, follow the `## Alerts` section of the `status-board` skill (rename the session, push once, rename back)." in text
    for reason in ["Confirm manual steps", "Approve <phase id>", "Fix <phase id>", "Resolve review findings", "Review PR #<n>"]:
        assert f"`{reason}`" in text
