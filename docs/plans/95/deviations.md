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

- worker: Worker reported no deviations of its own.
- retry: Sent back twice: first because a sweep test knows only the placeholder feature_branch with an underscore, so the playbook span was reworded; then for the owner decision below.
- gate: Owner decision (board ask): the secret scan of the Summary now runs at the end of section 4, before any commit, push or post, instead of at section 5 step 3 as plan 3.4 words it; step 3 writes the stored output. Also added: a retry cap, stop-and-rotate for published content, old-board fallback only for unknown-field errors.
- review: Non-blocking, left for the pull request: rerun the scan if the plan changes after it; do not hand-edit the handover object after a board error; the placeholder spelling feature_branch versus feature branch (the sweep test needs the underscore form).

## p5-retire

- worker: Worker reported no deviations of its own.
- review: Non-blocking, left for the pull request or the final review: the maintenance guide says a dismissed or old card moves to Done where the code and the spec say Hidden; the spec scenario for a secret in another field describes a message that the record rules pre-empt for the marker case; the changelog repeats the feature in three lines.

## Final review

- final: Blocking: the maintenance guide said a dismissed or old Plan ready card moves to Done, but the code and the spec put it in Hidden (p5-retire); a fix worker corrects the sentence.

## Finishing

- scope: Scope drift was not measured for p1, p3 and p5 (they were merged locally before the check ran) and was not recorded for p2 and p4; by hand, every changed file of each phase sat inside its declared touches.
- final: Fix fix-1 (one sentence in the maintenance guide) merged after the first final review; the second review and both final roles passed. The full suite passed on the final head.
- conflict: After the approval, main moved (pull request 97, combined dependency updates) and two files conflicted: tests/mutation/mutants.yaml (both sides only added entries; kept both) and evals/baselines/default.json (regenerated with the repository tool). The full suite passed on the merge (6808 passed, 6 skipped).
