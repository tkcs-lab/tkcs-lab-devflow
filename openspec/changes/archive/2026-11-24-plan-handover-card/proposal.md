## Why

When `/tld:make-plan` finishes, its board card moves to "Done" with only "done, finished x ago". The owner has to open the session or the issue to find the plan's summary, the links and the command that starts the implementation. A finished plan is the owner's next decision and must not end silently.

## What Changes

- A status record of a command may carry an optional `handover`: the plan's Summary, links to the tracking issue, the plan and the spec change, and the command that starts the implementation, ready to copy.
- A new command `tld plan handover` builds that object from a plan or an issue body, copying the Summary word for word.
- The owner page shows a finished record with a hand-over in a new "Plan ready" section, with the Summary, the links and a Copy button, until an implement run of that plan appears on the board, the owner dismisses it, or seven days pass.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `board-server`: two added requirements.
- `plan-run-tracking`: one added requirement.

## Impact

`src/tld/board/record.py`, `src/tld/schema/status-record.schema.json`, `src/tld/plan/handover.py`, `src/tld/cli.py`, `src/tld/board/web/rules.js`, `src/tld/board/web/board.html`, `playbooks/make-plan.md`, `playbooks/policies/status-board.md`. A board server older than this release refuses a record with `handover` (unknown field); the make-plan playbook then writes the record without it.
