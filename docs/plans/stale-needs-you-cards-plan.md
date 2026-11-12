# Plan: stale "needs you" cards on the board

Tracking issue: https://github.com/tkcs-lab/tkcs-lab-devflow/issues/18

## Goal

A "Needs you" card on the board always means something the owner can still act on. Today two kinds of card
outlive their reason, and the owner can do nothing about them:

1. The card of a session that is gone (the `/land` run whose pull requests were all merged stays "needs you" for
   ever).
2. The run card of a session that asked a question on the board: the ask card disappears when the owner answers,
   the run card stays until the session wakes (up to 10 minutes, or until the owner types in the chat).

After this change:

- The page shows one card per wait. While an ask is open only the ask card shows; once the owner answered, the run
  moves out of "Needs you" and shows "answer received".
- The owner can dismiss a stuck card on the page, and restore it. The board keeps the dismissal next to the record;
  it never rewrites a record (the owner still writes no record).
- `/land` asks only for what only the owner can fix. Its pull requests are items of its record, not a
  "needs you" alert.
- `/tld:board prune` also clears the "needs you" of a record whose pull requests are all merged or closed, after
  the owner confirms.

The owner's decisions (ask `a-c0d8dd064610711f`, answered 2026-11-12): `link: display`, `dismiss: overlay`,
`land_alert: quiet`, `reconcile: both`.

## Current state

- `src/tld/board/web/rules.js:25` `section()` returns `needs_you` for every record with `needs_you === true`,
  whatever its age. `isHidden` (`rules.js:11`) excludes them. `src/tld/board/stale.py:25` mirrors the rule and
  never prints a `needs_you` record (`stale.py:26`); `playbooks/board.md:31-32` promises the same.
- The owner has no write path to records: `server.py:78-79` allows `PUT` and `DELETE` of a record to the session
  token only, and `docs/guides/board-server.md:18-21` states it. Prune deletes with `tld board client delete`
  after a confirm (`playbooks/board.md:35`).
- `Store.answer_ask` (`src/tld/board/store.py:206-219`) changes only the ask. An ask has `created_by` and
  `project` but no link to a record (`ask.py:24` `FIELDS`). A record has `orchestrator_session`
  (`record.py:26`).
- `board.html:361-364` draws the open asks, then every `needs_you` record, in "Needs you". A record is drawn
  from `section(e.data, now)` alone (`board.html:342`).
- `playbooks/land.md:60-72` sets `needs_you` for `Review PR #<n>`; the 2026-11-12 land record kept
  `needs_you: true` after PRs #6, #7, #8 and #9 were merged, and its session was archived.
- `record.py:311` (rule 6) rejects a `done`, `failed`, `waiting_user` or `pr_open` record that has `next_check_at`.
- Database schema version is 3 (`store.py:27`); tests pin it (`tests/core/test_board_store.py:122,139`).

## Design

### 3.1 The record entry (store and API)

Every record entry the store returns gains one key, `dismissed_at`:

```json
{"id": "<doc id>", "version": 3, "dismissed_at": null, "data": {"...": "..."}}
```

`dismissed_at` is the ISO time of the owner's dismissal when it was made on the record's current version, else
`null`. It is in `GET /api/records`, `GET /api/records/<id>`, the `current` of a 409, and MCP `board_list` and
`board_get`. `PUT` results (`{"id", "version"}`) do not change.

Store (`src/tld/board/store.py`):

- `SCHEMA_VERSION = 4`. Migration step 4, idempotent:
  `CREATE TABLE IF NOT EXISTS dismissals(doc_id TEXT PRIMARY KEY, version INTEGER NOT NULL, dismissed_at TEXT NOT NULL)`.
- `_row`, `_get` and `list` read `records r LEFT JOIN dismissals d ON d.doc_id = r.id` and select
  `CASE WHEN d.version = r.version THEN d.dismissed_at END`.
- `Store.dismiss(doc_id: str, version: int) -> dict` returns `{"id", "version", "dismissed_at"}`. Under the one
  lock it raises `NotFound` (no record), `Conflict(current)` (stored version differs from `version`) and
  `Invalid(["the record does not need you"])` (`data.needs_you` is not true), else
  `INSERT OR REPLACE INTO dismissals`.
- `Store.restore(doc_id: str) -> dict` returns `{"id", "dismissed_at": None}`; raises `NotFound` when there is no
  record; deletes the dismissal row when there is one.
- `Store.delete` also deletes the dismissal row in the same lock.
- A session rewrite changes `version`, so the dismissal stops matching and the record returns if it still has
  `needs_you: true`. Nothing else touches `records` rows: `dismiss` and `restore` never change `data` or
  `version`.

Server (`src/tld/board/server.py`):

- Routes `^/api/records/([^/]+)/dismiss$` (name `dismiss`) and `^/api/records/([^/]+)/restore$` (name `restore`),
  method `POST`, both with `POLICY` `{OWNER}` only. The origin and CSRF checks in `_dispatch` apply with no new
  code.
- `POST .../dismiss`, body exactly `{"version": <int >= 1>}`: 200 with the `dismiss` result; 400 `bad_request` for
  any other body; 404 `not_found`; 409 `version_conflict` with `current`; 409 `not_needs_you` when the store raises
  `Invalid`.
- `POST .../restore`, empty body (as `cancel` reads it): 200 with the `restore` result; 404 `not_found`.
- MCP: no new tool. The descriptions of `board_list` and `board_get` say each entry has `dismissed_at`.

### 3.2 The ask-to-record link

