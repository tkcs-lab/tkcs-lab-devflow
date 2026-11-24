# Deviations: fix-round-and-quick

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-findings-check

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, four non-blocking (mention regex lets @0abc, .@a and -@a through; HTML check covers only comments and details; a near-miss heading turns the check off without --findings; invisible letters count as words). The code follows plan section 3.4; they are inputs for the fix round.
- level: Phase brief pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## p2-plan-gate-quick

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, two non-blocking (test asserts only before==after; the /tld:quick adapter path lands with p4).
- review: tests/core/test_docs_links.py fails on docs/plans/88/plan.md: its relative links to policies/findings-fix.md do not resolve from docs/plans/88/. The plan is protected; the owner decides.
- level: Phase briefs pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## p3-fix-round

- pending

## p4-quick-command

- pending

## p5-fix-round-eval

- pending

## p6-retire

- pending

## Final review

- pending

## Finishing

- pending
