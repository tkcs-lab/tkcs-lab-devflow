# Deviations: sysml-architecture

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-profile-sysml-key

- worker: none; one CHANGELOG.md line outside touches, as the rules require
- review: worker had no tld; orchestrator ran the security-reviewer role (pass), diff in scope

## p2-sysml-files

- retry: security-reviewer found 1 blocking (unbounded read; size limit checked after full read) and 7 non-blocking; p2 sent back to fix the blocking one plus depth/early-stop, name escaping, NUL, parent-vanished and test gaps
- review: accepted as follow-up, not fixed: TOCTOU between the lstat walk and the path-based use (needs a concurrent process; plan 3.3 fixes the lstat-walk design) and a write allow-list for the file layer (callers are fixed to sysml/ and docs/architecture.*)
- worker: see send-back entry; worker added bounded reads, depth cap 8, name escaping and extra tests beyond the first brief
- review: re-review: 0 blocking, 2 non-blocking left open (fstat before fdopen on a directory that appears after the walk leaks an fd; scandir listing is not capped for very wide trees)

## p2b-sysml-parse

- pending

## p3-sysml-model-check

- pending

## p4-sysml-change

- pending

## p5-sysml-layout

- pending

## p6-sysml-svg-markdown

- pending

## p7-ops-sysml-cli

- pending

## p8-manifest-sysml-change

- pending

## p9-sysml-record

- worker: none; one CHANGELOG.md line outside touches, as the rules require
- review: worker had no tld; orchestrator ran security-reviewer (pass); board_gate and plan_gate lists are p10 work

## p10-sysml-command

- pending

## p11-plan-playbooks

- pending

## p12-docs-lists

- pending

## p13-retire

- pending

## Final review

- pending

## Finishing

- pending
