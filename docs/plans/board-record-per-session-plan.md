# Plan: a status record for every run and every session

## 1. Goal

Every tld session that should show on the status board shows there, and two sessions never replace each
other's card. Today an `/implement` run that started on 2026-11-12 never appeared on the board, and a second
run in the same repository would have taken over the first one's card anyway. After this change:

- every implement run and every attended command has its own record (its own document id), so the board shows
  every run at once;
- a session that a record-writing tld command started cannot end its turn before it has written its record
  once, when a board is configured (a new opt-in Stop hook, `board-gate`);
- the playbooks tell a session to write the record first, to build the id with `tld board record-id`, and to
  fall back to `tld board client set` when the board tools of its runtime are missing or drop, never to skip
  the record.

Tracking issue: [#21](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/21).

The owner decided both choices on the board (ask `a-a6400a395dd9c2ae`): per-run keys (`ids: per-run`) and
wording plus a Stop hook (`gate: hook`).

## 2. Current state

Why session `session_013HAf76JWUMQ4X45aUJBP3v` (an `/implement` run for `plans-on-feature-branch`) is not on
the board, from its transcript and the code:

1. **It never wrote a record.** It loaded the board tools at 07:26, used `board_ask` at 07:27 and read the
   answers with `tld board answers` at 07:35, then told the owner at 07:37: "The board tools disconnected during
   the run, so that step is skipped until they come back". The board was reachable the whole time; only the
   runtime's MCP tools were not used. `playbooks/policies/status-board.md:36-47` says "The first record, before
   any work starts" and "A board error never stops the run"; nothing says what to do when the MCP tools are
   missing, so the session skipped the record. The same session then waited on two chat questions with no
   `needs_you` and no timer, so nothing on the board would have shown it either.
2. **One key per project and command.** `playbooks/policies/status-board.md:25` and
   `src/tld/board/record.py:217-223` key an implement run by the project slug (`tkcs-lab-devflow`) and every
   command by `<project>--<command>`. The board right now holds one `run` record (the
   `stale-needs-you-cards` run, which started later) and one `make-plan` record. The `plans-on-feature-branch`
   run could not have a card next to it. A second `make-plan` session replaces the first one's record the same
   way (this planning session overwrote a finished one at 08:04).
3. **Nothing enforces the first write.** The `dod-gate` and `plan-gate` hooks exist
   (`src/tld/dod/gate.py`, `src/tld/guard/plan_gate.py`); no hook looks at the board.
4. **The page and the prune list assume one record per project.** `src/tld/board/web/board.html:420-440`
   remembers which cards are open by `data-project`, so two cards of one project open and close together; the
   card heading `tagOf` (`board.html:166`) shows the plan slug for a run and the command name for a command,
   so two `make-plan` cards look the same. `src/tld/board/stale.py:27-35` never lists a record with
   `needs_you: true`, so a record left behind under an old key with `needs_you` true stays forever.

What is not wrong: git. Plan, feature and worker branches are already named per plan slug, and two runs work in
parallel there. Nothing in `playbooks/implement.md` limits a repository to one run.

## 3. Design

All names, strings and shapes below are final. A brief that needs one points to its subsection.

### 3.1 Document ids (`src/tld/board/record.py`)

`ID_RE` in `src/tld/board/store.py:26` (`^[a-z0-9][a-z0-9-]{0,99}$`) stays as it is. The id of a record:

| Record | Document id | Example |
|---|---|---|
| `kind: run` | `<project>--run--<plan>` | `tkcs-lab-devflow--run--stale-needs-you-cards` |
| `kind: command`, `attended: true` | `<project>--<command>--<tail>` | `tkcs-lab-devflow--make-plan--efghijkl` |
| `kind: command`, `attended: false` | `<project>--<command>` (unchanged) | `tkcs-lab-devflow--deps` |

- `<plan>` is `plan_slug` made safe: lower-case, every run of characters outside `[a-z0-9]` becomes one `-`,
  leading and trailing `-` removed, `plan` when nothing is left. When `len(<project>--run--) + len(plan)` is
  over 100, `plan` is cut to `100 - len(prefix) - 9` characters, trailing `-` removed, then `-` and the first 8
  hex characters of `sha256(plan_slug)` are appended. `run` is not in `COMMANDS`, so `--run--` never collides
  with a command id.
- `<tail>` is the last 8 characters of `orchestrator_session` after it is lower-cased and everything outside
  `[a-z0-9]` is removed (`session_01ABcdEFghIJkl` gives `efghijkl`). Fewer than 6 characters left is an error.
- New functions in `record.py`:
  - `doc_id(rec: dict) -> str`: the table above. It raises `ValueError(<message>)` for a record it cannot key:
    message `'orchestrator_session' needs at least 6 letters or digits to key an attended command record` for a
    short tail, `'project' is too long for a document id` when the prefix leaves fewer than 1 character for
    `<plan>` (run) or the id is over 100 characters (command).
  - `LEGACY_UNTIL = "1.2.0"` and `legacy_ids(rec: dict) -> tuple[str, ...]`: for a run `(project,)`, for a
    command `(f"{project}--{command}",)`.
  - `validate(rec, doc_id=None)`: when `doc_id` is given it must equal `doc_id(rec)` or be in `legacy_ids(rec)`;
    otherwise the error is `'--doc-id' is '<given>' but the document id of this record is '<doc_id(rec)>'`; a
    `ValueError` from `doc_id(rec)` is reported as its message. A record whose fields are too broken to key
    (no `project`, `kind` or `command` of the right shape) gets no id error; the other rules report it.
- One release of grace: a run that started before this change keeps writing under its legacy id until it ends,
  because its session read the old playbook. Playbooks only ever write the new ids. A session that resumes a
  run and finds its record under the legacy id keeps writing that one. `tests/core/test_board.py` has a test
  that fails once `tld.__version__` reaches `LEGACY_UNTIL`, with the message `remove LEGACY_UNTIL and
  legacy_ids from tld.board.record`.
- CLI `tld board record-id`, in `record.main` next to `project-slug`:
  `tld board record-id --repo <owner>/<repo> (--run --plan-slug <slug> | --command <cmd> (--session <id> | --unattended))`.
  It builds a record-shaped dict (`project` from `project_slug(repo)`, `kind`, `command`, `plan_slug`,
  `attended`, `orchestrator_session`), prints `doc_id(...)` and exits 0; on a bad repo, a command not in
  `COMMANDS`, a missing flag or a `ValueError` it prints `status-record: <message>` on stderr and exits 1.
  Registered in `src/tld/cli.py` as `("board", "record-id"): ("tld.board.record", ("record-id",), "the document id of a status record")`.

### 3.2 Board page and prune (`board.html`, `stale.py`)

- Cards: the open-or-closed memory (`openKeys`, `restoreOpen`) is keyed by the card's `data-doc`, not
  `data-project`. The `data-project` attribute stays (page tests select on it).
- Card tag: `tagOf(rec)` for a command record with `attended === true` and an `orchestrator_session` shows
  `<command> · <tail>`, `<tail>` computed by a new `sessionTail(s)` (lower-case, remove `[^a-z0-9]`, last 8
  characters, empty when under 6). A run keeps showing `plan_slug`; an unattended command keeps showing the
  command name.
- Prune: `stale.py` also prints a record whose id is one of `legacy_ids(data)` and whose `updated_at` is more
  than 24 hours old, even with `needs_you` true. It uses `tld.board.record.legacy_ids`. Every other rule is
  unchanged.

### 3.3 The `board-gate` hook

Opt-in, off by default: `hooks.board_gate.enabled` (boolean). `board-gate` is added to `HOOK_NAMES`, so
`hooks.disable` can switch it off. It has three events; all state is per session in
`<git dir>/tld/board-gate/<sha256(session id)[:16]>.json` (`tld.dod.gate.state_dir(project)`), content
`{"command": <str>, "opened_at": <epoch seconds>, "written": <bool>, "blocked": <bool>}`.

| Event | Action kind | What happens |
|---|---|---|
| UserPromptSubmit | `prompt` | `a.invoked` is in `RECORD_COMMANDS` and `a.session_id` is set: write the state file (`written` false, `blocked` false) unless a state file of the same command younger than the TTL exists. |
| PostToolUse | `tool_result` (new) | State exists, younger than the TTL, `written` false, and the call was a record write that succeeded: set `written` true. Never denies. |
| Stop | `stop` | Block once (below). |

- `RECORD_COMMANDS = ("make-plan", "implement", "review", "setup", "migrate", "land", "deps", "upstream", "docs", "ci")`
  (every playbook that writes a status record). `SESSION_TTL_SECONDS = 24 * 3600`.
- A **record write** is: (a) the adapter's `op` is `board_set` and the output text is a JSON object with a string
  `id` and an integer `version`; or (b) the Bash `command` contains the words `board`, `client`, `set` in that
  order and the last line of the output that starts with `{` is such an object.
- **Stop**: block when the hook is enabled and not in `hooks.disable`, `tld.board.client.load_config(os.environ)`
  returns a config (not `None`, no `ConfigError`), the state file exists and is younger than the TTL, `written`
  and `blocked` are both false and `a.continuing` is false. It then sets `blocked` true and returns the message
  `tld board-gate: this session was started by /tld:<command> and has not written its status record to the
  board. Write it now: use the board_set tool, or when that tool is missing or fails run "tld board client set
  <id> - " with the record on stdin (the id comes from "tld board record-id"). If the board cannot be reached,
  say so in your final reply and stop. This check blocks only once.` (`<command>` from the state file; the
  message is one line.) Every other case allows. Any exception inside `evaluate` allows (fail open; a profile
  error sets `ctx.notice` as `plan_gate` does).
- No session id (`a.session_id` empty): nothing is written and nothing blocks.
- It is a nudge, not a control: a session that can write files can write the state file
  (`docs/architecture/hooks.md`, "What the hooks do not protect", gets one sentence).
- Why not the alternatives (kept for `docs/architecture/hooks.md`): the client and the MCP bridge writing the
  marker (the bridge may not inherit the session id, outlives `/clear` and has to pair replies to requests); the
  hook asking the board (network and a token inside a hook, and a record cannot be tied to a hook session id,
  because `orchestrator_session` is the cloud id and the hook sees a different one).
- Claude adapter (`adapters/claude/hooks/claude_adapter.py`): `HOOKS["board-gate"] = ("tld.guard.board_gate", False)`;
  a `PostToolUse` payload becomes `Action("tool_result", ...)` for `Bash` (field `command` = the tool input's
  `command`) and for a tool whose name matches `^mcp__.*tld-board.*__board_set$` (field `op` = `board_set`,
  `args` = the tool input); other tools give no action. The tool output text, `Action.output`, is: the payload's
  `tool_response` when it is a string; for a mapping its `stdout` when that is a string, else the `text` fields
  of its `content` list joined by newlines; for a list the `text` fields joined by newlines; else the empty
  string. `hooks.json` gets: a `UserPromptSubmit` entry, a `PostToolUse` entry with matcher
  `Bash|mcp__.*tld-board.*__board_set`, and a `Stop` entry, each running
  `python3 "${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/board_gate.py"` (timeout 10, 10 and 20 seconds).
- `action.py`: `KINDS` gains `"tool_result"`; `Action` gains `output: str | None = None` (docstring: "tool_result:
  the text the tool returned").

### 3.4 Playbook wording

`playbooks/policies/status-board.md` changes in these places; every other playbook follows it.

- The `document id` row of the record table becomes: `` from `tld board record-id` (3.1): `<project>--run--<plan>` for a run, `<project>--<command>--<tail>` for an attended command, `<project>--<command>` for a scheduled one ``.
- New section **Keys and a record that already exists** after "The record": the id is built once with
  `tld board record-id` and kept for the whole run; a session that resumes a run and finds its record under the
  old id (the project slug, or `<project>--<command>`) keeps writing that one; hand-building an id is never
  right.
- New section **The write path** replacing "Where the board is"'s last sentences: the session writes with the
  runtime's board tools when its tool list shows them, otherwise (or when one fails or says it is
  disconnected) with `tld board client set <id> - [--if-version <n>]`. Only exit 3 (no `TLD_BOARD_URL` or
  `TLD_BOARD_TOKEN`) means there is no board. A runtime tool that is missing or dropped is never a reason to
  skip the record.
- "When to write": the first record is written before the first ask, the first worker and any other work that can
  take more than a minute; before `ask_human` the record is written with `needs_you`.
- Each playbook that names a record id (`migrate.md:15`, `ci.md:24`, `deps.md:23`, `setup.md:30`,
  `upstream.md:24`, `land.md:24`, `implement.md` "Status record", `make-plan.md` Setup item 3, `review.md`,
  `docs.md`) says "document id from `tld board record-id`" with its own flags in place of a literal id.
  `playbooks/board.md` prune says legacy records are listed after 24 hours.
- `adapters/claude/skills/runtime/SKILL.md` "Status board" paragraph: add that a dropped tool falls back to
  `tld board client set`.

### 3.5 What is not changed

`store.py`, the server routes, the MCP tools and the ask `record` field keep their shapes. (The ask `record`
field from `stale-needs-you-cards` takes a document id; `ask.py` validates it by shape and by equality with the
project slug or `<project>--<command>`, which this plan keeps accepting; phase p2 widens it, 3.2.)

## 4. ADRs

None: this repository has no `docs.adr_dir`. The decisions (per-run keys with a one-release legacy window; the
hook tracks writes through PostToolUse) go into `docs/architecture/hooks.md` and `CHANGELOG.md` in the last
phase.

## 5. Manual steps

### mb0-second-user: Second GitHub user ready (about 2 minutes if it already is)

Before implementation:

1. Open a new session in this repository and ask it to run `identity()`: it must return `andras-tkcs-agent`.
2. Open https://github.com/tkcs-lab/tkcs-lab-devflow/settings/rules and check that the main branch rule requires a
   Code Owner review. The checklist is in
   [profile-reference.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/board-record-per-session/docs/reference/profile-reference.md#second-github-user).

Done when `identity()` in a new session returns `andras-tkcs-agent` and the main branch requires a Code Owner
review.

### mb1-prereq-merged: The two plans that touch the same files are merged (about 5 minutes)

This plan changes `record.py`, `ask.py`, `board.html`, `stale.py`, `hooks.json`, `claude_adapter.py` and the
playbooks, which two plans in flight also change (`stale-needs-you-cards`, `plans-on-feature-branch`). Its
briefs name symbols those plans add.

Before implementation:

1. Open https://github.com/tkcs-lab/tkcs-lab-devflow/pulls and find the pull requests of the features
   `feature/stale-needs-you-cards` and `feature/plans-on-feature-branch`.
2. Review and merge each (you are the code owner). If one is not finished, wait: do not start this plan.

Done when both feature branches are merged into `main` (`git log origin/main` shows both merge commits).

### ma1-live-board: The board shows every session (about 15 minutes)

After the last merge, before the pull request merges:

1. Start a cloud session in this repository on the feature branch's code and run `/tld:make-plan` with any
   small request. Open https://board.tkcs.name: the session has its own card, tagged `make-plan · <8 characters>`.
2. Start a second `/tld:make-plan` session. Both cards are on the board at once and neither disappears.
3. With two `/tld:implement` runs of any two small plans in progress, check that each has its own card, tagged
   with its plan slug.

Report back: pass or fail for each of the three, one line each, in the pull request.

### ma2-enable-gate: Switch `board-gate` on for this repository (about 3 minutes)

The `protect-paths` hook forbids a session to edit `.tld/toolkit.yaml`, so you do it.

1. On the feature branch, open `.tld/toolkit.yaml` and under `hooks:` add, next to `plan_gate`:
   ```yaml
     board_gate:
       enabled: true
   ```
2. Run `launcher/tld profile validate .tld/toolkit.yaml` (expect `OK`), commit and push to the feature branch.
3. Start a cloud session with `/tld:docs` and tell it not to write any record. It must be blocked once with the
   message `tld board-gate: ...` and then write the record.

Report back: pass or fail for the block and for the card, one line each, in the pull request.

## 6. Risks and open questions

- **The PostToolUse payload.** Phase p4 assumes the hook payload has `tool_name`, `tool_input` and
  `tool_response` (a string, or a mapping with `stdout` or `content`). If the documentation of Claude Code's
  hooks (`claude-code-guide` agent) shows other field names, the worker stops with `status=blocked` and names
  them; ma2 step 3 is the live proof.
- **A phase finds the prerequisite code missing.** p2 relies on `stale.py` and `board.html` as the
  `stale-needs-you-cards` plan leaves them; p5 on the playbooks `plans-on-feature-branch` leaves. A worker that
  does not find a symbol a brief names stops with `status=blocked`.
- **Any valid record must produce a storable id.** If a valid record gives an id `ID_RE` rejects, p1 stops.
- **Legacy window.** Only the two legacy forms of 3.1 are ever accepted; p1 stops if a test seems to need a
  third.
- **Hand-built ids.** After p5, `grep -rn -- '<project>--' playbooks adapters docs` has no hit outside this plan
  document and `CHANGELOG.md`.
- **Hook blocks twice or without a board.** It must not; `tests/core/test_hook_board_gate.py` pins both.
- **The gate is a nudge.** A session can write the state file itself; the pull request review stays the control.
- **The record this planning session wrote.** `tkcs-lab-devflow--make-plan` was overwritten by this session
  before the cause was known; the playbooks' next run puts it right.

## Implementation manifest

```yaml
plan_slug: board-record-per-session
feature_branch: fix/board-record-per-session
tracking_issue: 21
max_parallel: 2
manual_before:
  - id: mb0-second-user
    title: Second GitHub user ready
    why: The agent opens PRs as git.bot_login and the code owner's review is the gate
    done_when: identity() in a new session returns andras-tkcs-agent and the main branch requires a Code Owner review
  - id: mb1-prereq-merged
    title: stale-needs-you-cards and plans-on-feature-branch are merged
    why: p2, p4 and p5 change files and symbols those two features add or rewrite; started earlier they conflict or find nothing to change
    done_when: git log origin/main shows the merge commits of feature/stale-needs-you-cards and feature/plans-on-feature-branch
manual_after:
  - id: ma1-live-board
    title: Every session has its own card on the live board
    why: CI cannot reach the owner's board or start cloud sessions
  - id: ma2-enable-gate
    title: Switch board-gate on in .tld/toolkit.yaml and check it blocks once
    why: protect-paths forbids a session to edit the profile, and only a live session proves the hook payload
verify_after_merge:
  - .venv/bin/python -m pytest tests/core tests/adapters/claude -q
final_checks:
  - docs/plans/board-record-per-session-plan.md is deleted and nothing links to it
  - the changelog has entries under Unreleased and no version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
phases:
  - id: p1-record-ids
    title: Document ids per run and per session, and tld board record-id
    depends_on: []
    complexity: M
    touches:
      - src/tld/board/record.py
      - src/tld/cli.py
      - src/tld/schema/status-record.schema.json
      - tests/core/test_board.py
    brief: |
      Read first: docs/README.md rows for the board (guides/board-server.md), src/tld/board/record.py, playbooks/policies/status-board.md. Design: section 3.1 of docs/plans/board-record-per-session-plan.md; implement it exactly.
      1. In src/tld/board/record.py add `LEGACY_UNTIL = "1.2.0"`, `doc_id(rec)` and `legacy_ids(rec)` as section 3.1 says (helpers `_plan_part(plan_slug, prefix)` and `_session_tail(session)`), with the exact error messages of 3.1.
      2. In `validate`, replace the block at the `if doc_id is not None` check (the one that builds `expected`) with: compute `want = doc_id(rec)` in a try; when `doc_id` is given and it is neither `want` nor in `legacy_ids(rec)`, append `'--doc-id' is '<given>' but the document id of this record is '<want>'`; a ValueError is appended as its message; skip the whole check when `project` or `kind` is not valid or `kind == "command"` has no valid `command`.
      3. In `main`, add the `record-id` branch next to `project-slug`, with the flags of 3.1 (argparse prog `tld board record-id`; `--run` and `--command` are mutually exclusive and one is required; `--session` and `--unattended` are mutually exclusive and one is required with `--command`; `--plan-slug` is required with `--run`).
      4. In src/tld/cli.py add the `("board", "record-id")` row of 3.1 right after the `project-slug` row.
      5. In src/tld/schema/status-record.schema.json change the top `description` sentence about keys to: "A run (kind 'run') is an implement orchestration keyed '<project>--run--<plan>'; an attended command record (kind 'command') is keyed '<project>--<command>--<session tail>' and an unattended one '<project>--<command>'. tld board record-id builds the id; the old keys (the project slug, '<project>--<command>') are still accepted until tld 1.2.0." Do not change anything else in the schema.
      6. Tests in tests/core/test_board.py (copy the style of the existing `validate` tests in that file): `test_run_id_uses_the_plan_slug` (the example of 3.1), `test_attended_command_id_uses_the_session_tail` (`session_01ABcdEFghIJkl` gives `...--make-plan--efghijkl`), `test_unattended_command_id_is_unchanged`, `test_plan_slug_is_made_safe` (`Plan_X  y!` gives `plan-x-y`; empty gives `plan`), `test_long_plan_slug_is_cut_with_a_hash` (a 150-character slug gives an id of exactly 100 characters that matches store.ID_RE and ends in `-` plus 8 hex), `test_short_session_tail_is_an_error`, `test_two_runs_get_two_ids`, `test_legacy_ids_are_still_accepted` (a run under the bare project id and a command under `<project>--<command>` validate with `--doc-id`; a third form does not), `test_new_id_is_required_for_a_wrong_id` (the error text of 3.1), `test_record_id_cli` (run `record.main(["record-id", ...])` for the three kinds and for each error: bad repo, missing session, unknown command, too-short session), and `test_legacy_window_ends` (fails with the message of 3.1 once `tld.__version__` is at or past `LEGACY_UNTIL`). Existing tests that pin the old key of a run or an attended command: update their expected ids and their `doc_id` arguments (grep `--doc-id` and `set(` calls with a project-slug id in tests/core/test_board*.py ONLY to find them; edit only tests/core/test_board.py; a failing test in another file is a stop condition).
      7. Run `.venv/bin/python -m pytest tests/core/test_board.py tests/core/test_contracts.py -q` and the profile and policy lines of verify.dod.
      Stop condition: a valid record whose id `store.ID_RE` rejects, a test outside `touches` that fails because of the new key, or a need to accept a third legacy form: stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board.py -q passes
      - .venv/bin/python launcher/tld board record-id --repo tkcs-lab/tkcs-lab-devflow --run --plan-slug stale-needs-you-cards prints tkcs-lab-devflow--run--stale-needs-you-cards
      - .venv/bin/python launcher/tld board record-id --repo tkcs-lab/tkcs-lab-devflow --command make-plan --session session_01ABcdEFghIJkl prints tkcs-lab-devflow--make-plan--efghijkl
      - .venv/bin/python launcher/tld board record-id --repo tkcs-lab/tkcs-lab-devflow --command deps --unattended prints tkcs-lab-devflow--deps
      - grep -n "def doc_id\|def legacy_ids\|LEGACY_UNTIL" src/tld/board/record.py matches
  - id: p2-board-page-and-prune
    title: Cards keyed by document, session tail in the tag, legacy records prunable
    depends_on: [p1-record-ids]
    complexity: M
    touches:
      - src/tld/board/web/board.html
      - src/tld/board/stale.py
      - src/tld/board/ask.py
      - tests/core/test_board_page.py
      - tests/core/test_board_stale.py
      - tests/core/test_board_inbox.py
    brief: |
      Read first: src/tld/board/web/board.html (functions `tagOf`, `row`, `openKeys`, `restoreOpen`), src/tld/board/stale.py, src/tld/board/ask.py (the `record` check). Design: sections 3.2 and 3.5 of docs/plans/board-record-per-session-plan.md.
      1. board.html: add `function sessionTail(s)` next to `tagOf`: `typeof s === "string"`, lower-case it, remove `[^a-z0-9]`, take the last 8 characters, return "" when under 6. Change `tagOf(rec)`: a command record with `rec.attended === true` and a non-empty `sessionTail(rec.orchestrator_session)` returns `span(rec.command + " · " + tail, "tag")` (the middle dot U+00B7 with a space on each side); a run and an unattended command return what they return today.
      2. board.html: in `openKeys` and `restoreOpen` build the key `"p:" + d.getAttribute("data-doc")` (fall back to `data-project` only when `data-doc` is absent). Leave the `data-project` attribute in `row`.
      3. stale.py: import `legacy_ids` from `tld.board.record`; add `LEGACY_HIDE = timedelta(hours=24)` and `def legacy_stale(doc, now)`: true when `doc["id"] in legacy_ids(doc["data"])` (catch ValueError, KeyError and TypeError as false) and `now - parse(doc["data"]["updated_at"]) > LEGACY_HIDE`. In `main` a doc is printed when `section(...) == "hidden"` or `legacy_stale(doc, now)`. Update the module docstring with one sentence.
      4. ask.py: where the `record` field is checked (the check the stale-needs-you-cards plan added: it equals the ask's project or `<project>--<command>`), also accept an id of the shapes `<project>--run--<plan>` and `<project>--<command>--<tail>` for the ask's own project: the id starts with `<project>--` and matches `record.DOC_ID_RE`. Error text unchanged.
      5. Tests: tests/core/test_board_stale.py (new, `import tld.board.stale as stale`): `test_a_legacy_record_with_needs_you_is_listed_after_24_hours`, `test_a_legacy_record_updated_an_hour_ago_is_kept`, `test_a_new_key_record_with_needs_you_is_never_listed`; tests/core/test_board_page.py: `test_open_cards_are_keyed_by_document` (the page source has `getAttribute("data-doc")` inside `openKeys`) and `test_command_tag_shows_the_session_tail` (the page source contains `sessionTail`); tests/core/test_board_inbox.py: one test that an ask with `record` set to `<project>--run--<plan>` validates and one with a different project's id does not (copy an existing `record` test there).
      6. Run `.venv/bin/python -m pytest tests/core/test_board_page.py tests/core/test_board_stale.py tests/core/test_board_inbox.py tests/core/test_board_rules.py -q`.
      Stop condition: `tagOf`, `openKeys`, `restoreOpen`, `stale.main` or the ask `record` check is not where this brief says (the prerequisite plans changed it): stop with `status=blocked` and name what you see.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_page.py tests/core/test_board_stale.py tests/core/test_board_inbox.py -q passes
      - grep -n "sessionTail" src/tld/board/web/board.html matches
      - grep -n "legacy_stale" src/tld/board/stale.py matches
  - id: p3-board-gate-core
    title: The board-gate decision logic, the tool_result action and the profile key
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/board_gate.py
      - src/tld/guard/action.py
      - src/tld/guard/_common.py
      - src/tld/schema/profile.schema.json
      - tests/core/test_hook_board_gate.py
    brief: |
      Read first: src/tld/guard/plan_gate.py (the model for state, `enabled`, `evaluate`), src/tld/dod/gate.py (`state_dir`), src/tld/guard/action.py, src/tld/guard/_common.py (`HOOK_NAMES`), tests/core/test_hook_plan_gate.py (the pattern for tests). Design: section 3.3 of docs/plans/board-record-per-session-plan.md; implement it exactly.
      1. action.py: add `"tool_result"` to `KINDS`, the field `output: str | None = None` to `Action` (comment: tool_result: the text the tool returned) and the example line `Action(kind="tool_result", ...)` to the module docstring.
      2. _common.py: add `"board-gate"` to `HOOK_NAMES`. profile.schema.json: add `board_gate` under `hooks.properties` next to `plan_gate`, copying its shape (`enabled`, boolean, `x-hook-default` false, description `Opt in: a session that a record-writing tld command started cannot end its turn before it has written its status record to the board once.`) and `"board-gate"` to the enum or list of hook names that `hooks.disable` allows (grep `plan-gate` in the schema to find it). A test keeps the schema defaults and the code defaults equal: run it.
      3. New src/tld/guard/board_gate.py with `NAME`, `RECORD_COMMANDS`, `SESSION_TTL_SECONDS`, `MESSAGE`, `enabled(ctx)` (same errors as `plan_gate.enabled` with `board_gate`), `state_file`, `_load`, `_save`, `is_record_write(action)` and `evaluate(ctx)` as 3.3 says. `evaluate` is wrapped: `except ProfileError as exc: ctx.notice = str(exc); return None` and `except Exception: return None`. It returns the message only for the Stop case; it returns `None` for `prompt` and `tool_result`. Respect `ctx.disabled(NAME)`.
      4. tests/core/test_hook_board_gate.py, one test per line, building `Action`s and `Ctx` the way tests/core/test_hook_plan_gate.py does, with `TLD_BOARD_URL=https://board.example` and `TLD_BOARD_TOKEN=t` set through `monkeypatch`: a command prompt opens the state; a plain prompt does not; a stop without a write blocks with the message and the command name; a second stop does not block; `continuing=True` does not block; a `board_set` tool result with `{"id": "x", "version": 2}` sets `written` and the stop is then allowed; the same with output `{"error": "invalid"}` does not; a Bash `tld board client set x - --if-version 1` with last line `{"id":"x","version":3}` sets `written`; `tld board client get x` does not; no `TLD_BOARD_URL` never blocks; `TLD_BOARD_URL=ftp://x` never blocks; no session id never blocks; a state file older than the TTL never blocks; `hooks.board_gate.enabled` false never blocks; `hooks.disable: [board-gate]` never blocks; an unreadable state file allows.
      5. Run `.venv/bin/python -m pytest tests/core/test_hook_board_gate.py tests/core/test_hook_plan_gate.py tests/core/test_guard_plumbing.py tests/core/test_profile_schema.py -q` (use the names that exist; drop one that does not).
      Stop condition: a test elsewhere pins the exact list of `KINDS` or `HOOK_NAMES` or the schema in a way your change cannot satisfy: stop with `status=blocked` and name the test.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_hook_board_gate.py -q passes
      - grep -n "board-gate" src/tld/guard/_common.py matches
      - grep -n "board_gate" src/tld/schema/profile.schema.json matches
  - id: p4-board-gate-adapter
    title: Claude Code adapter and hooks.json for board-gate
    depends_on: [p3-board-gate-core]
    complexity: S
    touches:
      - adapters/claude/hooks/claude_adapter.py
      - adapters/claude/hooks/board_gate.py
      - adapters/claude/hooks/hooks.json
      - tests/adapters/claude/test_hooks_config.py
      - tests/adapters/claude/test_hook_board_gate_adapter.py
    brief: |
      Read first: adapters/claude/hooks/claude_adapter.py, adapters/claude/hooks/dod_gate.py, adapters/claude/hooks/hooks.json, tests/adapters/claude/test_hooks_config.py, tests/hooks_helpers.py. Design: the Claude adapter paragraph of section 3.3 of docs/plans/board-record-per-session-plan.md.
      1. Add adapters/claude/hooks/board_gate.py as a copy of dod_gate.py with the docstring `Claude Code hook entry for board-gate` and `main("board-gate")`.
      2. claude_adapter.py: add `"board-gate": ("tld.guard.board_gate", False)` to `HOOKS`; add `_result_text(response)` (the output rule of 3.3) and, in `to_action`, a PostToolUse branch before the tool branches: for `Bash` an `Action("tool_result", project, cwd, command=<tool_input command>, output=_result_text(payload.get("tool_response")), session_id=_sid(payload))`; for a tool name matching `^mcp__.*tld-board.*__board_set$` the same with `op="board_set"`, `args=dict(tool_input)` and no `command`; every other tool returns `None`. A payload without `tool_response` gives output "".
      3. hooks.json: add the three entries of 3.3 (UserPromptSubmit next to the plan-gate one, a PostToolUse block, a Stop entry after dod-gate's), command `python3 "${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/board_gate.py"`.
      4. Tests in tests/adapters/claude/test_hook_board_gate_adapter.py (copy the payload helpers of tests/hooks_helpers.py): a Bash PostToolUse payload with a string `tool_response` becomes a `tool_result` action; an MCP `mcp__plugin_tld_tld-board__board_set` payload with `tool_response` `{"content": [{"type": "text", "text": "{\"id\":\"x\",\"version\":2}"}]}` gives `op == "board_set"` and that output text; a `Read` PostToolUse gives no action; a Stop payload round trip blocks once and a UserPromptSubmit `/tld:make-plan x` opens the state (use a temp git dir); the hook script exits 0 with no output for a payload it does not know. Extend tests/adapters/claude/test_hooks_config.py so the new entries are covered the way the existing ones are.
      5. Run `.venv/bin/python -m pytest tests/adapters/claude -q`.
      Stop condition: Claude Code's documented PostToolUse payload (ask the claude-code-guide agent, or find it in tests/hooks_helpers.py) does not carry `tool_name`, `tool_input` and `tool_response` as this brief says: stop with `status=blocked` and write the field names you found.
    acceptance:
      - .venv/bin/python -m pytest tests/adapters/claude -q passes
      - grep -c "board_gate.py" adapters/claude/hooks/hooks.json prints 3
      - grep -n "board-gate" adapters/claude/hooks/claude_adapter.py matches
  - id: p5-playbooks
    title: Playbook wording, the record-id calls and the runtime fallback
    depends_on: [p1-record-ids]
    complexity: M
    touches:
      - playbooks/policies/status-board.md
      - playbooks/implement.md
      - playbooks/make-plan.md
      - playbooks/review.md
      - playbooks/migrate.md
      - playbooks/setup.md
      - playbooks/land.md
      - playbooks/deps.md
      - playbooks/upstream.md
      - playbooks/ci.md
      - playbooks/docs.md
      - playbooks/board.md
      - adapters/claude/skills/runtime/SKILL.md
      - tests/core/test_board_record_wording.py
      - evals/baselines/default.json
    brief: |
      Read first: playbooks/policies/status-board.md, adapters/claude/skills/runtime/SKILL.md (the "Status board" paragraph), docs/plans/board-record-per-session-plan.md section 3.4, CONTRIBUTING.md (evals and baseline refresh). Design: section 3.4; use its wording, adapt only for grammar.
      1. playbooks/policies/status-board.md: make the four changes of 3.4 (the `document id` row, the section "Keys and a record that already exists", the section "The write path", the "When to write" sentence). Keep the file's existing headings and its "No secrets" and "Alerts" sections.
      2. In each of migrate.md, setup.md, land.md, make-plan.md (Setup item 3), review.md, docs.md, ci.md, deps.md and upstream.md find the sentence that names the document id (`grep -n "document id\|<project>--" playbooks/*.md`) and replace the literal id with "document id from `tld board record-id --repo <owner>/<repo> --command <name> --session <this session's id>`" for an attended command, and with "... `--command <name> --unattended`" for ci, deps, upstream and docs when it is scheduled (it says `attended: false`). implement.md "Status record": add "document id from `tld board record-id --repo <owner>/<repo> --run --plan-slug <plan_slug>`, written before any worker starts".
      3. playbooks/board.md prune: add after step 2: "Records still under an old key (the project slug, or `<project>--<command>`) are listed once they were not updated for 24 hours, even when they need the owner."
      4. adapters/claude/skills/runtime/SKILL.md: at the end of the "Status board" paragraph add: "When a board tool is missing or fails (disconnected, error), write the record with `tld board client set <id> - [--if-version <n>]`; only exit 3 means there is no board. Never skip a record for a dropped tool."
      5. tests/core/test_board_record_wording.py: `test_no_playbook_hand_builds_a_document_id` (no file under playbooks/ contains `<project>--` or `--<command>`, except `playbooks/policies/status-board.md` lines inside the table row of the legacy sentence: allow a line that also contains "old key" or "legacy"), `test_every_record_writer_names_record_id` (each of the ten playbooks of step 2 contains `tld board record-id`), `test_status_board_policy_has_the_fallback` (contains `tld board client set` and `Only exit 3`), `test_runtime_map_has_the_fallback` (SKILL.md contains `tld board client set`).
      6. Run `.venv/bin/python -m pytest tests/core/test_board_record_wording.py tests/core/test_contracts.py tests/core/test_no_project_words.py -q` and `python3 evals/run.py check-baseline`. If check-baseline says the baseline is stale, refresh it as CONTRIBUTING.md says (stub mode) and include evals/baselines/default.json.
      Stop condition: a playbook this brief names has no sentence about its document id, or a contract test rejects a `tld` call you wrote: stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_record_wording.py tests/core/test_contracts.py -q passes
      - python3 evals/run.py check-baseline exits 0
      - grep -rn -- "<project>--" playbooks prints nothing except lines that also say old key or legacy
  - id: p6-retire
    title: Docs, changelog and retire the plan
    depends_on: [p2-board-page-and-prune, p4-board-gate-adapter, p5-playbooks]
    complexity: M
    touches:
      - docs/architecture/hooks.md
      - docs/reference/profile-reference.md
      - docs/reference/cli.md
      - docs/guides/maintenance.md
      - docs/guides/board-server.md
      - docs/README.md
      - CHANGELOG.md
      - docs/plans/board-record-per-session-plan.md
    brief: |
      Read first: docs/README.md, docs/architecture/hooks.md (sections `dod-gate`, `plan-gate`, "What the hooks do not protect"), docs/reference/cli.md, docs/reference/profile-reference.md, CHANGELOG.md. No other doc.
      1. docs/architecture/hooks.md: add a section `### board-gate` after `plan-gate`, from section 3.3 of the plan: what it is, opt-in `hooks.board_gate.enabled`, the three events and the state file, the exact block message, "blocks once", fail open, the two rejected alternatives, and add `board-gate` to the list of hook names wherever the others are listed (grep `plan-gate`). Add to "What the hooks do not protect": "`board-gate` is a nudge: a session that can write files can write its state file."
      2. docs/reference/profile-reference.md: add the row `hooks.board_gate.enabled` after the `hooks.plan_gate.enabled` row (no, default `false`; opt in to the `board-gate` Stop hook; link to hooks.md) and add `board-gate` to the `hooks.disable` list.
      3. docs/reference/cli.md: add the row for `tld board record-id` next to `project-slug`, with its flags from section 3.1.
      4. docs/guides/maintenance.md (lines naming `<project>--ci`, `<project>--docs` and `<project>--<command>`) and docs/guides/board-server.md (if it names a record key; grep `--` and `document id`): state the new keys of 3.1 and the one-release legacy window.
      5. CHANGELOG.md under `## [Unreleased]`: `### Added` a line for the opt-in `board-gate` hook and `tld board record-id`; `### Changed` a line: "Status board: every implement run and every attended command has its own record (`<project>--run--<plan>`, `<project>--<command>--<session tail>`), so two runs or two sessions no longer replace each other's card; the old keys are accepted until 1.2.0, and `/tld:board prune` lists old-key records after 24 hours"; `### Fixed` a line: "A session no longer skips its status record when its runtime's board tools drop: the playbooks fall back to `tld board client set`". Add no version heading.
      6. Delete docs/plans/board-record-per-session-plan.md (`git rm`) and remove any link to it. Run `.venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0 (no new doc is added, so no new row; fix any row the check reports).
      Stop condition: a doc this brief names does not have the section or list it says: stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - grep -n "board-gate" docs/architecture/hooks.md docs/reference/profile-reference.md matches
      - grep -n "record-id" docs/reference/cli.md CHANGELOG.md matches
      - test ! -e docs/plans/board-record-per-session-plan.md
```
