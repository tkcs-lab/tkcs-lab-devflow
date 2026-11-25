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

- pending

## p6-summary-protect-playbooks

- pending

## p7-cli-readers

- pending

## p8-defaults-playbooks

- pending

## p9-survey

- pending

## p10-setup-playbook-evals

- pending

## p11-migrate

- pending

## p12-admin-profile

- pending

## p13-admin-gitops-secrets

- pending

## p14-retire

- pending

## Final review

- pending

## Finishing

- pending
