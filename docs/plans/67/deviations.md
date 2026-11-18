# Deviations: board-upkeep-enforcement

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-items-cli

- worker: none; worker ran tests with system python3 (no .venv) and had no tld, so the orchestrator ran the roles
- review: security-reviewer: 3 non-blocking findings (depends_on not validated, RecursionError exits 1, raw ids echoed in error text); left as is

## p2-gate-core

- worker: the brief negative test for grep board ask with an id-like output line was not written: the mandated ASK_COMMAND regex matches that command, so it counts as an ask; worker had no tld, orchestrator ran the roles
- review: security-reviewer: 3 non-blocking findings (RecursionError in _is_record, fixed tmp file name in _save, record write applied before a change in one command gives a spurious dirty block); left as is

## p3-gate-adapter

- pending

## p4-playbooks

- pending

## p5-retire

- pending

## Final review

- pending

## Finishing

- pending
