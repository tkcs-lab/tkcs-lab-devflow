# Deviations: reflektor-role

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-prepare

- review: security review found git run before the PATH check (plan 3.3 order); PATH check now runs first and git is resolved once; the worker fixed it in a second commit
- retry: phase sent back once for the PATH-order finding
- review: owner decision (ask a-b2414058b2c4bc6a): the docs-links test of plan.md was accepted as red for phases p1 to p8 on the premise that p9 would create the guide it links to; every other test had to pass (the premise was wrong: the link was broken in the plan text itself, see p9-retire)

## p2-page

- review: security review found the secret scan bypassable (allow mark, line-splitting characters) and the page title rule bypassable with HTML entities; verify_html now refuses the allow mark and line-splitting characters in the raw data, decoded strings and keys, and the title refuses &, control/format/line-separator characters and more than 200 characters
- retry: phase sent back once for the two blocking security findings
- final: the page check also refuses duplicate JSON keys in the payload (fails closed, tested); the plan had no such rule
- final: a nesting limit of 200 was added to the page check and to reflektor-check (the plan asked for an iterative walk without a limit); deeper data is refused

## p3-section

- review: security review found three bypasses in the cleaning: the secret scan could be silenced by the allow mark (also created by the 500-character cut), a token could be glued together by deleted separator characters, and forged report lines could be rebuilt by the link, image and cut steps; the command now refuses a block that carries the mark, scans the raw block as well as the cleaned text, and drops forged lines again after the last step
- review: --report-line now splits at newlines only and refuses a last line holding control or separator characters, so the gate file line matches what tld roles verify sees
- retry: phase sent back once for the three blocking security findings

## p4-role

- None.

## p5-real-run

- None.

## p6-board-store

- final: the 503 busy answer of the report upload carries a Retry-After: 1 header; the plan does not specify it

## p7-board-client-page

- None.

## p8-playbooks

- review: plan 3.7 had implement run tld roles section on the dod subsection, which holds cleaned text without the BEGIN/END markers, so the Change report section could never appear; implement now runs it on the saved reflektor answer file of dod step 5
- review: added to the playbooks: what the dod subsection holds when section exits 3, a roles.md Gate exception for reflektor, and saving the answer with a file-writing tool instead of a shell command
- retry: phase sent back once for the functional break and three wording gaps; the evals baseline hashes were refreshed again

## p9-retire

- review: security review found the guide claimed nothing leaves the machine but the download (the page embeds the full contents of the changed files and is stored on the board), and the pin refresh lacked the re-derivation of the link-target keys and the policies; the guide now says what is stored where and the refresh has the step
- review: the allowed-domains row of cloud-environments.md now says that github.com opens git and HTTPS traffic to all of GitHub for every session of that environment and recommends a dedicated environment; the guide corrects several claims (card rules versus enforced controls, three build rounds, scratch copies, DELETE of a stored page)
- retry: phase sent back twice for blocking doc findings
- final: owner decision (ask a-698d1c97c176a7f8, answer fix): the plan text itself was changed in one place, the markdown link to ../guides/reflektor.md in the p9 brief became plain text, because it resolved to docs/plans/guides/reflektor.md and kept the docs-links test red; the plan blob therefore differs from the one pinned by the Plan-Started commit

## Final review

- final: final review (changes): p2-page duplicate JSON keys rule and nesting limit of 200, and p6-board-store Retry-After on 503, were not recorded in this file; recorded above by the orchestrator

## Finishing

- final: scope: no phase had files outside its touches (nine phases, 0 out of scope, 0 collisions), so there was no drift to accept or revert
- final: dod: all rows passed except tests/core/test_docs_links.py for docs/plans/72/plan.md, which failed on a link inside the plan text itself; fixed on the owner's answer (see p9-retire), after which the whole suite passes
