#!/usr/bin/env python3
"""MCP stdio bridge to the tld status board server.

    board_mcp_stdio.py

Reads newline-delimited JSON-RPC from stdin and forwards each message to `POST /mcp` of the board
server named by TLD_BOARD_URL, authenticating with TLD_BOARD_TOKEN. Replies go to stdout, one
JSON object per line. When no board is configured it answers locally with an empty tool list.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from tld.board import client as board_client  # noqa: E402
from tld.board import mcp as board_mcp  # noqa: E402
from tld.board.client import Config  # noqa: E402

NO_BOARD = "No tld board is configured (TLD_BOARD_URL and TLD_BOARD_TOKEN are unset)."


def _write(stdout: TextIO, payload: dict) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    stdout.flush()


def _error(msg_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _local_reply(message: dict) -> dict | None:
    """Answer without a board: initialize, tools/list and ping; None for a notification."""
    if "id" not in message or "method" not in message:
        return None
    msg_id, method = message["id"], message["method"]
    if method == "initialize":
        params = message.get("params")
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        version = asked if asked in board_mcp.PROTOCOLS else board_mcp.PROTOCOLS[0]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "tld-board", "version": "1"},
            "instructions": NO_BOARD,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    return _error(msg_id, -32601, f"method not found: {method}")


def serve(stdin: TextIO, stdout: TextIO, config: Config | None, call: Callable = board_client.call) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            print("board_mcp_stdio: dropped a line that is not JSON", file=sys.stderr)
            continue
        if not isinstance(message, dict):
            print("board_mcp_stdio: dropped a message that is not a JSON object", file=sys.stderr)
            continue
        if config is None:
            reply = _local_reply(message)
            if reply is not None:
                _write(stdout, reply)
            continue
        is_request = "id" in message and "method" in message
        try:
            status, body = call(config, "POST", "/mcp", message)
        except OSError as err:
            if is_request:
                _write(stdout, _error(message["id"], -32000, f"board server: {type(err).__name__}"))
            continue
        if status == 200 and isinstance(body, dict):
            _write(stdout, body)
        elif status == 202:
            continue
        elif is_request:
            _write(stdout, _error(message["id"], -32000, f"board server: HTTP {status}"))


def main(argv: list[str] | None = None) -> int:
    try:
        config = board_client.load_config()
    except board_client.ConfigError as err:
        print(f"board_mcp_stdio: {err}", file=sys.stderr)
        config = None
    try:
        serve(sys.stdin, sys.stdout, config)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
