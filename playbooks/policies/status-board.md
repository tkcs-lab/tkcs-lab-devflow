# Writing to the status board

The board is the owner's inbox (D7, D8): it holds a status record of every run and every ask a playbook puts
to the owner. These playbooks write a status record, so the owner sees each run in one place: setup, review,
make-plan, implement, land, deps, upstream, docs, spec, sysml, questions and migrate, and the worker of a single-session prompt (make-plan's small scope). dod and board write none
(a report and the board itself), nor do git-ops, repo-admin and release. The record
format is `src/tld/schema/status-record.schema.json`; `tld board validate-record FILE --doc-id ID` checks one.
Asks are [runtime.md](../runtime.md)'s `ask_human`. This file says where, how and when to write records.

## Where the board is

`tld board client` talks to the board server when `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` are set (an adapter
may offer the same operations as tools; see its runtime map). The token lets a session write records and
post, read and cancel asks; only the owner, logged in on the board's page, answers an ask, and the owner never
writes a record. When there is no board (see "The write path"), skip every record step silently and carry on;
`ask_human` then uses its issue fallback and `notify_human` still goes out.

## Board upkeep

The board is part of the work, not a report written after it. A run that is not on the board does not exist for the owner. These five rules hold for every playbook that writes a record and are mandatory for make-plan and implement:

1. **First record first.** Write the first record (`starting`) before any step that can take more than a minute. In make-plan and implement that is before the research, before the first worker and before the first ask, except the "already running?" check, which asks before any record exists (see "When to write"); never "after the plan is understood".
2. **Every item up front.** The first record lists every item the run will have. In implement that is every phase of the manifest plus `final-review`, printed by `tld plan record-items <plan file>`; never a short list that grows later.
3. **Extra items at once.** A revision (`<phase id>-rev<n>`), a fix (`fix-<n>`) and a second final review (`final-review-2`) become items in the same record write that starts them, before their worker exists. Before every record write of implement, save the record to a scratch file and run `tld plan record-items <plan file> --check <record file>` with one `--add <id>=<title>` for every extra item so far, each value one quoted shell argument and the title a short label you write yourself, never text copied from a finding or an answer; it must exit 0.
4. **Every change is a write.** Every state change, every check-in, every ask and every answer is a record write, also when only `updated_at` changes. A session that asks, starts or stops a worker, opens a pull request or pushes without writing the record afterwards has forgotten the board.
5. **Every ask has a timer.** In the same turn that posts an ask: write the record with `needs_you` (no record during the "already running?" check), show the ask in the conversation (attended), start the watch (attended, with a board) and arm `schedule_wakeup` (60 minutes with the watch, else 10 minutes). Write the timer's time into `last_event` as `timer <ISO time>`: `next_check_at` must be null while the status is `waiting_user` and in every command record. Never end the turn of an ask without the timer. On every wake cancel the armed timer before arming the next one, and cancel it when the ask closes.

## The write path

The session writes with the runtime's board tools when its tool list shows them; otherwise, or when one fails
or says it is disconnected, with `tld board client set <id> - [--if-version <n>]`. Only exit 3 (no
`TLD_BOARD_URL` or `TLD_BOARD_TOKEN`) means there is no board. A runtime tool that is missing or dropped is
never a reason to skip the record.

## The record (C7)

| Field | Value |
|---|---|
| `kind` | `run` for implement and for a single-session prompt's worker; `command` for every other playbook (deps, upstream, land, setup, docs, spec, sysml, review, make-plan, questions, migrate) |
| `command` | `null` for a run; else the playbook: `setup`, `review`, `make-plan`, `deps`, `upstream`, `land`, `docs`, `spec`, `sysml`, `questions`, `migrate` |
| `plan_slug`, `plan_url`, `feature_branch` | a run's plan and branch; a single-session prompt's run has `plan_slug` `issue-<n>`, `plan_url` `null`, its branch and `phases: []`; all `null` for a command |
| `project` | `tld board project-slug <owner>/<repo>`: the repository name, lower case, other characters as `-` |
| document id | from `tld board record-id` (see "Keys and a record that already exists"): `<project>--run--<plan>` for a run, `<project>--<command>--<tail>` for an attended command, `<project>--<command>` for a scheduled one |
| `attended` | `true` when a person started the command and can answer; `false` for a scheduled run |
| `orchestrator_session` | this session's id, or `null` when the session cannot read its own id (only when `attended` is `false`) |
| `status` | `starting`, `running`, `waiting_user`, `reviewing`, then a final state: `done`, `failed` or `pr_open` (the run ended with a pull request waiting for the owner) |
| `finished_at` | set for `done` and `failed`, may be set for `pr_open`, `null` otherwise |
| `phases` | implement's phases; for the others the items the playbook names |
| `needs_you`, `needs_you_reason`, `needs_you_since` | true exactly while the owner is asked something or the run stopped on something only they can fix; the reason is one line starting with the verb the owner must do |
| `next_check_at` | the armed check-in time, or `null`; always `null` while the status is `waiting_user` and in every command record (the ask timer's time goes into `last_event`, Board upkeep, rule 5) |

## Keys and a record that already exists

Build the id once with `tld board record-id` and keep it for the whole run. A session that resumes a run and
finds its record under the old id (the project slug, or `<project>--<command>`) keeps writing that one.
Hand-building an id is never right.

## Writing a record

Write the whole document with `tld board client set <id> - --if-version <n>` (the JSON on stdin), `n` being
the version you last read; omit `--if-version` only on the very first write. The server validates the
record: on `invalid`, fix the listed errors and retry once. On `version_conflict`, re-read with
`tld board client get <id>`, merge in the fields this session owns, and retry once. A `version_conflict` on the
very first write means a record of an earlier run exists: read it and write over it with its version.

## Asks, alerts and the owner's cards

- Every ask a playbook posts carries `record`, the document id of its status record ([runtime.md](../runtime.md)
  `ask_human`), so the page shows one card per wait.
- The final record never keeps `needs_you: true` unless the run stopped on something only the owner can fix.
  Pull requests waiting for review are items of the record, not an alert.
- The owner can Dismiss any card on the page (a stuck "needs you" card, a "PR open" card whose pull requests are
  merged) and Restore it; the board keeps that next to the record and never rewrites it. Your next write of the record
  brings the card back. The board playbook's prune also clears the `needs_you` of a record whose pull requests are all merged or closed, after the owner confirms.
- A `version_conflict` with `current: null` means the record was deleted (pruned): write it again without
  `--if-version`.

## When to write

- One exception to the first-record rule: the "already running?" check of implement (section 0 step 4) and of
  make-plan (section 0, "already being planned") runs before the first record write and posts its `ask_human`
  with no record written, because the run's record id is the live run's id. A board-gate block during
  that check is answered by saying that the playbook says to write no record yet, and ending the turn. The `stop`
  answer writes no record at all. Write the first record once the check lets the run go on.
- The first record is written before the first ask, the first worker and any other work that can take more
  than a minute; before `ask_human` the record is written with `needs_you` (Board upkeep, rule 1).
- Every state change, and every check-in even when nothing changed (set `updated_at`).
- The final state.
- After the final write of a run (`done`, `failed` or `pr_open`), call `read_usage()` ([runtime.md](../runtime.md))
  and, when it returns a reading, save it to a scratch file and run `tld board usage <file>`. Best effort: an
  error is never reported and never stops the run. The usage playbook is excluded: it writes no record.
- `review apply` is the resume step of `questions`: it writes the questions record `done` when the document names it in `status_record`.

## Best effort

A board error never stops the run. Note it once in your reply and carry on without retrying until the next
planned write. The command questions reads its input from the board: without a board, or on a board that refuses its record, it stops with the message its playbook names.

## No secrets

A record holds no file contents, no commit messages and no tokens. The board is readable by every session
that has the token and by the owner. The one place a record names files is a phase's optional `scope` (implement's scope-drift
monitoring): at most 20 repository-relative paths, and counts. The board can also hold one checked HTML report page per record, stored beside it with `tld board client put-report` and never as part of a record.

## Alerts

When `needs_you` goes from false to true, call `notify_human("<project>: <reason>")` once. While it stays
true nothing new goes out unless the reason changes. The runtime map says what an alert looks like there.
