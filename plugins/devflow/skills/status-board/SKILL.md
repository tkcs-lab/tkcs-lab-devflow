---
name: status-board
description: How a devflow session writes its status record to the status board database — where the board is, how to write a record, when to write, and what must never go into one. Read before the first record and whenever a command says to follow it.
user-invocable: false
---

# Writing to the status board

The record format and its rules are in
`plugins/devflow/schema/status-record.schema.json`. This skill says where and how to write one.

## Where the board is

The board URL is the profile key `status.board_url` when set, else the environment variable
`DEVFLOW_BOARD_URL`. If neither is set there is no board: skip every board step silently and carry
on (alerts, when they exist, still go out).

## Writing a record

Write to collection `projects` with `ArtifactData` `set`, passing the whole document, with
`if_version` pinned to the version you last read (omit it only for the very first write). The
document id is the project slug for a `run` record, and `<project>--<command>` for a `maintenance`
record. Before writing, validate the document with `validate_status_record.py -` (pipe the JSON on
stdin, add `--doc-id <id>`). On a version conflict, re-read the document, merge in the fields this
session owns, and retry once.

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
everyone who can open it.

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
