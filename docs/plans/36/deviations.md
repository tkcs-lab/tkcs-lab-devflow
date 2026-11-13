# Deviations: review-summaries

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-summary-check

- worker: none reported; worker read four D1 gaps one way each (text-before only when placement is right; None. on Scope gives two lines; one line per near-miss heading; echoed offending line is raw)
- review: acceptance 1 (coverage with fail-under 100) cannot pass as written because the project coverage config measures all of tld; summary.py alone is at 100 percent
- retry: first merge failed the full suite (module-run test needed the package on the path); sent back and fixed in the test
- review: security review left four non-blocking findings (hidden-markup forms not covered, unbounded output, symlink and FIFO read, long-token word cap); listed in the pull request body

## p2-playbooks

- worker: none reported; step 6.3 of implement was reworded so the body and its check come before the pull request is created
- review: security review left six non-blocking findings (ask text not scanned for hidden markup, untrusted inputs not named as data, security rule judgement only, single-session check without deviations file, scratch file creation, ordering tests anchored on first mention); listed in the pull request body
- retry: final review sent step 6.3 back once with two blocking findings: the phase list needed its own Phases heading and the pasted deviations headings had to be demoted (fix-1)
- worker: fix-1 added a rule the plan did not make: when a pull request template has its own Summary heading it is merged into the checked Summary or left out (two Summary headings fail the check)
- review: owner chose polish after the second final review: fix-2 reworded the reason in step 6.3 and tightened three test items; no third full review ran after it

## p3-docs-retire

- None.

## Final review

- final: blocking: implement step 6.3 pastes the deviations file with phase headings that the pull request check reads as near-miss Summary headings (p2-playbooks)
- final: blocking: implement step 6.3 puts phase list, checklist and review verdict right after the Summary with no heading, so the check counts them as Summary text (p2-playbooks)
- final: blocking (second review): the template Summary rule added by fix-1 was missing from the deviations file; recorded under p2-playbooks (p2-playbooks)

## Finishing

- scope: scope disposition: no out-of-scope paths in any phase or fix; nothing accepted or reverted
