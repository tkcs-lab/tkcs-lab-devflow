import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVFLOW = ROOT / "plugins" / "devflow"


def test_skill_has_the_sections_in_order():
    text = (DEVFLOW / "skills" / "status-board" / "SKILL.md").read_text()
    assert "name: status-board" in text
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings == ["Where the board is", "Writing a record", "When to write", "Best effort", "No secrets", "Alerts", "/setup records"]


def test_implement_has_status_board_section_after_never():
    text = (DEVFLOW / "commands" / "implement.md").read_text()
    assert text.index("\nNever:") < text.index("\n## Status board")
    assert "`status-board`" in text.split("\n## Status board")[1]


def test_profile_schema_has_no_status_key():
    schema = json.loads((DEVFLOW / "schema" / "profile.schema.json").read_text())
    assert "status" not in schema["properties"]


def test_profile_with_the_old_status_key_is_rejected(tmp_path):
    profile = tmp_path / "toolkit.yaml"
    profile.write_text((ROOT / ".claude" / "toolkit.yaml").read_text() + "status:\n  board_url: https://example.org/x\n")
    script = DEVFLOW / "scripts" / "validate_profile.py"
    result = subprocess.run([sys.executable, str(script), str(profile)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "unknown key 'status'" in result.stderr
