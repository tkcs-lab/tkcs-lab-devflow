# Deviations: org-base-profile

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-defaults-merge

- worker: none reported by the worker
- retry: sent back once: clamp let the security posture fall below the default branch value when the default writes no posture; fixed, with three small hardening changes in the same files

## p2-base-fetch

- worker: design 3.2: a pin is accepted only if it is a version tag commit or an ancestor of the default branch head (needs a full fetch of the head); the changelog line for tld profile base was left out because CHANGELOG.md is outside touches
- retry: sent back once: a fetch by SHA also serves commits that only a pull request head holds; fixed by the tag or default-branch rule, plus checking the base text before caching, verifying the blob id and a bounded tag pattern

## p3-schema-validate

- worker: none reported by the worker
- review: worker added two rows to docs/reference/profile-reference.md (outside touches) on the orchestrator's approval so the docs test passes until p14

## p4-resolve

- worker: none reported by the worker
- retry: sent back once: a --ref value starting with a dash was read by git as an option; fixed by resolving the ref to a commit hash first, with three smaller hardening fixes in resolve.py
- final: the test that keeps the profile modules small gives base.py a bound of 600 lines (it has 574) instead of the 480 of the p4 brief, because base.py was already over 480 lines when p4 reached it and no phase splits it; accepted by the orchestrator as a size-hygiene limit with no safety effect, to be split in a later change

## p5-hooks

- worker: touches: tests/core/test_validate_manifest.py (orchestrator-approved: manifest tests moved to a listed-profile fixture because the profile and ordinary workflows are no longer protected by default); evals/stubs/release-head-moved.json head updated because the tiny_app profile changed
- review: design addition to 3.4/3.5: dod-gate reads verify.dod and max_attempts from the trusted copy (working copy only when no trusted copy), because the profile is no longer protected and verify.dod is run with a shell at Stop
- retry: sent back three times by the security review: malformed gate values bypassed the clamp, dod-gate ran the working-tree verify.dod, and a malformed verify value crashed dod-gate so Stop did not block; all fixed
- review: open, left to the owner and final review: the trust lookup also runs in repositories that never had a profile; with an origin but no reachable trusted copy the working-tree verify.dod runs; a trusted profile that is empty or not a mapping falls back to the working copy

## p6-summary-protect-playbooks

- worker: none reported by the worker
- retry: sent back twice by the security review: the Security-line check could be bypassed with markup hiding the path (first inside the value, then across labels) and the make-plan pull request path had no changed-files check or test; fixed, with the check now refusing risky markup anywhere in the Summary when a workflow or the profile changes
- review: open for the final review: strikethrough opened and closed across labels is not refused; the cli reference and module docstring do not describe the whole-Summary refusal

## p7-cli-readers

- worker: touches extended (orchestrator-approved): spec and sysml call and playbook tests, playbooks/spec.md and sysml.md stop-message lines, two eval stubs, evals/fixtures/commands.py, baseline hashes, resolve.py (base-missing flags), base.py (tld profile base fetch --ref) and test_profile_resolve.py
- retry: sent back once: with the default branch base uncached, tld roles required silently dropped the roles the base requires; fixed with structured base_missing and trusted_base_missing flags that stop the run, plus a fetch --ref remedy
- review: open for the final review: roles required has no trusted floor when no default-branch copy is reachable; the stop hint names origin/<branch> rather than the trusted ref; deps_prepare and release_prepare still use the current directory or ignore a missing base; resolver error text is not escaped; one flaky board listener test

## p8-defaults-playbooks

- worker: none reported by the worker
- review: open for the fix round: the git-ops, land and repo-admin playbooks do not say what to do when the resolved profile lacks git_ops.repo, land.max_prs or admin.policy because the off switch false is removed from the resolved profile; the starter template comments and one fixture docstring still describe missing-key stops

## p9-survey

- worker: touches: src/tld/profile/validate.py and tests/core/test_validate_profile.py (orchestrator-approved): the bot-versus-code-owner check is now case-insensitive
- retry: sent back once: the survey could propose the bot login as a code owner when no base supplied it; fixed with the repository own profile as a second source, case-insensitive filtering, a cap of 50 owners and a verified tld.extends edit
- review: open for p10 and the final review: deps.audit and deps.lock_freshness proposals must stay owner-confirmed items; the base bot login is ignored when the own profile sets another; a leading @ in bot_login is not normalised

## p10-setup-playbook-evals

- worker: touches extended (orchestrator-approved): src/tld/profile/base.py and tests/core/test_profile_base.py (source pattern narrowed to safe path characters), eval graders and tasks beyond the listed files
- retry: sent back twice by the security review: the eval ask counter missed real asks, the no-tests task rewarded a guessed command, safety rules were not graded and the base source was pasted into a shell command; all fixed
- review: OWNER DECISION NEEDED: setup copies commands found in CI into verify.fast and verify.dod without a confirm and runs verify.fast before the pull request exists; the plan asks only when something is missing, the review says a command found in repository files should be confirmed first
- review: open for the fix round: ask counter counts a read-only mention of tld board ask and misses indirect forms; Not verified text check is weak; the starter template comments are out of date

## p11-migrate

- worker: touches: tests/core/test_evals_graders.py (orchestrator-approved) for the negative test of the dry-run eval
- retry: sent back three times by the security review: the rename rewrote command and workflow files, protected files and agent command files; repository text could forge the ask; the dry-run eval allowed asks; a failed move left a staged half-moved directory; all fixed with a protect check, a snapshot with rollback and escaped output
- review: open for the fix round: SIGTERM during a move leaves a half-moved tree; an unrelated change already staged is committed by the playbook; plugin command files without front matter can be rewritten; a dead attribute in the profile resolution check

## p12-admin-profile

- worker: touches: docs/guides/admin.md got minimal rows for the new policy keys and check (orchestrator-approved, p14 rewrites); three existing admin tests needed them
- review: reviewer notes the starter admin policy has the profile and git_ops sections active with placeholder org names, where the plan asks for commented examples; left for the fix round or the final review

## p13-admin-gitops-secrets

- worker: touches: docs/guides/admin.md (orchestrator-approved) got one row for the new git_ops check
- retry: sent back four times by the security review: the allowlist rebuild dropped protections, over-broad and bash extglob entries passed unseen, repository names were compared case-sensitively and the owner fix could switch on every-repository or dangling entries; all fixed
- review: OWNER DECISION NEEDED: tld-git-ops.yml should read full_name from the target repository lookup and refuse unless it equals the requested repository ignoring case, because GitHub follows the old name of a renamed repository; this edits a guarded workflow so it was reported as a protected change and not applied
- review: open for the fix round: a wildcard entry can still match the old name of an excluded repository under a wrong owner; dangling allowlist entries get no finding of their own; the admin policy schema accepts any allowlist path while the code accepts one

## p14-retire

- worker: none reported by the worker
- retry: sent back twice by the security review: the docs presented the base floor as enforced by the hooks and understated what making the org .github repository public exposes; fixed and the wording checked against the code
- review: open for the fix round: SECURITY.md and hooks.md name only release.workflow as unprotected with an empty trusted profile and should also name git_ops.workflow

## Final review

- final: first final review: changes, one blocking finding (the 600-line bound for base.py was not recorded); recorded under p4-resolve

## Finishing

- pending
