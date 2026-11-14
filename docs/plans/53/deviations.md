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
- final: The digest turns every non-ASCII character that is not a letter or digit into a space when a vocabulary is given, which the plan does not state.
- final: A question whose id does not match the board question id pattern is emitted with the id q followed by its index, instead of being skipped.
- final: The cut treats the number placeholder as one unit and cuts before its hash sign, where the plan says to cut before the angle bracket.
- final: Tokens are cut to 200 characters before masking, as input bounding added after the security review.
- final: Owner decision (board ask, answer hash_emitted): the cluster fingerprint now hashes the emitted, vocabulary-filtered template with source and kind, not the template before the filter. This departs from plan 3.2 and from the p2 acceptance wording that the fingerprint is equal with a vocabulary.
- final: Effects of that decision: the corpus value without a vocabulary is unchanged; a changed vocabulary changes fingerprints, so an earlier finding can resurface once; clusters that differ only in filtered words, also two in one digest, can share a fingerprint, and step 4 of the questions playbook then hides a later finding of either.
- fix: Fix worker fix-1 (Plan-Phase question-review/fix-1) made the change above and added two tests for similarity of empty word sets and for the empty flag of an unanswered ask.

## p3a-policy

- None.
- review: No deviation in the diff. Worker notes for p3b and p3c: the questions playbook must push only review/questions branches, and review apply must write the record only when status_record equals the computed record id.

## p3b-command

- worker: Design change: the playbook and the document report the own total (analysed plus open_asks plus excluded_questions_asks) instead of the digest top-level asks count, and leave foreign_count out of the fields it reads, because asks and foreign_count carry other projects volume and plan section 3.6 forbids showing it. Plan section 3.6 text that puts asks in What was reviewed is therefore not followed.
- worker: Added hardening lines the plan lacks: format checks for the review/questions branch name, asks_until and decisions_ask, a timestamp-form check on the input since and the record cursor passed as one quoted argument, and a note that the helper brief carries finding ids and Where lines only.
- review: The security role was not re-run after the last wording edits of the worker; the final review runs it again. Residual risk accepted for now: a forged review/questions branch can steer a run (stop or widen the window) without leaking data.

## p3c-review-header

- worker: The worker added guards beyond the brief to the review apply sentence: the repository is the checkout, never the header; exact string comparison; only the command output is used as the record id; the write happens only when the record read is a questions record in waiting_user. It also added a second guard test. The baseline refresh also updated the questions playbook hash, which was stale after p3b (hashes only).
- review: The worker ran the dod rows by hand, not the dod playbook; this merge ran the full suite, docs index and baseline checks green. Open non-blocking security notes for the final review: a stale document naming the public questions record id could close a later waiting run; a version-conflict retry should repeat the questions and waiting_user checks; the guard test only checks phrases.

## p4-retire
- worker: The guide has a few lines beyond the brief steps (78 lines, under the limit) and states the own-total reporting, the review apply guards and the accepted forged-branch risk. The security role did not run again after the last two wording edits of the guide.
- review: Open items the worker raised for the final review and the owner: SECURITY.md has no entry for the forged-branch risk; step 0 of the questions playbook trusts the decisions_ask of a branch header without checking it belongs to this repository; the digest allows a run without the vocabulary option and only the playbook prevents it; no branch ruleset scopes review/questions branches to the agent account.


## Final review

- final: Blocking 1, p2-digest: the fingerprint is an unkeyed hash of the masked text before the vocabulary filter and is published beside the filtered template. The plan fixes this form, so the owner decides; see the board ask.
- final: Blocking 2, p2-digest: four digest behaviours were missing from the deviations file; added by the orchestrator under p2-digest.
- final: Round 1 blocking 1 resolved: owner answered hash_emitted, fix-1 merged; see p2-digest.
- final: Round 2 blocking 1, p2-digest: the owner-decision entry was cut at 500 characters by the deviations CLI; rewritten as two entries by the orchestrator.

## Finishing

- pending
