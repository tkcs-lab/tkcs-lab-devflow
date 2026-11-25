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

- pending

## Final review

- pending

## Finishing

- pending
