# Deviations: admin-policy-inheritance

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-policy-model

- worker: worker reported none; it chose to ignore unknown top-level keys in key_errors (schema reports them)
- retry: sent back twice after the security review: derive_logins let the agent account become the release reviewer (case, owner login unchecked, trailing newline in login pattern); fixed with fullmatch, casefold and a reviewer-equals-agent rule
- review: security notes for later phases: clamp RUN_ONLY/ORG_LEVEL keys in apply_override, fail closed on odd guarded values, guard release.reviewer_login against the agent login, 39 char login cap, anchor schema login patterns with \Z (p4)

## p2-detect-pure

- pending

## p3-extends

- pending

## p4-schema-kinds

- pending

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
