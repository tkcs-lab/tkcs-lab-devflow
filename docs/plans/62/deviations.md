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
- retry: second send-back: the re-review found 2 blocking gaps (rename detection in the feature-branch check, excluded paths missing from it); worker asked to fix with the non-blocking hardening items
- worker: none
- review: third security review (non-blocking): patch should be forced to unified format, the secret scan floor is not named, the post-write path listing needs --no-renames, the file mode at the pinned SHA is not checked, lockfile hits of the feature-branch check are blocking even for a deps phase
- review: follow-up outside this plan: protect-paths does not cover MCP file writes (create_or_update_file, push_files); the policy relies on a mechanical diff check instead

## p5-implement-and-make-plan

- worker: none
- review: security review (non-blocking): the Merge step 2 protected-path check is a manual glob match (no deterministic command); the lockfile exemption relies on the worker word and contradicts the policy and final reviewer line; step 3 and the fallback use the working-tree profile, not the main profile; the fallback run_role call omits the role fields; tests miss the safety words; no tld-unavailable fallback for the final reviewer; two meanings of protected path
- review: orchestrator addition to the brief: the Merge step 2 check uses git diff --name-only --no-renames against the effective protect list plus the policy excluded paths (from the second p4 review)
- retry: tld unavailable in the worker session: the orchestrator ran the roles and the roles verify step itself

## p6-retire

- worker: none
- review: changelog line for validate-manifest says warns about instead of rejects (the plan text said rejects; p2 added a warning only), set in the worker brief
- retry: tld unavailable in the worker session: the orchestrator ran the roles and the roles verify step itself

## Final review

- final: blocking (p4/p5): the lockfile rule differed between the policy, Merge step 2 and the final reviewer line; one rule is written in all three places by fix-1
- final: blocking (p4/p5): .env.example and the profile allow list were caught by the protected-path checks; the allow lists are subtracted in the policy and Merge step 2 by fix-1
- final: the p4 send-backs changed the design in these named ways: apply is not recommended for a workflow or profile diff; the pull request for a workflow path is a draft; a mechanical feature-branch check was added before a pull request is opened; file_put takes the recorded blob id as sha instead of reading it from the target branch; the base SHA is pinned; the branch is checked after the write

## Finishing

- pending
