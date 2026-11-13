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

- pending

## p5-retire

- pending

## Final review

- pending

## Finishing

- pending
