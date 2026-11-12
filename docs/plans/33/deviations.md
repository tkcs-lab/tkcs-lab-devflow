# Deviations: limited-environment-research

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-research-cli

- worker: D3 extended: prompt rejects invisible characters (Cf, C1, U+2028/2029) as a character problem, secret scan runs on a normalised copy, report body stripped of them, empty --forbid handled, rest-file write errors exit 2, messages never echo values; Design D3 should be updated to match
- review: No finding; scope matches touches exactly (4 files); scope check skipped because it ran after the local merge
- retry: Merge verification was red before any phase because docs/plans/33/plan.md line 72 has a broken relative link; the owner chose to keep the plan and deselect that one test (test_docs_links.py::test_relative_links_and_anchors_resolve[docs/plans/33/plan.md]) in merge verification; the failure stays in the final pull request

## p2-policy-core

- pending

## p3-playbook-links

- pending

## p4-adapter-environment

- pending

## p5-guide-and-retire

- pending

## Final review

- pending

## Finishing

- pending
