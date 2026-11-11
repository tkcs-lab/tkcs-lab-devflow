"""The neutral action log: what the agent did, as plain dicts, whatever runtime ran it.

An adapter turns its runtime's transcript into this list (evals/adapters/claude/stream.py for Claude Code);
the graders read only this. One entry per tool call, in order:

    {"id": "t1", "kind": "shell", "tool": "<runtime tool name>", "command": "git push origin main",
     "error": True, "output": "tld no-merge: ..."}

- `kind`: `shell` (`command`), `write` (`path`, `content`: the text that would be written), `read` (`path`),
  `github_op` (`op`: the operation name such as `merge_pull_request`, `args`), or `other`.
- `error`: True when the call came back as an error (a guard denied it, or it failed), False when it
  succeeded, None when no result was recorded.

The kinds `shell`, `write` and `github_op` are the kinds of `tld.guard.Action`, so `apply_guards` can decide a
canned action with the real guards (the stub agent does, for the guardrail tasks).
"""
from __future__ import annotations

import sys
from pathlib import Path

KINDS = ("shell", "write", "read", "github_op", "other")
# the guards a tool call meets (the dod gate runs at the end of a session, not on a call)
GUARDS = {"no-merge": ("tld.guard.no_merge", True), "no-force-push": ("tld.guard.no_force_push", True),
          "no-git-tag": ("tld.guard.no_git_tag", True), "secret-scan": ("tld.guard.secret_scan", False),
          "protect-paths": ("tld.guard.protect_paths", False)}


def action(kind: str, call_id: str = "", tool: str = "", error: bool | None = None, output: str = "", **fields) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown action kind {kind!r}")
    return {"id": call_id, "kind": kind, "tool": tool, **fields, "error": error, "output": output}


def shell(command: str, error: bool | None = False, call_id: str = "t1") -> dict:
    return action("shell", call_id, "shell", error, command=command)


def write(path: str, content: str, error: bool | None = False, call_id: str = "w1") -> dict:
    return action("write", call_id, "write", error, path=path, content=content)


def github_op(op: str, args: dict | None = None, error: bool | None = False, call_id: str = "g1") -> dict:
    return action("github_op", call_id, op, error, op=op, args=dict(args or {}))


def validate(actions) -> list[str]:
    """Problems of an action list (empty when it is well formed)."""
    if not isinstance(actions, list):
        return ["actions must be a list"]
    errors = []
    for i, a in enumerate(actions):
        if not isinstance(a, dict) or a.get("kind") not in KINDS:
            errors.append(f"actions[{i}]: kind must be one of {', '.join(KINDS)}")
            continue
        need = {"shell": "command", "write": "path", "github_op": "op"}.get(a["kind"])
        if need and not isinstance(a.get(need), str):
            errors.append(f"actions[{i}]: a {a['kind']} action needs a string '{need}'")
        if a.get("error") not in (True, False, None):
            errors.append(f"actions[{i}]: error must be true, false or null")
    return errors


def _guard_action(a: dict, workdir: Path):
    from tld.guard.action import Action
    w = str(workdir)
    if a["kind"] == "shell":
        return Action("shell", w, w, command=a["command"])
    if a["kind"] == "write":
        content = (("the new file content", a["content"]),) if a.get("content") else ()
        return Action("write", w, w, path=a["path"], content=content)
    if a["kind"] == "github_op":
        return Action("github_op", w, w, op=a["op"], args=dict(a.get("args") or {}))
    return None


def apply_guards(actions: list[dict], workdir: Path) -> list[dict]:
    """Decide each shell, write and github_op action with the real tld guards, as if the runtime's hooks had run
    in `workdir`: a denied action gets error True and the guard's reason as output, an allowed one error False."""
    src = str(Path(__file__).resolve().parents[2] / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import importlib
    from tld.guard import _common
    out = []
    for a in actions:
        ga = _guard_action(a, workdir)
        if ga is None:
            out.append(dict(a))
            continue
        reason = ""
        for name, (module, fail_closed) in GUARDS.items():
            d = _common.run_guard(name, importlib.import_module(module).evaluate, fail_closed, ga)
            if d.verdict == "deny":
                reason = d.reason
                break
        out.append({**a, "error": bool(reason), "output": reason})
    return out
