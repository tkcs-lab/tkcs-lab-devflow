# Deviations: fix-round-and-quick

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-findings-check

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, four non-blocking (mention regex lets @0abc, .@a and -@a through; HTML check covers only comments and details; a near-miss heading turns the check off without --findings; invisible letters count as words). The code follows plan section 3.4; they are inputs for the fix round.
- level: Phase brief pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## p2-plan-gate-quick

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, two non-blocking (test asserts only before==after; the /tld:quick adapter path lands with p4).
- review: tests/core/test_docs_links.py fails on docs/plans/88/plan.md: its relative links to policies/findings-fix.md do not resolve from docs/plans/88/. The plan is protected; the owner decides.
- level: Phase briefs pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## p3-fix-round

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, four non-blocking, all in policy text the plan says to write as is (undo path of the fix merge, fix-worker brief lacks the plan-directory and no-merge rules, newline folding of finding text, location field copied into the PR body). Inputs for the fix round.
- review: The worker did not re-run the whole suite after its last fixes; the orchestrator did on the merged branch: 6638 passed, only the known plan-link test excluded.
- level: Phase brief pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## p4-quick-command

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, four non-blocking (step 6.3 pushes to the PR head without the protected-path check; an outsider-only issue gives an empty ask; the branch kebab from an issue title is not validated; pr-steward branch table omits quick). Inputs for the fix round.
- level: Phase brief pointed the worker at its manifest entry in the plan instead of pasting it verbatim, and asked for an adapter-level /tld:quick test (a p2 review follow-up).
- final: Final review (code-reviewer, blocking): the quick playbook never pushes the fix round merge before the protected-path check and the pull request, so the pull request would open without the fixes it lists. Sent to fix-1.

## p5-fix-round-eval

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: pass, no findings. One note: the new grader reads the first matching document instead of the worktree copy; the agent controls both, so no grade can be forged.
- level: Phase brief pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## p6-retire

- worker: none
- review: The worker could not run tld, so the orchestrator ran the security-reviewer: no blocking finding, two non-blocking (the duplicate-findings-section message is not in the archived spec; ask wording after the new /quick sentence does not say who starts the command). The orchestrator ran the spec, docs-index, sysml, baseline and full test checks on the merged branch: all pass except the known plan-link test.
- level: Phase brief pointed the worker at its manifest entry in the plan instead of pasting it verbatim.

## Final review

- final: Blocking: the fix round merge is not pushed before the pull request in quick (p4); fix-1 follows. Eleven non-blocking findings of the final reviewers go to the fix round.

## Finishing

- pending
