"""The plugin's wiring of the status board: .mcp.json, the status-board skill, the /board command."""
from __future__ import annotations

import json

from conftest import CLAUDE, BIN

SKILL = CLAUDE / "skills" / "status-board" / "SKILL.md"


def test_mcp_json_declares_the_bridge():
    server = json.loads((CLAUDE / "mcp.json").read_text())["mcpServers"]["tld-board"]
    assert server["command"] == "python3"
    assert server["args"] == ["${CLAUDE_PLUGIN_ROOT}/bin/tld", "board", "mcp-stdio"]
    assert BIN.is_file()
    assert set(server["env"]) == {"TLD_BOARD_URL", "TLD_BOARD_TOKEN"}


def test_mcp_json_has_no_remote_url_or_literal_token():
    server = json.loads((CLAUDE / "mcp.json").read_text())["mcpServers"]["tld-board"]
    assert "url" not in server and "headers" not in server and server.get("type", "stdio") == "stdio"
    for value in server["env"].values():
        assert value.startswith("${") and value.endswith(":-}")


def test_skill_names_the_tools_and_the_client():
    text = SKILL.read_text()
    for needle in ("board_get", "board_list", "board_set", "board_delete", "board client",
                   "TLD_BOARD_URL", "TLD_BOARD_TOKEN"):
        assert needle in text


def test_skill_has_no_artifact_words():
    text = SKILL.read_text()
    for needle in ("ArtifactData", "status.board_url", "claude.ai/artifact"):
        assert needle not in text


def test_skill_alerts_table_has_five_rows():
    section = SKILL.read_text().split("## Alerts", 1)[1]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    assert len(rows) - 1 == 5  # the header row; the separator starts with "|-"


def test_board_command_has_no_artifact_publishing():
    text = (CLAUDE / "commands" / "board.md").read_text()
    for needle in ("capabilities", "icon", "Artifact"):
        assert needle not in text
