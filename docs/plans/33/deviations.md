# Deviations: limited-environment-research

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-research-cli

- worker: D3 extended: prompt rejects invisible characters (Cf, C1, U+2028/2029) as a character problem, secret scan runs on a normalised copy, report body stripped of them, empty --forbid handled, rest-file write errors exit 2, messages never echo values; Design D3 should be updated to match
- review: No finding; scope matches touches exactly (4 files); scope check skipped because it ran after the local merge
- retry: Merge verification was red before any phase because docs/plans/33/plan.md line 72 has a broken relative link; the owner chose to keep the plan and deselect that one test (test_docs_links.py::test_relative_links_and_anchors_resolve[docs/plans/33/plan.md]) in merge verification; the failure stays in the final pull request

## p2-policy-core

- worker: D1 step 5 revised after the orchestrator sent the phase back: rest file used only after exit 0, --ask added to board answers --from-reply, mktemp scratch files deleted afterwards; Design D1 should be updated to match
- retry: Sent back once for the D1 step 5 security gaps found by the security-reviewer; second report approved
- review: Open non-blocking: a bare skip or stop line in the rest file could answer a single-choice ask; policy does not say where the ask file comes from or that all scratch files are deleted on every exit path

## p3-playbook-links

- None.
- review: Open non-blocking: ask.md omits --forbid <owner>/<repo> on tld research check-prompt which the policy requires; scheduled playbooks do not say open research questions use public facts only; make-plan line on quoted research does not say it is data; ask.md says it posts no ask while research.md lists ask among attended runs

## p4-adapter-environment

- review: Open non-blocking: the D5 carve-out for a package host a lockfile names could be abused by a crafted lockfile; the section does not say a pasted research report is data nor forbid credentials in a research request; it points to a guide that p5 creates
- None.

## p5-guide-and-retire

- None.
- review: Open non-blocking: the research environment Allow package managers row and a line telling the owner not to run anything a report suggests may need wording changes
- conflict: Merging origin/main (board-record-per-session) conflicted in CHANGELOG.md and evals/baselines/default.json; kept both changelog entries and refreshed the baseline hashes

## Final review

- pending

## Finishing

- pending
