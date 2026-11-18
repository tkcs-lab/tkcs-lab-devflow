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

- worker: worker reported blocked: the D4 matcher is an unanchored regex, so the two planned negative matcher rows (ScheduleWakeupX, mcp__github__add_issue_comment_x) cannot pass; the worker left those two rows out and kept the D4 matcher string exactly
- review: orchestrator accepted the two dropped rows and the unanchored matcher as the plan words it; security-reviewer: 2 non-blocking findings (RecursionError in execute, timer and worker tool names accepted from any MCP server); left as is

## p4-playbooks

- worker: step 8 sentence Add the item first placed before On requested changes, not after it, so it precedes the worker start; no tld in the worker, orchestrator ran the roles
- review: security-reviewer: 5 non-blocking wording findings (the no-record clause also appears in make-plan step 3; timer sentence placement; next_check_at wording still says armed check-in; --add titles need quoting; gate sentence placement); left as the plan words them

## p5-retire

- worker: none beyond the orchestrator note: hooks.md also states the unanchored matcher and any-MCP-server tool names as built; worker had no tld, orchestrator ran the roles
- review: security-reviewer: 3 non-blocking doc findings (gh pr create not listed, isError claim true only for MCP calls, stop chain bound is two blocks not three); left for the final review

## Final review

- pending

## Finishing

- pending
