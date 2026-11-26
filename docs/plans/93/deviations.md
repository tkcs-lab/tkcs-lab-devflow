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

- review: security review passed with two non-blocking notes: validate-policy --resolved or --explain with --offline on a run file that has extends shows the unresolved file as the effective policy (should refuse), and some network errors (timeouts, incomplete reads) escape as tracebacks instead of ApiError
- worker: worker reported none

## p6a-per-repo

- gate: owner decision on the board (ask a-dbab5fe8ade05cda): guarded keys the organisation omits stay unguarded as plan 3.6 says, so an override can loosen them; overrides of agent.agent_login, release.reviewer_login and release.environment are applied with a warning only, except that release.environment equal to the agent environment is always refused
- retry: sent back once after the security review: a reviewer equal to the agent login (case-insensitive) stayed in force when the organisation did not set that login; now both unset logins are dropped and the release check stands down; also one shared effective-policy function, restricted workflow entries, quoted environment names and a message-length fix
- review: worker Deviations line was not read by the orchestrator; security review notes left open: an override setting the agent environment gives two warnings with the same subject; the size limit applies after the whole override file is downloaded; the p7 phase must repeat the reviewer-vs-agent comparison after derive_logins; p6b must emit the recorded override problems and loosenings as findings

## p6b-policy-check

- worker: the generic away-from-organisation warning is skipped for the agent-environment drop (subject release:environment kept); extra override problems get subjects override:invalid:N; CHANGELOG.md was edited though not in touches; the optional refusal of equal logins in validate_policy was not added
- retry: sent back once after the security review: the keep-live rule dropped the integration_id of live required checks, and equal logins from the organisation side kept the agent as release reviewer; both fixed, plus # and & escaping in pull request notes
- review: open notes: # is escaped with a backslash only (a zero-width space like the @ handling would be safer, p7 puts repository text into notes); an override file is treated as absent when the default branch tree is truncated, so p7 must not propose to create it then; convert notes show only in the pull request body, not in the audit report

## p7-derive-detect

- worker: roles and dod playbook not run by the worker (tld unavailable); changelog and docs left to later phases
- retry: sent back three times after the security reviews: derived logins gave no finding naming them; the detected workflows proposal dropped the organisation repos scoping; the reviewer-versus-agent comparison was skipped without an agent section and trusted the profile own same-login reason; all fixed, third review passed
- scope: scope: tests/core/test_repo_admin_policy_check.py

## p8-reproduce

- pending

## p9-mutants

- worker: twelve extra mutants LG1 to LG12 for the safety rules (same-login check on the effective pair, override params limit, derived-login warnings, integration_id keep-live, agent environment drop, login patterns) beyond the plan list; the test files test_repo_admin_derive.py and test_repo_admin_kinds.py were added to the repo_admin.py tests map; every why names its killing test; tld unavailable for the worker
- scope: scope: tests/core/test_repo_admin_policy_check.py (one test added to kill the surviving mutant RB2)
- retry: blocked once on the surviving mutant RB2 and sent on with permission for one extra test; sent back once more after the security review to add the safety-rule mutants and name the killing tests; merged in two steps (head fdd8f6e then 757386e) because the first merge used a stale ref

## p10-playbook-docs-evals

- pending

## p11-retire

- pending

## Final review

- pending

## Finishing

- pending
