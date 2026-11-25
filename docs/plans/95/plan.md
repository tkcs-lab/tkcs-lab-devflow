# Plan: a "Plan ready" card on the board when make-plan finishes

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** When `/tld:make-plan` finishes, the board no longer files the run silently under "Done". It shows a "Plan ready" card. The card has the plan's Summary with bold labels, links to the issue, the plan and the spec change, and the line `/tld:implement <plan URL>` in a field with a Copy button. The card moves to "Done" once `/tld:implement` of that plan writes its first record, when you dismiss it, or after seven days. You also get one push notification.

**Scope:** New: an optional `handover` field on make-plan status records, checked by the record validator and so by the board server. New: a command `tld plan handover`, which copies the Summary word for word and builds the links and the command. New: the "Plan ready" section on the owner page, and the playbook and policy steps that write it. Not changed: other records, the 350-word Summary limit, `tld board stale` and prune, and the issue body. A small-scope prompt's card has the Summary and the issue link but no command to copy (3.4).

**Security:** The owner pastes the copied line into an agent, and the board shows the links. So the command is built from a fixed prefix plus the checked plan link. It is never free text. Every link must point to the repository the record names, on github.com, and the card shows that repository next to the command, because the session that writes the record chooses it. The Summary refuses invisible and control characters and is drawn as text only. The board does not scan for secrets; only `tld plan handover` does (3.1, 3.3).

**Review focus:** the record rules and the trust in the record's own `repo` (3.1); the page re-checks and the copy control inside a `<summary>` element (3.3); the supersede rule by project, plan slug and time (3.3); the secret scan living only in the CLI (3.2); dropping the field on an old board's 422 (3.4).

## 1. Goal

