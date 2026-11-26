# Plan: Reflektor change report survives a quoted secret-scan allow mark, and a missing page is always said out loud

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Nothing new to type. When a branch quotes the secret-scan allow mark (in docs, tests or the guard itself), `tld roles reflektor-html --send` now builds and stores the page: every credential check runs on the original text with the mark's skip turned off, and then each literal mark in the page is replaced by the visible text `[secret-scan mark removed]`. When a page is refused or cannot be stored (the role's own build failing is not a refusal: a role that ends `n/a` still fails the row), the dod row for `reflektor` reads `needs attention (... ; HTML page not stored)` and the `## Change report` section of the pull request starts with one line, `HTML page not stored: <reason>`.

**Scope:** Changed: `secret_scan.scan_text` (a keyword-only option, default unchanged), `src/tld/roles/reflektor.py`, two new commands in one new module (`tld roles page-note`, `tld roles change-report`), the dod and implement playbooks, the reflektor role card, `docs/guides/reflektor.md`, `docs/architecture/hooks.md`, `docs/reference/cli.md`, the mutation list and its module list, the eval baseline hashes, the changelog and the `role-dispatch` spec. Not changed: the board, `report_check.py`, `VIEWER_PARTS`, `section.py`, `research.py`, the guard hook's behaviour, the Reflektor pin. No architecture change and no `project-profile` spec change (it does not cover this).

**Security:** The scan is stricter than before, never looser: both scan calls ignore the mark, so a credential on a line that ends in the mark is found and blocks the page. The stored page holds no mark. A mark that is only present in a JSON-escaped form is still refused.

**Review focus:** the scan-then-neutralise order and the "cannot re-form" argument (3.2); the page note taking only fixed text and known reasons (3.3); the row becoming `needs attention`, not `FAIL` (3.5); the playbook rule that nobody edits the page (3.5).

## 1. Goal

