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
- final: two small wrapper decisions the plan did not state: the node version probe has a 60 second timeout, and a node version with a pre-release or build suffix (such as 22.20.0-rc.1) is compared by its numeric part

## p3-manifest-spec-change

- worker: none
- review: security review, 3 non-blocking findings left open: a phase without touches is not fenced out of openspec/, touches entries with .. or absolute paths are not rejected, a non-mapping profile gives a traceback

## p4-spec-record

- worker: none

## p5-spec-command

- retry: sent back once: the first review found init would destroy uncommitted work in a dirty tree; fixed by stopping before branching
- worker: none
- review: security review, open and non-blocking: plan_gate opens a write session for spec check as well as init; init marks the checkout exempt from the definition-of-done gate; the capability list is validated for the reply but not stated for the proposal when the reply is ok; the TBD stop wording says to list it in the pull request though no pull request opens
- final: the spec playbook decides four things the plan did not: Deliver stages only openspec/ and stops when other paths are staged; no literal value (credential, key, hostname, URL, e-mail, account id) is copied into a spec or the pull request; a TBD hit after archive stops the run instead of a hand edit; the pull request subscription runs only when the runtime offers it

## p6-plan-playbooks

- worker: none
- review: security review, 3 non-blocking findings left open: the slug in the git rm snippet is not checked, the main-spec comparison in the retirement brief does not fetch first or fail closed, and the fix-worker exception for openspec/ rests on the session grouping findings

## p7-docs-lists

- worker: none

## p8-retire

- retry: sent back once: the first review found the guide overstated the reduced environment (HOME and proxy variables pass through, the package is not sandboxed); fixed in the guide
- worker: none
- review: security review, 2 non-blocking findings left open: the guide says the public registry although a scoped registry line in ~/.npmrc would override it, and says no tokens without naming credentials inside proxy URLs

## Final review

- pending

## Finishing

- pending