Owner ask ([#95](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/95)): a finished make-plan must not end silently on the board. Its card should show the plan's Summary, a link to the issue, the plan and the spec, and the implement command ready to copy and paste. The owner wrote "capped about 300 words". The existing check caps the Summary at 350 words (`src/tld/plan/summary.py:19`). This plan keeps 350, so the card and the issue show the same text.

## 2. Current state

- **The record.** A make-plan run writes a `kind: command` record with `plan_slug`, `plan_url` and `feature_branch` all null.
  - `src/tld/board/record.py:259-400` validates it. Rule 1 refuses unknown fields (`record.py:265-273`), and the command rules force those three to null (`record.py:309-311`).
  - The only control-character check is ASCII (`CONTROL`, `record.py:38`).
  - `src/tld/schema/status-record.schema.json` documents the shape, and `tests/core/test_status_record.py:176-181` asserts that FIELDS equals the schema's properties and its required list.
  - The store validates every write with this module (`src/tld/board/store.py:141`) and caps a record at 262144 bytes (`store.py:30`). The MCP `board_set` tool goes through the same store.
- **The page.**
  - `section()` (`src/tld/board/web/rules.js:25-32`) puts a `done` record that finished in the last 7 days under "Done". `doneRow` (`src/tld/board/web/board.html:373-378`) then shows only "✓ done · finished x ago", which is the silent ending.
  - `place()` (`rules.js:78-88`) takes no list of the other entries.
  - `link()` (`board.html:150-157`) accepts any `https://` URL. All page text is set with `textContent`.
  - `render()` (`board.html:421-492`) builds the groups `needs_you`, `pr_open`, `running`, `done` and `hidden`.
  - The page CSP is `default-src 'none'; script-src 'unsafe-inline'; ... connect-src 'self'` (`src/tld/board/server.py:65`).
- **Prune.** `tld board stale` mirrors `section()` in Python (`src/tld/board/stale.py:26-39`).
- **The Summary.** It is checked by `tld plan summary-check` (`src/tld/plan/summary.py`).
  - Its parser is `scan`, `normalise` and `count_words`, and its unsafe set is `UNSAFE = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")` (`summary.py:37`).
  - The make-plan playbook copies the Summary into the issue (`playbooks/make-plan.md:431-441`).
- **Secret scan.** `scan_text(text)` in `src/tld/guard/secret_scan.py:112` returns `(line, name, description)` hits.
- **Commands and the end of a run.** CLI routes live in `src/tld/cli.py:22-31`, and `docs/reference/cli.md` must list each command (`tests/core/test_cli_reference.py`). Every `tld` command a playbook names must parse with the real CLI (`tests/core/test_contracts.py`). A playbook change makes `evals/baselines/default.json` stale (CONTRIBUTING.md, "Baseline refresh").
- **Spec.** `openspec/specs/board-server/spec.md` has no requirement for the page's sections.

## 3. Design

### 3.1 The `handover` field (record.py, schema)

- **Where it is allowed.** `handover` is an optional top-level field, and `schema` stays `1`, like the optional phase field `scope`. It is allowed only when `kind` is `command`, `command` is `make-plan` and `status` is `done`.
- **New constants in `record.py`:**
  - `OPTIONAL_FIELDS = ("handover",)`
  - `HANDOVER_FIELDS = ("summary", "plan_slug", "issue_url", "plan_url", "spec_url", "next_command")`
  - `HANDOVER_UNSAFE = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")`
  - `HANDOVER_MAX_WORDS = 350`
  - `HANDOVER_MAX_CHARS = 4000`
  - `HANDOVER_URL_MAX = 300`
  - `NEXT_COMMAND_PREFIXES = ("/tld:implement", "implement")`
  - `HANDOVER_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")`
  - `REF_PATH = r"[A-Za-z0-9._/-]+"`
- **Trust.** Every link is bound to the record's own `repo`, and the page shows `repo`. The writer of a record chooses `repo` (the only tie is that `project` equals the slug of the repository name, `record.py:61-64`), so a session with the board token could name another owner. That session can already write any record and ask; the board adds no owner allowlist here, and the card shows the repository as text so the owner sees where the command points.
- **Imports.** `record.py` stays stdlib-only and imports nothing from `tld.plan`, because the board image needs only `tld.board`.
- **Public helper.** Add `handover_errors(handover, repo: str) -> list[str]`. It returns messages without the `status-record: ` prefix.
- **Unknown-field check.** In Rule 1 a key in `OPTIONAL_FIELDS` is not unknown. Then, when `"handover" in rec`:
  - a run record, or a record of another command, gives `'handover' is only allowed in a make-plan command record`;
  - a status other than `done` gives `'handover' is only allowed when 'status' is 'done'`;
  - in all cases `errors += handover_errors(rec["handover"], rec.get("repo", ""))`.

`handover_errors` produces exactly these messages, in order:

1. **Not an object:** `'handover' must be an object`, and stop.
2. **Keys:** `'handover' is missing '<key>'` and `'handover' has unknown field '<key>'`, using `HANDOVER_FIELDS`.
3. **`summary`:**
   - It must be a non-empty string; otherwise `'handover.summary' must be a non-empty string`.
   - Any character whose `unicodedata.category` is in `HANDOVER_UNSAFE`, other than `"\n"`, gives `'handover.summary' holds a control, format, surrogate, private-use or separator character`.
   - Words are counted as `sum(1 for t in s.split() if re.search(r"\w", t))`, the same rule as `summary.count_words`. More than 350 gives `'handover.summary' has <n> words, at most 350 are allowed`.
   - More than 4000 characters gives `'handover.summary' has <n> characters, at most 4000 are allowed`.
4. **`plan_slug`:** it must match `HANDOVER_SLUG`; otherwise `'handover.plan_slug' must match ^[a-z0-9][a-z0-9-]{0,79}$`.
5. **Links.** Each link is null or a string, matched with `re.fullmatch` in one helper `_link_ok(pattern, value)` that holds the only `re.fullmatch` call of the module (never `match` with `$`, which also accepts a trailing line break). With `R = re.escape(repo)` and `REF_PATH` above, the patterns are:
   - `issue_url`: `^https://github\.com/R/issues/[1-9][0-9]{0,9}$`
   - `plan_url`: `^https://github\.com/R/blob/REF_PATH\.md$`
   - `spec_url`: `^https://github\.com/R/tree/REF_PATH/openspec/changes/<re.escape(plan_slug)>$`. This is checked only when `plan_slug` is valid; otherwise only the generic shape.

   A value also fails when it is longer than 300 characters, or when the part after `https://github.com/` has an empty, `.` or `..` segment when split on `/`. A failing value gives `'handover.<key>' must be null or https://github.com/<repo>/<shape> (at most 300 characters, no empty, . or .. segment)`. The `<shape>` is one of:
   - `issues/<n>`
   - `blob/<branch>/<path>.md`
   - `tree/<branch>/openspec/changes/<plan_slug>`
6. **`next_command`:**
   - It is null or a string. `null` with a `plan_url` set is valid (`tld plan handover` prints it when no prefix is given).
   - When `plan_url` is null it must be null: `'handover.next_command' must be null when 'handover.plan_url' is null`.
   - Otherwise it must equal `p + " " + plan_url` for some `p` in `NEXT_COMMAND_PREFIXES`: `'handover.next_command' must be '<prefix> <plan_url>' with a prefix of /tld:implement, implement`.

**Schema.** Add `handover` to `properties`, not to `required`. Its `$defs/handover` object has `additionalProperties: false`, the six keys as required, and descriptions that copy the rules above. Add one example record that has a `handover`.

### 3.2 `tld plan handover` (new `src/tld/plan/handover.py`)

```
tld plan handover FILE --kind plan|issue --repo OWNER/NAME --plan-slug SLUG
                  [--issue-url URL] [--plan-url URL] [--spec-url URL] [--command-prefix PREFIX]
```

1. Read `FILE` with `summary.read`. Its `ReadError` prints `handover: <message>` and exits 1.
2. Run `summary.check(text, kind)`. Each problem prints `handover: summary: <problem>` and exits 1.
3. Extract the section with `summary.normalise` and `summary.scan`. The section is the lines after the `## Summary` heading up to the next `heading` line, or the end of the file. Strip leading and trailing blank lines and join them with `"\n"`.
4. Reject the section before the scan: when it holds a character whose category is in `record.HANDOVER_UNSAFE` (other than `"\n"`), print `handover: 'handover.summary' holds a control, format, surrogate, private-use or separator character` and exit 1; when it has more than `record.HANDOVER_MAX_CHARS` characters, print `handover: 'handover.summary' has <n> characters, at most 4000 are allowed` and exit 1. (The scan splits lines on more characters than `"\n"`, and `summary.check` does not test these.)
4b. Run `secret_scan.scan_text(section)`. Each hit prints `handover: the Summary holds a secret-like value on line <n>`, where `n` counts from the first non-blank line of the stripped section (that line is line 1). It never prints the value. Exit 1.
5. Build the object:
   - `summary`, `plan_slug`, and the three links (`None` when a link is not given);
   - `next_command` = `f"{prefix} {plan_url}"` when `--command-prefix` is given, else `None`;
   - a prefix without `--plan-url` prints `handover: --command-prefix needs --plan-url` and exits 1.
6. Run `record.handover_errors(obj, repo)`. Each error prints `handover: <error>` and exits 1.
7. Print `json.dumps(obj, ensure_ascii=False)` and exit 0. Nothing is written and nothing is run.

The route in `src/tld/cli.py` after `summary-check` is `("plan", "handover"): ("tld.plan.handover", (), "print the board hand-over of a finished plan: its Summary, links and the implement command")`.

### 3.3 The page (rules.js, board.html)

**rules.js**, new pure functions (exported):

- `escapeRe(s)` returns `s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")`.
- `handoverLinks(rec)` returns `[{name: "issue"|"plan"|"spec", url}]` for each link that is set and matches the same pattern as 3.1, built from `rec.repo`: the same regexes anchored with `^` and `$` and tested on the string as it is (JS `$` does not match before a trailing line break, so a link that ends with one fails), the 300-character limit and the segment rule.
- `handoverCommand(rec)` returns `rec.handover.next_command` only when it equals a prefix from `["/tld:implement", "implement"]` plus `" "` plus a plan link that `handoverLinks` accepted; otherwise `null`.
- `summaryParts(text)` turns the summary into parts:
  - split the text on `"\n"` and skip blank lines;
  - a line matching `/^(?:- )?\*\*([A-Za-z ]{1,30}):\*\*\s?(.*)$/` starts a part `{label, text}`;
  - any other line is appended to the last part's text as `"\n" + line`, or starts `{label: null, text: line}` when there is none;
  - URLs inside the summary stay plain text.
- `planReady(entry, entries, nowMs)` is true when all of these hold:
  - `rec.kind === "command"`, `rec.command === "make-plan"` and `rec.status === "done"`;
  - `rec.handover` is an object with a string `plan_slug`;
  - `section(rec, nowMs) === "done"`;
  - no entry in `entries` has `data.kind === "run"`, `data.project === rec.project`, `data.plan_slug === rec.handover.plan_slug` and `Date.parse(data.updated_at) >= Date.parse(rec.finished_at)` (a run of the same slug that is older than this plan, for example a failed run before a re-plan, does not hide the card).
- `place(entry, asks, nowMs, entries)` gains an optional fourth argument, defaulting to `[]`. The dismissed and needs_you branches stay as they are. The final line becomes: `var s = section(rec, nowMs); if (s === "done" && planReady(entry, entries || [], nowMs)) s = "ready"; return { section: s, badge: null, ask: null };`.
- `section()` is unchanged, so `tld board stale` needs no change. "Plan ready" is a sub-state of "Done".

**board.html:**

- **Groups and placement.** `groups` gets `ready: []`, and `render` calls `place(e, asks, now, entries)`.
- **Counts.** The counts row adds `["✓ plan ready", groups.ready]` after "⇄ PR open".
- **Section.** A section `sect("ready", "Plan ready", n)` is drawn after "PR open" and before "Running", only when it is not empty, sorted `newestFirst("finished_at")`.
- **The card.** `readyRow(entry, now)` uses `row(entry, "ready", now, builder, dismissButton)`. The builder adds:
  - `headLine(rec, span("✓ plan ready", "badge"))` and `span("finished " + ago(rec.finished_at, now))`;
  - a `div.handover` (CSS `white-space: pre-wrap; margin-top: 6px`). Each part is a `div.hpart` holding a `strong` with `label + ":"`, then a text node `" " + text`, or only the text node. Everything uses `el()`/`textContent`, never `innerHTML`;
  - a `div.links` with `link(url, name)` for each `handoverLinks(rec)` item;
  - when `handoverCommand(rec)` is not null, a `div.copy`. It holds an `input` (`type="text"`, `readOnly`, `value` the command, `className = "cmd"`, `aria-label = "Command to start the implementation"`) and a `button` (`type="button"`, `data-action="copy"`, `aria-label = "Copy the command"`, text `Copy`). Above the field a `span.meta` reads `for <rec.repo>` (text).
- **Copy controls inside `<summary>`.**
  - Clicks on the input and the button call `ev.preventDefault(); ev.stopPropagation();`, so the card does not toggle.
  - A `keydown` of Enter or Space on the input does the same.
  - The input then calls `select()`. The button calls `copy(text, input, button)`.
- **`copy()`.** When `window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText`, it calls `writeText(text)`. On success the button text becomes `Copied`. On rejection it falls back. The fallback is `input.focus(); input.select(); input.setSelectionRange(0, input.value.length);` (iOS ignores `select()` on a read-only input) and the button text `Selected: copy it`.
- **CSS:**
  - `.row.ready { border-left: 6px solid var(--ok); }`
  - `.copy { display: flex; gap: 6px; margin-top: 6px; }`
  - `.copy input.cmd { flex: 1 1 auto; min-width: 0; font: 13px ui-monospace, monospace; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; }`

  At 400 px the row must not scroll sideways.

### 3.4 Playbook and policy

**`playbooks/make-plan.md`:**

- **Setup step 3.** Append: `The final `done` write carries the record's `handover` ("The hand-over" in section 5).`
- **Section 5, new step 3.** Insert a new step 3 and renumber the old steps 3 and 4 to 4 and 5. The new step:

  > 3. **The hand-over.** Run `tld plan handover <plan file> --kind plan --repo <owner>/<repo> --plan-slug <plan slug> --issue-url https://github.com/<owner>/<repo>/issues/<n> --plan-url <plan URL> --command-prefix <prefix>`. Add `--spec-url https://github.com/<owner>/<repo>/tree/<feature branch>/openspec/changes/<plan slug>` only with spec parts and when `git ls-tree -d origin/<feature branch> openspec/changes/<plan slug>` prints a line. Leave out `--issue-url` without a tracking issue. `<prefix>` is the runtime's form of the implement command (the runtime map's Names table; `implement` when it names none). Exit 1: fix what each line names (a `summary:` line: fix the plan's Summary, run section 4's checks again, commit and push) and run it again. Exit 0: its stdout is the `handover`. Write the record `done` with it, every item done, `finished_at` set and `last_event` `plan ready: <plan URL>`. When the board answers `invalid` and every listed error names `handover`, write the record once more without `handover` and put `The board is older than this release: update it to see the plan card.` in the final reply. Any other `invalid` follows the record rules. Then `notify_human("<project>: plan ready: <plan slug>")` once; it never carries the Summary.

- **Small scope.** After `Then post `Plan ready: single-session prompt (see the issue body).`` add:

  > With a tracking issue, the final record carries a hand-over as in section 5 step 3, built with `tld plan handover <issue body file> --kind issue --repo <owner>/<repo> --plan-slug issue-<n> --issue-url https://github.com/<owner>/<repo>/issues/<n>` (no plan link, spec link or prefix: the prompt is in the final reply), and the alert reads `<project>: prompt ready: issue #<n>`. Without a tracking issue there is no hand-over.

  The worker's run record has `plan_slug` `issue-<n>` (`make-plan.md:164`), so its first write moves the card to "Done".

**`playbooks/policies/status-board.md`:**

- **The record table.** Add a row after `next_check_at`: `| `handover` | optional, a make-plan record in `done` only: the plan's Summary, its slug, the issue, plan and spec links and the command to copy, printed by `tld plan handover`; the board shows it under "Plan ready" until a run of that plan slug is on the board, the owner dismisses it or 7 days pass |`
- **"No secrets".** The first sentence becomes: `A record holds no file contents, no commit messages and no tokens; the one excerpt it may hold is `handover.summary`, the plan's Summary, which is already in the tracking issue and which only `tld plan handover` scans for secret-like values (the board does not scan a record).`
- **"Alerts".** Append: `A make-plan run that ends with a hand-over also calls `notify_human` once (make-plan, section 5).`

No adapter file changes: the Names table of the runtime skill already maps `implement <URL>` to `/tld:implement <URL>`.

### 3.5 The spec change

`openspec/changes/plan-handover-card/` holds `proposal.md` and two deltas:

- `specs/board-server/spec.md` (ADDED):
  - "Hand-over on a status record", with scenarios Valid hand-over, Hand-over in the wrong record, Unsafe hand-over text, Foreign or malformed link, Command not built from the plan link, and Record without hand-over;
  - "Plan ready cards on the owner page", with scenarios Plan ready card, Copy the command, Implementation started, and Old or dismissed card, plus Re-planned card (a run of the same plan slug that is older than the record does not move it).
- `specs/plan-run-tracking/spec.md` (ADDED): "Hand-over from a plan or an issue body", with scenarios Hand-over printed, Summary word for word and command built, Summary fails its check, Secret in the Summary, Value fails the record rules, and Unreadable file.

The change alters no component, port or dependency of the architecture model: `board.sysml` already has the board service and its client. So it has no `sysml_change`.

### 3.6 Rejected alternatives

- **Reuse the per-record report page (`put-report`).** `report_check.py` pins one viewer by hash, so this would need a second pinned viewer, and the card would still only link to the text.
- **Show `last_event` and parse links out of it.** This parses free text into links, which is not acceptable at the critical security posture.
- **Set `needs_you` with a reason "Start implement".** `status-board.md` keeps `needs_you` for things only the owner can fix, and prune would clear it.
- **Free-text `next_command`.** A line the owner pastes into an agent must not carry text from an issue. That is why it is built from a fixed prefix list plus the checked plan link.
- **Supersede by `plan_url`.** The blob ref can differ (`main` against the feature branch). The plan slug is the run record's key.

## 4. ADRs

This repository's profile has no `docs.adr_dir`.

## 5. Manual steps

**Before implementation:** none.

**After implementation:**

1. **ma1-board-card-look** (about 15 minutes): check the card in a real browser, once on localhost and once from a phone.
   1. Check out `feature/plan-handover-card` and follow "Try it locally" in [docs/guides/board-server.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/plan-handover-card/docs/guides/board-server.md) to start `cli/tld board server --port 8787 --insecure-cookie`, with a token and a passphrase. Export `TLD_BOARD_URL=http://127.0.0.1:8787` and `TLD_BOARD_TOKEN` as that guide says.
   2. The fixture's times are fixed in 2026, so write the first record of the fixture with the current time (the board hides a record not updated for 7 days). Run:
      ```bash
      ID=$(jq -r '.[0].id' tests/fixtures/board-records-handover.json)
      NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      jq --arg now "$NOW" '.[0].data | .finished_at=$now | .updated_at=$now' tests/fixtures/board-records-handover.json | cli/tld board client set "$ID" -
      ```
      The terminal prints the id and version 1.
   3. Open `http://127.0.0.1:8787/` and log in. You should see a "Plan ready" section with the card: bold labels, the issue, plan and spec links, `for tkcs-lab/tkcs-lab-devflow`, and the command field. Press Copy: on localhost the button says `Copied`; paste into a note and check the text is exactly `/tld:implement <plan URL>`.
   4. For the phone: stop the server, start it again with `--host 0.0.0.0` (add `--insecure-cookie` as before), and open `http://<your computer's LAN address>:8787/` on the phone. Over plain http on a LAN address Copy says `Selected: copy it`; use the phone's own copy on the selected text and paste it somewhere. Check that the card does not scroll sideways.
   5. Report back in the pull request: `ma1: pass` or `ma1: fail - <what you saw>`.

## 6. Risks and open questions

- **An old board.** A board server older than this release answers 422 `'handover' is not a known field`. The playbook then writes the record without it (3.4). A worker who sees any other 422 on a record without `handover` has changed something outside 3.1 and stops with `status=blocked`.
- **A long Summary.** A Summary under 350 words but over 4000 characters (long URLs) fails `tld plan handover`. The planner shortens the Summary. If the limit proves too tight in practice, raise `HANDOVER_MAX_CHARS` in one place with its test.
- **The copy control.** Clicks inside `<summary>` toggle a `details` element. If the Playwright check shows the card opening on Copy, the `preventDefault`/`stopPropagation` handlers are missing. Do not move the controls into the detail, because the ask is that the card shows them.
- **Changed contract tests.** `tests/core/test_contracts.py` parses every `tld ...` span in the playbooks. If the new spans with `<placeholders>` do not parse, follow how the existing `tld plan summary-check <issue body file>` span is written; do not change the test.
- **Eval hashes.** The make-plan eval graders check the manifest and the prompt, not the final record, so a hash refresh is honest. Say so in the commit message.
- **Nothing is built in the middle.** If a phase needs the owner, stop with `status=blocked`.

## Implementation manifest

```yaml
plan_slug: plan-handover-card
feature_branch: feature/plan-handover-card
tracking_issue: 95
spec_change: plan-handover-card
max_parallel: 2
manual_before: []
manual_after:
  - id: ma1-board-card-look
    title: Look at a Plan ready card on a phone-width browser and copy its command
    why: the Playwright checks stub the clipboard and use a fixed page; only a real browser on a phone shows the layout, the tap behaviour and what lands on the clipboard
verify_after_merge:
  - .venv/bin/python -m pytest -q -k handover
final_checks:
  - tld plan deviations check --file docs/plans/95/deviations.md --plan docs/plans/95/plan.md --all exits 0
  - the changelog has entries under "## [Unreleased]" and no new version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
  - tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/plan-handover-card does not exist
phases:
  - id: p1-record-handover
    title: Validate the optional handover field of a make-plan status record
    depends_on: []
    complexity: M
    touches:
      - src/tld/board/record.py
      - src/tld/schema/status-record.schema.json
      - tests/core/test_status_record.py
      - tests/core/test_board_store.py
      - tests/core/test_board_server.py
      - tests/fixtures/status-records/good-command-handover.json
      - tests/fixtures/handover-links.json
      - tests/mutation/mutants.yaml
      - tests/core/test_mutants_file.py
    brief: |
      Read first: playbooks/policies/status-board.md (the record table), plan sections 3.1 and 3.6.
      1. In src/tld/board/record.py add the constants of plan 3.1 (OPTIONAL_FIELDS, HANDOVER_FIELDS, HANDOVER_UNSAFE, HANDOVER_MAX_WORDS, HANDOVER_MAX_CHARS, HANDOVER_URL_MAX, NEXT_COMMAND_PREFIXES, HANDOVER_SLUG, REF_PATH) after PR_FIELDS, with `import unicodedata`. Keep the module stdlib-only; import nothing from tld.plan.
      2. Add `def handover_errors(handover, repo: str) -> list[str]` implementing plan 3.1 items 1-6 with exactly the message texts given there, in that order.
      3. In validate(): Rule 1 treats keys of OPTIONAL_FIELDS as known. After Rule 2, when "handover" is in rec, add the two placement errors of plan 3.1 and then `errors += handover_errors(rec["handover"], rec.get("repo") if isinstance(rec.get("repo"), str) else "")`.
      4. Update the module docstring with one sentence on the optional handover field.
      5. src/tld/schema/status-record.schema.json: add `handover` to properties (not required) as `{"$ref": "#/$defs/handover"}`, add `$defs/handover` (six required keys, additionalProperties false, each description stating its rule from plan 3.1), extend the top-level description by one sentence, and add one example: the `data` of tests/fixtures/status-records/good-command-handover.json (written in step 6).
      6. tests/fixtures/status-records/good-command-handover.json: a valid done make-plan record (repo tkcs-lab/tkcs-lab-devflow, orchestrator_session "session_0123456789abcdef", attended true, five items done) with a handover: a three-label summary (Use it, Scope, Review focus, about 60 words, with a line break between labels), plan_slug "demo-plan", issue_url .../issues/7, plan_url .../blob/feature/demo-plan/docs/plans/7/plan.md, spec_url .../tree/feature/demo-plan/openspec/changes/demo-plan, next_command "/tld:implement " + plan_url.
      6b. tests/fixtures/handover-links.json: a JSON list of `{"repo", "plan_slug", "key", "url", "ok"}` cases shared by Python and JavaScript. Include accepted links for each key and refused ones: another repo, http://, `github.com.evil.com`, `/issues/0`, a trailing "\n", ".." "." and empty ("//") segments, "?x=1", "#a", a wrong extension, 301 characters, a spec slug mismatch, a space in the path, `%2e%2e`, `@`, a non-ASCII letter (`é`) in the branch, `HTTPS://GitHub.com/...`, and a repo with a dot (`o/r.x` against `https://github.com/o/rAx/issues/1`, refused). A case becomes a whole hand-over by one rule used by both languages: the link of `key` is `url`, the other links and `next_command` are null, `plan_slug` is the case's, and the summary is the good fixture's.
      7. tests/core/test_status_record.py: add "good-command-handover" to test_good_fixture_passes; change test_fields_match_schema to `set(FIELDS) | set(OPTIONAL_FIELDS) == set(schema["properties"])` with `required == FIELDS`, and also assert `set(schema["$defs"]["handover"]["required"]) == set(schema["$defs"]["handover"]["properties"]) == set(HANDOVER_FIELDS)` and `additionalProperties is False` there. Every error test mutates the good fixture and asserts the WHOLE list: `validate(rec) == [expected]` (never `in`). Cases: (a) placement: handover on good-run.json (a running run: the list is exactly the two placement errors, kind first, status second), on a deps record with status done (only the first), and on the good fixture with status running and finished_at null (only the second); (b) shape: `handover: null`, not an object, a missing key, an unknown key, a non-string summary, a non-string link (7), a non-string next_command, an invalid plan_slug together with a spec_url (the generic-shape path); (c) summary: empty; each of "\u202e" (Cf), "\u200b" (Cf), "\t", "\r", "\x7f", "\x85" (Cc), "\u2028" (Zl), "\u2029" (Zp), "\ue000" (Co) and a lone surrogate built with `json.loads('"\\ud800"')` (Cs) gives the unsafe-character message; 351 words; 4001 characters in 300 words; (d) boundaries that must PASS: `test_handover_accepts_limits` with a summary of exactly 350 words, one of exactly 4000 characters, and a plan_url of exactly 300 characters with next_command built from it, plus "\n" in the summary, `implement <plan_url>`, and `next_command: null` with plan_url set; (e) plan_slug "Demo"; (f) links: for each of issue_url, plan_url and spec_url, the good value plus "\n" is refused with the exact shape message (`test_handover_link_rejects_trailing_newline`); plan_url with "..", with "?x=1", with "#a", ending .txt, 301 characters; spec_url whose last segment differs from plan_slug; (g) next_command "/tld:implement " + plan_url + " && rm -rf x", the same plus "\n", "tld implement " + plan_url, a double space, and one set while plan_url is null. (h) `test_handover_link_corpus`: read tests/fixtures/handover-links.json (step 6b) and assert `handover_errors` is empty for exactly the cases with `ok: true`. (i) `test_handover_rules_match_summary_check`: HANDOVER_UNSAFE == tld.plan.summary.UNSAFE and HANDOVER_MAX_WORDS == summary.MAX_WORDS["plan"] (load modules with conftest._load). (j) `test_old_board_refuses_handover_with_one_named_error`: monkeypatch `record.OPTIONAL_FIELDS = ()` and assert `validate(good) == ["'handover' is not a known field"]`.
      8. tests/core/test_board_store.py: one test that Store.set accepts the good fixture under its record id and returns it unchanged by get, and one that a handover with a foreign issue_url raises Invalid whose errors mention 'handover.issue_url' (follow the existing Store tests in that file); name every new store test `test_store_*handover*`. In tests/core/test_board_server.py, following `test_put_invalid_returns_422_with_errors`, add `test_put_handover_foreign_link_returns_422` (errors contain `'handover.issue_url'`) and `test_put_handover_round_trip` (200, then GET returns the handover unchanged).
      9. tests/core/test_mutants_file.py: add `src/tld/board/record.py` to MODULES (its test_every_mutant_applies requires every mutant file to be listed). tests/mutation/mutants.yaml: use the ids REC-H1 to REC-H6 in the order listed below and add `src/tld/board/record.py: [tests/core/test_status_record.py, tests/core/test_board_store.py]` under `tests:` and mutants (copy the existing entries' shape; each `old` text must occur exactly once in record.py) for: `fullmatch` changed to `match`, the empty/dot segment check removed, the word limit comparison `>` changed to `>=`, the next_command equality changed to `startswith`, `re.escape(repo)` changed to `repo`, and the `status == "done"` placement check removed. Run `.venv/bin/python tests/mutation/run_mutants.py --only <the new ids>`: none may survive.
      Stop condition: if any existing test of tests/core/test_board*.py or test_status_record.py fails after step 3 for a record without handover, stop with status=blocked and quote the failure: plan 3.1 says such records validate exactly as before.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_board_store.py -q passes, including the new handover tests (scenarios Valid hand-over, Hand-over in the wrong record, Unsafe hand-over text, Foreign or malformed link, Command not built from the plan link, Record without hand-over)
      - .venv/bin/python cli/tld board validate-record tests/fixtures/status-records/good-command-handover.json --doc-id tkcs-lab-devflow--make-plan--89abcdef prints status-record OK
      - .venv/bin/python tests/mutation/run_mutants.py --only REC-H1 REC-H2 REC-H3 REC-H4 REC-H5 REC-H6 reports no surviving mutant
      - .venv/bin/python -m pytest tests -q passes
  - id: p2-plan-handover-cli
    title: Add tld plan handover, which prints the hand-over of a plan or an issue body
    depends_on: [p1-record-handover]
    complexity: S
    touches:
      - src/tld/plan/handover.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_plan_handover.py
    brief: |
      Read first: docs/reference/cli.md, src/tld/plan/summary.py, plan section 3.2.
      1. Create src/tld/plan/handover.py (module docstring with the usage line of plan 3.2 and "Python 3.11+, stdlib only"; follow summary.py's layout: argparse main(argv) -> int, `if __name__ == "__main__": sys.exit(main())`). Implement steps 1-7 of plan 3.2 exactly, using tld.plan.summary (read, check, normalise, scan), tld.guard.secret_scan.scan_text and tld.board.record.handover_errors. Import them the way other tld.plan modules import sibling packages (look at src/tld/plan/phases.py).
      2. src/tld/cli.py: add the route of plan 3.2 right after ("plan", "summary-check").
      3. docs/reference/cli.md: add a row after the summary-check row: `| \`tld plan handover FILE --kind plan\|issue --repo OWNER/NAME --plan-slug SLUG [--issue-url URL] [--plan-url URL] [--spec-url URL] [--command-prefix PREFIX]\` | \`tld.plan.handover\` | prints the board hand-over of a finished plan as JSON: the \`## Summary\` word for word, the slug, the links and \`<prefix> <plan URL>\`, checked by the status-record rules and the secret scan; \`handover: <problem>\` lines and exit 1 otherwise |`.
      4. tests/core/test_plan_handover.py (run through conftest.tld_cmd("plan", "handover") like tests/core/test_plan_summary.py): a plan file whose Summary passes prints JSON whose summary equals the section text without the heading and without leading/trailing blank lines, whose next_command is "/tld:implement " + plan_url and whose missing links are null; --kind issue run as the small scope does (`--plan-slug issue-12 --issue-url .../issues/12`, no plan link, spec link or prefix, a non-ASCII character in the Summary) prints a JSON object equal to the whole expected dict with plan_url, spec_url and next_command null and the character unchanged; `--plan-url` without a prefix prints next_command null; the word-for-word fixture has two blank lines after `## Summary`, a blank line before the next `## ` heading and a fenced block holding a `## not a heading` line, and the test compares `summary` with a literal string; `test_handover_summary_unsafe_character` (a Summary label line with U+202E: exit 1, empty stdout, stderr exactly the unsafe-character message) and its twin for 4001 characters in under 350 words (exact characters message), and a Summary with U+2028 before a secret line exits 1 with the unsafe-character message and no line number; a Summary over 350 words prints `handover: summary: ` lines and exits 1; a Summary line holding a high-entropy value assigned to a name ending in `_key` (build the value at runtime with a seeded random generator, as tests/core/test_hook_secret_scan.py does, so no literal credential is in the test file) with a title and blank lines before `## Summary`, one blank line right after the heading and one blank line between line 1 of the stripped section and the secret line, which is line 3 of the stripped section (inner blank lines count), prints exactly `handover: the Summary holds a secret-like value on line 3`, shows the value in neither stdout nor stderr, prints no JSON and exits 1; --plan-url on another repo prints `handover: 'handover.plan_url' must be null or ...` and exits 1; --command-prefix without --plan-url exits 1 with its message; --command-prefix "tld implement" exits 1; `test_handover_unreadable_file[missing|too_large|not_utf8]` (a tmp file of 1000001 bytes, one holding b"\xff") each print exactly one `handover:` line, exit 1 and print nothing on stdout; the printed JSON passes record.handover_errors.
      Stop condition: if tests/core/test_cli_reference.py or test_contracts.py fails on the new route after step 3, stop with status=blocked and quote it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_plan_handover.py -q passes (scenarios Hand-over printed, Summary word for word and command built, Summary fails its check, Secret in the Summary, Value fails the record rules, Unreadable file)
      - .venv/bin/python cli/tld plan handover docs/plans/95/plan.md --kind plan --repo tkcs-lab/tkcs-lab-devflow --plan-slug plan-handover-card --plan-url https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/plan-handover-card/docs/plans/95/plan.md --command-prefix /tld:implement exits 0
      - .venv/bin/python -m pytest tests -q passes
  - id: p3-board-plan-ready
    title: Show done make-plan records with a hand-over in a Plan ready section of the board page
    depends_on: [p1-record-handover]
    complexity: M
    touches:
      - src/tld/board/web/rules.js
      - src/tld/board/web/board.html
      - tests/fixtures/board-records-handover.json
      - tests/board_handover_rules_check.js
      - tests/board_handover_page_check.js
      - tests/core/test_board_handover.py
    brief: |
      Read first: docs/guides/maintenance.md (section "Cards that wait"), plan section 3.3.
      1. src/tld/board/web/rules.js: add escapeRe, handoverLinks, handoverCommand, summaryParts and planReady exactly as plan 3.3 says, give place() its optional fourth argument entries, and export the new functions in module.exports. Leave section() unchanged.
      2. src/tld/board/web/board.html: add groups.ready, the place() call with entries, the counts chip, the "Plan ready" section between PR open and Running, readyRow, the handover block, the copy control and copy(), and the CSS, exactly as plan 3.3 says. Build every node with el()/textContent; never use innerHTML.
      3. tests/fixtures/board-records-handover.json: a JSON list of {id, data} documents (ids from `cli/tld board record-id`), each valid with `cli/tld board validate-record - --doc-id <id>`, at NOW 2026-11-09T12:00:00Z. Every record has project `tkcs-lab-devflow` and repo `tkcs-lab/tkcs-lab-devflow` except (g). Done make-plan records have updated_at equal to finished_at. The records: (a) done make-plan with a full handover, plan_slug "demo-plan", finished 60 minutes before NOW; (i) done make-plan with handover plan_slug "re-planned" finished 90 minutes before NOW; (b) done make-plan with handover plan_slug "issue-12", issue link only, next_command null, finished 120 minutes before NOW; (c) done make-plan with handover plan_slug "other-plan" finished 3 h before; (d) a running run record with plan_slug "other-plan", updated_at 1 h before NOW; (e) done make-plan with handover finished 8 days before; (f) done make-plan without handover finished 1 h before; (g) a running run record of ANOTHER project (project "other-project", repo "tkcs-lab/other-project") with plan_slug "demo-plan" and updated_at 20 minutes before NOW; (h) a running run record with plan_slug "unrelated" and updated_at 10 minutes before NOW (both newer than (a), (i) and (b), so only the project and slug conditions keep (a) ready); every item of the records above has `pr: null` and `branch: null`; (j) a failed run record with plan_slug "re-planned", updated_at 5 h before NOW; (k) done make-plan with handover plan_slug "same-time" finished 2 h before NOW and (l) a run record with plan_slug "same-time" whose updated_at equals (k)'s finished_at; (m) a run record with status `pr_open` (valid: plan_slug "pr-plan", feature_branch "feature/pr-plan", pr {number 5, url https://github.com/tkcs-lab/tkcs-lab-devflow/pull/5, state open, ci pending, awaiting codeowner}, needs_you false), updated_at 30 minutes before NOW. Summaries hold labels on separate lines and one line with a URL; in (a) one line is `**Scope:** <img src=x onerror="window.__xss=1"><a href="https://evil.example">x</a> see https://example.com/page`.
      4. tests/board_handover_rules_check.js (pure node, require rules.js; print OK): place() of (a) and (b) is "ready", (c) is "done" given the fixture entries, (e) is "hidden", (f) is "done", a dismissed copy of (a) is "hidden"; with (g) and (h) on the board (a) stays "ready" (removing the project condition from planReady would make it "done", because (g) is newer), and (i) is "ready" despite (j), and (k) is "done" because of (l) (the `>=` boundary), and (m) is "pr_open"; summaryParts gives the labels in order with their texts and leaves URLs as text; handoverLinks iterates tests/fixtures/handover-links.json and keeps a link exactly when `ok` is true (so the Python and JavaScript rules agree, including the trailing line break and the dotted repo); handoverCommand returns null for "/tld:implement <plan> x", for "/tld:implement <plan>" + "\n", for a double space and for a foreign plan link, and accepts "implement <plan>" and "/tld:implement <plan>".
      5. tests/board_handover_page_check.js (Playwright, like tests/board_prompt_run_check.js: build the page with `cli/tld board build --fixture ... --now NOW`, viewport 400x800): the "Plan ready" section holds exactly the cards of (a), (i) and (b), in that order (newest first), sits after "PR open" and before "Running" in document order, and the counts row shows `✓ plan ready 3` (the PR open section exists because of (m), which is its only card); (c) and (k) are under "Done" and not under "Plan ready"; (a) shows strong elements "Use it:", "Scope:", "Review focus:", links named issue, plan and spec with the fixture hrefs, and an input.cmd whose value is the next_command; (a) contains a `span.meta` whose textContent is exactly `for tkcs-lab/tkcs-lab-devflow` and which comes before `input.cmd` in document order; (b) shows, inside its `summary`, no `span.meta` whose text starts with "for ", no `div.copy` and no `input.cmd`, and the `div.links` that readyRow adds to the summary holds exactly one `a`, named issue, with the fixture href; in (a) `div.handover img` and `div.handover a` both count 0, `window.__xss` is undefined, and the text contains the literal `<img` and the literal URL as text; with an addInitScript that defines navigator.clipboard.writeText to store its argument in window.__copied, (context 1 init script: `Object.defineProperty(navigator,"clipboard",{value:{writeText:async t=>{window.__copied=t}}})`; file:// is a secure context in Chromium) pressing Copy sets window.__copied to the command, a click event dispatched on the button and on the input has `defaultPrevented` true, the button text to "Copied", and leaves the details element closed (also open the card first by clicking its summary outside the controls, press Copy, and assert it stays open); in the insecure-context and rejecting-writeText contexts also assert `details.open === false` after Copy; clicking the input, and pressing Enter and then Space on the focused input, leave it closed with the whole text selected; in a third context whose writeText returns Promise.reject(), Copy shows "Selected: copy it" with the text selected; in a second context whose init script is `Object.defineProperty(window,"isSecureContext",{get:()=>false})`, Copy leaves the input's text selected (selectionStart 0, selectionEnd its length) and the button text "Selected: copy it"; document.documentElement.scrollWidth <= 400; no console errors; print OK.
      6. tests/core/test_board_handover.py: run both node checks (need_tool("node"), skip like tests/core/test_board.py does when Playwright is missing), assert each fixture record validates, and a parity test: the ids that `tld board stale <fixture> --now 2026-11-09T12:00:00Z` prints equal the ids whose rules.section() is "hidden" (compute the node side with a short `node -e` that requires rules.js), and that set contains (e) and excludes (a), (b) and (f). Mark the two node-check tests `@pytest.mark.slow`, as tests/core/test_board.py does.
      Stop condition: if the page check shows the details element open after Copy, or a horizontal scroll at 400 px, fix the handlers or the CSS of plan 3.3; if that needs moving the controls out of <summary>, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_handover.py -q passes with no skipped tests (`-rs` shows none) or in the CI test workflow (scenarios Plan ready card, Copy the command, Implementation started, Re-planned card, Old or dismissed card)
      - tests/core/test_board.py::test_page_builds_the_dom_from_text_only passes and the page check proves the Summary is text only (no img or a element from its markup, no script run)
      - .venv/bin/python -m pytest tests -q passes
  - id: p4-playbook-handover
    title: Make make-plan write the hand-over and alert once, and document the field in the status-board policy
    depends_on: [p2-plan-handover-cli]
    complexity: S
    touches:
      - playbooks/make-plan.md
      - playbooks/policies/status-board.md
      - evals/baselines/default.json
    brief: |
      Read first: playbooks/make-plan.md, playbooks/policies/status-board.md, CONTRIBUTING.md ("Baseline refresh"), plan section 3.4.
      1. playbooks/make-plan.md: make the three edits of plan 3.4 (Setup step 3 sentence, the new section 5 step 3 with the old 3 and 4 renumbered to 4 and 5, the small-scope paragraph) with the literal text given there.
      2. playbooks/policies/status-board.md: make the three edits of plan 3.4 (table row, "No secrets" sentence, "Alerts" sentence) with the literal text given there.
      3. Run `.venv/bin/python -m pytest tests/core/test_contracts.py -q`; it must pass (every tld span parses with the real CLI).
      4. Refresh the eval hashes last: `python3 evals/run.py baseline --refresh-hashes`; commit evals/baselines/default.json in its own commit whose message says: "Refresh eval hashes: make-plan writes a board hand-over at its end; the make-plan graders check the manifest and the prompt, not the final record."
      Stop condition: if test_contracts.py rejects a new span, stop with status=blocked and quote the failure (plan section 6).
    acceptance:
      - grep -n "tld plan handover" playbooks/make-plan.md matches at least twice
      - grep -n "handover" playbooks/policies/status-board.md matches at least three times
      - python3 evals/run.py check-baseline exits 0
      - .venv/bin/python -m pytest tests -q passes
  - id: p5-retire
    title: Retire the plan - the board docs, the README row, the changelog line and the spec archive
    depends_on: [p3-board-plan-ready, p4-playbook-handover]
    complexity: S
    touches:
      - docs/guides/maintenance.md
      - README.md
      - CHANGELOG.md
      - openspec/**
    brief: |
      Read first: docs/guides/maintenance.md ("Cards that wait"), README.md (the Commands table), CHANGELOG.md, plan sections 3 and 6, docs/plans/95/deviations.md.
      1. docs/guides/maintenance.md, "Cards that wait": add after the "One card per wait" bullet: `- **Plan ready.** When /tld:make-plan finishes, its card shows under "Plan ready" with the plan's Summary, links to the issue, the plan and the spec change, and the implement command with a Copy button (over plain http, except on localhost, the button selects the text instead). The card moves to "Done" once /tld:implement of that plan writes its record, when you dismiss it, or after 7 days. A board older than this release refuses the hand-over; make-plan then writes the record without it and says so: update the board.`
      2. README.md, Commands table, the `/tld:make-plan` row: append `; when it finishes, the board shows a Plan ready card with the Summary, the links and the implement command to copy` before the closing `|`.
      3. CHANGELOG.md, under `## [Unreleased]` in `### Added`: `- When /tld:make-plan finishes, the board shows a "Plan ready" card with the plan's Summary, links to the issue, the plan and the spec change, and the implement command ready to copy; new \`tld plan handover\` and the optional \`handover\` field of a make-plan status record (#95).` No version heading.
      4. The spec archive, in this order: (1) reconcile openspec/changes/plan-handover-card/ with docs/plans/95/deviations.md so the deltas describe what was built; (2) `git diff --quiet $(git merge-base HEAD origin/main) origin/main -- openspec/specs` must exit 0, otherwise stop with status=blocked (main changed the specs); (3) `tld ops spec archive --profile .tld/toolkit.yaml plan-handover-card`; (4) `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0; (5) `grep -rn "TBD" openspec/specs` must print nothing; (6) commit the moved change and the updated specs.
      5. No doc is added, moved or deleted, so docs/README.md keeps its rows; run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, then `.venv/bin/python cli/tld ops sysml check` and `.venv/bin/python cli/tld ops sysml render --check` (both exit 0; this plan has no architecture change).
    acceptance:
      - sed -n '/^## \[Unreleased\]/,/^## \[1/p' CHANGELOG.md | grep -n "#95" matches
      - .venv/bin/python cli/tld ops spec validate exits 0 and test ! -e openspec/changes/plan-handover-card
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - .venv/bin/python -m pytest tests -q passes
```
