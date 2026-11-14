# Deviations: question-review

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-board

- worker: The worker also capped the limit parameter at four characters before converting it, after a security-review finding, and added a test for a very long digit string.
- worker: The worker ran without the toolkit root and the venv, using the repository cli and system python; the full suite passed on the merged branch here.

## p2-digest

- worker: The worker added input hardening after a security review: ids must fully match the board id pattern, unknown question kinds and malformed fields are skipped, input is length-bounded before masking, backslash tokens count as paths, and main exits 1 if digest raises.
- review: No deviation from the plan text in the diff. Open worker findings for later phases: the playbook must always pass the vocabulary option and treat qid as data; the email pattern is quadratic on hostile input, kept as the plan spells it.
- retry: No retry; the worker reran the security role once after fixing blocking findings itself.

## p3a-policy

- None.
- review: No deviation in the diff. Worker notes for p3b and p3c: the questions playbook must push only review/questions branches, and review apply must write the record only when status_record equals the computed record id.

## p3b-command

- worker: Design change: the playbook and the document report the own total (analysed plus open_asks plus excluded_questions_asks) instead of the digest top-level asks count, and leave foreign_count out of the fields it reads, because asks and foreign_count carry other projects volume and plan section 3.6 forbids showing it. Plan section 3.6 text that puts asks in What was reviewed is therefore not followed.
- worker: Added hardening lines the plan lacks: format checks for the review/questions branch name, asks_until and decisions_ask, a timestamp-form check on the input since and the record cursor passed as one quoted argument, and a note that the helper brief carries finding ids and Where lines only.
- review: The security role was not re-run after the last wording edits of the worker; the final review runs it again. Residual risk accepted for now: a forged review/questions branch can steer a run (stop or widen the window) without leaking data.

## p3c-review-header

- pending

## p4-retire

- pending

## Final review

- pending

## Finishing

- pending
