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

- worker: Stricter than the plan: a release dispatch is denied if any skip_checks value is not exactly false; dry_run counts as true only for the exact value true (not 1, yes, on); gh api --input is denied for the release workflow; dynamic or glob words are denied even with the marker; gh workflow run, gh api and curl endpoints are normalised (percent-decoding, dot segments, slashes, fragments, api/v3 prefix).
- worker: The workflow argument of gh workflow run is the first positional word, and a curl URL built from a variable is denied for dispatch and tag calls; curl bodies as attached or clustered options are treated as unreadable. The release-confirm.json marker was added to the protected-marker test.
- gate: Owner approved on the board: the release dispatch code moved to a new module src/tld/guard/_release_dispatch.py (size cap), and the expected --end-allow string in tests/core/test_hook_protect_paths_setup.py was updated.
- retry: First worker stopped blocked (size cap, an outdated test string, open security findings); a follow-up worker finished the phase.
- review: Worker admitted reading some required docs only in part; the orchestrator ran the full suite after the merge (4412 passed).
- scope: scope: src/tld/guard/_release_dispatch.py and tests/core/test_hook_protect_paths_setup.py (outside touches; owner-approved, see gate entry)
- review: ROLES GATE NOT PASSED, OWNER-ACCEPTED: a read-only security review of 23f11f8 reported blocking=6 non_blocking=12, so tld roles verify exits 1 for this phase. The owner chose accept on the board and the merge went ahead. Blocking: (1) curl -d@f and -sd@f bodies pass the git/refs exemption; (2) curl unique long-option prefixes (--data-r, --data-b, --upload-f) read as GET; (3) curl -K config file hides URL and body; (4) curl glob ranges hide keywords; (5) the dynamic-URL check skips words by curl 
- review: Non-blocking findings of that review, owner-accepted residual risk: raw-word tag endpoint match (dot segments, percent escapes); JSON-escaped ref in a git/refs body; gh api --input body not read; GraphQL createRef on a tag; repositories/<id> API alias; case-sensitive workflow names; encoded path as workflow id; older MCP tool name run_workflow; curlrc and wget -i planted config; dispatch ref not constrained to main; release.workflow not yet in the profile (manual step ma1); gh run rerun in Bash.

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
