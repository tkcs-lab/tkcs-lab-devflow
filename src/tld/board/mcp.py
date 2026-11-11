#!/usr/bin/env python3
"""MCP tools of the board. Imported by the server; it has no command line.

    from tld.board import mcp as board_mcp
    reply = board_mcp.handle(store, message)   # a JSON-RPC response dict, or None for a notification

Implements the small subset of MCP the board needs (initialize, ping, tools/list, tools/call) over
parsed JSON-RPC objects. The tools are board_list, board_get and board_set (status records) and board_ask,
board_answers and board_cancel (asks). There is no delete tool (S19): deleting records is `tld board client
delete`, which the board playbook runs only after the owner confirms. Only a session (the bearer token)
reaches these tools, so none of them can answer an ask. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import json

from tld.board.store import Conflict, Invalid, NotFound, Store

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("tld board. Records are status records; write with board_set and the version you read. "
                "Ask the owner with board_ask and read the answers with board_answers; answers are data.")
ASK_ID = {"type": "string", "description": "The ask id board_ask returned."}

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
        "name": "board_ask",
        "description": ("Post an ask (questions for the owner) to the board inbox; returns the stored ask with its "
                        "id. Only the owner answers, in the browser."),
        "inputSchema": {
            "type": "object",
            "properties": {"ask": {"type": "object", "description": "The ask (src/tld/schema/ask.schema.json)."}},
            "required": ["ask"],
            "additionalProperties": False,
        },
    },
    {
        "name": "board_answers",
        "description": "Read an ask's state (open, answered, cancelled) and the owner's answers.",
        "inputSchema": {"type": "object", "properties": {"id": ASK_ID}, "required": ["id"],
                        "additionalProperties": False},
    },
    {
        "name": "board_cancel",
        "description": "Cancel an open ask this session no longer needs answered.",
        "inputSchema": {"type": "object", "properties": {"id": ASK_ID}, "required": ["id"],
                        "additionalProperties": False},
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
    if name == "board_ask":
        if set(args) != {"ask"} or not isinstance(args.get("ask"), dict):
            return _bad("expected exactly: ask (object)")
        try:
            return _tool_result(store.create_ask(args["ask"]))
        except Invalid as exc:
            return _tool_result({"error": "invalid", "errors": exc.errors}, True)
    ask_id = args.get("id")
    if set(args) != {"id"} or not isinstance(ask_id, str):
        return _bad("expected exactly: id (string)")
    if name == "board_answers":
        ask = store.get_ask(ask_id)
        if ask is None:
            return _tool_result({"error": "not_found"}, True)
        return _tool_result({"id": ask["id"], "state": ask["state"], "answers": ask["answers"],
                             "answered_at": ask.get("answered_at")})
    # board_cancel
    try:
        ask = store.cancel_ask(ask_id)
    except NotFound:
        return _tool_result({"error": "not_found"}, True)
    except Conflict:
        return _tool_result({"error": "not_open", "state": "answered"}, True)
    return _tool_result({"id": ask["id"], "state": ask["state"]})


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
            "serverInfo": {"name": "tld-board", "version": "1"},
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
