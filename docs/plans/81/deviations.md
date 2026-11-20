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

- pending

## p5-sysml-layout

- worker: none
- review: worker had no tld; orchestrator ran security-reviewer: 0 blocking, 1 non-blocking left open (layout does not itself reject a model over the element and relation limits, so a caller must lay out only a model that built without findings; p7 must enforce this)

## p6-sysml-svg-markdown

- pending

## p7-ops-sysml-cli

- pending

## p8-manifest-sysml-change

- pending

## p9-sysml-record

- worker: none; one CHANGELOG.md line outside touches, as the rules require
- review: worker had no tld; orchestrator ran security-reviewer (pass); board_gate and plan_gate lists are p10 work

## p10-sysml-command

- pending

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
