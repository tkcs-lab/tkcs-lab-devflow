# Deviations: admin-policy-inheritance

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-policy-model

- worker: worker reported none; it chose to ignore unknown top-level keys in key_errors (schema reports them)
- retry: sent back twice after the security review: derive_logins let the agent account become the release reviewer (case, owner login unchecked, trailing newline in login pattern); fixed with fullmatch, casefold and a reviewer-equals-agent rule
- review: security notes for later phases: clamp RUN_ONLY/ORG_LEVEL keys in apply_override, fail closed on odd guarded values, guard release.reviewer_login against the agent login, 39 char login cap, anchor schema login patterns with \Z (p4)

## p2-detect-pure

- worker: tag_workflow_creates_release uses a one-pass line scanner instead of the regex stated in plan 3.9, which backtracked exponentially on ordinary push workflows
- retry: sent back once after the security review for the exponential regex; the second review passed with no findings
- review: security notes for later phases: release_params should ignore tag prefixes outside the safe-parameter pattern; required check names can come from any source (name-only, as today); pr_notes output must go through _cell escaping in the PR body writer, with a test

## p3-extends
- worker: a base file in an internal repository counts as public even when the API says private, and a missing or non-boolean private also counts as public (the plan contradicts itself; the fail-closed reading was chosen and tested)
- review: security review passed with four non-blocking notes: sanitise key names in fetched-base error messages, cap the read size before parsing and check UTF-8 on raw bytes, latest_pin should skip tags that are not ancestors of the default branch, more fail-closed tests (internal visibility, ahead or diverged compare, non-text answer, oversize file)


## p4-schema-kinds

- worker: login, org, environment and workflow dest patterns in the schema now end in a portable end-of-string lookahead instead of $ (a trailing newline is rejected); validate_policy raises ValueError for an unknown kind
- retry: sent back once after the security review: workflow_params.release and override workflow params could set main_branch or the release environment; now limited to the four plan-listed keys; the second review passed
- review: security note for a later phase: repos.override_path should be allow-listed and URL-quoted where the contents API path is built

## p5-cli-resolve

- pending

## p6a-per-repo

- pending

## p6b-policy-check

- pending

## p7-derive-detect

- pending

## p8-reproduce

- pending

## p9-mutants

- pending

## p10-playbook-docs-evals

- pending

## p11-retire

- pending

## Final review

- pending

## Finishing

- pending
