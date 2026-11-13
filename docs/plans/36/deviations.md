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

## p3-docs-retire

- None.

## Final review

- pending

## Finishing

- pending
