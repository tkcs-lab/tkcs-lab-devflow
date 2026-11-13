# Deviations: usage-monitor

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-store-api

- None.

## p2-cli

- review: Worker hardened the parser (finite numbers, Path.read_text, RecursionError) in a commit after the security review; the role was not rerun, the changes only address its non-blocking findings and the full suite passed.

## p3-page

- review: Worker pinned choices the plan leaves open: a window counts for the verdict when resets_at is not older than the range, usageAgo returns no "ago" (the page adds it), the Max bar is last_standard divided by factor, column titles use browser local time.

## p4-collect

- scope: evals/fixtures/commands.py
- review: Brief gap: the eval step needs a usage branch in evals/fixtures/commands.py, which was not in touches; the worker stopped, the orchestrator approved adding only that branch. The evals baseline refresh also updated the hashes of the 12 existing commands (new policy text).
- retry: Worker was sent back once (blocked on the brief gap above) and then completed the phase.

## p5-retire

- None.

## Final review

- final: p1-store-api: docs/guides/board-server.md "Usage readings" lacked the plan 3.9 caveats and a description of the #usage page; fix worker fix-1 adds them.

## Finishing

- pending
