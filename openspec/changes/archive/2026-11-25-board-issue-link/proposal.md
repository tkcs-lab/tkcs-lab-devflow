## Why

A board card links its plan, its session and its pull request, but not the tracking issue of the run. The issue is where the request, the plan in plain words and every event comment of make-plan, implement and quick live. The owner has to open the session or search GitHub to find it.

## What Changes

- A status record of any kind may carry an optional `tracking_issue`: the number of the run's tracking issue in the record's repository, a positive integer of at most ten digits, or null.
- A record whose `tracking_issue` disagrees with the issue of its hand-over, or with the number in a `plan_slug` of the form `issue-<n>`, is refused.
- The owner page shows an `issue #<n>` link first in a card's links, built from the record's repository and the number.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `board-server`: two added requirements.

## Impact

`src/tld/board/record.py`, `src/tld/schema/status-record.schema.json`, `src/tld/board/web/rules.js`, `src/tld/board/web/board.html`, `playbooks/make-plan.md`, `playbooks/implement.md`, `playbooks/quick.md`, `playbooks/board.md`, `playbooks/policies/status-board.md`. A board server older than this release refuses a record with `tracking_issue` (unknown field); the status-board policy then has the session write the record without it for the rest of the run.
