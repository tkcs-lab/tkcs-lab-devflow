# Deviations: plan-handover-card

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-record-handover

- worker: Worker reported none; fixture summary has 46 words instead of about 60, and a non-string next_command gets the existing prefix message.
- retry: Sent back once: the security review found that the repo pattern let a trailing line break through into handover links; fixed with fullmatch and a repo check in handover_errors, plus mutant REC-H7.
- review: Non-blocking, left for the pull request: Cn and Zs spoofing in summaries, the renderer must escape the summary, schema link patterns, other older REPO.match and DOC_ID_RE.match uses.

## p2-plan-handover-cli

- pending

## p3-board-plan-ready

- pending

## p4-playbook-handover

- pending

## p5-retire

- pending

## Final review

- pending

## Finishing

- pending
