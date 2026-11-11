"""The agent roster is the same in the agent files, the schema, the test table and the docs."""
import json
import re
from pathlib import Path

from agents_support import EXPECTED

ROOT = Path(__file__).resolve().parent.parent


def test_roster_is_consistent():
    files = {p.stem for p in (ROOT / "plugins/devflow/agents").glob("*.md")}
    schema = json.loads((ROOT / "plugins/devflow/schema/profile.schema.json").read_text())
    enum = set(schema["properties"]["agents"]["properties"]["disable"]["items"]["enum"])
    text = (ROOT / "docs/architecture/agents.md").read_text()
    roster = text.split("| `architect` |", 1)[1].split("\n\n", 1)[0]
    table = set(re.findall(r"^\| `([a-z-]+)` \|", "| `architect` |" + roster, re.M))
    assert files == enum == set(EXPECTED) == table
