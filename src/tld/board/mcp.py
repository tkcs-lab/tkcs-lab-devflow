#!/usr/bin/env python3
"""MCP tools of the status board. Imported by board_server.py; it has no command line.

    import board_mcp
    reply = board_mcp.handle(store, message)   # a JSON-RPC response dict, or None for a notification

Implements the small subset of MCP the board needs (initialize, ping, tools/list, tools/call) over
parsed JSON-RPC objects. The four tools are board_get, board_list, board_set and board_delete.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from board_store import Conflict, Invalid, Store  # noqa: E402

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("Devflow status board. Records are status records (collection 'projects'); "
                "write with board_set and the version you read.")
MAX_DELETE_IDS = 50

TOOLS: list[dict] = [
    {
        "name": "board_list",
        "description": "List every status record on the board with its id, version and data.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "board_get",
        "description": "Read one status record (id, version, data) by its document id.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Document id of the record."}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "board_set",
        "description": ("Write one whole status record; pass if_version as the version you read, "
                        "and omit it only to create a record that does not exist yet."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Document id of the record."},
                "data": {"type": "object", "description": "The whole status record."},
                "if_version": {"type": "integer", "minimum": 1,
                               "description": "The version last read; omit to create."},
            },
            "required": ["id", "data"],
            "additionalProperties": False,
        },
    },
    {
        "name": "board_delete",
        "description": "Delete status records by document id (1 to 50 ids); reports which existed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"},
                        "minItems": 1, "maxItems": MAX_DELETE_IDS},
            },
            "required": ["ids"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}


def _error(msg_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id: object, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _tool_result(payload: object, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": is_error}


def _bad(detail: str) -> dict:
    return _tool_result({"error": "bad_arguments", "detail": detail}, True)


def _call_tool(store: Store, name: str, args: dict) -> dict:
    if name == "board_list":
        if args:
            return _bad("board_list takes no arguments")
        return _tool_result({"records": store.list()})
    if name == "board_get":
        doc_id = args.get("id")
        if set(args) != {"id"} or not isinstance(doc_id, str):
            return _bad("expected exactly: id (string)")
        record = store.get(doc_id)
        if record is None:
            return _tool_result({"error": "not_found"}, True)
        return _tool_result(record)
    if name == "board_set":
        doc_id, data = args.get("id"), args.get("data")
        if_version = args.get("if_version")
        if not set(args) <= {"id", "data", "if_version"} or not isinstance(doc_id, str) \
                or not isinstance(data, dict):
            return _bad("expected: id (string), data (object), optional if_version (integer >= 1)")
        if "if_version" in args and (isinstance(if_version, bool) or not isinstance(if_version, int)
                                     or if_version < 1):
            return _bad("if_version must be an integer >= 1")
        try:
            return _tool_result(store.set(doc_id, data, if_version))
        except Conflict as exc:
            return _tool_result({"error": "version_conflict", "current": exc.current}, True)
        except Invalid as exc:
            return _tool_result({"error": "invalid", "errors": exc.errors}, True)
    # board_delete
    ids = args.get("ids")
    if set(args) != {"ids"} or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) \
            or not 1 <= len(ids) <= MAX_DELETE_IDS:
        return _bad(f"expected: ids (array of 1 to {MAX_DELETE_IDS} strings)")
    deleted: list[str] = []
    missing: list[str] = []
    for doc_id in ids:
        (deleted if store.delete(doc_id) else missing).append(doc_id)
    return _tool_result({"deleted": deleted, "missing": missing})


def handle(store: Store, message: object) -> dict | None:
    """The JSON-RPC response to one message, or None when the message needs none."""
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")
    if "id" not in message or "method" not in message:
        return None
    msg_id = message["id"]
    method = message["method"]
    params = message.get("params")
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        return _result(msg_id, {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "devflow-board", "version": "1"},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        if not isinstance(params, dict) or params.get("name") not in TOOL_NAMES:
            return _error(msg_id, -32602, "Unknown tool")
        args = params.get("arguments", {})
        if not isinstance(args, dict):
            return _error(msg_id, -32602, "arguments must be an object")
        return _result(msg_id, _call_tool(store, params["name"], args))
    return _error(msg_id, -32601, "Method not found")
