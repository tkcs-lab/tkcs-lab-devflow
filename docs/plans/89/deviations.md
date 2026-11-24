# Deviations: deps-combined-pr

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-deps-prepare

- worker: merge-tree: only exit 1 is does-not-apply, other non-zero exits raise an error; a T type change is unexpected-change; .env.example and siblings exempt from every protect entry; lock_entries takes an optional resolved argument; test profiles set deps.cooldown_days and time_budget_minutes explicitly; the "no trusted copy" test moves refs/tld/trusted.
- review: Security review found three blocking issues; the rename-into-protected-path and case-folding ones were fixed (post-merge path-set check, NFC and casefold matching).
- retry: p1 was sent back once after the security review and re-run; the second review had no blocking finding.
- review: Accepted by the owner (ask a-3f7eeb33d2bf0e46): a tld-deps/* work ref skips the bot-identity check for its whole history, as plan 3.1 says; the workflow blob comparison and owner review remain the controls.
- review: Non-blocking, open: lockfile classification and a few Unicode or trailing-dot aliases are not case-folded; the post-merge path check requires equal sets, so an overlapping group may be left out as does-not-apply. Plan 3.1 should mention that check.
- review: tests/mutation/run_mutants.py deselects slow tests, so mutants whose tests are all slow count as killed; all p1 mutants were killed with a loop that includes slow tests. Needs a fix in another phase.

## p2-deps-body

- pending

## p3-deps-eval

- pending

## p4-deps-playbook

- pending

## p5-retire

- pending

## Final review

- pending

## Finishing

- pending
