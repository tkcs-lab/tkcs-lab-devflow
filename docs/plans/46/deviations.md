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
- review: Continuation of the residual-risk entry above (item 5 and 6): the dynamic-URL check skips words by curl option table, also for wget, http and xh; gh api grouped short options (-if) are read as a field-less GET and can dispatch with dry_run false or skip_checks true. All owner-accepted on the board.

## p4-release-prepare

- worker: The coverage acceptance command fails as written (pyproject source_pkgs makes the total cover the whole package, 4.2%); the module itself measures 98.4% branch coverage, and the orchestrator confirmed 98.40% with --cov-config=/dev/null.
- worker: release-prepare --check --base diffs the working tree against git merge-base REF HEAD, not REF...HEAD, so the playbook can run it before the commit; the plan text says REF...HEAD plus git status.
- worker: After the security review (3 blocking, fixed): each changed version file must equal its base blob with only the version replaced; diff lines are taken after the first @@ only; a REF starting with a dash is rejected; renames are shown as an added and a deleted path (--no-renames).
- worker: With no version argument the command also refuses an empty unreleased section, so a release of nothing is caught early.
- review: Orchestrator checks: roles verify exit 0 (round 2 blocking=0), full suite after the merge 4480 passed, scope check clean. Open non-blocking findings: the profile is read from the PR head; the check reads the working tree, not the committed head; CR handling, a trailing space in a porcelain path, a ref with a leading space; running from a subdirectory; mode-only changes.
- review: Final review: not stated in the plan, added by the worker: extra usage errors (--check needs --version, --check cannot be combined with --write or --bump, --write needs --version or --bump), a --date shape check and an is-outside-the-repository path confinement.
- retry: fix-1 (final review round 1, blocking): release-prepare treated --version patch|minor|major as --bump; now any non-X.Y.Z --version exits 1 with "<v> is not X.Y.Z" (plan 3.5). Fixed in 5eb006f, roles ok, suite 4626 passed. Open non-blocking: SEMVER accepts a trailing newline and non-ASCII digits.

## p5-release-skill

- worker: The skill description is wrapped in double quotes (the brief text contains a colon-space that breaks YAML). Playbook step 2 says "Create the branch chore/release-<X-Y-Z>" instead of a git checkout -b span, because tests/adapters/claude/test_hooks_compat.py rejects the placeholder inside a git span.
- worker: The evals baseline hashes were refreshed as the brief allows (playbooks linked by recorded commands changed; no recorded task is affected).
- review: Orchestrator checks: roles verify exit 0 (blocking=0, 7 non-blocking), scope check clean, full suite after the merge 4502 passed, evals check-baseline exit 0. Open non-blocking findings: main can move between the post-merge check and the dispatch; changelog text is pasted into the PR body and the ask; the newest-run lookup can match another actor run; log lines are shown verbatim; the version input has no format check in the playbook (release-prepare checks it); the merged head of the release PR
- review: Continuation of the findings entry above: the merged head of the release PR is not compared with the pushed head; the structural tests of the playbook are line-based.

## p6-docs-reference

- worker: The docs describe the merged guard (exact dry_run true, skip_checks must be exactly false, no curl or gh api --input dispatch, no dynamic or glob words), not the plan section 3.4 design; they do not list the open findings and say the owner merge and publish approval are the controls. A workflow under another name is guarded only once the profile names it (the hook guards the names the profile lists).
- review: Orchestrator checks: roles verify exit 0 (round 2 blocking=0; round 1 had one blocking, fixed), scope check clean, full suite after the merge 4502 passed, evals baseline current, docs index 0 errors. The first acceptance grep only hits the plan own brief. Out of scope for this phase: README.md:81, docs/guides/git-ops.md:10 and docs/guides/admin.md:236 still say the owner runs the release by hand.

## p7-retire

- review: Orchestrator checks: roles verify exit 0 (blocking=0), scope check clean, full suite after the merge 4503 passed, evals baseline current, docs index 0 errors; the three acceptance greps run by the orchestrator (one index row, tld:release in README, one Added heading). The guide and changelog follow the merged guard, not the plan wording. Stale wording left: docs/guides/git-ops.md:10 and docs/guides/admin.md:236 (outside every phase touches).

## Final review

- final: Round 1 (changes, 1 blocking): tld ops release-prepare --version minor|patch|major was treated as --bump; the plan says exit 1 with minor is not X.Y.Z. Sent to fix-1.

## Finishing

- pending
