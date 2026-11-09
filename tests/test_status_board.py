import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVFLOW = ROOT / "plugins" / "devflow"


def test_skill_has_the_sections_in_order():
    text = (DEVFLOW / "skills" / "status-board" / "SKILL.md").read_text()
    assert "name: status-board" in text
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings == ["Where the board is", "Writing a record", "When to write", "Best effort", "No secrets", "Alerts"]


def test_implement_has_status_board_section_after_never():
    text = (DEVFLOW / "commands" / "implement.md").read_text()
    assert text.index("\nNever:") < text.index("\n## Status board")
    assert "`status-board`" in text.split("\n## Status board")[1]


def test_profile_schema_has_status_board_url():
    schema = json.loads((DEVFLOW / "schema" / "profile.schema.json").read_text())
    assert "board_url" in schema["properties"]["status"]["properties"]
