"""Claude Code's stream-json output -> AgentResult, and its tool calls -> the neutral action log."""
from __future__ import annotations

import json

from evals.harness.actions import action
from evals.harness.model import AgentResult

WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read", "Glob", "Grep")


def tool_calls(transcript: list[dict]) -> list[dict]:
    """Each tool call of a stream-json transcript with its result: {id, name, input, is_error, output}.

    A call with no recorded result has is_error None.
    """
    calls: dict[str, dict] = {}
    order: list[str] = []
    for ev in transcript:
        msg = ev.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block["id"]] = {"id": block["id"], "name": block.get("name", ""),
                                      "input": block.get("input", {}), "is_error": None, "output": ""}
                order.append(block["id"])
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                c = calls[block["tool_use_id"]]
                c["is_error"] = bool(block.get("is_error"))
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
                c["output"] = str(content)
    return [calls[i] for i in order]


def _written(tool: str, ti: dict) -> str:
    if tool == "Write":
        parts = [ti.get("content")]
    elif tool == "Edit":
        parts = [ti.get("new_string")]
    elif tool == "MultiEdit":
        parts = [e.get("new_string") for e in ti.get("edits", []) if isinstance(e, dict)] if isinstance(ti.get("edits"), list) else []
    else:
        parts = [ti.get("new_source")]
    return "\n".join(p for p in parts if isinstance(p, str))


def to_actions(transcript: list[dict]) -> list[dict]:
    """The neutral action log of a transcript; the tool mapping is the one of adapters/claude/hooks/claude_adapter.py."""
    out = []
    for c in tool_calls(transcript):
        name, ti = c["name"], c["input"] if isinstance(c["input"], dict) else {}
        common = {"call_id": c["id"], "tool": name, "error": c["is_error"], "output": c["output"]}
        if name == "Bash":
            out.append(action("shell", command=str(ti.get("command", "")), **common))
        elif name in WRITE_TOOLS:
            out.append(action("write", path=str(ti.get("file_path") or ti.get("notebook_path") or ""),
                              content=_written(name, ti), **common))
        elif name in READ_TOOLS:
            out.append(action("read", path=str(ti.get("file_path") or ti.get("path") or ti.get("pattern") or ""), **common))
        elif name.startswith("mcp__") and "__" in name[5:]:
            out.append(action("github_op", op=name.rsplit("__", 1)[-1], args=dict(ti), **common))
        else:
            out.append(action("other", input=ti, **common))
    return out


def parse_stream(lines: list[str]) -> AgentResult:
    """Turn the stream-json output of one run into an AgentResult."""
    res = AgentResult()
    kept: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t in ("stream_event", "rate_limit_event", "autocompact_state", "active_goal"):
            continue
        if t == "system" and ev.get("subtype") == "init":
            res.model = ev.get("model", res.model)
            names = [p.get("name") for p in ev.get("plugins", [])]
            if ev.get("plugin_errors") or "tld" not in names:
                res.error = f"plugin did not load: errors={ev.get('plugin_errors')} loaded={names}"
        if t == "assistant" and isinstance(ev.get("message"), dict):
            blocks = ev["message"].get("content")
            if isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        b.pop("signature", None)
        if t == "result":
            res.result_text = ev.get("result", "") or ""
            res.turns = int(ev.get("num_turns", 0) or 0)
            res.cost_usd = float(ev.get("total_cost_usd", 0.0) or 0.0)
            u = ev.get("usage", {}) or {}
            res.tokens = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                          "cache_read": u.get("cache_read_input_tokens", 0),
                          "cache_creation": u.get("cache_creation_input_tokens", 0)}
            res.duration_s = float(ev.get("duration_ms", 0) or 0) / 1000
            if ev.get("subtype") == "error_max_budget_usd":
                res.aborted = "cost_ceiling"
            elif ev.get("is_error"):
                res.error = res.error or f"result error: {ev.get('subtype')}"
        kept.append(ev)
    res.transcript = kept
    res.actions = to_actions(kept)
    return res
