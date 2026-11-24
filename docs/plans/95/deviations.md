# Deviations: plan-handover-card

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-record-handover

- worker: Worker reported none; fixture summary has 46 words instead of about 60, and a non-string next_command gets the existing prefix message.
- retry: Sent back once: the security review found that the repo pattern let a trailing line break through into handover links; fixed with fullmatch and a repo check in handover_errors, plus mutant REC-H7.
- review: Non-blocking, left for the pull request: Cn and Zs spoofing in summaries, the renderer must escape the summary, schema link patterns, other older REPO.match and DOC_ID_RE.match uses.

## p2-plan-handover-cli

- worker: Worker reported no deviations.
- retry: Sent back once: the security review found that a secret-scan:allow marker in the Summary skipped the secret scan and that link fields were not scanned; fixed in handover.py, with the docs row and the hit message updated.
- review: Non-blocking, left for the pull request: errors from the Summary check and a bad --repo can echo input text on stderr (never stdout or the board). One unrelated test, test_report_slots, failed once under load and passed on rerun.

## p3-board-plan-ready

- worker: Worker reported no deviations.
- review: Non-blocking, left for the pull request: the browser does not re-check the shape of the repo name before building link patterns; the server already enforces it on every write.

## p4-playbook-handover

- pending

## p5-retire

- pending

## Final review

- pending

## Finishing

- pending
