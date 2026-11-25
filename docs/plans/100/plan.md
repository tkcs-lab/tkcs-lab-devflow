# Plan: the tracking issue link on every board card

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Every card on the board for a run that has a tracking issue (a `/tld:make-plan` run, a `/tld:implement` run whose plan names its issue, a `/tld:quick` run, a single-session prompt's worker) shows a link `issue #<n>` first in its links when you open it, before plan, session, PR and report. One tap takes you to the request and the event comments of that run.

**Scope:** New: an optional `tracking_issue` number on every status record, checked by the record validator and so by the board server; the `issue #<n>` link on the owner page; the playbook lines that write it (make-plan, the prompt worker, implement, quick) and one shared rule for a board older than this release, which also changes prune: an older plugin leaves a record with `tracking_issue` and asks the owner to update it. Not changed: the record schema version, the card summaries, the Plan ready card, `tld board stale`, prune's logic, ids, asks and the issue comments.

**Security:** The page builds the link from the record's `repo` and the number, never from stored free text; the number is capped at ten digits on both sides so the browser never rounds it; a repository with a `.` or `..` part gets no link. The validator refuses a number that disagrees with the record's hand-over issue or with an `issue-<n>` plan slug (3.1, 3.2).

**Review focus:** the validation rules and their messages (3.1); the page's `issueUrl` checks matching the server's (3.2); the one shared old-board rule that drops `handover` and `tracking_issue` together, and that this drop is not the one retry of `invalid` (3.3); keeping the link in the card's details rather than its summary (3.5).

## 1. Goal

Owner ask ([#100](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/100)): put the link of the tracking issue on the board card for the plan, the implement, the quick and the other runs that have one. The issue holds the request, the plan in plain words and every event comment (`Planning started`, `Phase merged`, `PR opened`), so it is the first place the owner goes from a card.

## 2. Current state

- **The record.** `src/tld/board/record.py:29-33` lists the required `FIELDS`; `OPTIONAL_FIELDS = ("handover",)` (`record.py:43`). Rule 1 of `validate` (`record.py:338-346`) refuses any other top-level key with `'<key>' is not a known field`. No field names the tracking issue; the only issue link is `handover.issue_url` of a done make-plan record (`record.py:186-237`, shape `issues/[1-9][0-9]{0,9}`).
  - `_is_int` refuses booleans (`record.py:167-168`).
  - The schema is `src/tld/schema/status-record.schema.json`; `tests/core/test_status_record.py:176-184` asserts `set(FIELDS) | set(OPTIONAL_FIELDS) == set(schema["properties"])` and `required == FIELDS`.
  - Every write path goes through `Store.set` and so `validate` (`src/tld/board/store.py`): the HTTP `PUT /api/records/<id>`, the server's `/mcp` `board_set` (`src/tld/board/mcp.py:100-134`, forwarded by `mcp_stdio.py`), and `tld board client set`. None needs a change.
- **The page.** `detail()` (`src/tld/board/web/board.html:251-256`) builds the links row `plan`, `session`, `PR #<n>`, `Change report`. `link(url, text)` (`board.html:154-161`) accepts only `https://` and sets `target=_blank`, `rel=noopener noreferrer`. A phase's `PR #<n>` link is already built from `rec.repo` and a number (`board.html:280`). Pure rules live in `src/tld/board/web/rules.js` and are exported at `rules.js:215-220`; `handoverLinks` (`rules.js:85-105`) is the pattern for link shape checks.
- **Who has a tracking issue.**
  - make-plan: created or named in section 0 step 1 (`playbooks/make-plan.md:51-58`); the record is `kind: command` (Setup step 3, `make-plan.md:41-47`).
  - The small scope's worker: its run record has `plan_slug` `issue-<n>` (`make-plan.md:163-173`).
  - implement: the manifest's optional `tracking_issue` (`playbooks/implement.md:57-72`); the record is described under "Status record" (`implement.md:472-480`).
  - quick: always has one; its record has `plan_slug` `issue-<n>` (`playbooks/quick.md:29-34`).
- **An older board.** make-plan section 5 step 3 (`make-plan.md:446`) drops only `handover` on an old board's `invalid`; `playbooks/policies/status-board.md` "Writing a record" (`status-board.md:59-65`) has no rule for unknown optional fields.
- **Prune.** `tld board resolve` validates the cleared copy locally (`src/tld/board/resolve.py:40-43`); `playbooks/board.md:44-50` runs it.
- **Spec.** `openspec/specs/board-server/spec.md` has "Hand-over on a status record" and "Plan ready cards on the owner page" and nothing on a tracking issue.

## 3. Design

### 3.1 The `tracking_issue` field (record.py, schema)

- **Where it is allowed.** An optional top-level field on records of both kinds; `schema` stays `1`. Not in `FIELDS` (so not required): records of older writers stay valid.
- **New constants in `record.py`** (after `OPTIONAL_FIELDS`):
  - `OPTIONAL_FIELDS = ("handover", "tracking_issue")`
  - `ISSUE_MAX = 9_999_999_999` (ten digits, the same bound as the hand-over's `issues/[1-9][0-9]{0,9}`)
  - `ISSUE_SLUG = re.compile(r"^issue-([1-9][0-9]{0,9})$")`
  - `ISSUE_IN_URL = re.compile(r"/issues/([1-9][0-9]{0,9})\Z")`
- **Rules**, in `validate`, right after the `handover` block (after Rule 2), when `"tracking_issue" in rec`, with `ti = rec["tracking_issue"]`:
  1. `ti is None`: nothing more.
  2. Not `_is_int(ti) and 1 <= ti <= ISSUE_MAX`: `'tracking_issue' must be null or a positive integer of at most 10 digits`, and nothing more for this field.
  3. When `rec.get("handover")` is a dict whose `issue_url` is a string and `ISSUE_IN_URL.search(issue_url)` matches with a number other than `ti`: `'tracking_issue' must agree with 'handover.issue_url'`. (A malformed `issue_url` is reported by `handover_errors` only.)
  4. When `rec.get("plan_slug")` is a string and `ISSUE_SLUG.fullmatch(plan_slug)` matches with a number `m` other than `ti`: `'tracking_issue' must be <m>, the number in 'plan_slug'`.
- **The code**, so the mutants have literal text. In `validate`, after the `handover` block:
  ```python
  if "tracking_issue" in rec and rec["tracking_issue"] is not None:
      ti = rec["tracking_issue"]
      if not (_is_int(ti) and 1 <= ti <= ISSUE_MAX):
          errors.append("'tracking_issue' must be null or a positive integer of at most 10 digits")
      else:
          ho = rec.get("handover")
          m = ISSUE_IN_URL.search(ho["issue_url"]) if isinstance(ho, dict) and isinstance(ho.get("issue_url"), str) else None
          if m and int(m.group(1)) != ti:
              errors.append("'tracking_issue' must agree with 'handover.issue_url'")
          s = ISSUE_SLUG.fullmatch(rec["plan_slug"]) if isinstance(rec.get("plan_slug"), str) else None
          if s and int(s.group(1)) != ti:
              errors.append(f"'tracking_issue' must be {int(s.group(1))}, the number in 'plan_slug'")
  ```
  The `else` branch is the early stop after rule 2. Inside `validate` every line of this block is indented 4 spaces more than shown.
- **Module docstring.** One sentence: the optional `tracking_issue` names the run's tracking issue by number; the page builds its link from `repo`.
- **Schema.** `properties.tracking_issue = {"type": ["integer", "null"], "minimum": 1, "maximum": 9999999999, "description": "Optional, any record: the number of the run's tracking issue in 'repo'. It must equal the issue of handover.issue_url and the <n> of a plan_slug 'issue-<n>'. The board links it as 'issue #<n>'."}`; not in `required`. Extend the top-level `description` with one sentence naming the optional `tracking_issue`. Add one example: the `data` of `tests/fixtures/status-records/good-run-prompt-issue.json`.

### 3.2 The page (rules.js, board.html)

**rules.js**, a new pure function, exported:

```js
// The issue page of a record's tracking issue (the same rules as tld.board.record), else null.
var ISSUE_MAX = 9999999999;
var ISSUE_REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
function issueUrl(rec) {
  if (!rec || typeof rec.repo !== "string" || !ISSUE_REPO.test(rec.repo)) return null;
  if (rec.repo.split("/").some(function (s) { return s === "." || s === ".."; })) return null;
  var n = rec.tracking_issue;
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || n > ISSUE_MAX) return null;
  return "https://github.com/" + rec.repo + "/issues/" + n;
}
```

JavaScript `$` without the `m` flag does not match before a trailing line break, so a repo ending in `"\n"` fails.

**board.html**, in `detail()`: the links row becomes

```js
var issue = issueUrl(rec);
add(links, issue ? link(issue, "issue #" + rec.tracking_issue) : null, link(rec.plan_url, "plan"), sessionLink(rec),
  rec.pr && rec.pr.url ? link(rec.pr.url, "PR #" + rec.pr.number) : null, reportLink(entry));
```

Nothing else on the page changes; every node is built with `el()`/`link()` and `textContent`.

### 3.3 Playbooks and the policy

Literal edits (each phase brief repeats them):

**`playbooks/policies/status-board.md`:**

- **The record table**, a new row directly after the `handover` row:
  `| \`tracking_issue\` | optional, any record: the number of the run's tracking issue in \`repo\` (make-plan once its issue exists, implement with a manifest \`tracking_issue\`, quick, a single-session prompt's worker), else left out; it must equal the issue of \`handover.issue_url\` and the \`<n>\` of a \`plan_slug\` \`issue-<n>\`; the board links it on the card as \`issue #<n>\` |`
- **"Writing a record"**, a new paragraph at its end:
  `**An older board.** \`handover\` and \`tracking_issue\` are optional fields that a board older than this release does not know. On \`invalid\`, when every listed error is \`'handover' is not a known field\` or \`'tracking_issue' is not a known field\`, write the record once more without the fields those errors name (this write is not the one retry above), leave those fields out of every later write of this run, and put \`The board is older than this release: update it to see the issue link and the plan card.\` once in the final reply.`

**`playbooks/make-plan.md`:**

- **Setup step 3**: insert directly before `Write it first (\`starting\`)` the sentence `With a tracking issue every write from the moment it exists carries \`tracking_issue\` \`<n>\` (the first \`starting\` write comes before section 0 step 1 when the ask names no issue, so it may lack it); without one leave the field out.`
- **Small scope, step 8 (Finish)**: directly after `` `next_check_at: null`; `` insert `` `tracking_issue` the tracking issue's number (left out without one); ``.
- **Section 5 step 3**: replace the sentence `When the board answers \`invalid\` and every listed error says \`handover\` is an unknown or unexpected field, write the record once more without \`handover\` and put \`The board is older than this release: update it to see the plan card.\` in the final reply.` with `When the board refuses \`handover\` or \`tracking_issue\` as unknown fields, follow "An older board" in [policies/status-board.md](policies/status-board.md).`

**`playbooks/implement.md`**, "Status record": directly after `` `plan_slug`, `plan_url` and `feature_branch` from the plan, `` insert `` `tracking_issue` the manifest's `tracking_issue` (left out when the manifest has none), ``.

**`playbooks/quick.md`**, Setup step 4: directly after `` `orchestrator_session` this session's id, `` insert `` `tracking_issue` `<n>` (the tracking issue), ``.

**`playbooks/board.md`**, prune step 6: append the sentence `When \`tld board resolve\` says \`'tracking_issue' is not a known field\`, the plugin is older than the board: leave that record, say so, and tell the owner to update the plugin.`

No adapter file changes: the adapters point to these playbooks and the policy.

### 3.4 The spec change

`openspec/changes/board-issue-link/` holds `proposal.md` and one delta, `specs/board-server/spec.md` (ADDED):

- "Tracking issue on a status record", scenarios Valid tracking issue, Malformed tracking issue, Tracking issue disagrees with the hand-over, Tracking issue disagrees with an issue plan slug, Record without tracking issue;
- "Issue link on the owner page", scenarios Issue link on a card, No issue link.

The change alters no component, port or dependency of the architecture model (the board service and its clients exist already), so the plan has no `sysml_change`.

### 3.5 Rejected alternatives

- **An `issue_url` string.** It needs its own shape, length and segment checks, duplicating `handover_errors`; the page already builds a phase's PR link from `repo` and a number.
- **No new field; derive the number from `plan_slug` `issue-<n>` or `handover.issue_url`.** Misses implement and every make-plan card before `done`, and a worker without an issue takes its slug from the branch name, which could read `issue-12` by chance.
- **The link in the card's always-visible summary line.** The summary is one line per card at 400 px; the details already hold the plan, session and PR links, so the issue goes first there.
- **Hiding the detail's issue link on a Plan ready card that already shows the hand-over's issue link.** The validator makes the two equal (3.1 rule 3), so the duplicate is harmless, and a done make-plan card outside "Plan ready" would lose its only issue link.
- **Retrying without unknown fields inside `tld board client`.** The MCP `board_set` tool goes to the server's `/mcp`, not through the client, so the rule must be in the policy that every writer follows.

## 4. ADRs

This repository's profile has no `docs.adr_dir`.

## 5. Manual steps

**Before implementation:** none.

**After implementation:**

1. **ma1-board-issue-link-look** (about 10 minutes): check the link in a real browser.
   1. Check out `feature/board-issue-link` and follow "Run it locally" in [docs/guides/board-server.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/board-issue-link/docs/guides/board-server.md) to start `cli/tld board server --port 8787 --insecure-cookie` with a token and a passphrase; export `TLD_BOARD_URL=http://127.0.0.1:8787` and `TLD_BOARD_TOKEN` as that guide says.
   2. Write the first record of the fixture with the current time (the board hides a record not updated for 7 days):
      ```bash
      ID=$(jq -r '.[0].id' tests/fixtures/board-records-issue.json)
      NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      jq --arg now "$NOW" '.[0].data | .updated_at=$now' tests/fixtures/board-records-issue.json | cli/tld board client set "$ID" -
      ```
      The terminal prints the id and version 1.
   3. Open `http://127.0.0.1:8787/`, log in, tap the card under "Running". Its links start with `issue #42`; tapping it opens `https://github.com/tkcs-lab/tkcs-lab-devflow/issues/42` in a new tab.
   4. Report back in the pull request: `ma1: pass` or `ma1: fail - <what you saw>`.

## 6. Risks and open questions

- **An older board.** It answers 422 `'tracking_issue' is not a known field` on every record write that carries the field. The policy rule (3.3) drops it for the rest of the run. A worker that sees any other 422 on a record without `tracking_issue` has changed something outside 3.1 and stops with `status=blocked`.
- **An older plugin against a newer board.** `tld board resolve` of an old plugin refuses a stored record with `tracking_issue`; prune then leaves it and asks for a plugin update (3.3, board.md).
- **Existing tests.** `tests/core/test_status_record.py` has `test_old_board_refuses_handover_with_one_named_error`, which monkeypatches `OPTIONAL_FIELDS = ()`; it must still pass unchanged. If any existing test of a record without `tracking_issue` fails, stop with `status=blocked`.
- **Contract tests.** No new `tld` span is added to a playbook; if `tests/core/test_contracts.py` fails after the playbook edits, stop with `status=blocked` and quote it.
- **Eval hashes.** The playbook edits make `evals/baselines/default.json` stale; the make-plan, implement and quick graders check plans, prompts and pull requests, not record fields, so a hash refresh is honest. Say so in the commit message.
- **The prompt worker.** A single-session prompt's worker follows the prompt, which repeats make-plan's step 8 text; the new `tracking_issue` words there reach it.

## Implementation manifest

```yaml
plan_slug: board-issue-link
feature_branch: feature/board-issue-link
tracking_issue: 100
spec_change: board-issue-link
max_parallel: 2
manual_before: []
manual_after:
  - id: ma1-board-issue-link-look
    title: Open a card on a real board and follow its issue link
    why: the Playwright check uses a static page; only the served board in a real browser shows the link opening the real issue in a new tab
verify_after_merge:
  - .venv/bin/python -m pytest -q -k "tracking_issue or issue_link"
final_checks:
  - tld plan deviations check --file docs/plans/100/deviations.md --plan docs/plans/100/plan.md --all exits 0
  - the changelog has entries under "## [Unreleased]" and no new version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
  - tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/board-issue-link does not exist
phases:
  - id: p1-record-tracking-issue
    title: Validate the optional tracking_issue field of a status record
    depends_on: []
    complexity: S
    touches:
      - src/tld/board/record.py
      - src/tld/schema/status-record.schema.json
      - tests/core/test_status_record.py
      - tests/core/test_board_server.py
      - tests/fixtures/status-records/good-run-prompt-issue.json
      - tests/mutation/mutants.yaml
    brief: |
      Read first: playbooks/policies/status-board.md (the record table), plan sections 3.1 and 3.5.
      1. src/tld/board/record.py: set OPTIONAL_FIELDS = ("handover", "tracking_issue") and add ISSUE_MAX, ISSUE_SLUG and ISSUE_IN_URL exactly as plan 3.1 says, after OPTIONAL_FIELDS.
      2. In validate(), right after the `if "handover" in rec:` block, add the four rules of plan 3.1 in that order with exactly the message texts given there (rule 2 stops the other rules for the field; rules 3 and 4 run only for a valid non-null number). Add the docstring sentence of plan 3.1.
      3. src/tld/schema/status-record.schema.json: add the `tracking_issue` property of plan 3.1 (not to `required`), the top-level description sentence, and one example: the data of the fixture of step 4.
      4. tests/fixtures/status-records/good-run-prompt-issue.json: a copy of tests/fixtures/status-records/good-run-prompt.json (plan_slug "issue-42") with `"tracking_issue": 42` added after "repo".
      5. tests/core/test_status_record.py: add "good-run-prompt-issue" to the parametrize list of test_good_fixture_passes. Add tests that mutate a fixture and assert the WHOLE error list (`validate(rec) == [expected]`, never `in`), each named test_tracking_issue_*: (a) on good-run.json (plan_slug "example-plan"): values 0, -1, 10_000_000_000, True, 1.5 and "12" each give exactly ["'tracking_issue' must be null or a positive integer of at most 10 digits"]; values 1, 9_999_999_999 and None give []; (b) on good-command.json (a command record) 7 gives []; (c) on good-command-handover.json (issue_url .../issues/7): tracking_issue 7 and None give [], 8 gives exactly ["'tracking_issue' must agree with 'handover.issue_url'"]; test_tracking_issue_malformed_issue_url_reports_once: with issue_url changed to the same URL ending in `/issues/07` and tracking_issue 7, `validate(rec) == record.handover_errors(rec["handover"], rec["repo"])` and no error names 'tracking_issue'; test_tracking_issue_malformed_skips_agreement_rules: on good-run-prompt.json (plan_slug "issue-42") the values "42" and 0 each give exactly the one malformed message, and on good-command-handover.json the value 0 gives exactly that message too; (d) on good-run-prompt.json (plan_slug "issue-42"): 43 gives exactly ["'tracking_issue' must be 42, the number in 'plan_slug'"], None gives []; (e) on good-run-prompt-issue.json with plan_slug changed to "issue-042x" (no match) 42 gives []; (f) test_old_board_refuses_tracking_issue_with_one_named_error: monkeypatch record.OPTIONAL_FIELDS = ("handover",) and assert validate(good-run-prompt-issue) == ["'tracking_issue' is not a known field"].
      6. tests/core/test_board_server.py, following test_put_handover_round_trip: add test_put_tracking_issue_round_trip (200, then GET returns tracking_issue unchanged; repeat with null) and test_put_tracking_issue_invalid_returns_422 (tracking_issue 0: 422 `invalid`, `body["errors"] == ["'tracking_issue' must be null or a positive integer of at most 10 digits"]`).
      7. tests/mutation/mutants.yaml: add mutants REC-T1 to REC-T6 for src/tld/board/record.py, copying the REC-H entries' shape (each `old` text must occur exactly once in record.py): REC-T5 changes `if s and int(s.group(1)) != ti:` to `if False:`, REC-T6 replaces the two lines `        else:\n            ho = rec.get("handover")` (8 and 12 leading spaces: the code of 3.1 sits 4 spaces deep inside `validate`) with `        if True:\n            ho = rec.get("handover")` (rules 3 and 4 then also run on a malformed value); REC-T1 accepts a boolean (`_is_int(ti)` becomes `isinstance(ti, int)`), REC-T2 accepts zero (`1 <= ti <= ISSUE_MAX` becomes `0 <= ti <= ISSUE_MAX`), REC-T3 accepts eleven digits (`ti <= ISSUE_MAX` becomes `ti <= ISSUE_MAX * 10`), REC-T4 drops the hand-over agreement (`if m and int(m.group(1)) != ti:` becomes `if False:`). The record.py tests entry already lists tests/core/test_status_record.py. Run `.venv/bin/python tests/mutation/run_mutants.py --only REC-T1 REC-T2 REC-T3 REC-T4 REC-T5 REC-T6`: none may survive.
      Stop condition: if any existing test of tests/core/test_board*.py or tests/core/test_status_record.py fails for a record without tracking_issue, stop with status=blocked and quote the failure: plan 3.1 says such records validate exactly as before.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_board_server.py -q -k "tracking_issue or good_fixture or fields_match_schema" passes (scenarios Valid tracking issue, Malformed tracking issue, Tracking issue disagrees with the hand-over, Tracking issue disagrees with an issue plan slug, Record without tracking issue)
      - .venv/bin/python cli/tld board validate-record tests/fixtures/status-records/good-run-prompt-issue.json prints `status-record: OK`
      - .venv/bin/python tests/mutation/run_mutants.py --only REC-T1 REC-T2 REC-T3 REC-T4 REC-T5 REC-T6 reports no surviving mutant
      - the existing test_old_board_refuses_handover_with_one_named_error and the bad-* fixture tests of tests/core/test_status_record.py still pass unchanged (scenario Record without tracking issue)
      - .venv/bin/python -m pytest tests -q passes
  - id: p2-board-issue-link
    title: Show the issue link first in a card's links on the board page
    depends_on: [p1-record-tracking-issue]
    complexity: S
    touches:
      - src/tld/board/web/rules.js
      - src/tld/board/web/board.html
      - tests/fixtures/board-records-issue.json
      - tests/board_issue_link_check.js
      - tests/board_issue_link_page_check.js
      - tests/core/test_board_issue_link.py
    brief: |
      Read first: docs/guides/maintenance.md (section "Cards that wait"), plan section 3.2.
      1. src/tld/board/web/rules.js: add ISSUE_MAX, ISSUE_REPO and issueUrl exactly as plan 3.2 shows, directly before the `module.exports` block, and add `issueUrl: issueUrl` to module.exports.
      2. src/tld/board/web/board.html: in detail(), replace the `add(links, ...)` call with the two statements of plan 3.2. Change nothing else.
      3. tests/fixtures/board-records-issue.json: a JSON list of {id, data} documents (ids from `cli/tld board record-id`), each valid with `cli/tld board validate-record - --doc-id <id>`, at NOW 2026-11-20T12:00:00Z, project tkcs-lab-devflow, repo tkcs-lab/tkcs-lab-devflow, status running, updated_at 10 minutes before NOW, every item with pr null and branch null: Every record has feature_branch "feature/<its plan_slug>" ("fix/issue-7" for (b)), needs_you false, needs_you_reason "", needs_you_since null, last_event "running", next_check_at null, finished_at null, pr all-null object, and `phases: []`, except (c). (a) first in the list, an implement run, plan_slug "demo-plan", plan_url https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/demo-plan/docs/plans/42/plan.md, orchestrator_session "session_0123456789abcdef", tracking_issue 42; (b) a quick run, plan_slug "issue-7", tracking_issue 7; (c) an attended make-plan command record (orchestrator_session "session_fedcba9876543210", plan_slug, plan_url and feature_branch null, items `research`, `decide`, `write` in state done and `review`, `hand-over` in state pending, titles "Research", "Decide", "Write", "Review", "Hand over", each with depends_on [], complexity null, session null, branch null, started_at and finished_at null) with tracking_issue 100; (d) a run, plan_slug "no-issue", without the field; (e) a run, plan_slug "null-issue", tracking_issue null.
      4. tests/board_issue_link_check.js (pure node, require ../src/tld/board/web/rules.js; print OK): issueUrl returns "https://github.com/o/r/issues/1" for {repo:"o/r", tracking_issue:1} and the URL with 9999999999 for that value; it returns null for tracking_issue true, 0, -1, 1.5, "5", 10000000000, 2**53, null and a missing field, and for repo "o/r/x", "../r", "o/..", "./r", "o/r\n", "" and a non-string repo.
      5. tests/board_issue_link_page_check.js (Playwright, built like tests/board_handover_page_check.js with `cli/tld board build --fixture tests/fixtures/board-records-issue.json --now NOW`, viewport 400x800): for each of (a), (b), (c) open the card (click its summary) and assert the first `a` in its `.detail .links` has text `issue #42`, `issue #7`, `issue #100` and href `https://github.com/tkcs-lab/tkcs-lab-devflow/issues/<n>`, target `_blank` and rel `noopener noreferrer`; then build the page a second time from the same fixture with `tracking_issue` deleted from every record, and assert that for each of (a), (b) and (c) the list of `[text, href]` pairs of `.detail .links a` of the first page equals `[["issue #<n>", <issue href>]]` followed by exactly the list of the second page (so no other link changed or moved); (d) and (e) have no `a` whose text starts with `issue` and their lists equal their lists on the second page; document.documentElement.scrollWidth <= 400; no console errors; print OK.
      6. tests/core/test_board_issue_link.py: run both node checks (need_tool("node"); skip the page check when Playwright is missing, as tests/core/test_board_handover.py does, and mark both `@pytest.mark.slow` as it does), name the tests test_issue_link_rules and test_issue_link_page, add test_issue_link_fixture_is_valid that validates every fixture record with tld.board.record.validate(data, id), and add test_issue_link_bounds_match_the_validator (plain unit test, no node): read rules.js as text and assert it contains `var ISSUE_MAX = 9999999999;` with that number equal to record.ISSUE_MAX, and that the source of its `ISSUE_REPO` regex literal between the slashes equals `record.REPO.pattern` with the anchors kept. The page check only runs where Playwright is installed; the CI test workflow (.github/workflows/test.yml) installs it, so that run is what proves the page.
      Stop condition: if the page check finds the issue link anywhere but first in the detail links, or another card's links changed order, fix step 2 to match plan 3.2; if that is not possible without changing other links, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_issue_link.py -q -rs passes with no skipped test where Playwright is installed (the CI test workflow `.github/workflows/test.yml` is that place; scenarios Issue link on a card, No issue link)
      - tests/core/test_board.py::test_page_builds_the_dom_from_text_only passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p3-playbooks-tracking-issue
    title: Make the playbooks write tracking_issue and share one old-board rule
    depends_on: [p1-record-tracking-issue]
    complexity: S
    touches:
      - playbooks/policies/status-board.md
      - playbooks/make-plan.md
      - playbooks/implement.md
      - playbooks/quick.md
      - playbooks/board.md
      - tests/core/test_board_record_wording.py
      - evals/baselines/default.json
    brief: |
      Read first: playbooks/policies/status-board.md, CONTRIBUTING.md ("Baseline refresh"), plan section 3.3.
      1. playbooks/policies/status-board.md: add the table row and the "An older board." paragraph of plan 3.3, with the literal text given there.
      2. playbooks/make-plan.md: make the three edits of plan 3.3 (Setup step 3 sentence, small-scope step 8 insertion, section 5 step 3 sentence replacement) with the literal text given there.
      3. playbooks/implement.md, playbooks/quick.md and playbooks/board.md: make the one edit each of plan 3.3 with the literal text given there.
      3b. tests/core/test_board_record_wording.py: add `test_status_board_policy_has_the_older_board_rule`, following the file's helpers (`POLICY`, `_text`): the literal paragraph of plan 3.3 starting `**An older board.**` occurs exactly once in playbooks/policies/status-board.md, and playbooks/make-plan.md contains the link `[policies/status-board.md](policies/status-board.md)` on the line that holds `An older board`.
      4. Run `.venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_board_record_wording.py -q`; it must pass.
      5. Refresh the eval hashes last: `python3 evals/run.py baseline --refresh-hashes`; commit evals/baselines/default.json in its own commit whose message says: "Refresh eval hashes: the playbooks write tracking_issue on their status records; the graders check plans, prompts and pull requests, not record fields."
      Stop condition: if an anchor text of plan 3.3 does not occur exactly once in its file, or test_contracts.py fails, stop with status=blocked and quote it.
    acceptance:
      - grep -c '^| `tracking_issue`' playbooks/policies/status-board.md prints 1 and grep -n 'An older board' playbooks/policies/status-board.md matches
      - .venv/bin/python -m pytest tests/core/test_board_record_wording.py -q passes, including the new test_status_board_policy_has_the_older_board_rule
      - grep -n "An older board" playbooks/make-plan.md matches and grep -n "update it to see the plan card" playbooks/make-plan.md matches nothing
      - grep -n "the manifest's \`tracking_issue\`" playbooks/implement.md matches, and grep -n "\`tracking_issue\` \`<n>\`" playbooks/quick.md matches, and grep -n "'tracking_issue' is not a known field" playbooks/board.md matches
      - .venv/bin/python -m pytest tests/core/test_evals_baseline.py tests/core/test_contracts.py tests/core/test_board_record_wording.py -q passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p4-retire
    title: Retire the plan - the board docs, the changelog line and the spec archive
    depends_on: [p2-board-issue-link, p3-playbooks-tracking-issue]
    complexity: S
    touches:
      - docs/guides/maintenance.md
      - docs/guides/board-server.md
      - CHANGELOG.md
      - openspec/**
    brief: |
      Read first: docs/guides/maintenance.md ("Cards that wait"), docs/guides/board-server.md (the example record), CHANGELOG.md, plan sections 3 and 6, docs/plans/100/deviations.md.
      1. docs/guides/maintenance.md, "Cards that wait": add after the "Plan ready" bullet: `- **Issue link.** A card whose run has a tracking issue (make-plan, implement with a plan that names its issue, quick, a single-session prompt's worker) shows \`issue #<n>\` first in its links when you open it. A board older than this release refuses the field; the session then writes its records without it and says so: update the board.`
      2. docs/guides/board-server.md, the example record: add `"tracking_issue": 7,` on its own line directly after the `"repo"` line, with the same indentation.
      3. CHANGELOG.md, under `## [Unreleased]` in `### Added`: `- Board cards link the run's tracking issue (\`issue #<n>\`) for make-plan, implement, quick and a single-session prompt's worker; new optional \`tracking_issue\` field of a status record, and one rule for a board that does not know an optional field (#100).` No version heading.
      4. The spec archive, in this order: (1) reconcile openspec/changes/board-issue-link/ with docs/plans/100/deviations.md so the deltas describe what was built; (2) `git diff --quiet $(git merge-base HEAD origin/main) origin/main -- openspec/specs` must exit 0, otherwise stop with status=blocked (main changed the specs); (3) `tld ops spec archive --profile .tld/toolkit.yaml board-issue-link`; (4) `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0; (5) `grep -rn "TBD" openspec/specs` must print nothing; (6) commit the moved change and the updated specs.
      5. No doc is added, moved or deleted, so docs/README.md keeps its rows; run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, then `.venv/bin/python cli/tld ops sysml check` and `.venv/bin/python cli/tld ops sysml render --check` (both exit 0; this plan has no architecture change).
    acceptance:
      - sed -n '/^## \[Unreleased\]/,/^## \[1/p' CHANGELOG.md | grep -n "#100" matches
      - .venv/bin/python cli/tld ops spec validate exits 0 and test ! -e openspec/changes/board-issue-link
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - .venv/bin/python -m pytest tests -q passes
```
