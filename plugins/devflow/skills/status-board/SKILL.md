---
name: status-board
description: How a devflow session writes its status record to the status board — where the board is (the board_* tools or board_client.py), how to write a record, when to write, and what must never go into one. Read before the first record and whenever a command says to follow it.
user-invocable: false
---

# Writing to the status board

The record format and its rules are in
`plugins/devflow/schema/status-record.schema.json`. This skill says where and how to write one.

## Where the board is

The board is reached through the tools `board_get`, `board_list`, `board_set` and `board_delete` of
the `devflow-board` MCP server, whichever prefix the tool list shows, when the tool list has them.
When it has none and both `DEVFLOW_BOARD_URL` and `DEVFLOW_BOARD_TOKEN` are set, use
`board_client.py` (same operations; it sits next to the `project-profile` skill's scripts, see its
"Find the toolkit scripts" step). When neither works there is no board: skip every board step
silently and carry on (alerts, when they exist, still go out).

## Writing a record

Write with `board_set` (or `board_client.py set ID - [--if-version N]` with the JSON on stdin),
passing the whole document, with `if_version` set to the version you last read (omit it only for
the very first write). The document id is the project slug for a `run` record, and
`<project>--<command>` for a `maintenance` record. The server validates the record: on `invalid`,
fix the listed errors and retry once. On `version_conflict`, re-read with `board_get`, merge in the
fields this session owns, and retry once. A `version_conflict` on the very first write (no
`if_version`) means a record of an earlier run exists: `board_get` it and write over it with its
version.

## When to write

- The first record, before any work starts.
- Every state change.
- Every check-in, even when nothing changed (the heartbeat: set `updated_at`).
- The final state (`done` or `failed`, with `finished_at`).

## Best effort

A board error never stops the run. Note it once in your own reply, then carry on without
retrying again until the next planned write.

## No secrets

A record holds no file contents, no commit messages and no tokens. The board is readable by
everyone who has the read token or the write token. The one place a record names files is a phase
item's optional `scope` field (scope-drift monitoring, written by `/implement`): at most 20
repository-relative paths, and counts. The board page shows only the count.

## Alerts

| When | Action | Exact text |
|---|---|---|
| `needs_you` goes false to true | rename own session (`set_session_title`) | `[NEEDS YOU] <project> · <reason>` (the separator is the middle dot U+00B7 with a space on each side) |
| `needs_you` goes false to true | `PushNotification` once | `<project>: <reason>` cut to 190 characters |
| `needs_you` goes true to false | rename back to the title read with `get_session` before the first rename | the saved title |
| `needs_you` stays true | nothing | no new push, no new rename unless the reason changed (then rename only) |
| record has `kind: maintenance` | push only | the same push text; never rename (a scheduled session cannot read its own title: it has no `get_session`) |

All of it is best effort. Alerts do not depend on a board: they go out even when no board URL is set. `<project>` is the record's `project`; `<reason>` is `needs_you_reason`.

Before the first rename, read the session's current title with `get_session` and keep it in memory; that is the title to rename back to.

## /setup records

`/setup` writes a maintenance record: `kind: maintenance`, `command: setup`, document id
`<project>--setup`. Unlike `deps`, `upstream` and `land`, its `orchestrator_session` is the real
session id (a non-empty string), not the literal `scheduled`. The phase items are the five steps
`survey`, `confirm`, `write`, `verify` and `pr`, using the item states the other maintenance records
use. Alerts follow the maintenance rule: push only, never a rename.
