"""The plugin's MCP bridge to the status board (adapters/claude/mcp.json)."""
from __future__ import annotations

import json

from conftest import CLAUDE, BIN


def test_mcp_json_declares_the_bridge():
    server = json.loads((CLAUDE / "mcp.json").read_text())["mcpServers"]["tld-board"]
    assert server["command"] == "python3"
    assert server["args"] == ["${CLAUDE_PLUGIN_ROOT}/cli/tld", "board", "mcp-stdio"]
    assert BIN.is_file()
    assert set(server["env"]) == {"TLD_BOARD_URL", "TLD_BOARD_TOKEN"}


def test_mcp_json_has_no_remote_url_or_literal_token():
    server = json.loads((CLAUDE / "mcp.json").read_text())["mcpServers"]["tld-board"]
    assert "url" not in server and "headers" not in server and server.get("type", "stdio") == "stdio"
    for value in server["env"].values():
        assert value.startswith("${") and value.endswith(":-}")
