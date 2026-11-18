# Deviations: openspec-integration

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-profile-spec-key

- worker: none; the worker ran python3 in place of .venv/bin/python because no venv existed there
- review: schema block placed before admin instead of directly after land; no behaviour change
- review: security review (non-blocking): schema pattern accepts a trailing newline and non-ASCII digits; the wrapper re-checks, see p2

## p2-ops-spec-cli

- worker: none; the worker used system python in place of .venv/bin/python; smoke step ran against real OpenSpec 2.1.0: all flags accepted, nothing outside openspec/ written, tasks.md not required, an empty change fails validate unless it has a delta
- review: security review, 7 non-blocking findings left open: non-ASCII digits pass the version pattern, partial npm install tree is trusted, node/npm resolved by bare name, raw id in stderr, YAML errors reported as a missing key, grandchild processes survive the timeout, transitive dependencies float (accepted in the plan)

## p3-manifest-spec-change

- worker: none
- review: security review, 3 non-blocking findings left open: a phase without touches is not fenced out of openspec/, touches entries with .. or absolute paths are not rejected, a non-mapping profile gives a traceback

## p4-spec-record

- worker: none

## p5-spec-command

- retry: sent back once: the first review found init would destroy uncommitted work in a dirty tree; fixed by stopping before branching
- worker: none
- review: security review, open and non-blocking: plan_gate opens a write session for spec check as well as init; init marks the checkout exempt from the definition-of-done gate; the capability list is validated for the reply but not stated for the proposal when the reply is ok; the TBD stop wording says to list it in the pull request though no pull request opens

## p6-plan-playbooks

- worker: none
- review: security review, 3 non-blocking findings left open: the slug in the git rm snippet is not checked, the main-spec comparison in the retirement brief does not fetch first or fail closed, and the fix-worker exception for openspec/ rests on the session grouping findings

## p7-docs-lists

- pending

## p8-retire

- pending

## Final review

- pending

## Finishing

- pending
