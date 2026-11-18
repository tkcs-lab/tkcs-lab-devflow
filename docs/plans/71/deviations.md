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

- pending

## p4-spec-record

- worker: none

## p5-spec-command

- pending

## p6-plan-playbooks

- pending

## p7-docs-lists

- pending

## p8-retire

- pending

## Final review

- pending

## Finishing

- pending
