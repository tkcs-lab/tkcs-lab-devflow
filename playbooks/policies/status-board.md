# Writing to the status board

The board is the owner's inbox (D7, D8): it holds a status record of every run and every ask a playbook puts
to the owner. Every playbook writes a status record, so the owner sees each run in one place. The record
format is `src/tld/schema/status-record.schema.json`; `tld board validate-record FILE --doc-id ID` checks one.
Asks are [runtime.md](../runtime.md)'s `ask_human`. This file says where, how and when to write records.

## Where the board is

`tld board client` talks to the board server when `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` are set (an adapter
may offer the same operations as tools; see its runtime map). The token lets a session write records and
post, read and cancel asks; only the owner, logged in on the board's page, answers an ask, and the owner never
writes a record. When neither works there is no board: skip every record step silently and carry on;
`ask_human` then uses its issue fallback and `notify_human` still goes out.

## The record (C7)

| Field | Value |
|---|---|
| `kind` | `run` for implement; `command` for every other playbook (deps, upstream, land, setup, docs, review, make-plan) |
| `command` | `null` for a run; else the playbook: `setup`, `review`, `make-plan`, `deps`, `upstream`, `land`, `docs` |
| `project` | `tld board project-slug <owner>/<repo>`: the repository name, lower case, other characters as `-` |
| document id | the project slug for a run, `<project>--<command>` for the others |
| `attended` | `true` when a person started the command and can answer; `false` for a scheduled run |
| `orchestrator_session` | this session's id, or `null` when the session cannot read its own id (only when `attended` is `false`) |
| `status` | `starting`, `running`, `waiting_user`, `reviewing`, then a final state: `done`, `failed` or `pr_open` (the run ended with a pull request waiting for the owner) |
| `finished_at` | set for `done` and `failed`, may be set for `pr_open`, `null` otherwise |
| `phases` | implement's phases; for the others the items the playbook names |
| `needs_you`, `needs_you_reason`, `needs_you_since` | true exactly while the owner is asked something or the run stopped on something only they can fix; the reason is one line starting with the verb the owner must do |
| `next_check_at` | the armed check-in time, or `null` |

## Writing a record

Write the whole document with `tld board client set <id> - --if-version <n>` (the JSON on stdin), `n` being
the version you last read; omit `--if-version` only on the very first write. The server validates the
record: on `invalid`, fix the listed errors and retry once. On `version_conflict`, re-read with
`tld board client get <id>`, merge in the fields this session owns, and retry once. A `version_conflict` on the
very first write means a record of an earlier run exists: read it and write over it with its version.

## When to write

- The first record, before any work starts.
- Every state change, and every check-in even when nothing changed (set `updated_at`).
- The final state.

## Best effort

A board error never stops the run. Note it once in your reply and carry on without retrying until the next
planned write.

## No secrets

A record holds no file contents, no commit messages and no tokens. The board is readable by every session
that has the token and by the owner. The one place a record names files is a phase's optional `scope` (implement's scope-drift
monitoring): at most 20 repository-relative paths, and counts.

## Alerts

When `needs_you` goes from false to true, call `notify_human("<project>: <reason>")` once. While it stays
true nothing new goes out unless the reason changes. The runtime map says what an alert looks like there.
