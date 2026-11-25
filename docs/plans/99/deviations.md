# Deviations: reflektor-page-allow-mark

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-page-code

- worker: worker ran with system python3 (no .venv) and without tld, so the orchestrator ran the roles and the docs-index check
- review: security-reviewer found that the swap can expose a token glued to the mark; prepare_page now runs the full verify_html on the neutral page (plan 3.2 said report_check.check); mutant RF6 added
- retry: phase sent back once for the security finding above
- review: verify_after_merge pytest names tests that p2 and p3 create, so after p1 only the existing files were run, plus the full fast check

## p2-page-note-command

- worker: the brief listed a required stage for page-note; the worker followed plan 3.3 (role, check, board, send only) and the module has no required stage
- review: security-reviewer: a block line could forge a page note, so change-report now drops block lines that look like the note (plan 3.3 said position alone protects it); the note file and stderr are read as bounded regular files; an unreadable --note exits 1
- retry: phase sent back four times for security findings (forged-note filter: raw match, then a skeleton match, then one look-alike letter, then invisible fillers); the forged lines are now replaced by one fixed marker line
- gate: owner answered ask a-dda2e75dcd79c654 with fix_then_merge: after the last fix round the orchestrator checked it with tests and its own probes and merged without a fifth security review, so the last security-reviewer report (one blocking finding, since fixed) was not re-run; accepted residual risk: paraphrases of the note, a phrase split mid-word over four or more lines, and look-alikes with fewer than 6 real letters
- review: the p2 scope check was not run before the merge; verify_after_merge used the existing test files only until p3 adds its own

## p3-playbooks

- worker: the worker ran without tld; the orchestrator ran the security role and the checks. The dod sequence puts the change-report build in sub-step 1 before note.txt is written and writes note.txt, html.err and board.err as bare names (two non-blocking security findings, left for the fix round)
- review: verify_after_merge ran in full for the first time: all four test files exist now and pass

## p4-docs-spec-retire

- pending

## Final review

- pending

## Finishing

- pending
