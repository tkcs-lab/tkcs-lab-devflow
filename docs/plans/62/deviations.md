# Deviations: worker-toolkit-protected-changes

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-gate-and-messages

- worker: none
- review: security review (non-blocking): hooks.md still says the profile deny text mentions /setup, and the WORKER_TOKEN comment says first line while the regex matches any line (as plan 3.3 specifies)
- retry: tld unavailable in the worker session: the orchestrator ran the roles and the roles verify step itself

## p2-manifest-protected-touches

- worker: none
- review: security review (non-blocking): the warning does not normalise ".." segments or a leading "/", leaves out the always-protected and guarded-workflow patterns, trusts a non-mapping profile, and prints the touches entry raw; the guard still blocks the write in every case
- retry: tld unavailable in the worker session: the orchestrator ran the roles and the roles verify step itself

## p3-worker-preamble

- worker: none
- review: security review (non-blocking): the ls glob fallback trusts a binary by version only; the preamble gives workers a working tld including allow-* guard commands; the path and title are not validated; the tests check only a few phrases
- retry: tld unavailable in the worker session: the orchestrator ran the roles and the roles verify step itself

## p4-protected-changes-policy

- retry: send-back: the security review found 6 blocking gaps in the policy text (pinned base SHA, branch reuse and post-write check, excluded paths, exact-path check, mechanical feature-branch check, full-diff display); worker asked to fix inside the phase touches

## p5-implement-and-make-plan

- pending

## p6-retire

- pending

## Final review

- pending

## Finishing

- pending
