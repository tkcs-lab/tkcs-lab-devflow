# Deviations: board-issue-link

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-record-tracking-issue

- worker: Worker ran with python3 instead of .venv and without tld; orchestrator ran roles and checks.
- review: Security reviewer: non-blocking, a foreign-repo issue_url ending in /issues/<n> yields two errors where plan 3.1 says one; left as is.

## p2-board-issue-link

- worker: Worker ran without tld, so roles were run by the orchestrator; it used one shared orchestrator_session id in the fixture runs.

## p3-playbooks-tracking-issue

- worker: Worker ran without tld; it skipped the dod run and three acceptance greps, so the orchestrator ran the roles and the greps.

## p4-retire

- worker: Worker ran without the plugin tld; its role line was not trusted, the orchestrator ran the security review.
- review: Security reviewer: non-blocking, the archived spec requirement omits the dot-segment, https-only and text-only rules the code enforces; left as the approved delta.

## Final review

- None.

## Finishing

- final: scope: all four phases stayed inside their touches lists, no out-of-scope path and no collision; the fix round has no touches list and was not scope-checked.
- final: fix round: 5 fixed, 3 declined
- final: fix round changed record.py so the issue_url agreement rule runs only for a same-repo issue_url (one error, as plan 3.1 says); the playbooks/board.md prune sentence now names a separately installed older CLI.
- final: declined: the archived spec stays as approved (closed change); the bounds test already runs in the fast run; CI already installs Node, Playwright and Chromium for the slow tests.
