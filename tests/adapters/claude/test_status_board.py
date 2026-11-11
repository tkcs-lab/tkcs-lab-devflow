import json
import re
import subprocess
import sys
from pathlib import Path
from conftest import ROOT, TLD, CLAUDE, tld_cmd



def test_skill_has_the_sections_in_order():
    text = (CLAUDE / "skills" / "status-board" / "SKILL.md").read_text()
    assert "name: status-board" in text
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings == ["Where the board is", "Writing a record", "When to write", "Best effort", "No secrets", "Alerts", "/setup records"]


def test_implement_has_status_board_section_after_never():
    text = (CLAUDE / "commands" / "implement.md").read_text()
    assert text.index("\nNever:") < text.index("\n## Status board")
    assert "`status-board`" in text.split("\n## Status board")[1]


def test_profile_schema_has_no_status_key():
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    assert "status" not in schema["properties"]


def test_profile_with_the_old_status_key_is_rejected(tmp_path):
    profile = tmp_path / "toolkit.yaml"
    profile.write_text((ROOT / ".tld" / "toolkit.yaml").read_text() + "status:\n  board_url: https://example.org/x\n")
    result = subprocess.run([*tld_cmd("profile", "validate"), str(profile)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "unknown key 'status'" in result.stderr
