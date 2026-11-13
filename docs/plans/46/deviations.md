# Deviations: release-skill

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-workflow-tests

- gate: Owner approved on the board extending the phase to tests/core/test_ci_workflows.py: the permission rule now lets only the build job of release.yml have permissions without an environment (contents read, checks read, packages write).
- retry: First worker stopped blocked on the out-of-scope test failure; a follow-up worker on the same branch fixed it.
- review: Worker admitted skimming some docs and not copying the plan acceptance items; the orchestrator ran all four acceptance checks and the full suite after the merge (4259 passed).
- scope: scope: tests/core/test_ci_workflows.py (outside touches; owner-approved, see gate entry)

## p2-release-profile

- worker: Added a path confinement (release.version_files paths must resolve inside the repository root, else the existing file-not-found error) and a 1,000,000 character read cap for version files; section 3.2 does not say this, the security reviewer required it.
- worker: One extra sentence in the release.version_files row of profile-reference.md: the pattern is trusted input, avoid nested quantifiers. Four mutants VP13 to VP16 added, all killed.
- review: Orchestrator diff review found nothing else outside the brief; full suite after the merge: 4272 passed. Open non-blocking: a catastrophic-backtracking profile pattern can hang profile validate (needs a plan decision).

## p3-release-dispatch-guard

- pending

## p4-release-prepare

- pending

## p5-release-skill

- pending

## p6-docs-reference

- pending

## p7-retire

- pending

## Final review

- pending

## Finishing

- pending
