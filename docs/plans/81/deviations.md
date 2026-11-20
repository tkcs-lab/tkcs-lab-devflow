# Deviations: sysml-architecture

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-profile-sysml-key

- worker: none; one CHANGELOG.md line outside touches, as the rules require
- review: worker had no tld; orchestrator ran the security-reviewer role (pass), diff in scope

## p2-sysml-files

- retry: security-reviewer found 1 blocking (unbounded read; size limit checked after full read) and 7 non-blocking; p2 sent back to fix the blocking one plus depth/early-stop, name escaping, NUL, parent-vanished and test gaps
- review: accepted as follow-up, not fixed: TOCTOU between the lstat walk and the path-based use (needs a concurrent process; plan 3.3 fixes the lstat-walk design) and a write allow-list for the file layer (callers are fixed to sysml/ and docs/architecture.*)
- worker: see send-back entry; worker added bounded reads, depth cap 8, name escaping and extra tests beyond the first brief
- review: re-review: 0 blocking, 2 non-blocking left open (fstat before fdopen on a directory that appears after the walk leaks an fd; scandir listing is not capped for very wide trees)

## p2b-sysml-parse

- retry: security-reviewer found 1 blocking: a lone carriage return was accepted in code and comments, which lets a terminal show a comment where code is parsed (and the reverse); p2b sent back to refuse a CR not followed by LF, run the character pass over the whole file first, and document the parse_file size precondition
- review: design change vs plan 3.2: a carriage return is allowed only as part of CRLF (stricter than the plan text, which does not mention CR); long names and words are still echoed in full in two messages as the plan words them (non-blocking, left open)
- worker: lone CR refused everywhere (stricter than plan 3.2); whole-text character pre-pass added
- review: re-review: 0 blocking; 1 non-blocking left open: default-ignorable invisible characters (variation selectors, Hangul fillers, U+034F) are accepted in doc text and can hide a link or secret trigger word from the heuristic checks

## p3-sysml-model-check

- worker: none
- review: worker had no tld; orchestrator ran security-reviewer: 0 blocking, 1 non-blocking left open (names label in Finding.file is not escaped; no caller passes names yet, so p7 must pass only checked relpaths)

## p4-sysml-change

- retry: security-reviewer found 1 blocking: new_change kept an existing change copy but recorded the current model hash as its base, so a later archive could overwrite or revert another plan merged edit; p4 sent back to refuse a copy not recorded in base.json unless it equals the model file
- review: design change vs plan 3.6 new-change row: an existing change copy that is not recorded in base.json is refused unless identical to the model file (plan text said copy unless it exists and record the hash unless recorded); archive_plan trusts its caller, so p7 must run check_change with zero findings and check_writable on every target before the first write
- worker: change ids capped at 100 characters; change.py imports the private files._check_components (read-only existence checks, judged safe by the re-review)
- review: re-review after the send-back: pass, 0 findings

## p5-sysml-layout

- worker: none
- review: worker had no tld; orchestrator ran security-reviewer: 0 blocking, 1 non-blocking left open (layout does not itself reject a model over the element and relation limits, so a caller must lay out only a model that built without findings; p7 must enforce this)

## p6-sysml-svg-markdown

- worker: none
- review: worker had no tld; orchestrator ran security-reviewer: 0 blocking, 3 non-blocking left open (an email address or mailto: in a model doc is not neutralised in docs/architecture.md and GitHub can autolink it; a package doc that starts with a list or thematic-break marker changes the page structure; the SVG writer does not reject code points that are invalid in XML 1.0, unreachable through the parser)
- retry: merge was pushed with one red test (tests/core/test_docs_links.py: the golden markdown fixture links to architecture.svg, which does not exist next to it); the merge was reverted and p6 sent back to fix the link check
- worker: golden fixtures moved to tests/fixtures/sysml/golden/connect/ so the markdown image link resolves; the three open review findings were fixed by the worker
- review: re-review after the fixes: pass, 0 findings; re-merged after reverting the revert, full suite green (5802)

## p7-ops-sysml-cli

- retry: security-reviewer found 1 blocking: when an archive write fails and the rollback also fails, the rollback errors were swallowed and the model was left half applied with only the first error shown; p7 sent back to report the paths left changed and tell the user to restore from git, to roll back on any exception, and to add mutants for the archive gates
- retry: second send-back: the 400-character bound on the archive failure line could cut off the part that says whether the undo worked, so a half-applied model could be reported without that status; p7 told to put the status first, bound each part separately, make the restore attempt even when the comparison read fails, and attempt every undo step
- worker: none; the archive rollback now reports the undo status first and a non-interrupt exception in an undo step is listed as left changed (exit 2, no traceback), accepted by the review
- review: third review: 0 blocking, 3 non-blocking left open (an interrupt between the directory move and its undo entry can report the model as restored while the change folder stays in archive; an interrupt cause prints empty and an undo error type is dropped; an interrupt inside the handler outside the per-step try can stop the undo without a status line); the removed base-hash mutant stays out of scope

## p8-manifest-sysml-change

- worker: existing mutants VM14 and VM15 were edited because the refactor moved the code their match strings pointed at; one CHANGELOG.md line outside touches
- review: worker had no tld; orchestrator ran security-reviewer: 0 blocking, 4 non-blocking left open (a profile whose sysml key is null or not a mapping turns the no-change-no-touch rule off silently; a phase with missing or empty touches is never fenced, as already for spec_change; VM14 and VM15 now mutate both fences so they no longer pin the spec control alone; phase ids are echoed unescaped in manifest messages)

## p9-sysml-record

- worker: none; one CHANGELOG.md line outside touches, as the rules require
- review: worker had no tld; orchestrator ran security-reviewer (pass); board_gate and plan_gate lists are p10 work

## p10-sysml-command

- retry: security-reviewer found 2 blocking in the sysml playbook: no refusal path after the component-list confirmation (a no could still lead to a branch and pull request), and the no-literal-values rule did not cover the pull request body or the ask text; p10 sent back to add a stop path with a test, extend the rule to the ask and the pull request, validate the proposal, and forbid pushes to main or other branches
- worker: none beyond the send-back fixes; eval baseline hash refreshed
- review: re-review: 0 blocking, 6 non-blocking left open (the commit message is not covered by the no-literal rule; the list of literal kinds in the rule reads as complete; the pre-ask check does not say what to do with an entry that fails; a refusal on the second ask does not repeat the cleanup and the branch is checked out when it is deleted; the new tests miss the 4/12 limit and an order check; plan_gate opens the write session for sysml check as well as init, as it does for spec)

## p11-plan-playbooks

- pending

## p12-docs-lists

- pending

## p13-retire

- pending

## Final review

- pending

## Finishing

- pending