- An ask gains the optional field `record`: `null` or the document id of the status record that posted it
  (`<project>` for a run, `<project>--<command>` for a command). Validation in `ask.py`: when present and not
  `null`, it matches `tld.board.record.DOC_ID_RE` (new, `^[a-z0-9][a-z0-9-]{0,99}$`, the same pattern as
  `store.ID_RE`) and equals the ask's `project` or `<project>--<command>` for a `command` in
  `record.COMMANDS`. Error text: `'record' must be null, the project slug, or '<project>--<command>'`. `record`
  is the last entry of `ask.FIELDS` and of the schema's `properties`.
- `create_ask` keeps dropping `None` values; a missing `record` means `null` everywhere.
- Playbooks set `record` (section 3.6).

### 3.3 The placement rules (`src/tld/board/web/rules.js`)

`section(rec, nowMs)`, `isHidden`, `isSilent`, `drift` and `elapsed` do not change. New pure functions, all
exported next to them (an `entry` is `{id, version, dismissed_at, data}`; `asks` are stored asks):

- `isDismissed(entry)`: `entry.dismissed_at` is a string and `entry.data.needs_you === true`.
- `linksTo(ask, entry)`: when `ask.record` is a string, `ask.record === entry.id`. Otherwise all of:
  `entry.data.orchestrator_session` is a non-empty string, `ask.created_by === entry.data.orchestrator_session`
  and `ask.project === entry.data.project`.
- `linkedAsks(entry, asks)`: the asks with `linksTo(ask, entry)`.
- `answerReceived(entry, asks)`: no linked ask is `open`, and some linked ask has `state === "answered"` with
  `Date.parse(answered_at) >= Date.parse(entry.data.needs_you_since)`. Returns that ask, else `null`.
- `place(entry, asks, nowMs)` returns `{section, badge, ask}`:
  - `section` is `needs_you`, `linked`, `pr_open`, `running`, `done` or `hidden`; `linked` means no record card is
    drawn (the open ask card is the one card of the wait).
  - `badge` is `null`, `"answer_received"` or `"dismissed"`; `ask` is the answered ask for `answer_received`,
    else `null`.
  - For `data.needs_you === true` the order is: `isDismissed` gives `{hidden, dismissed}`; an open linked ask
    gives `{linked, null}`; `answerReceived` gives `{running, answer_received, <ask>}`; everything else is
    `section(rec, nowMs)` with a `null` badge. For `needs_you !== true` the result is `section(rec, nowMs)`.

A cancelled linked ask has no effect (the card is the ordinary `needs_you` card); the owner can dismiss it.
`linked` records count in neither "needs you" nor "running" in the page's counts.

### 3.4 The page (`src/tld/board/web/board.html`)

- `render` groups entries by `place(entry, asks, now).section` and skips `linked`.
- A record in `running` with badge `answer_received` is drawn by a new `answeredRow`: head line with the badge
  `✓ answer received`, then the meta line `Waiting for the session to continue · answered <ago(ask.answered_at)>`.
- A `Dismiss` button (class `quiet`, `data-action="dismiss"`) is in the detail block of every `needs_you` card
  (not inside the `<summary>`), drawn only when `csrf` is set. It posts
  `api("POST", "api/records/<id>/dismiss", {version: entry.version})`, then `load()`. A 409 shows the notice
  `The record changed. Look at it again.` and reloads.
- A `Restore` button (`data-action="restore"`) is in the detail block of every hidden entry with `badge`
  `dismissed`, drawn only when `csrf` is set. It posts `api("POST", "api/records/<id>/restore")`, then `load()`.
