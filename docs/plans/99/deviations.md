# Deviations: reflektor-page-allow-mark

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-page-code

- worker: worker ran with system python3 (no .venv) and without tld, so the orchestrator ran the roles and the docs-index check
- review: security-reviewer found that the swap can expose a token glued to the mark; prepare_page now runs the full verify_html on the neutral page (plan 3.2 said report_check.check); mutant RF6 added
- retry: phase sent back once for the security finding above
- review: verify_after_merge pytest names tests that p2 and p3 create, so after p1 only the existing files were run, plus the full fast check

## p2-page-note-command

- pending

## p3-playbooks

- pending

## p4-docs-spec-retire

- pending

## Final review

- pending

## Finishing

- pending