Issue [#99](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/99): three open pull requests carried the text `secret-scan:allow` in their diff, two lost the HTML change report and nobody could tell. The page is now built and stored whenever it is safe, and when it is not stored the pull request says so in one plain line with the reason.

## 2. Current state

- `src/tld/roles/reflektor.py:354-394`: `verify_html` refuses the whole page with `the page carries a secret-scan allow mark` when the mark is in the page text or in any decoded key or string of its JSON data. Its two `secret_scan.scan_text` calls (`:387`, `:390`) honour the mark, which is why the refusal exists.
- `src/tld/guard/secret_scan.py:116`: `scan_text` skips every line whose stripped end is the mark. Its callers are the guard hook (`:170`), `src/tld/research.py:85`, `src/tld/roles/section.py:143` and `reflektor.py`.
- `harden_html` (`reflektor.py:427`) and `send_copy` (`:449`) call `verify_html` and write the page unchanged.
- `playbooks/dod.md` step 5 (lines 47-56): "a non-zero exit of any of these is noted in the report, never a failure". No sentence says what the note is or where it goes. `playbooks/implement.md:427-428` pastes `tld roles section --report` under `## Change report`; exit 3 leaves the section out.
- `roles/reflektor.md:37`: a refusal at step 7 leaves out the `REPORT-HTML` line and says nothing else.
- `src/tld/board/report_check.py` is the board's page rule. A page without the mark passes it unchanged; the board image has no `tld.guard`, so the secret scan never ran there. The board needs no change.
- Tests: `tests/core/test_roles_reflektor_page.py:156-179` pin the old refusal. `tests/core/test_hook_secret_scan.py:108-157` pin the guard's mark handling. `tests/core/test_contracts.py:400-431` pin the playbook and role-card tokens.

## 3. Design

### 3.1 Options and the recommendation

| Option | Trade-off |
|---|---|
| **A. Scan the original with the mark's skip off, then replace each literal mark by a visible placeholder, then check the result (recommended)** | Small. Keeps the board and `report_check` as they are. A credential on a marked line is still found. The page no longer holds the mark. A mark that is only present in a JSON-escaped form (`secret-scan:allow`) is still refused, loudly. |
| B. Re-serialise the JSON payload after the replacement | Would handle escaped marks, but changes every byte of the payload, must re-escape `<` and may break the viewer. Rejected. |
| C. Keep refusing, but say so loudly | No code risk, but the page stays lost for every branch about secret scanning, which is issue #99. Rejected as the only fix; its loud line is part of A (3.3 to 3.5). |
| Substitutes rejected: a zero-width space or a look-alike character inside the mark | Can be removed or normalised back into the mark, and is invisible to the reader. |

### 3.2 The page code (`src/tld/guard/secret_scan.py`, `src/tld/roles/reflektor.py`)

`secret_scan.scan_text(text: str, *, skip_marked: bool = True)`: the check is `if skip_marked and line.rstrip().endswith(ALLOW_MARK):`. The parameter is keyword-only. The guard hook, `research.py` and `section.py` keep the default and are not edited. The module docstring gains one sentence: a caller that must not honour the mark passes `skip_marked=False`.

In `reflektor.py` (the local `ALLOW_MARK = "secret-scan:allow"` at line 354 becomes `ALLOW_MARK = secret_scan.ALLOW_MARK`):

```python
REDACTED_MARK = "[secret-scan mark removed]"
REASON_SPLIT = "the data holds a line-splitting character"
REASON_ESCAPED = "the data carries an escaped secret-scan allow mark"
REASON_MARK_RAW = "the page carries a secret-scan allow mark outside its data"

def verify_html(text) -> list[str]        # the check of the ORIGINAL page
def neutralise_page(text) -> tuple[str, int]
def marks_left(text) -> list[str]
def prepare_page(text) -> str
def known_reason(reason: str) -> bool
```

- `verify_html(text)`: as today (the `report_check.check` first, then the line-splitting refusals with `REASON_SPLIT`, then the secret scan) with these changes: both "carries a secret-scan allow mark" refusals are removed; the raw scan is `secret_scan.scan_text(text, skip_marked=False)` and the scan of each decoded key and string is `secret_scan.scan_text(s, skip_marked=False)`. The credential reason text is unchanged: `the page holds something that looks like a credential (<names>)`.
- `neutralise_page(text)`: `report_check.split(text)` gives `(title, payload)` (a list result raises `ValueError(reason)`); the positions are `t_start = n1 + len(report_check.CSP_META) + n2 + len(report_check.TITLE_OPEN)`, `p_start = t_start + len(title) + len(report_check.TITLE_CLOSE) + n3` and `p_end = len(text) - n4`, with `n1..n4` the four lengths of `report_check.VIEWER_PARTS`. A private `_swap(s)` returns `(s.replace(ALLOW_MARK, REDACTED_MARK), s.count(ALLOW_MARK))`. Only the title and the payload are swapped; the four fixed viewer parts and the CSP are copied byte for byte. It returns the new text and the number of marks replaced.
- `marks_left(text)`: `[REASON_MARK_RAW]` when `ALLOW_MARK in text`; else it parses the payload (`report_check.split`, `report_check.parse_payload`), walks every key and string with `_walk`, and returns `[REASON_ESCAPED]` when one holds the mark; else `[]`.
- `prepare_page(text)`: `verify_html(text)`; then `neutralise_page`; then `report_check.check(neutral)` and `marks_left(neutral)`; any reasons raise `_refuse(reasons)`. Only after every check has passed, and only when the count is above 0, it prints `tld roles: reflektor: removed <n> secret-scan allow marks from the page` on stderr, so the stderr of a refusal holds the refusal reasons and nothing else. It returns the neutral text.
- `harden_html` runs `prepare_page(hardened)` where it ran `verify_html(hardened)` and writes the neutral text; `send_copy` runs `prepare_page(text)` and writes the neutral text. Exit codes and every other message are unchanged.
- `known_reason(reason)` is True only when `reason` fully matches one of these patterns: the reasons of `report_check` (`the page is not text`, `page part [1-4] differs from the pinned viewer`, `the Content-Security-Policy meta tag is missing or changed`, `the title tag is missing`, `the title tag is not closed`, `the title is not plain one-line text`, `invalid payload` with or without one of the parenthesised texts `NaN or Infinity`, `duplicate key`, `not one line`, `contains '<'`, `not JSON`, `nested too deeply`, and `the data has a link target under '<k>'` with `<k>` one of `report_check.NULL_KEYS`, `branch.pr` or `avatar.image`), the three constants above, the credential reason with one or more names from `[name for name, _d, _rx in secret_scan.SPECIFIC] + ["high-entropy-assignment"]` joined by `, `, and the texts `already hardened`, `the page must have exactly one <head>`, `the answer has no REPORT-HTML line`, `the REPORT-HTML path is not an out/report.html path`, `cannot (open|read|write) (the page|the answer): <letters>`, `(the page|the answer) is (not a regular file|not UTF-8|larger than <digits> bytes)`.

**Why the control holds.** (1) No line is skipped when scanning: both scan calls pass `skip_marked=False`, so a credential on a line that ends in the mark is found in the raw text, in the title, and in every decoded key and string (a JSON `\n` becomes a real line break there), and the page is refused before anything is neutralised. (2) The stored page holds no mark: the mark `secret-scan:allow` has no border (no proper prefix equals a suffix), so its occurrences never overlap and `str.replace` removes all of them; a new occurrence would have to cross a placeholder boundary, and the placeholder starts with `[` and ends with `]`, characters outside the mark, and its inside `secret-scan mark removed` is not the mark. `marks_left` checks the result anyway: the raw text, and every decoded key and string, so an escaped form is refused. (3) Only the title and the payload change, and `report_check.check(neutral)` runs on the result, so the board accepts the page by the same rule as before: `VIEWER_PARTS` and `CSP_META` are not touched.

### 3.3 The page note (`src/tld/roles/page_note.py`, new)

One module, two commands, registered like `reflektor-prepare` (`src/tld/cli.py:34-36`): `("roles", "page-note")` with `("note",)` and `("roles", "change-report")` with `("report",)`. Constant `NOTE = "HTML page not stored: "`.

`tld roles page-note --stage role|check|board|send [--stderr FILE] [--sent]` prints exactly one line and exits 0. `--stderr` is read as bytes (at most 20000), decoded with replacement, and an unreadable file counts as empty. The lines are built only from fixed text, a known reason and a three-digit status:

| Stage | Line |
|---|---|
| `role` | `HTML page not stored: the reflektor role built no checked page.` |
| `check` | `HTML page not stored: the page check refused it (<reason>).` where `<reason>` is the part after `tld roles: reflektor: ` of the first such line of FILE when `reflektor.known_reason` accepts it; otherwise `HTML page not stored: the page check refused it.` |
| `board` | by the first match in FILE: `the server answered HTTP <nnn>` gives `HTML page not stored: the board answered HTTP <nnn>.`; `cannot read the report (larger than` gives `HTML page not stored: the page is too large to upload.`; `cannot reach the board` gives `HTML page not stored: the board cannot be reached.`; nothing matches: `HTML page not stored: the board did not accept it.` With `--sent` the line ends with ` It was sent to the owner as a file instead.` |
| `send` | `HTML page not stored: the page could not be sent as a file.` |

A missing or unknown stage, or `--sent` with a stage other than `board`, is a usage error (exit 2). No board URL, host, header or exception text can reach the line.

`tld roles change-report --report FILE [--note FILE]` prints the note, a blank line and the cleaned block of the report. The block is produced with the functions of `tld.roles.section` (`extract`, `clean`, `_suspect`), exactly as `tld roles section --report FILE` produces it; `section.py` is not edited. With no note (missing, empty, or `--note` not given) its output and exit codes are those of `section --report`. The note must pass `valid_note(line)`: one line, after strip, that starts with `NOTE`; the rest, minus the optional suffix ` It was sent to the owner as a file instead.` (allowed only on the board forms), is exactly one of: `the reflektor role built no checked page.`; `the page check refused it.`; `the page check refused it (<R>).` where it starts with `the page check refused it (`, ends with `).` and `known_reason(<the text between>)` is true (a slice, so a reason that itself holds parentheses, such as the credential reason or `invalid payload (contains '<')`, is judged whole); `the board answered HTTP <three digits>.`; `the page is too large to upload.`; `the board cannot be reached.`; `the board did not accept it.`; `the page could not be sent as a file.`; anything else exits 1 with `tld roles: the page note is not a page-note line`. A valid note with no usable block (no block, empty after cleaning, or `_suspect`) prints only the note and exits 0. Position is the control: the line is printed by this command, first, so text inside the role's own block cannot forge or move it, and `section.py` needs no filter.

### 3.4 The board

No change: the page it receives has no mark, `report_check.check` accepts it as before, and `VIEWER_PARTS`, `CSP_META`, `NULL_KEYS` and the 20 MiB limit stay. The ask said to check this: the neutral page is longer by 9 bytes per mark, which does not matter against the limit. A board failure (422, 413, 503, unreachable) is made loud by 3.3 and 3.5 only.

### 3.5 The playbooks and the role card

**dod.md step 5** (replace the text of the `reflektor` paragraph from "The gate file gets only the line printed by" to "is noted in the report, never a failure."). The new rules, in this order:

1. The gate file gets only the line printed by `tld roles section --report-line --report <the saved answer file>` (this rule stays as it is today). The report subsection of `reflektor` holds the output of `tld roles change-report --report <the saved answer file> --note <note.txt>` followed by the line of `section --report-line`; on exit 3 it holds only the stderr line and the report line; on exit 1 (the note is not a page-note line, or the answer cannot be read) the row is `FAIL` with that stderr line, and the note file is never edited to get past it. `note.txt`, `html.err` and `board.err` are three files in a scratch directory made for this role; `note.txt` starts empty.
2. The role's verdict is not `n/a` and the saved answer has no `REPORT-HTML <path>` line: `tld roles page-note --stage role > note.txt`.
3. Otherwise, with the line: `tld roles reflektor-html --send --answer <file> --dest <a new scratch directory> 2> html.err`. A non-zero exit: `tld roles page-note --stage check --stderr html.err > note.txt`, and the page is not sent anywhere. Exit 0: the printed path is the page; when `html.err` has a line `tld roles: reflektor: removed <n> secret-scan allow marks from the page`, add it as a plain line after the `change-report` output. Then:
   - with this run's status record: `tld board client health 2> board.err`. Exit 0: `tld board client put-report <id> <path> 2> board.err`; exit 0 ends the page, no note. A non-zero put-report, or a health exit other than 0 and 3, is a board failure: `show_human(<path>, "change report")`, then `tld roles page-note --stage board --stderr board.err --sent > note.txt` when `show_human` returned without an error, else the same without `--sent`.
   - without a status record, or with health exit 3 (no board configured): `show_human(<path>, "change report")`; when it fails, `tld roles page-note --stage send > note.txt`.
4. **The row.** A non-empty `note.txt` makes the row `needs attention (<blocking> + <non-blocking>; HTML page not stored)` unless the row is `FAIL`, which stays `FAIL`. A lost page does not block the pull request (the dod report and the `## Change report` text, when `section` accepts it, are still there); it is never `PASS`.
5. **Never work around a refusal.** Never edit, rebuild, re-hash or rewrite the page, the saved answer or the `REPORT-HTML` path to get past a refusal, never change the bytes and send again, and never delete `note.txt`. A refusal is final for the run; the note says so.

**implement.md** (the `## Change report` paragraph, section 6 step 3): the section is `tld roles change-report --report <the saved reflektor answer file of dod step 5> --note <the page note file of dod step 5>` pasted as is (the note file is empty or missing when the page was stored); exit 3 still means leave the section out. When there is a note, its first line is `HTML page not stored: <reason>`: never remove, shorten, reword or move it, and never edit, rebuild or re-send the page to make it go away. Name the note in the final reply to the human.

**roles/reflektor.md step 7**: "A non-zero exit: leave out the `REPORT-HTML` line, add one non-blocking finding `HTML page refused: <the first reason line of its stderr>`, and never edit `report.html` to get past it." This gives the owner the reason of the most common refusal (it happens in the role's own shell); the orchestrator's note for that case is the fixed `role` line.

**Row decision.** `needs attention`, not `FAIL`: the owner asked that the loss cannot be overlooked, and a row and a line at the top of the section do that; blocking the pull request for a page the text section already summarises would stop work for a viewer's convenience. A role that cannot run at all still fails the row (`required role did not run`).

### 3.6 Tests that must exist

In `tests/core/test_roles_reflektor_page.py` (use its fake viewer and `page()` helper):

- `test_quoted_mark_is_built_and_stored`: a prose quote of the mark in the data, in a key, in a value and in the title is built and written by `harden_html` and `send_copy` with no mark in the file, `REDACTED_MARK` in its place, `report_check.check` of the result empty (the board's rule) and the stderr line with the count.
- `test_credential_on_marked_line_is_refused`: a real token on a marked line is refused with the credential reason and nothing is written, in three forms that each kill a different mutant: (a) the raw text, with a pinned viewer part replaced by a fake part A of `"<!doctype html>\n<!-- " + TOKEN + " secret-scan:allow\n--><head>"` (`test_raw_scan_ignores_mark_in_viewer_part`; a valid page has no other raw line that ends in the mark, because the payload is one line followed by part 4 and the title is followed by `</title>`); (b) a decoded string and a decoded key whose token is written through a JSON escape so the raw text does not hold it: payload `'{"s":"\\u0067' + TOKEN[1:] + ' secret-scan:allow\\nx"}'` and the same text as a key (`test_escaped_token_on_marked_decoded_line_is_refused`); (c) the token with the readable form in a decoded string with `\n` (the existing style). A title holding a token and ending in the mark is kept as a regression test only.
- `marks_left`: a mark inside a fake pinned part is refused by `prepare_page` with exactly `REASON_MARK_RAW` (`test_mark_in_viewer_part_is_refused`), and `marks_left(page('{"s":"secret-scan:allow"}')) == [REASON_MARK_RAW]`; `secret-scan\u003aallow` in the data is refused with `REASON_ESCAPED` (`test_escaped_mark_is_refused`).
- Adversarial overlaps (`secret-scan:secret-scan:allowallow`, `secret-scan:allowsecret-scan:allow`) leave no mark; a title over 200 characters after the swap is refused by `report_check`; a refusal leaves the stderr holding no `removed` line; every rewritten old test keeps its credential case refused.

In `tests/core/test_hook_secret_scan.py`: `scan_text` ignores a marked line by default, finds it with `skip_marked=False`, and rejects a positional second argument.

New `tests/core/test_roles_page_note.py` (p2): `test_note_line_*` for the table rows, `test_every_note_line_is_valid` (every `note_line` output, including a multi-name credential reason, `invalid payload (contains '<')` and a link-target reason, passes `valid_note`), `test_change_report_*` for the command, `test_check_note_keeps_known_reason` (parametrised over `REASON_ESCAPED`, `REASON_SPLIT`, a two-name credential reason and `the page is larger than 20971520 bytes`), `test_known_reason_covers_every_emitted_reason` (collects every string literal passed to `PrepareError`, `_refuse` or `_Reject` in `reflektor.py` and `report_check.py` and asserts `known_reason` accepts it, with fixed text for the formatted ones), and an integration test that runs `reflektor.main(["html", "--send", ...])` on a page holding a literal and an escaped mark and feeds its stderr to `note_line("check", ...)`, expecting a line that ends `(the data carries an escaped secret-scan allow mark).`. New `tests/core/test_page_note_playbooks.py` (p3): the playbook tokens and the PR-body section. The dod row and the order of its rules are prose and are checked by tokens only; there is no end-to-end harness for a playbook.

## 4. ADRs

None: the profile has no `docs.adr_dir`.

## 5. Manual steps

### ma1-real-run

**After implementation** (about 10 minutes, needs network and Node 18):

1. In a checkout of the feature branch run `TLD_REFLEKTOR_REAL=1 .venv/bin/python -m pytest tests/core/test_reflektor_real.py -q`.
2. You see the whole file pass, including the new case that builds a real page from a diff that quotes `secret-scan:allow` and stores it. That case also answers the one open fact of this plan: that Reflektor's build writes `:`, `-` and letters into its data as plain characters, so an escaped mark can only come from repository content.
3. Report back: `ma1 PASS` or `ma1 FAIL: <first failing line>` for the pull request.

## 6. Risks and open questions

- Reflektor's `build.mjs` could escape `:` or `-` in its data (not checked: the web was closed and the release was not run here). Every page quoting the mark would then end in `REASON_ESCAPED`, loud but lost. Early signal: the new real-test case of p1 and ma1. A worker that sees this in the real test stops with `status=blocked`.
- Each replaced mark adds 9 characters. A title near 200 characters can overflow the title cap and be refused by `report_check`; rare, loud.
- The placeholder shifts string lengths. If the viewer stores character offsets in its data, a highlight could move; only ma1 looks at the rendered page.
- A line or decoded string over 1 MB skips the assignment patterns of `scan_text` (`MAX_LINE_FOR_ASSIGNMENT`): a gap that was there before this change and is not touched.
- The dod row text changes. A worker greps the repository for code that parses the row; none is expected. Anything found goes to the owner as a stop.
- `tld roles section` refuses a block that itself quotes the allow mark (`section.py:143`, unchanged on purpose), so on exactly the branches this plan is about the `## Change report` section can hold only the note line. That is still loud, and it is the existing control.
- The note for a refusal inside the role's own shell is the fixed `role` line; its reason is in the role's non-blocking finding (3.5).
- The branch is pushed to a branch named by this plan (`fix/reflektor-page-allow-mark`), not to the session's own branch name.

## Implementation manifest

```yaml
plan_slug: reflektor-page-allow-mark
feature_branch: fix/reflektor-page-allow-mark
tracking_issue: 99
max_parallel: 1
manual_before: []
manual_after:
  - id: ma1-real-run
    title: Run the real Reflektor test with a diff that quotes the allow mark
    why: no test in CI downloads the pinned release, so only this shows that a real page with a quoted mark is built and passes the page rule
verify_after_merge:
  - .venv/bin/python -m pytest tests/core/test_roles_reflektor_page.py tests/core/test_hook_secret_scan.py tests/core/test_roles_page_note.py tests/core/test_page_note_playbooks.py -q
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - tld plan deviations check --file docs/plans/99/deviations.md --plan docs/plans/99/plan.md --all exits 0
  - the changelog has entries under docs.changelog.section and no version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
  - tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/reflektor-page-allow-mark does not exist
spec_change: reflektor-page-allow-mark
phases:
  - id: p1-page-code
    title: Scan with the mark ignored, then neutralise the mark in the page
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/secret_scan.py
      - src/tld/roles/reflektor.py
      - tests/core/test_roles_reflektor_page.py
      - tests/core/test_hook_secret_scan.py
      - tests/core/test_reflektor_real.py
      - tests/core/test_mutants_file.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/guides/reflektor.md, plan sections 3.2 and 3.6, src/tld/roles/reflektor.py:354-474.
      1. src/tld/guard/secret_scan.py: change `def scan_text(text: str)` to `def scan_text(text: str, *, skip_marked: bool = True)` and the line-116 test to `if skip_marked and line.rstrip().endswith(ALLOW_MARK):`. Add to the module docstring: "A caller that must not honour the mark passes skip_marked=False." Edit nothing else in the file.
      2. src/tld/roles/reflektor.py: replace the local `ALLOW_MARK = "secret-scan:allow"` by `ALLOW_MARK = secret_scan.ALLOW_MARK`; add `REDACTED_MARK`, `REASON_SPLIT`, `REASON_ESCAPED`, `REASON_MARK_RAW` with the exact texts of plan 3.2; rewrite `verify_html` as plan 3.2 says (both mark refusals removed; the two scan calls are exactly `hits = secret_scan.scan_text(text, skip_marked=False)` and `hits = secret_scan.scan_text(s, skip_marked=False)`); add `_swap`, `neutralise_page`, `marks_left`, `prepare_page` and `known_reason` as plan 3.2 says (the `_swap` body is exactly `return s.replace(ALLOW_MARK, REDACTED_MARK), s.count(ALLOW_MARK)`; `marks_left` tests `if ALLOW_MARK in text:` for the raw text and `if ALLOW_MARK in s:` for each decoded string). In `harden_html` use `neutral = prepare_page(hardened)` and write `neutral`; in `send_copy` use `text = prepare_page(_read_regular(rest, "the page"))` and write that text. Update the module docstring paragraph of `reflektor-html` with one sentence: the page is written with each literal allow mark replaced by `[secret-scan mark removed]`, after a scan that ignores the mark.
      3. tests/core/test_roles_reflektor_page.py: rewrite the tests at lines 156-179 for the new behaviour and add the tests of plan 3.6 for this file. Every rewritten test keeps its credential case refused: `test_allow_mark_with_line_splitter_is_refused` stays as is, its assertion widened to also accept `credential`; `test_allow_mark_behind_newline_escape_is_refused` expects the credential reason (a `github-token` hit); in `test_allow_mark_in_a_key_and_plain_is_refused` the first payload expects the credential reason, the plain `secret-scan:allow` value expects `[]` from `verify_html`, and the `:` payload expects `[REASON_ESCAPED]` from `prepare_page`'s refusal (assert on `PrepareError.message`). Add `test_default_scan_unchanged` in tests/core/test_hook_secret_scan.py as plan 3.6 says. The three token tests of plan 3.6 (the fake part A, the escaped token in a decoded string and in a key, the mark in a fake part) are required: without them the mutants RF1, RF2 and RF5 survive.
      4. tests/core/test_reflektor_real.py: add one opt-in case (same markers as the existing ones) that builds the real page from a diff that adds a file whose text quotes `secret-scan:allow` in prose, runs `reflektor.harden_html`, then `report_check.check` on the result with the real `VIEWER_PARTS`, and asserts `reflektor.ALLOW_MARK not in` the text and `reflektor.REDACTED_MARK in` it. Also assert `reflektor.ALLOW_MARK not in` the pinned `assets/viewer.html` text.
      5. tests/core/test_mutants_file.py: add `"src/tld/roles/reflektor.py"` to the tuple `MODULES`. tests/mutation/mutants.yaml: under `tests:` add `src/tld/roles/reflektor.py:` with `tests/core/test_roles_reflektor_page.py` and `tests/core/test_roles_reflektor.py`; add `tests/core/test_roles_reflektor_page.py` to the list of `src/tld/guard/secret_scan.py`. First update the existing mutant `SS1` of secret_scan.py: `old: 'skip_marked and line.rstrip().endswith(ALLOW_MARK):'` and `new: 'skip_marked and ALLOW_MARK in line:'` (its text changes because step 1 changed that line). Then add six mutants (each `old` occurs once, and each has a `why:` line as the neighbouring entries do): `SS12` (why: the allow mark is honoured when the flag says not to) in secret_scan.py `skip_marked and line.rstrip().endswith(ALLOW_MARK):` to `line.rstrip().endswith(ALLOW_MARK):`; `RF1` (why: the raw page scan honours the mark) raw scan `hits = secret_scan.scan_text(text, skip_marked=False)` to `hits = secret_scan.scan_text(text)`; `RF2` (why: the decoded string scan honours the mark) string scan `hits = secret_scan.scan_text(s, skip_marked=False)` to `hits = secret_scan.scan_text(s)`; `RF3` (why: the mark is not replaced) `return s.replace(ALLOW_MARK, REDACTED_MARK), s.count(ALLOW_MARK)` to `return s, 0`; `RF4` (why: an escaped mark is not found in the decoded data) `if ALLOW_MARK in s:` to `if False:`; `RF5` (why: a mark left in the raw text is not found) `if ALLOW_MARK in text:` to `if False:`. Run `python3 tests/mutation/run_mutants.py --only SS1 SS12 RF1 RF2 RF3 RF4 RF5`; every one must be killed. If a mutant survives, add the missing test (never edit the mutant).
      6. `.venv/bin/python -m pytest tests -q` must pass.
      Stop conditions: If the real test (with TLD_REFLEKTOR_REAL=1; skip it when there is no network and say so) shows Reflektor's data holds an escaped mark, stop with status=blocked and quote the data. Do not edit src/tld/board/report_check.py, section.py or research.py.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_roles_reflektor_page.py tests/core/test_hook_secret_scan.py tests/core/test_mutants_file.py -q passes
      - .venv/bin/python -m pytest tests/core/test_roles_reflektor_page.py -k "quoted_mark_is_built_and_stored or credential_on_marked_line or escaped_mark_is_refused" -q passes (Scenarios Quoted allow mark, Credential on a marked line, Escaped allow mark)
      - python3 tests/mutation/run_mutants.py --only SS1 SS12 RF1 RF2 RF3 RF4 RF5 reports every mutant killed
      - git diff origin/main --stat -- src/tld/board src/tld/roles/section.py src/tld/research.py prints nothing
      - grep -n "skip_marked=False" src/tld/roles/reflektor.py prints exactly two lines
  - id: p2-page-note-command
    title: Add tld roles page-note and tld roles change-report
    depends_on: [p1-page-code]
    complexity: M
    touches:
      - src/tld/roles/page_note.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_roles_page_note.py
      - tests/core/test_mutants_file.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/reference/cli.md, plan section 3.3, src/tld/roles/section.py, src/tld/roles/reflektor.py (known_reason).
      1. Create src/tld/roles/page_note.py with a module docstring in the style of section.py and `main(argv)` with two subparsers, dest `cmd`: `note` (arguments `--stage` choices role, check, board, send, required; `--stderr FILE`; `--sent` flag) and `report` (`--report FILE` required; `--note FILE`). Constant `NOTE = "HTML page not stored: "`. Functions `note_line(stage, stderr_text, sent) -> str`, `valid_note(line) -> bool` and the two commands, exactly as plan 3.3 says (the table gives every text; `known_reason` comes from `tld.roles.reflektor`). `--sent` with a stage other than board is `ap.error(...)` (exit 2). `report` imports `extract`, `clean`, `_suspect` from `tld.roles.section` and, without a note, returns what `section.main(["--report", FILE])` returns for the same file by calling the same functions in the same order (read with the same `_read`, same messages and codes: 1 unreadable, 3 no block or secret).
      2. src/tld/cli.py: register `("roles", "page-note"): ("tld.roles.page_note", ("note",), "print the one line that says the HTML change report page was not stored, and why")` and `("roles", "change-report"): ("tld.roles.page_note", ("report",), "print the change-report block of a role report with the page note as its first line")` directly after the `("roles", "section")` row, in the style of the reflektor rows at lines 34-37.
      3. docs/reference/cli.md: two table rows after the `tld roles section` row, in its style, naming the module `tld.roles.page_note`.
      4. tests/core/test_roles_page_note.py: every row of the plan 3.3 table (exact line), `--stderr` with a credential-looking first reason line gives the no-reason check line, an unknown reason gives the no-reason line, an unreadable stderr file counts as empty, the board texts for HTTP 413, 422 and 503 (`board_client: the server answered HTTP 503`), `cannot reach the board`, `cannot read the report (larger than 20971520 bytes)` and an unmatched text, `--sent` suffix and its misuse exit 2, the check-note tests and the `known_reason` coverage test and the stderr integration test of plan 3.6, a missing stage exit 2; `change-report`: note and block, note and no block, note and a block with a token, no note equals `section --report` output and exit code for four reports (usable, no block, token, unreadable), an empty note file, and each invalid note (two lines, the wrong prefix `XTML page not stored: the board cannot be reached.` whose tail is valid, a forged reason such as `the page check refused it (ghp_<36 letters>).`, a control character) exits 1 with `tld roles: the page note is not a page-note line`. Run each through `cli.main(["roles", ...])` once to prove the registration.
      5. tests/mutation/mutants.yaml: add `src/tld/roles/page_note.py:` under `tests:` with `tests/core/test_roles_page_note.py`; add `"src/tld/roles/page_note.py"` to the tuple `MODULES` of tests/core/test_mutants_file.py, and add four mutants with a `why:` line each (each `old` occurs once in page_note.py, and you write each `old` from the code you wrote): `PN1` the `known_reason` guard of the check line to `True`; `PN2` the `--sent` suffix condition to `False`; `PN3` the `valid_note` prefix test to `True`; `PN4` the "note only" branch for a valid note without a usable block to a return of 3. Run them with `python3 tests/mutation/run_mutants.py --only PN1 PN2 PN3 PN4`; every one must be killed.
      6. `.venv/bin/python -m pytest tests -q` must pass.
      Stop conditions: if `tests/core` has a test that counts the `tld roles` commands or the rows of cli.md and fails after step 3, extend its expected count only; if it fails for another reason, stop with status=blocked. Do not edit section.py.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_roles_page_note.py tests/core/test_contracts.py -q passes
      - .venv/bin/python cli/tld roles page-note --stage send prints the line `HTML page not stored: the page could not be sent as a file.`
      - python3 tests/mutation/run_mutants.py --only PN1 PN2 PN3 PN4 reports every mutant killed
      - .venv/bin/python -m pytest tests/core/test_roles_page_note.py tests/core/test_mutants_file.py -q passes, including test_note_line_, test_every_note_line_is_valid and test_change_report_ tests (Scenarios Page check refused, Board refused or unreachable, Note and block, Invalid note)
      - git diff origin/main --stat -- src/tld/roles/section.py prints nothing
  - id: p3-playbooks
    title: Say the loud line in the dod report and the PR body, and forbid editing the page
    depends_on: [p2-page-note-command]
    complexity: M
    touches:
      - playbooks/dod.md
      - playbooks/implement.md
      - roles/reflektor.md
      - tests/core/test_contracts.py
      - tests/core/test_page_note_playbooks.py
      - evals/baselines/default.json
    brief: |
      Read first: plan section 3.5, playbooks/dod.md (step 5), playbooks/implement.md (section 6 step 3), roles/reflektor.md (step 7), CONTRIBUTING.md (Baseline refresh).
      1. playbooks/dod.md: in step 5 replace the sentences from "The gate file gets only the line printed by" through "is noted in the report, never a failure." by the text of plan 3.5 (its five rules, in that order, in the same plain words; the commands written exactly as there). Keep the sentence about `n/a (worker)` after it unchanged. Write it as the playbook's own prose: no "plan 3.5" reference. Add to the sentence that defines the row values: "`needs attention (<blocking> + <non-blocking>; HTML page not stored)` when a page note exists".
      2. playbooks/implement.md: replace the `## Change report` sentence of section 6 step 3 (the one that names `tld roles section --report`) by the text of plan 3.5 for implement. Keep the phrase `the saved reflektor answer file of dod step 5`.
      3. roles/reflektor.md step 7: replace the sentence after the command by the text of plan 3.5 for the card.
      4. tests/core/test_contracts.py: in `test_reflektor_card_markers_match_the_code` add the dod tokens `tld roles page-note --stage role`, `--stage check`, `--stage board`, `--stage send`, `tld roles change-report`, `HTML page not stored` and `Never edit, rebuild, re-hash or rewrite the page`; change the `between(implement, ...)` call to end at `tld roles change-report --report`; keep every existing token and the assertion of the phrase `the saved reflektor answer file of dod step 5`; add `the page note file of dod step 5` to the implement tokens. Add to the card tokens `never edit`.
      5. New tests/core/test_page_note_playbooks.py: (a) the set of `--stage (role|check|board|send)` words in playbooks/dod.md is exactly those four; (b) dod.md names the row text `needs attention (<blocking> + <non-blocking>; HTML page not stored)`; (c) for each of the four stages build the note with `page_note.note_line`, write it to a note file with an answer file holding a real change-report block, run `page_note.main(["report", "--report", ..., "--note", ...])` through `capsys`, build a pull request body string `"## Change report\n" + output`, and assert the first non-blank line under that heading equals the note and starts with `HTML page not stored: `; (d) with the note file empty the first line under the heading is the first line of the block, not a note; (e) implement.md contains the sentences that forbid removing, rewording or moving the line.
      6. Refresh the eval hashes: `python3 evals/run.py baseline --refresh-hashes`. Say in the commit message: playbook text changed, no command's behaviour that the evals measure (pattern: commit bc6d8aa).
      7. `.venv/bin/python -m pytest tests -q` and `python3 evals/run.py check-baseline` must pass.
      Stop conditions: if a test other than test_contracts fails because of a changed playbook sentence, show it and stop with status=blocked. Do not edit the profile or any protected path.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_page_note_playbooks.py tests/core/test_contracts.py -q passes
      - python3 evals/run.py check-baseline exits 0
      - grep -c "tld roles page-note --stage" playbooks/dod.md prints 4 or more
      - grep -n "HTML page not stored" playbooks/implement.md matches
  - id: p4-docs-spec-retire
    title: Update the guide, hooks doc and changelog, and archive the spec change
    depends_on: [p3-playbooks]
    complexity: S
    touches:
      - docs/guides/reflektor.md
      - docs/architecture/hooks.md
      - CHANGELOG.md
      - openspec/**
    brief: |
      Read first: docs/guides/reflektor.md, docs/architecture/hooks.md, plan sections 3.2 to 3.5.
      1. docs/guides/reflektor.md "What you get": replace the bullet "A failed upload or send is noted in the dod report, never a failure." by: "A page that is refused or cannot be stored is never silent: the dod row reads `needs attention (... ; HTML page not stored)` and the `## Change report` section starts with the line `HTML page not stored: <reason>` (the page check refused it, the board answered an error or could not be reached, the file could not be sent). A page the check refused is not edited or rebuilt to get past it."; add a bullet: "A branch that quotes the secret-scan allow mark still gets its page: the mark is shown as `[secret-scan mark removed]` in the page (the count is printed by `reflektor-html`)."
      2. "Safety rules": in the bullet about the page send (the one that says `verify_html` refuses a page or data carrying the secret-scan allow mark) replace that clause by: "`verify_html` scans every line of the original page and of every decoded string with the allow mark's skip turned off (a credential on a line that ends in the mark is found and refuses the page), and only then replaces each literal mark in the title and the data by `[secret-scan mark removed]`; a mark that survives as an escaped form is refused, and a page with a line-splitting character is refused". In the bullet about `tld roles section` leave the text as is. Add one bullet: "The page note (`tld roles page-note`) is built only from fixed text, a known reason and an HTTP status, and `tld roles change-report` prints it as the first line of the section, so text inside the role's own block cannot forge or move it."
      3. docs/architecture/hooks.md: in the paragraph that names the allow mark add one sentence: "`scan_text(text, skip_marked=False)` scans every line and ignores the mark; `tld roles reflektor-html` uses it." Find the paragraph with `grep -n "secret-scan:allow" docs/architecture/hooks.md`; if no paragraph names the mark in prose, add the sentence to the secret-scan section.
      4. CHANGELOG.md under `## [Unreleased]`: under `### Fixed` add: "The Reflektor change report page is no longer lost when the branch quotes the secret-scan allow mark: the page check scans every line with the mark's skip turned off and then shows each quoted mark as `[secret-scan mark removed]`. When the page is refused or cannot be stored the dod row says `needs attention (... ; HTML page not stored)` and the `## Change report` section starts with `HTML page not stored: <reason>` (#99)." Under `### Added`: "`tld roles page-note` and `tld roles change-report` print the page note and the change-report section with it as first line."
      5. Archive the spec change, in this order: (1) reconcile `openspec/changes/reflektor-page-allow-mark/` with docs/plans/99/deviations.md so the deltas describe what was built; (2) `git diff --quiet $(git merge-base HEAD origin/main) origin/main -- openspec/specs` must exit 0, otherwise stop with status=blocked (main changed the specs, so a MODIFIED block may be stale); (3) `tld ops spec archive --profile .tld/toolkit.yaml reflektor-page-allow-mark`; (4) `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0; (5) `grep -rn "TBD" openspec/specs` must print nothing; (6) commit the moved change and the updated specs.
      6. `.venv/bin/python cli/tld ops docs-index check` exits 0. No doc was added, moved or deleted, so no docs-index row changes.
      Stop condition: a docs-index error or a spec archive error you cannot fix by reconciling the deltas stops the phase with status=blocked.
    acceptance:
      - .venv/bin/python cli/tld ops spec validate exits 0 and openspec/changes/reflektor-page-allow-mark does not exist
      - grep -n "HTML page not stored" docs/guides/reflektor.md CHANGELOG.md matches both files
      - grep -n "skip_marked" docs/architecture/hooks.md matches
      - .venv/bin/python cli/tld ops docs-index check exits 0
```