- The hidden row's badge reads `dismissed` for a dismissed entry; the Hidden note reads `No update for more than
  7 days, finished earlier, or dismissed. Still stored.`
- The page writes records never: no `api("PUT"` and no `"DELETE"` appear (`tests/core/test_board.py:59`).

### 3.5 Prune and the new command

- `src/tld/board/stale.py`: a document is `hidden` also when `doc.get("dismissed_at")` is a string and
  `data.needs_you` is true. The docstring and `playbooks/board.md` say a `needs_you` record is printed only when
  the owner dismissed it.
- New `src/tld/board/resolve.py`, pure (imports only `tld.board.record`), command
  `tld board resolve FILE|- --now ISO --reason TEXT` (row in `src/tld/cli.py` `COMMANDS`, row in
  `docs/reference/cli.md`). `FILE` is a bare status record, or a board entry `{"id", "version", "data"}` (its
  `data` is used). It prints the cleared record as JSON on stdout: `needs_you` false, `needs_you_reason` `""`,
  `needs_you_since` null, `status` `done`, `finished_at` `--now`, `next_check_at` null, `updated_at` `--now`,
  `last_event` `--reason` (at most 200 characters), everything else unchanged. Exit 1 with a line starting
  `board_resolve: ` when the record does not have `needs_you` true, the reason is empty or too long, or the output
  fails `record.validate`. `resolve` never reads the network.
- `playbooks/board.md` prune adds a second list: a record with `data.needs_you` true that is not in the stale
  output and that names at least one pull request number (`phases[].pr` or `pr.number`), where
  `github.pr_read` says every one of them is merged or closed. One `ask_human` with a `confirm` question per non-empty list; both lists empty: say `Nothing to prune` and stop.
  On yes, per record: `tld board client get <id>`, `tld board resolve` on its `data`, then
  `tld board client set <id> - --if-version <n>` (a `version_conflict`: leave the record, say so). A record with no
  pull request number, or with one still open, is never offered.

### 3.6 Playbooks

- `playbooks/land.md`: a new section 0 "Reconcile" (read the old record `<project>--land`, report each pull
  request it names as carried over (still open) or settled (merged or closed), never carry a `needs_you` over:
  the first write replaces the record). `needs_you` is set only for: the `land_order` error, a non-mechanical
  conflict, red integration CI, and the missing workflows permission. The integration draft
  and the workflow pull request are items (`integration`, `workflow`) with their `pr` number; no `needs_you`
  for `Review PR #<n>`. The final record is `pr_open` with `needs_you` false unless one of the blocking cases
  above happened.
- `playbooks/runtime.md` `ask_human`: the ask example gains `"record": "<the status record's document id>"` and a
  sentence: the page shows one card while the ask is open and `answer received` after the owner answers.
- `playbooks/policies/status-board.md`: the rule that a playbook's asks carry `record`; the final record never
  keeps `needs_you: true` unless the run stopped on something only the owner can fix; the owner's Dismiss and
  prune's clearing; and `version_conflict` with `current: null` means the record was deleted: write it again
  without `if_version`.
- `adapters/claude/skills/runtime/SKILL.md`: the sentence about prune also names `tld board resolve`.

### 3.7 Rejected alternatives

- **The board rewrites the record when an ask is answered** (`link: server-writes`): simplest for every reader of
  the record, but the board would write records, which `docs/guides/board-server.md:18-21` rules out and the auth
  matrix tests.
- **A Dismiss that rewrites the record**: smallest change, same objection; it also loses what the session wrote.
- **Hiding a `needs_you` card by age**: a real open question could vanish unseen after a week.
- **`dismissed_at` through a second endpoint**: prune reads `tld board client list`, so `stale.py` would need two
  reads; one entry shape serves the page, prune and MCP.
- **`section()` with a context argument**: it is pinned by the 13-record fixture and mirrored by `stale.py`;
  `place()` sits on top and leaves both stable.
- **GitHub-side clearing** (the land workflow calling the board): it needs the board token as a secret in
  GitHub; out of scope.

### 3.8 Existing tests this change touches

`tests/core/test_board_store.py:122,123,139` (schema 3, whole-entry equality), `tests/core/test_board_deploy.py:101`
(every route is in the guide), `tests/core/test_board_server.py:44` (the auth matrix `MATRIX` is a hand list; p1 adds a test that it covers every `POLICY` entry),
`tests/core/test_board_inbox.py:49` (`schema` properties equal `ask.FIELDS` in order), `tests/core/test_board.py:59`
(page writes no record). The 13-record fixture `tests/fixtures/board-records.json` and its three checks
(`tests/board_rules_check.js`, `tests/board_render_check.js`, `tests/core/test_board_rules.py`) are not edited.
New cases go in the new fixture `tests/fixtures/board-links.json`.

## Manual steps

### Before implementation

#### mb0-second-user: Second GitHub user ready (about 2 minutes: it already exists)

The agent opens pull requests as `andras-tkcs-agent` and your review is the gate.

1. Open `https://github.com/tkcs-lab/tkcs-lab-devflow/settings/rules` and check that `main` still requires a pull
   request and a Code Owners review.
2. Open a new Claude session on this repository and ask it for its GitHub identity; it must print
   `andras-tkcs-agent`.
3. Done when `identity()` in a new session returns `andras-tkcs-agent` and the main branch requires a Code Owner
   review. The full checklist is
   `https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/stale-needs-you-cards/docs/reference/profile-reference.md#second-github-user`.

### After implementation

#### ma1-deploy-board: Back up and redeploy the board (about 15 minutes)

The new board uses database schema 4; an older image refuses it, so a backup is the way back.

1. On the board host, make the backup:
   `docker exec tld-board python -c "import sqlite3; sqlite3.connect('/data/board.sqlite3').backup(sqlite3.connect('/data/copy.sqlite3'))"`
   then `docker cp tld-board:/data/copy.sqlite3 ./board-backup.sqlite3`. You see `board-backup.sqlite3` in the current
   directory.
2. In a clone of this repository on the feature branch `feature/stale-needs-you-cards`, build the image:
   `docker build -f deploy/board/Dockerfile -t tld-board .`
3. Restart the container with the `docker rm -f tld-board` and `docker run ...` of the guide
   (`https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/stale-needs-you-cards/docs/guides/board-server.md#docker`),
   with the same secrets and volume.
4. `curl -sS https://board.tkcs.name/healthz` answers `{"ok": true}`; log in on the page.
5. Report back: pass or fail of step 4.

#### ma2-owner-flow: Try the cards in the real board (about 10 minutes)

1. Start `/tld:make-plan` in a session on any small ask that needs a decision. On the board you see one "asks you"
   card for it and no second card for the run.
2. Answer the ask on the board. Within a minute the run moves to "Running" with "answer received"; it never shows
   "needs you".
3. In a session, ask it to `board_set` a test record with `needs_you` true. On its card tap "Dismiss": it moves to "Hidden" with
   "dismissed". Tap "Restore": it returns to "Needs you".
4. Run `/tld:board prune` in a session. It lists dismissed records and `needs_you` records whose pull requests are
   all merged or closed; say no, nothing is changed.
5. Report back: one pass or fail line per step (1 to 4) in the pull request.

## Risks and open questions

- **A phase's tests pin an old shape** (section 3.8). A worker that sees a failing test outside its `touches` stops
  with `status=blocked` and names the test; it never edits a test file the phase does not list.
- **`dismissed_at` in every entry** reaches sessions through `board_list`. A session that copies a whole entry into
  `board_set` would send an unknown key: the record validator rejects unknown top-level keys of `data` only, and
  `dismissed_at` is outside `data`, so a correct session is unaffected. A worker that finds `dismissed_at` inside
  `data` stops with `status=blocked`.
- **A cancelled linked ask** brings the "needs you" card back until the session wakes. Accepted; the owner can
  dismiss it.
- **A dismissed record can be pruned** while its attended session is alive. The session's next write gets
  `version_conflict` with `current: null` and writes the record again without `if_version` (documented in
  `status-board.md` by phase p5).
- **A `pr_open` land record stays in "PR open"** after its pull requests merge, for up to 7 days, until the board
  hides it. Prune clears `needs_you` records only. Accepted; a later change can list `pr_open` records too.
- **Rolling the board back** needs the backup of ma1 (schema 4 is refused by an older image). The guide says so
  (phase p1).
- **Mixed deploys**: a session on the new playbooks posts asks with `record` to an old board; the old board's ask
  validation rejects the unknown field with 422. Deploy the board first (ma1), then update the plugin.
- **Eval baselines**: the playbook edits change command hashes. Phase p5 refreshes the hashes in their own commit;
  a real re-run of the attended tasks costs money and is left to the owner.

## Implementation manifest

```yaml
plan_slug: stale-needs-you-cards
feature_branch: feature/stale-needs-you-cards
tracking_issue: 18
max_parallel: 2
manual_before:
  - id: mb0-second-user
    title: Second GitHub user ready
    why: The agent opens PRs as git.bot_login and the code owner's review is the gate
    done_when: identity() in a new session returns andras-tkcs-agent and the main branch requires a Code Owner review
manual_after:
  - id: ma1-deploy-board
    title: Back up and redeploy the board with schema 4
    why: The server, the page and the schema change only on a real board; CI runs them against a local server
  - id: ma2-owner-flow
    title: Try one card per wait, Dismiss, Restore and prune in the real board
    why: Only the real board with real sessions shows the wake timing and the owner's phone view
verify_after_merge:
  - .venv/bin/python -m pytest tests/core/test_board_*.py -q
  - .venv/bin/python launcher/tld ops docs-index check --index docs/README.md
final_checks:
  - docs/plans/stale-needs-you-cards-plan.md is deleted and nothing links to it
  - CHANGELOG.md has entries under Unreleased and no version heading (the AGENTS.md rule)
  - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
phases:
  - id: p1-store-dismissals
    title: Dismissals in the store, the two owner routes and the guide rows
    depends_on: []
    complexity: M
    touches:
      - src/tld/board/store.py
      - src/tld/board/server.py
      - src/tld/board/mcp.py
      - tests/core/test_board_store.py
      - tests/core/test_board_server.py
      - tests/core/test_board_mcp.py
      - docs/guides/board-server.md
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md (sections 3.1 and 3.8), docs/guides/board-server.md,
      src/tld/board/store.py, src/tld/board/server.py, tests/core/test_board_server.py (the MATRIX).
      1. store.py: set `SCHEMA_VERSION = 4`; add migration step 4 (the `dismissals` table of Design 3.1) after the
         step 3 block, before the `user_version` pragma. Add `Store.dismiss`, `Store.restore` and the dismissal
         delete inside `Store.delete`, as Design 3.1 says. Change `_row`, `_get` and `list` to the LEFT JOIN so every
         entry is `{"id", "version", "dismissed_at", "data"}`; `Store.set` keeps returning `{"id", "version"}` and a
         `Conflict.current` is the same entry shape. Update the module docstring ("Three tables") to four tables and name
         `dismissals`.
      2. server.py: add the two routes to `ROUTES` (after the `record` row) and the two `POLICY` rows
         (`frozenset({OWNER})`). Add `_do_dismiss` (read the body with `_read_json`; it must be a dict with exactly
         the key `version`, an int >= 1 and not a bool, else 400 `bad_request`; map `NotFound` to 404, `Conflict` to
         409 `version_conflict` with `current=exc.current`, `Invalid` to 409 `not_needs_you`) and `_do_restore`
         (read a non-empty body with `_read_body` the way `_do_cancel` does; `NotFound` is 404).
      3. mcp.py: add to the descriptions of `board_list` and `board_get` the words `each entry has id, version,
         dismissed_at and data`. Add no tool.
      4. tests/core/test_board_store.py: change `schema_version() == 3` to 4 at both places and the whole-entry
         equality at the old-database test to include `"dismissed_at": None`. Add: a v3 database (user_version 3,
         the three old tables) opens at schema 4 and keeps its records and asks; dismiss then get shows
         `dismissed_at`; a `set` with `if_version` afterwards shows `dismissed_at` null again; `dismiss` with a wrong
         version raises `Conflict`; `dismiss` of a record with `needs_you` false raises `Invalid`; `restore` clears
         it; `restore` of a missing record raises `NotFound`; `delete` then re-creating the id at version 1 shows
         `dismissed_at` null; after `dismiss` and `restore` the stored `data` and `version` equal what they were.
      5. tests/core/test_board_server.py: make `_matrix_record` return a record with `needs_you` true,
         `needs_you_reason` `Answer the ask`, `needs_you_since` `2026-11-09T11:00:00Z`, `status` `waiting_user`
         and `next_check_at` null. Add the matrix rows
         `("POST", "/api/records/{rec}/dismiss", "dismiss", (401, 403, 200))` and
         `("POST", "/api/records/{rec}/restore", None, (401, 403, 200))`, and the body `"dismiss": {"version": 1}`
         in `_body`. Add tests through the owner login: dismiss then `GET /api/records` shows `dismissed_at`; wrong
         `version` is 409 `version_conflict`; a record with `needs_you` false is 409 `not_needs_you`; a body with an
         extra key is 400; a session write after the dismissal makes `dismissed_at` null; the owner cannot `PUT`
         (403, unchanged); without Origin or CSRF the dismiss is 403.
         Also add: `test_dismiss_of_a_missing_record_raises_not_found` in the store tests; with
         `Store(path, clock=lambda: "2026-11-09T12:00:00Z")` assert `dismiss(...)["dismissed_at"]` and
         `store.list()[0]["dismissed_at"]` equal that time, and that after `dismiss` a `set(id, data, 7)` with a
         stale version raises `Conflict` whose `.current["dismissed_at"]` equals it;
         `test_dismiss_body_must_be_exactly_a_positive_int_version` (bodies `{"version": true}`, `{"version": 0}`,
         `{"version": "1"}`, `{"version": 1.0}`, `[]`, `{}` and raw `{` are 400 `bad_request`; dismiss and restore of
         `/api/records/no-such/...` are 404 `not_found`); parametrise the existing
         `test_owner_post_needs_the_csrf_token_and_the_origin` over every owner POST route (`answer`, `cancel`,
         `dismiss`, `restore`, `logout`), each with a valid body, with the same six outcomes it asserts today;
         `test_a_session_cannot_dismiss_through_put` (session `PUT` of a valid needs_you record with an extra
         top-level `dismissed_at` answers 200 or 400 and a following `GET` shows `dismissed_at` null);
         `test_the_matrix_covers_every_policy_entry` (map each `MATRIX` method and path to its route name through
         `ROUTES`; the set of `(name, method)` equals `set(POLICY)`).
      6. tests/core/test_board_mcp.py: assert the tool names are unchanged and `board_list` entries carry
         `dismissed_at`.
      7. docs/guides/board-server.md: add the two rows to the HTTP API table (`POST /api/records/<id>/dismiss`,
         owner only, body `{"version": n}`, errors 400, 404, 409 `version_conflict`, 409 `not_needs_you`, 403
         `csrf`; `POST /api/records/<id>/restore`, owner only, 404); add `dismissed_at` to the entry shape of the
         `GET /api/records` rows and to the `board_list` and `board_get` rows of the MCP table; change `schema version 3` to `schema version 4` in the bullet about `revoked_sessions`, and in the Security
         notes next to it add one bullet: dismissals are kept in the database (`dismissals`, schema
         version 4); the owner still writes no record; and in Backup and restore add: a database at schema 4 is
         refused by an older image, so keep the backup from before the upgrade to roll back. The line "can never
         write a record" stays true.
      Stop condition: if `tests/core/test_board_deploy.py` fails for a reason other than a missing route or flag
      row, or any test outside the files above fails, stop with `status=blocked` and name the test.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_store.py tests/core/test_board_server.py tests/core/test_board_mcp.py tests/core/test_board_deploy.py -q exits 0
      - grep -n "SCHEMA_VERSION = 4" src/tld/board/store.py prints one line
      - grep -c "dismiss" docs/guides/board-server.md prints at least 4
  - id: p2-ask-record
    title: The optional record field of an ask
    depends_on: []
    complexity: S
    touches:
      - src/tld/board/record.py
      - src/tld/board/ask.py
      - src/tld/schema/ask.schema.json
      - tests/core/test_board_inbox.py
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md (section 3.2), src/tld/board/ask.py,
      src/tld/schema/ask.schema.json, tests/core/test_board_inbox.py.
      1. record.py: add `DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")` next to `SLUG`.
      2. ask.py: add `"record"` as the last entry of `FIELDS`. In `_check`, after the `fallback_issue` check, add:
         when `"record" in ask` and the value is not None, it must be a string that matches `DOC_ID_RE` and equals
         `project` or `f"{project}--{command}"` for a `command` in `record.COMMANDS` (when `project` is not a valid
         string, only the pattern is checked); else append
         `'record' must be null, the project slug, or '<project>--<command>'`. Import `DOC_ID_RE` and `COMMANDS`
         from `tld.board.record`.
      3. ask.schema.json: add `record` as the last entry of `properties`: type `["string", "null"]`, pattern
         `^[a-z0-9][a-z0-9-]{0,99}$`, description: the status record that posted the ask (the project slug for a
         run, `<project>--<command>` for a command); the board page shows one card per wait.
      4. tests/core/test_board_inbox.py: add cases to the existing bad-asks parametrisation (a record of another
         project, a record with a capital letter, a record of 101 characters, a number, `<project>--bogus`; use the
         needle `must be null, the project slug, or`, not `record`, so the generic unknown-field text cannot match) and good cases (`None`, the
         project slug, `<project>--make-plan`); add `test_an_ask_keeps_its_record_field` (post an ask with `record` the project slug through the `server`
         fixture; `GET /api/asks/<id>` returns it; an ask posted without `record` has no `record` key or `null`) and a
         test that `store.ID_RE.pattern == record.DOC_ID_RE.pattern`
         (import `tld.board.store`).
      Stop condition: if any test outside tests/core/test_board_inbox.py fails, stop with `status=blocked` and
      name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_inbox.py tests/core/test_status_record.py -q exits 0
      - grep -n "DOC_ID_RE" src/tld/board/record.py src/tld/board/ask.py prints at least 3 lines
  - id: p3a-placement-rules
    title: The placement rules in rules.js and their fixture
    depends_on: [p2-ask-record]
    complexity: S
    touches:
      - src/tld/board/web/rules.js
      - tests/fixtures/board-links.json
      - tests/board_links_check.js
      - tests/core/test_board_links.py
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md (section 3.3), src/tld/board/web/rules.js,
      tests/board_rules_check.js, tests/core/test_board_rules.py.
      1. rules.js: add `isDismissed`, `linksTo`, `linkedAsks`, `answerReceived` and `place` exactly as Design 3.3
         specifies (names, arguments, return shapes) and export them in `module.exports`. Do not change `section`,
         `isHidden`, `isSilent`, `drift` or `elapsed`. Treat a missing `dismissed_at` and a missing `ask.record` as
         null.
      2. tests/fixtures/board-links.json: one JSON object `{"now", "entries", "asks", "expected",
         "expected_stale"}`. `now` is `2026-11-09T12:00:00Z`. Build the entries from records of
         tests/fixtures/board-records.json (copy the `f-waiting` data for needs_you cases, `f-running-ok` for a plain
         running case) with these ids and expectations (`expected` maps id to `{section, badge}`). Every entry has `data.project` equal to its id, `data.repo` `example-org/<id>` and `data.orchestrator_session` `session_<id>`, so no two entries share a session; an ask's `project` and `created_by` are `<id>` and `session_<id>` of the entry it is meant to link to, except `linked-open-other-project`, whose ask has `created_by` `session_linked-open-other-project` and `project` `other-project`; `dismissed-and-linked` (dismissed, with an open linked ask): `hidden`/`dismissed`; `null-session` (data copied from `f-maint-deps--deps` with `orchestrator_session` null, and an open ask with `created_by` `deps` and no `record`): `needs_you`/null; `dismissed-but-clear` and `stale-quiet` have `needs_you_reason` `""` and `needs_you_since` null:
         `plain-needs` needs_you, no ask: `needs_you`/null; `linked-open-record` (open ask with `record` equal to
         its id): `linked`/null; `linked-open-session` (open ask without `record`, `created_by` equal to the
         record's `orchestrator_session`, same project): `linked`/null; `linked-open-other-project` (same session
         id, ask project differs): `needs_you`/null; `record-field-wins` (open ask whose `record` names another
         id, `created_by` equal to this record's session): `needs_you`/null; `answered-after` (answered ask with
         `answered_at` equal to `needs_you_since`): `running`/`answer_received`; `answered-before` (answered one
         minute before `needs_you_since`): `needs_you`/null; `cancelled-ask`: `needs_you`/null;
         `open-and-answered` (one open and one answered linked ask): `linked`/null; `dismissed-needs`
         (`dismissed_at` set, needs_you true): `hidden`/`dismissed`; `dismissed-but-clear` (`dismissed_at` set,
         needs_you false, status running): `running`/null; `stale-quiet` (needs_you false, `updated_at` ten days
         old): `hidden`/null. `expected_stale` lists the ids `stale.py` must print at `now`: `dismissed-needs` and
         `stale-quiet`. Entries carry `id`, `version` 1, `dismissed_at` and `data`.
      3. tests/board_links_check.js: loads the fixture, asserts `place(entry, asks, Date.parse(now))` equals each
         `expected` (section, badge) and, for `answer_received`, that `.ask` is the answered ask; asserts the ids
         whose section is `hidden` equal `expected_stale`, and that the sorted keys of `expected` equal the sorted entry ids; prints `OK`.
      4. tests/core/test_board_links.py: runs the node check the way `test_rules_in_node` does (skip without node)
         and asserts stdout `OK`; add `test_links_fixture_is_valid`: every `entries[].data` passes
         `record.validate(data, id)` and every ask passes `ask.validate_stored`.
      Stop condition: if `tests/board_rules_check.js` fails, stop with `status=blocked`; `section` must not change.
    acceptance:
      - node tests/board_links_check.js prints OK
      - node tests/board_rules_check.js prints OK
      - .venv/bin/python -m pytest tests/core/test_board_links.py tests/core/test_board_rules.py -q exits 0
  - id: p3b-page
    title: One card per wait, answer received, Dismiss and Restore on the page
    depends_on: [p1-store-dismissals, p2-ask-record, p3a-placement-rules]
    complexity: M
    touches:
      - src/tld/board/web/board.html
      - tests/board_links_page_check.js
      - tests/core/test_board_page.py
      - tests/core/test_board.py
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md (section 3.4), src/tld/board/web/board.html,
      tests/board_poll_check.js, tests/core/test_board_page.py, tests/core/test_board.py.
      1. board.html `render`: replace `groups[section(e.data, now)]` by `place(e, asks, now).section` (`asks` is the
         argument of `render`); skip entries placed `linked`; keep the count labels. Keep the fixture mode working
         (`render(validEntries(FIXTURE), [])`, no csrf, no buttons).
      2. Add `answeredRow(entry, placed, now)` as Design 3.4 says and draw it in the Running section before the
         other running rows.
      3. Add the Dismiss button to `needsRow`'s card and the Restore button to the hidden row's card, in the detail
         block, drawn only when the `csrf` variable is set. `row(...)` gains an optional fifth argument, a builder
         that appends to the box after `detail`. The click handlers call `api("POST", ...)` with the paths and the
         body of Design 3.4 and then `load()`; on status 409 show the notice of Design 3.4 through `fail`'s notice
         element and call `load()`.
      4. Hidden row badge and the Hidden note as Design 3.4 says.
      5. tests/board_links_page_check.js (usage: `node tests/board_links_page_check.js BASE TOKEN PASSPHRASE`, copy
         the login and `api` helpers of tests/board_poll_check.js): with the session token write a record R1 (document id `links-one`, repo `example-org/links-one`) with
         `needs_you` true and post an ask whose `project` is `links-one`, `repo` `example-org/links-one` and
         `record` `links-one`; after login assert R1 has no card in Needs you and the
         ask card is there; answer the ask through the page form and assert R1 appears in Running with the text
         `answer received`; write record R2 (document id `links-two`, repo `example-org/links-two`) with `needs_you` true, assert its card has a `[data-action="dismiss"]`
         button inside the details, tap Dismiss, assert R2 is in Hidden with `dismissed`; tap Restore and assert R2
         is in Needs you again; dismiss R2 again, rewrite R2 through the API with `if_version`, assert R2 is back
         in Needs you; assert no console errors and no dialogs. Load the page with `?poll=500`; wait for the ask card first, then assert the page has no element `[data-doc="links-one"]` and the count reads `needs you 0`; assert `[data-doc="links-two"] > summary [data-action="dismiss"]` has count 0; with `page.route` on `**/api/records/links-two/dismiss` answering 409 `{"error":"version_conflict"}`, tap Dismiss and assert the notice text is visible and R2 is still in Needs you. Print `OK`.
      6. tests/core/test_board_page.py: add `test_links_dismiss_and_restore_in_a_browser`, built like
         `test_login_poll_and_answer_an_ask_in_a_browser`, running the new script. tests/core/test_board.py: change
         the comment at line 58 to say the page writes nothing but answers, cancels, dismissals and the login;
         keep both assertions. Add `test_fixture_page_has_no_dismiss_or_restore_buttons`: build with `--fixture tests/fixtures/board-records.json`, open it in Chromium, assert `[data-action]` count 0 and `[data-section="needs_you"] .row` count above 0.
      Stop condition: if `tests/board_render_check.js` or `tests/board_poll_check.js` fails after the change, stop
      with `status=blocked`; they pin the unchanged parts of the page.
    acceptance:
      - TLD_REQUIRE_BROWSER=1 .venv/bin/python -m pytest tests/core/test_board_page.py tests/core/test_board.py -q exits 0
      - node tests/board_render_check.js prints OK
      - grep -c 'api("PUT"' src/tld/board/web/board.html prints 0
      - grep -c 'data-action="dismiss"' src/tld/board/web/board.html and grep -c 'data-action="restore"' src/tld/board/web/board.html each print at least 1
  - id: p4-resolve-stale
    title: The resolve command and stale printing dismissed records
    depends_on: [p1-store-dismissals, p3a-placement-rules]
    complexity: M
    touches:
      - src/tld/board/stale.py
      - src/tld/board/resolve.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_board_resolve.py
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md (section 3.5), src/tld/board/stale.py,
      src/tld/board/record.py, src/tld/cli.py, docs/reference/cli.md, tests/fixtures/board-links.json.
      1. stale.py: `section(rec, now)` gains a third parameter `dismissed=False`; when `rec.get("needs_you") is
         True` it returns `hidden` if `dismissed` else `needs_you`. `main` passes
         `isinstance(doc.get("dismissed_at"), str)`. Update the module docstring: a record with needs_you true is
         printed only when the owner dismissed it.
      2. resolve.py: write the module as Design 3.5 describes (`resolve(rec, now, reason)` returning the cleared
         record or raising `ValueError` with the message; `main(argv)` with `FILE|-`, `--now`, `--reason`; the
         error lines start with `board_resolve: `; accept a bare record or an entry with `data`). Validate the
         output with `record.validate(out)` (no doc id) and fail with exit 1 on errors. Stdlib only.
      3. cli.py: add `("board", "resolve"): ("tld.board.resolve", (), "clear needs_you of a record whose pull
         requests are all merged or closed")` after the `stale` row. docs/reference/cli.md: add the row for
         `tld board resolve FILE|- --now T --reason TEXT` after the `stale` row and change the `stale` row to say
         it also prints dismissed records.
      4. tests/core/test_board_resolve.py: cases: a needs_you record (copy `f-waiting` from the 13-record fixture,
         then set `status` `running` and `next_check_at` to a time, so the input is valid) is cleared and passes `record.validate`; the output has `status` done,
         `finished_at` and `updated_at` equal `--now`, `next_check_at` null, `needs_you_reason` `""`; an entry
         `{id, version, data}` is accepted, also with `dismissed_at` null and with `dismissed_at`
         `2026-11-09T11:00:00Z` (an entry is recognised by its `data` key, never by its exact key set); a record with needs_you false exits 1 with `board_resolve: `; an empty
         and a 201-character reason exit 1; stdin `-` works; the input is not changed;
         `test_resolve_clears_a_command_record` (copy `f-maint-deps--deps`, `pr_open` with `needs_you`: exit 0,
         `status` `done`, `finished_at` equal `--now`, `record.validate(out, "f-maint-deps--deps") == []`);
         `test_resolve_refuses_an_output_that_does_not_validate` (an input with an unknown top-level key: exit 1, stderr
         starts `board_resolve: `);
         `test_prune_clears_a_record_through_client_get_resolve_and_set` (integration: `board_helpers.running(tmp_path)`,
         store `f-waiting` data with fresh timestamps under its id, `srv.store.dismiss(id, 1)`, then run the real
         `tld board client get <id>` with `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` set to the test server, pipe it to
         `tld board resolve - --now <T> --reason "PRs merged"`, pipe that to
         `tld board client set <id> - --if-version 1`: all three exit 0, and `GET /api/records/<id>` shows `version`
         2, `data.needs_you` false, `data.status` `done`, `dismissed_at` null). Parity: load
         tests/fixtures/board-links.json, run `tld board stale - --now <now>` on its `entries` and assert the printed
         ids equal `expected_stale`.
      5. tests/core/test_board_resolve.py: add a test that a dismissed needs_you entry is printed by `tld board stale`
         while the same entry without `dismissed_at` is not.
      Stop condition: if the parity test disagrees with the fixture, fix stale.py, never the fixture.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_resolve.py tests/core/test_board_rules.py tests/core/test_contracts.py -q exits 0
      - .venv/bin/python launcher/tld board resolve --help exits 0
  - id: p5-playbooks
    title: The playbooks set the link, quiet land and prune clears
    depends_on: [p2-ask-record, p4-resolve-stale]
    complexity: M
    touches:
      - playbooks/land.md
      - playbooks/board.md
      - playbooks/runtime.md
      - playbooks/policies/status-board.md
      - adapters/claude/skills/runtime/SKILL.md
      - tests/core/test_stale_cards_playbooks.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md (section 3.6 and 3.5), playbooks/land.md,
      playbooks/board.md, playbooks/runtime.md (the ask_human part), playbooks/policies/status-board.md,
      adapters/claude/skills/runtime/SKILL.md, AGENTS.md (the rules about playbook wording).
      1. playbooks/land.md: add the section `## 0. Reconcile` before section 1 and edit sections 3, 4 and 5 and
         the Rules, all as Design 3.6 says: the integration draft is an item `integration` and the workflow pull
         request an item `workflow`, each with its `pr` number and `state` `done` once it exists; `needs_you` is
         set only for the four cases listed; section 4.2 no longer sets `needs_you` for `Review PR #<n>`; the final
         record is `pr_open` with `needs_you` false unless a blocking case happened.
      2. playbooks/board.md: add the dismissed records to the prune list and the second list with its one
         `ask_human` of one `confirm` question per non-empty list (both lists empty: say `Nothing to prune` and stop)
         and the per-record commands of Design 3.5; change the two sentences
         that say a `needs_you` record is never printed; add the line that nothing is cleared that is not on the
         confirmed list. Every `tld` call you write must parse with the real CLI (tests/core/test_contracts.py).
      3. playbooks/runtime.md: the ask example gains the `record` line and its sentence as Design 3.6 says, and
         step 2 says the page hides the record's card while the ask is open and shows `answer received` after the
         answer; the session still reads the answer on its wake.
      4. playbooks/policies/status-board.md: the four additions of Design 3.6.
      5. adapters/claude/skills/runtime/SKILL.md: name `tld board resolve` in the prune sentence.
      6. tests/core/test_stale_cards_playbooks.py (behaviour only; CONTRIBUTING.md allows no sentence greps): the ask
         example JSON of runtime.md, with `record` set and its placeholders replaced by these values: project
         `example-project`, repo `example-org/example-project`, record `example-project`, created_by `session_x`,
         context_url `https://example.com/x`, question ids `q1`, `q2`, `q3`, option values `a`, `b`, passes
         `tld.board.ask.validate_new`; every JSON status-record example in land.md, if any, passes
         `record.validate(rec, "example-project--land")` and none has `status` `pr_open` together with `needs_you`
         true. The wording is checked by the acceptance greps below, not by a test.
      7. Run `.venv/bin/python evals/run.py check-baseline`. When it exits 1, run
         `.venv/bin/python evals/run.py baseline --refresh-hashes` and commit evals/baselines/default.json alone in its own
         commit whose message says the playbook wording changed and a real re-run of the attended tasks is left to
         the owner.
      Stop condition: a test that pins the old land wording and is outside the touches: stop with
      `status=blocked` and name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_stale_cards_playbooks.py tests/core/test_contracts.py tests/core/test_no_project_words.py -q exits 0
      - .venv/bin/python evals/run.py check-baseline exits 0
      - grep -n "Review PR" playbooks/land.md prints nothing
      - grep -c "tld board resolve" playbooks/board.md and grep -c -e "--if-version" playbooks/board.md each print at least 1
      - grep -c "current: null" playbooks/policies/status-board.md prints at least 1
      - grep -c '"record"' playbooks/runtime.md prints at least 1
  - id: p6-retire
    title: Docs, changelog and retire the plan
    depends_on: [p3b-page, p5-playbooks]
    complexity: M
    touches:
      - docs/guides/board-server.md
      - docs/guides/maintenance.md
      - README.md
      - CHANGELOG.md
      - docs/plans/stale-needs-you-cards-plan.md
    brief: |
      Read first: docs/plans/stale-needs-you-cards-plan.md, docs/guides/board-server.md,
      docs/guides/maintenance.md (the board section), CHANGELOG.md (the Unreleased part), README.md (the
      `/tld:board` row), docs/README.md.
      1. docs/guides/maintenance.md (162 lines; board-server.md is already near the 400-line limit): add a section
         `## Cards that wait` after the board section, saying in plain words: one card per wait and when `answer
         received` shows; the Dismiss and Restore buttons and that a session's next write brings a still-needing
         record back; what prune lists and clears now; that the board still never writes a record on the owner's
         behalf; that a cancelled ask brings the record's card back until the session wakes. Also update the two
         paragraphs about `/board prune` (the lines that say never one that needs you) to describe the dismissed
         records and the clearing after the confirm.
      2. docs/guides/board-server.md: fix the `/tld:board` sentence about prune (MCP tools section, around line
         293) and add one link to `maintenance.md#cards-that-wait`. Add no section.
      3. README.md: the `/tld:board [prune]` row says it also clears cards whose pull requests are done.
      4. CHANGELOG.md under `## [Unreleased]`: `### Fixed`: one line that a "needs you" card no longer outlives
         its reason (one card per wait, `answer received`, Dismiss and Restore, `/tld:board prune` clearing
         finished pull requests); `### Added`: `tld board resolve` and the optional `record` field of an ask;
         `### Changed`: `/land` asks only for what only you can fix and lists its pull requests as items; the
         board database moves to schema version 4 (keep a backup to roll back). Add no version heading.
      5. Delete docs/plans/stale-needs-you-cards-plan.md and check nothing links to it
         (`grep -rn "stale-needs-you-cards-plan" . --include=*.md --include=*.py --include=*.json` prints nothing
         outside the deleted file).
      6. Run `.venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0;
         docs/README.md needs no new row because this phase adds no document.
      Stop condition: if the docs-index check reports a missing row, stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - test ! -e docs/plans/stale-needs-you-cards-plan.md
      - grep -n "^## \[" CHANGELOG.md | head -2 prints `## [Unreleased]` and then `## [1.0.0] - 2026-11-11`
```
