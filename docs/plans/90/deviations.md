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

- pending

## p8-defaults-playbooks

- pending

## p9-survey

- worker: touches: src/tld/profile/validate.py and tests/core/test_validate_profile.py (orchestrator-approved): the bot-versus-code-owner check is now case-insensitive
- retry: sent back once: the survey could propose the bot login as a code owner when no base supplied it; fixed with the repository own profile as a second source, case-insensitive filtering, a cap of 50 owners and a verified tld.extends edit
- review: open for p10 and the final review: deps.audit and deps.lock_freshness proposals must stay owner-confirmed items; the base bot login is ignored when the own profile sets another; a leading @ in bot_login is not normalised

## p10-setup-playbook-evals

- pending

## p11-migrate

- pending

## p12-admin-profile

- worker: touches: docs/guides/admin.md got minimal rows for the new policy keys and check (orchestrator-approved, p14 rewrites); three existing admin tests needed them
- review: reviewer notes the starter admin policy has the profile and git_ops sections active with placeholder org names, where the plan asks for commented examples; left for the fix round or the final review

## p13-admin-gitops-secrets

- pending

## p14-retire

- pending

## Final review

- pending

## Finishing

- pending
