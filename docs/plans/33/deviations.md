# Deviations: limited-environment-research

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-research-cli

- worker: D3 extended: prompt rejects invisible characters (Cf, C1, U+2028/2029) as a character problem, secret scan runs on a normalised copy, report body stripped of them, empty --forbid handled, rest-file write errors exit 2, messages never echo values; Design D3 should be updated to match
- review: No finding; scope matches touches exactly (4 files); scope check skipped because it ran after the local merge
- retry: Merge verification was red before any phase because docs/plans/33/plan.md line 72 has a broken relative link; the owner chose to keep the plan and deselect that one test (test_docs_links.py::test_relative_links_and_anchors_resolve[docs/plans/33/plan.md]) in merge verification; the failure stays in the final pull request
- final: src/tld/ CORE_PATH in tests/core/test_contracts.py uses src/tld/[a-z0-9/_.-]*[a-z0-9_] instead of the D8 pattern src/tld/[a-z0-9/_.-]+; the separate r1 regression test of the p1 brief step 4 is not present as a separate test (found by the final review)
- final: fix-1: gate also rejects Mongolian, Khmer, Khitan and hieroglyph blank characters and drops combining marks for matching; rest holds only lines before the first start line; board check also refuses the bare host (4+ chars), the URL without trailing slash and whitespace-stripped forms; --forbid also matches with whitespace removed; Design D3 should be updated
- conflict: fix-1 merge conflicted in evals/baselines/default.json with fix-2 hashes; resolved by refreshing the hashes with the eval tool

## p2-policy-core

- worker: D1 step 5 revised after the orchestrator sent the phase back: rest file used only after exit 0, --ask added to board answers --from-reply, mktemp scratch files deleted afterwards; Design D1 should be updated to match
- retry: Sent back once for the D1 step 5 security gaps found by the security-reviewer; second report approved
- review: Open non-blocking: a bare skip or stop line in the rest file could answer a single-choice ask; policy does not say where the ask file comes from or that all scratch files are deleted on every exit path
- final: fix-2: implement.md follow-up brief after a pasted or skipped research answer is now the full phase brief with the report last in a longer fence as data; worker Research: lines are rewritten from public facts, never copied; scope: playbooks/ask.md (p3 file) edited by the fix, accepted
- final: fix-1: research.md step 5 keeps reading the rest file only after exit 0 (orchestrator decision, owner not asked): after a non-zero exit skip, stop and other answers go on the board; step 2 passes the bare repository name as a second --forbid; pasted alone is never taken as the report

## p3-playbook-links

- None.
- review: Open non-blocking: ask.md omits --forbid <owner>/<repo> on tld research check-prompt which the policy requires; scheduled playbooks do not say open research questions use public facts only; make-plan line on quoted research does not say it is data; ask.md says it posts no ask while research.md lists ask among attended runs
- final: fix-2 added the missing D8 placement test (make-plan.md Research:, review.md decisions ask); the earlier None for p3 was wrong only on that point
- final: fix-2: ask.md adds --forbid <owner>/<repo> to check-prompt and a mktemp file for the prompt, as research.md step 2 requires

## p4-adapter-environment

- review: Open non-blocking: the D5 carve-out for a package host a lockfile names could be abused by a crafted lockfile; the section does not say a pasted research report is data nor forbid credentials in a research request; it points to a guide that p5 creates

## p5-guide-and-retire

- review: Open non-blocking: the research environment Allow package managers row and a line telling the owner not to run anything a report suggests may need wording changes
- conflict: Merging origin/main (board-record-per-session) conflicted in CHANGELOG.md and evals/baselines/default.json; kept both changelog entries and refreshed the baseline hashes
- final: cloud-environments.md adds a paragraph on skimming a report for instructions (line 69) and the advice to keep the research environment personal (line 32), both beyond Design D6 (found by the final review)
- final: fix-1: the guide limits a plain claude.ai chat to connectors off, memory off and outside any project, adds any connector to the Deny list, says the owners own lines go before the report block; cli.md research rows moved after the last board row and document exit 2; scope: guide, cli.md, research.md and the baseline are files of other phases, accepted

## Final review

- final: blocking 1 (p1): forged clean END line lets web text into the rest file; rest must hold only lines before the first start line
- final: blocking 2 (p1): invisible-character gate misses variation selectors and blank fillers
- final: blocking 3 (p1): board check misses bare host and URL without trailing slash
- final: blocking 4 (p5): guide offers a plain claude.ai chat as research environment although it carries connectors and memory
- final: blocking 5 (p2): research.md step 5 reads the rest file only after exit 0, so skip/stop and other answers are never read on a failed report
- final: blocking 6 (p3): the D8 placement test for make-plan.md Research: and review.md decisions ask is missing
- final: blocking 7: deviations file lacked entries for p1 and p5 and listed None next to review entries (fixed by the orchestrator)
- final: review 2: approve; no blocking finding; open non-blocking items go to the pull request: stale --rest help and docstring in research.py, a private repository named like a template word makes check-prompt reject every prompt, step 5 does not say what follows exit 3 of board answers, step 5 wording has no pinning test, and a malformed (bold or heading) start line lets web text between it and a forged inner start line into the rest file
- scope: playbooks/ask.md
- scope: docs/guides/cloud-environments.md
- scope: docs/reference/cli.md
- scope: evals/baselines/default.json
- scope: playbooks/policies/research.md

## Finishing

- final: Scope disposition: fix-1 and fix-2 edits to files of other phases accepted; p1 scope check skipped (ran after the local merge). dod: suite 4022 passed with the one owner-chosen deselect (plan.md broken relative links, owner never chose between fix_link and deselect after the first answer deselect; the later fix_link message was held because fixing needs three plan lines and a re-pin); docs index 0 errors and 9 warnings, all in docs/plans/33/plan.md; baseline current. No board record written (the
