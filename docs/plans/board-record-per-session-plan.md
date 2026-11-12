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
  - `DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")` (the pattern of `store.ID_RE`; `store.py` imports
    `ask`, which imports `record`, so `record` cannot import it).
  - `LEGACY_UNTIL = "1.2.0"` and `legacy_ids(rec: dict) -> tuple[str, ...]`: for a run `(project,)`, for an
    attended command `(f"{project}--{command}",)`, for an unattended command `()` (its current id is that
    string already, so it is never legacy).
  - `owns_doc_id(project: str, doc_id: str) -> bool`: true when `DOC_ID_RE` matches `doc_id` and `doc_id` is
    `project`, or starts with `project + "--"` and the rest, split on `--`, is `run` followed by one non-empty
    part, or a name in `COMMANDS` alone, or a name in `COMMANDS` followed by one non-empty part. (`ask.py` uses it
    for an ask's `record` field.)
  - `validate(rec, doc_id=None)`: only when `doc_id` is given (never for a call without it) and it is not in
    `legacy_ids(rec)`: compute `doc_id(rec)`; a `ValueError` is reported as its message, otherwise a different id
    gives `'--doc-id' is '<given>' but the document id of this record is '<doc_id(rec)>'`. A non-string
    `plan_slug` counts as `""` and a non-string `orchestrator_session` as too short. A record whose fields are too
    broken to key (no valid `project`, `kind`, or `command` for a command) gets no id error; the other rules
    report it.
- A grace window until tld 1.2.0: a run that started before this change keeps writing under its legacy id until
  it ends, because its session read the old playbook. Playbooks only ever write the new ids. A session that
  resumes a run and finds its record under the legacy id keeps writing that one. A session that continues under
  a new cloud session id cannot rewrite an attended command record keyed with the old tail (`Store.set` rejects
  it with the message above); it writes a record of its own. `tests/core/test_status_record.py` has a test that
  fails once `tuple(int(x) for x in tld.__version__.split(".")[:3]) >= (1, 2, 0)`, with the message `remove
  LEGACY_UNTIL and legacy_ids from tld.board.record`.
- CLI `tld board record-id`, in `record.main` next to `project-slug`:
  `tld board record-id --repo <owner>/<repo> (--run --plan-slug <slug> | --command <cmd> (--session <id> | --unattended))`.
  It builds a record-shaped dict (`project` from `project_slug(repo)`, `kind`, `command`, `plan_slug`,
  `attended`, `orchestrator_session`), prints `doc_id(...)` and exits 0; on a bad repo, a command not in
  `COMMANDS`, a missing or conflicting flag or a `ValueError` it prints `status-record: <message>` on stderr and
  exits 1 (the parser's `error` method is overridden to do this, so argparse's exit 2 never shows).
  Registered in `src/tld/cli.py` as `("board", "record-id"): ("tld.board.record", ("record-id",), "the document id of a status record")`.

### 3.2 Board page and prune (`board.html`, `stale.py`)

- Cards: the open-or-closed memory (`openKeys`, `restoreOpen`) is keyed by the card's `data-doc`, not
  `data-project`. The `data-project` attribute stays (page tests select on it).
- Card tag: `tagOf(rec)` for a command record with `attended === true` and an `orchestrator_session` shows
  `<command> · <tail>`, `<tail>` computed by a new `sessionTail(s)` (lower-case, remove `[^a-z0-9]`, last 8
  characters, empty when under 6). A run keeps showing `plan_slug`; an unattended command keeps showing the
  command name.
- Prune: `stale.py` also prints a record whose id is one of `legacy_ids(data)` and whose `updated_at` is more
  than 24 hours old, even with `needs_you` true. It uses `tld.board.record.legacy_ids`, which is empty for an
  unattended command, so a scheduled record is never pruned by this rule. Every other rule is unchanged.
- Ask `record` field (`src/tld/board/ask.py`): the check the `stale-needs-you-cards` plan added (equal to the
  ask's project or `<project>--<command>`) becomes `record.owns_doc_id(<the ask's project>, <record>)`; the error
  text is unchanged.

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
  `id` and an integer `version`; or (b) the Bash `command` matches the regex `\bboard\s+client\s+set\b` and the
  last line of the output that starts with `{` is such an object.
- **Stop**: block when the hook is enabled and not in `hooks.disable`, `tld.board.client.load_config(os.environ)`
  returns a config (not `None`, no `ConfigError`), the state file exists and is younger than the TTL, `written`
  and `blocked` are both false and `a.continuing` is false. It then sets `blocked` true and returns `MESSAGE` (the guard
  runner puts the prefix `tld board-gate: ` in front, so `MESSAGE` itself starts at `this session`):
  `this session was started by /tld:<command> and has not written its status record to the
  board. Write it now: use the board_set tool, or when that tool is missing or fails run "tld board client set
  <id> - " with the record on stdin (the id comes from "tld board record-id"). If the board cannot be reached,
  say so in your final reply and stop. This check blocks only once.` (`<command>` from the state file; the
  message is one line.) Every other case allows. Any exception inside `evaluate` allows (fail open; a profile
  error sets `ctx.notice` as `plan_gate` does). `board_gate` checks `ctx.disabled(NAME)` itself, only on Stop and
  after `enabled`, and `run_guard` in `src/tld/guard/_common.py` skips its own `disabled` lookup for `board-gate`
  (as it does for `plan-gate`), so a malformed `hooks.disable` can never make the hook block.
- No session id (`a.session_id` empty): nothing is written and nothing blocks.
- It is a nudge, not a control: a session that can write files can write the state file
  (`docs/architecture/hooks.md`, "What the hooks do not protect", gets one sentence).
- Why not the alternatives (kept for `docs/architecture/hooks.md`): the client and the MCP bridge writing the
  marker (the bridge may not inherit the session id, outlives `/clear` and has to pair replies to requests); the
  hook asking the board (network and a token inside a hook, and a record cannot be tied to a hook session id,
  because `orchestrator_session` is the cloud id and the hook sees a different one).
- Claude adapter (`adapters/claude/hooks/claude_adapter.py`): `GUARDS["board-gate"] = ("tld.guard.board_gate", False)`;
  a `PostToolUse` payload becomes `Action("tool_result", ...)` for `Bash` (field `command` = the tool input's
  `command`) and for a tool whose name matches `^mcp__.*tld-board.*__board_set$` (field `op` = `board_set`,
  `args` = the tool input); other tools give no action. The tool output text, `Action.output`, is: the payload's
  `tool_response` when it is a string; for a mapping its `stdout` when that is a string, else the `text` fields
  of its `content` list joined by newlines; for a list the `text` fields joined by newlines; else the empty
  string. `hooks.json` gets: a `UserPromptSubmit` entry, a `PostToolUse` entry with matcher
  `Bash|mcp__.*tld-board.*__board_set`, and a `Stop` entry, each running
  `python3 "${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/board_gate.py"` (timeout 10, 10 and 20 seconds).
- `action.py`: `KINDS` gains `"tool_result"`; `Action` gains `output: str | None = None` (comment: "tool_result:
  the text the tool returned"); the comments of `op` and `args` say "github_op, tool_result".

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
  `playbooks/board.md` prune says legacy records are listed after 24 hours (its step 2 sentence "never one with
  `needs_you: true`" gets "except a record under an old key not updated for 24 hours").
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

1. Load the feature branch's plugin, not the installed one: in a terminal on your machine, `git clone` this
   repository, `git checkout fix/board-record-per-session`, then run
   `claude plugin marketplace add <the clone's path>` and `claude plugin install tld@tkcs-lab-devflow`
   ([delivery.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/board-record-per-session/docs/guides/delivery.md)
   describes this), and start Claude Code there with `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` set. Run
   `/tld:make-plan` with any small request. Open https://board.tkcs.name: the session has its own card, tagged `make-plan · <8 characters>`.
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
3. In that same session (it loads the branch's hooks), run `/tld:docs` and tell it not to write any record. It
   must be blocked once with the message `tld board-gate: ...`, then write the record, and a second turn end is
   not blocked.
4. Run `/tld:docs` again and tell it to write its record with `tld board client set`: it must not be blocked.

Report back: pass or fail for the block, the fallback and the card, one line each, in the pull request.

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
- **Hand-built ids.** After p5, `grep -rn -- '<project>--' playbooks adapters` has no hit outside
  `playbooks/policies/status-board.md`. (`docs/guides/maintenance.md` keeps `<project>--ci` and `<project>--docs`,
  the unattended ids.)
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
      - tests/core/test_status_record.py
      - tests/core/test_board_store.py
      - tests/core/test_board_mcp.py
    brief: |
      Read first: src/tld/board/record.py, tests/core/test_status_record.py, playbooks/policies/status-board.md. Design: section 3.1 of docs/plans/board-record-per-session-plan.md; implement it exactly.
      1. src/tld/board/record.py: add `DOC_ID_RE`, `LEGACY_UNTIL = "1.2.0"`, `doc_id(rec)`, `legacy_ids(rec)` and `owns_doc_id(project, doc_id)` as 3.1 says (private helpers `_plan_part(plan_slug, prefix)` and `_session_tail(session)`), with the exact error messages of 3.1.
      2. In `validate`, replace the block under `if doc_id is not None and isinstance(project, str)` with the rule of 3.1 (`validate`): only when `doc_id` is given and not in `legacy_ids(rec)`; skip it when `project` is not a valid slug, `kind` is not valid, or a command has no valid `command`.
      3. In `main`, add the `record-id` branch next to `project-slug` with the flags of 3.1 (argparse prog `tld board record-id`; `--run` and `--command` mutually exclusive, one required; `--session` and `--unattended` mutually exclusive, one required with `--command`; `--plan-slug` required with `--run`). Subclass `argparse.ArgumentParser` and override `error(self, message)` to print `status-record: <message>` on stderr and exit 1.
      4. src/tld/cli.py: add the `("board", "record-id")` row of 3.1 right after the `project-slug` row.
      5. src/tld/schema/status-record.schema.json: replace the first sentence of the top `description` ("One database document per project and command (collection 'projects').") with "One database document per run or session (collection 'projects').", and the sentence about keys with: "A run (kind 'run') is an implement orchestration keyed '<project>--run--<plan>'; an attended command record (kind 'command') is keyed '<project>--<command>--<session tail>' and an unattended one '<project>--<command>'. tld board record-id builds the id; the old keys (the project slug for a run, '<project>--<command>' for an attended command) are still accepted until tld 1.2.0." Change nothing else in the schema.
      6. tests/core/test_status_record.py (use its `command_record` and `setup_record` helpers and its CLI style; move `test_doc_id_for_run` and `test_review_and_make_plan_write_records` to the new ids and keep one explicit legacy test): `test_run_id_uses_the_plan_slug` (the example of 3.1), `test_attended_command_id_uses_the_session_tail` (`session_01ABcdEFghIJkl` gives `...--make-plan--efghijkl`), `test_unattended_command_id_is_unchanged`, `test_plan_slug_is_made_safe` (`Plan_X  y!` gives `plan-x-y`; empty gives `plan`), `test_plan_slug_at_the_limit_is_not_cut` (prefix plus plan is exactly 100: no hash), `test_plan_slug_one_over_the_limit_is_cut` (exactly 100 characters, matches `DOC_ID_RE`, ends in `-` and 8 hex), `test_two_long_slugs_with_one_prefix_get_two_ids` (150 characters, differing after character 100), `test_long_project_is_an_error` (run and command, message of 3.1), `test_six_character_tail_is_enough`, `test_five_character_tail_is_an_error`, `test_run_is_not_a_command` (`"run" not in COMMANDS`), `test_two_runs_get_two_ids`, `test_legacy_ids_are_still_accepted` (a run under the bare project id and an attended command under `<project>--<command>` validate with `--doc-id`; a third form does not), `test_unattended_command_has_no_legacy_id`, `test_wrong_id_gets_the_message_of_3_1`, `test_broken_record_gets_no_id_error` (no `project`, `--doc-id x`: no `'--doc-id'` line), `test_validate_without_doc_id_ignores_the_tail` (an attended record with a 3-character session validates when no `doc_id` is given), `test_attended_record_rewritten_by_a_new_session` (same record, other `orchestrator_session`, old id given: error of 3.1), `test_owns_doc_id` (accepts the project, `p--run--x`, `p--deps`, `p--make-plan--abcdefgh`; rejects `p--run--`, `p--nope--abcdefgh`, `q--run--x` for project `p`, a 101-character id), `test_record_id_cli` (the three kinds through `record.main`, and for `--run` without `--plan-slug`, `--command x` with neither `--session` nor `--unattended`, `--run --command make-plan`, a bad repo, an unknown command, a 3-character session: returncode 1 and stderr starting `status-record: `), `test_version_compare_reads_two_digit_parts` (`(1,10,0) >= (1,2,0)` through the helper the next test uses) and `test_legacy_window_ends`.
      7. tests/core/test_board_store.py: `test_store_accepts_new_and_legacy_ids` (`Store.set("p--run--x", run with plan_slug x)` and `Store.set("p", same)` succeed; `Store.set("p--run--y", same)` raises `Invalid` with the 3.1 message; use the file's own store and record helpers with project `p`). tests/core/test_board_mcp.py: `test_board_set_with_a_per_session_id` (a `board_set` call with the id of an attended make-plan record succeeds; copy an existing `board_set` test there).
      8. Run `.venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_board_store.py tests/core/test_board_mcp.py tests/core/test_contracts.py -q` and `.venv/bin/python launcher/tld profile validate .tld/toolkit.yaml`.
      Stop condition: a valid record whose id `DOC_ID_RE` rejects, a test outside `touches` that fails because of the new key, or a need to accept a third legacy form: stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_board_store.py tests/core/test_board_mcp.py -q passes
      - .venv/bin/python launcher/tld board record-id --repo tkcs-lab/tkcs-lab-devflow --run --plan-slug stale-needs-you-cards prints tkcs-lab-devflow--run--stale-needs-you-cards
      - .venv/bin/python launcher/tld board record-id --repo tkcs-lab/tkcs-lab-devflow --command make-plan --session session_01ABcdEFghIJkl prints tkcs-lab-devflow--make-plan--efghijkl
      - .venv/bin/python launcher/tld board record-id --repo tkcs-lab/tkcs-lab-devflow --command deps --unattended prints tkcs-lab-devflow--deps
      - grep -n "def doc_id\|def legacy_ids\|def owns_doc_id\|LEGACY_UNTIL" src/tld/board/record.py matches
  - id: p2-board-page-and-prune
    title: Cards keyed by document, session tail in the tag, legacy records prunable, ask record check
    depends_on: [p1-record-ids]
    complexity: M
    touches:
      - src/tld/board/web/board.html
      - src/tld/board/stale.py
      - src/tld/board/ask.py
      - tests/core/test_board_page.py
      - tests/core/test_board_stale.py
      - tests/core/test_board_inbox.py
      - tests/core/test_board_rules.py
      - tests/board_cards_check.js
      - tests/fixtures/board-records.json
      - tests/fixtures/board-records-sessions.json
    brief: |
      Read first: src/tld/board/web/board.html (functions `tagOf`, `row`, `openKeys`, `restoreOpen`), src/tld/board/stale.py, src/tld/board/ask.py (the `record` check), tests/core/test_board_rules.py, tests/board_poll_check.js, tests/core/test_board_page.py (`test_login_poll_and_answer_an_ask_in_a_browser`). Design: sections 3.2 and 3.5 of docs/plans/board-record-per-session-plan.md.
      1. board.html: add `function sessionTail(s)` next to `tagOf`: `typeof s === "string"`, lower-case it, remove `[^a-z0-9]`, take the last 8 characters, return "" when under 6. Change `tagOf(rec)`: a command record with `rec.attended === true` and a non-empty `sessionTail(rec.orchestrator_session)` returns `span(rec.command + " · " + tail, "tag")` (the middle dot U+00B7 with a space on each side); a run and an unattended command return what they return today.
      2. board.html: in `openKeys` and `restoreOpen` build the key `"p:" + d.getAttribute("data-doc")` (use `data-project` only when `data-doc` is absent). Leave the `data-project` attribute in `row`.
      3. stale.py: import `legacy_ids` from `tld.board.record`; add `LEGACY_HIDE = timedelta(hours=24)` and `def legacy_stale(doc, now)`: true when `doc["id"] in legacy_ids(doc["data"])` (ValueError, KeyError and TypeError count as false) and `now - parse(doc["data"]["updated_at"]) > LEGACY_HIDE`. In `main` a doc is printed when `section(...) == "hidden"` or `legacy_stale(doc, now)`. Update the module docstring with one sentence.
      4. ask.py: where the ask's `record` field is checked, replace the equality test with `record.owns_doc_id(<the ask's project>, <value>)`; keep the error text.
      5. tests/fixtures/board-records.json: every `run` record there has an id equal to its project (the legacy form). Rename each run's id to `<project>--run--<plan_slug>` (keep each record's other fields), and add one record with the bare project id as its id, `kind` `run`, `needs_you` true and `updated_at` 3 days before the fixture's clock, whose id is the legacy one. Then update tests/core/test_board_rules.py: the expected stale ids become the old two plus that legacy id; the record-count assertion goes up by one; `assert not needs & set(ids)` stays true except for that id (exclude it by name with a comment). Run the whole file to find any other id it names.
      6. tests/fixtures/board-records-sessions.json (new): four records of one project `p`: two attended make-plan records (sessions `session_01ABcdEFghIJkl` and `session_01ZZyyXXwwVVuu`), one unattended deps record, one attended make-plan with session `ab`; each with a valid id from section 3.1, `needs_you` false, status `running`. tests/board_cards_check.js (new; copy the login and helper shape of tests/board_poll_check.js): with the session token write the four records, open the page, assert the tags read `make-plan · efghijkl`, `make-plan · xxwwvvuu`, `deps`, `make-plan`; open the first card, trigger a poll, assert only that card has the `open` attribute afterwards.
      7. Tests: tests/core/test_board_stale.py (new, `import tld.board.stale as stale`): `test_a_legacy_record_with_needs_you_is_listed_after_24_hours`, `test_a_legacy_record_updated_an_hour_ago_is_kept`, `test_a_new_key_record_with_needs_you_is_never_listed`, `test_an_unattended_command_with_needs_you_is_never_listed` (id `p--deps`, `attended` false, `needs_you` true, 3 days old), `test_an_unattended_record_is_not_listed_after_24_hours`; tests/core/test_board_page.py: `test_cards_are_per_document_and_tagged_with_the_session_tail` (`@pytest.mark.slow`, `need_browser()`, runs `node tests/board_cards_check.js` as the poll test runs its script); tests/core/test_board_inbox.py (copy an existing `record` test there): an ask whose `record` is `<project>--run--<plan>` validates, `<other project>--run--x` does not, `<project>--nope--abcdefgh` does not, `<project>--run--` does not.
      8. Run `.venv/bin/python -m pytest tests/core/test_board_page.py tests/core/test_board_stale.py tests/core/test_board_inbox.py tests/core/test_board_rules.py -q`.
      Stop condition: `tagOf`, `openKeys`, `restoreOpen`, `stale.main` or the ask `record` check is not where this brief says (the prerequisite plans changed it), or a test outside `touches` that reads the fixture fails: stop with `status=blocked` and name what you see.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_page.py tests/core/test_board_stale.py tests/core/test_board_inbox.py tests/core/test_board_rules.py -q passes
      - grep -n "sessionTail" src/tld/board/web/board.html matches
      - grep -n "legacy_stale" src/tld/board/stale.py matches
      - grep -n "owns_doc_id" src/tld/board/ask.py matches
  - id: p3-board-gate-core
    title: The board-gate decision logic and the tool_result action
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/board_gate.py
      - src/tld/guard/action.py
      - tests/core/test_hook_board_gate.py
    brief: |
      Read first: src/tld/guard/plan_gate.py (the model for state, `enabled`, `evaluate`), src/tld/dod/gate.py (`state_dir`), src/tld/guard/action.py, tests/core/test_hook_plan_gate.py (the pattern for tests, including `make_repo_with_origin`). Design: section 3.3 of docs/plans/board-record-per-session-plan.md; implement it exactly.
      1. action.py: add `"tool_result"` to `KINDS`, the field `output: str | None = None` to `Action`, change the comments of `op` and `args` to say "github_op, tool_result" and add the example line `Action(kind="tool_result", ...)` to the module docstring.
      2. New src/tld/guard/board_gate.py with `NAME`, `RECORD_COMMANDS`, `SESSION_TTL_SECONDS`, `MESSAGE`, `enabled(ctx)` (same errors as `plan_gate.enabled` with `board_gate`), `state_file`, `_load`, `_save` (the state file's `opened_at` is epoch seconds; the TTL compares it with `time.time()` read as `board_gate.time.time()`), `is_record_write(action)` and `evaluate(ctx)` as 3.3 says. `evaluate` is wrapped: `except ProfileError as exc: ctx.notice = str(exc); return None` and `except Exception: return None`. It returns `MESSAGE` only for the Stop case and `None` for `prompt` and `tool_result`.
      3. tests/core/test_hook_board_gate.py, one test per line, building `Action`s and `Ctx` the way tests/core/test_hook_plan_gate.py does. Every test starts with `monkeypatch.delenv` of `TLD_BOARD_URL` and `TLD_BOARD_TOKEN`, and the ones that need a board set `TLD_BOARD_URL=https://board.example` and `TLD_BOARD_TOKEN=t`. Time is read through `monkeypatch.setattr(board_gate.time, "time", ...)`; an unreadable state file is invalid JSON or a directory, never chmod. Tests: a command prompt opens the state; a plain prompt does not; `board` and `repo-admin` prompts do not open it; a stop without a write blocks and the message names the command and, joined with the runner prefix `tld board-gate: `, reads exactly once as in 3.3; a second stop does not block; `continuing=True` does not block; a re-prompt of the same command keeps `written`; a prompt of a different command reopens the state; a `board_set` tool result with `{"id": "x", "version": 2}` sets `written` and the stop is then allowed; output `{"error": "invalid"}` does not; a Bash `tld board client set x - --if-version 1` with last output line `{"id":"x","version":3}` sets `written`; `tld board client get x && echo reset` does not; output `{"error":"version_conflict","current":{"id":"x","version":3}}` does not; no `TLD_BOARD_URL`, no token, `ftp://x`, no session id, a state older than the TTL (time patched), `hooks.board_gate.enabled` false, `hooks.disable: [board-gate]` in the committed profile, and an unreadable state file each never block; `test_board_gate_stop_makes_no_network_call` (monkeypatch `socket.socket` to raise; the Stop still returns the message); `test_real_mcp_board_set_result_is_a_record_write` (call `tld.board.mcp._call_tool(Store(tmp_path / "b.db"), "board_set", {...})` with a valid record, pass its text as `output` of a `tool_result` action: written; a conflicting second call with a stale `if_version`: not written; use the helpers of tests/core/test_board_mcp.py).
      4. Run `.venv/bin/python -m pytest tests/core/test_hook_board_gate.py tests/core/test_hook_plan_gate.py tests/core/test_guard_plumbing.py -q`.
      Stop condition: a test elsewhere pins the exact list of `KINDS` in a way your change cannot satisfy: stop with `status=blocked` and name the test.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_hook_board_gate.py -q passes
      - grep -n "tool_result" src/tld/guard/action.py matches
      - grep -n "RECORD_COMMANDS" src/tld/guard/board_gate.py matches
  - id: p4-board-gate-adapter
    title: Claude Code adapter, hooks.json, the profile key and the hook docs
    depends_on: [p3-board-gate-core]
    complexity: M
    touches:
      - adapters/claude/hooks/claude_adapter.py
      - adapters/claude/hooks/board_gate.py
      - adapters/claude/hooks/hooks.json
      - src/tld/guard/_common.py
      - src/tld/schema/profile.schema.json
      - tests/hooks_helpers.py
      - tests/adapters/claude/test_hooks_config.py
      - tests/adapters/claude/test_hook_board_gate_adapter.py
      - docs/architecture/hooks.md
    brief: |
      Read first: adapters/claude/hooks/claude_adapter.py, adapters/claude/hooks/dod_gate.py, adapters/claude/hooks/hooks.json, tests/adapters/claude/test_hooks_config.py (`test_hook_names_agree_everywhere`, `test_docs_cover_every_hook_and_key`, `test_hooks_json_is_valid_and_every_script_exists`, `test_matchers`, `test_schema_rejects_bad_hooks_sections`, `test_schema_defaults_equal_the_hooks_built_in_defaults`), tests/hooks_helpers.py, docs/architecture/hooks.md. Design: the Claude adapter paragraph of section 3.3 of docs/plans/board-record-per-session-plan.md.
      1. src/tld/guard/_common.py: add `"board-gate"` to `HOOK_NAMES`; in `run_guard` change `if name != "plan-gate" and ctx.disabled(name)` to `if name not in ("plan-gate", "board-gate") and ctx.disabled(name)`. src/tld/schema/profile.schema.json: add `board_gate` under `hooks.properties` next to `plan_gate`, copying its shape (`enabled`, boolean, `x-hook-default` false, description `Opt in: a session that a record-writing tld command started cannot end its turn before it has written its status record to the board once.`) and add `board-gate` wherever the schema lists the hook names `hooks.disable` allows (grep `plan-gate` in the schema).
      2. Add adapters/claude/hooks/board_gate.py as a copy of dod_gate.py with the docstring `Claude Code hook entry for board-gate` and `main("board-gate")`.
      3. claude_adapter.py: add `"board-gate": ("tld.guard.board_gate", False)` to `GUARDS` (line 26); add `_result_text(response)` (the output rule of 3.3) and, in `to_action`, a PostToolUse branch (`hook_event_name == "PostToolUse"`) before the tool branches: for `Bash` an `Action("tool_result", project, cwd, command=<tool_input command>, output=_result_text(payload.get("tool_response")), session_id=_sid(payload))`; for a tool name matching `^mcp__.*tld-board.*__board_set$` the same with `op="board_set"`, `args=dict(tool_input)` and no `command`; every other tool returns `None`. A payload without `tool_response` gives output "".
      4. hooks.json: add the three entries of 3.3 (UserPromptSubmit next to the plan-gate one, a PostToolUse block with the matcher `Bash|mcp__.*tld-board.*__board_set`, a Stop entry after dod-gate's), command `python3 "${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/board_gate.py"`; in the top `description` change "plus the opt-in plan-gate" to "plus the opt-in plan-gate and board-gate".
      5. tests/hooks_helpers.py: `MODULES`, `CORE` and `FAIL_CLOSED` gain `board-gate` (`tld.guard.board_gate`, fail-open). tests/adapters/claude/test_hooks_config.py: in `test_hooks_json_is_valid_and_every_script_exists` the event set becomes `{PreToolUse, PostToolUse, UserPromptSubmit, Stop}`, a matcher is required for PreToolUse and PostToolUse (none for the others) and the expected script list gains `board_gate.py` three times; `test_matchers` gains PostToolUse rows (`mcp__plugin_tld_tld-board__board_set` true, `mcp__plugin_tld_tld-board__board_get` false, `Read` false, `mcp__github__push_files` false); `test_schema_rejects_bad_hooks_sections` gains `({"board_gate": {"enabled": "yes"}}, "'hooks.board_gate.enabled': must be true/false")`; `test_schema_defaults_equal_the_hooks_built_in_defaults` also asserts `props["board_gate"]["properties"]["enabled"]["x-hook-default"] is False`.
      6. docs/architecture/hooks.md: add `### board-gate` after `plan-gate` (what it is, opt-in `hooks.board_gate.enabled`, the three events, the state file `<git dir>/tld/board-gate/<hash>.json`, "blocks once", fails open) and add `board-gate` to every list of hook names there (grep `plan-gate`); the rejected alternatives and the nudge sentence are written in p6.
      7. tests/adapters/claude/test_hook_board_gate_adapter.py (copy the payload helpers and `run_script`/`make_repo_with_origin` usage of tests/hooks_helpers.py): unit: a Bash PostToolUse with a string `tool_response` becomes a `tool_result` action; an MCP `mcp__plugin_tld_tld-board__board_set` payload with `tool_response` `{"content": [{"type": "text", "text": "{\"id\":\"x\",\"version\":2}"}]}` gives `op == "board_set"` and that text; a `Read` PostToolUse gives no action; `test_record_commands_are_known_commands` (each `board_gate.RECORD_COMMANDS` entry is in `claude_adapter.known_commands()`); integration, in a temp git repo with `hooks: board_gate: enabled: true`, `TLD_BOARD_URL=https://board.example`, `TLD_BOARD_TOKEN=t` and one `session_id`, through `run_script("board-gate", ...)`: `test_prompt_then_board_set_then_stop_allows` (a UserPromptSubmit `/tld:docs x`, a PostToolUse `board_set` with `{"id":"p--docs","version":1}`, then Stop: exit 0, empty stderr), `test_prompt_then_client_set_then_stop_allows` (a Bash `tld board client set p--docs - --if-version 1` with `tool_response` `{"stdout":"{\"id\":\"p--docs\",\"version\":2}\n","stderr":"","interrupted":false}`), `test_prompt_then_failed_board_set_then_stop_blocks` (output `{"error":"version_conflict"}`: Stop exits 2, stderr starts `tld board-gate:`, a second Stop exits 0), `test_unknown_payload_exits_0_silently`, `test_a_malformed_hooks_disable_never_blocks` (a committed profile with `hooks: {disable: "board-gate"}`: Stop exits 0).
      8. Run `.venv/bin/python -m pytest tests/adapters/claude tests/core/test_hook_board_gate.py tests/core/test_guard_plumbing.py -q`.
      Stop condition: Claude Code's documented PostToolUse payload (ask the claude-code-guide agent, or find it in tests/hooks_helpers.py) does not carry `tool_name`, `tool_input` and `tool_response` as this brief says: stop with `status=blocked` and write the field names you found.
    acceptance:
      - .venv/bin/python -m pytest tests/adapters/claude -q passes
      - grep -c "board_gate.py" adapters/claude/hooks/hooks.json prints 3
      - grep -n "board-gate" adapters/claude/hooks/claude_adapter.py src/tld/guard/_common.py matches
      - grep -n "### board-gate" docs/architecture/hooks.md matches
  - id: p5a-status-board-policy
    title: The status-board policy, implement, make-plan, review, board playbooks and the runtime map
    depends_on: [p1-record-ids]
    complexity: M
    touches:
      - playbooks/policies/status-board.md
      - playbooks/implement.md
      - playbooks/make-plan.md
      - playbooks/review.md
      - playbooks/board.md
      - adapters/claude/skills/runtime/SKILL.md
    brief: |
      Read first: playbooks/policies/status-board.md, adapters/claude/skills/runtime/SKILL.md (the "Status board" paragraph), docs/plans/board-record-per-session-plan.md section 3.4. Design: section 3.4; use its wording, adapt only for grammar.
      1. playbooks/policies/status-board.md: make the four changes of 3.4 (the `document id` row, the section "Keys and a record that already exists", the section "The write path", the "When to write" sentence). Keep the file's other headings, "No secrets" and "Alerts".
      2. implement.md "Status record": append "document id from `tld board record-id --repo <owner>/<repo> --run --plan-slug <plan_slug>`, written before any worker starts" to the sentence that names `kind: run`. make-plan.md Setup item 3 (the "Status record" line): append "document id from `tld board record-id --repo <owner>/<repo> --command make-plan --session <this session's id>`". review.md: the same append at its Status record line with `--command review`.
      3. playbooks/board.md prune: in step 2 change "never one with `needs_you: true`" to "never one with `needs_you: true`, except a record under an old key (the project slug, or `<project>--<command>` of an attended command) not updated for 24 hours", and add after step 2: "Records under an old key are listed once they were not updated for 24 hours, even when they need the owner."
      4. adapters/claude/skills/runtime/SKILL.md: at the end of the "Status board" paragraph add: "When a board tool is missing or fails (disconnected, error), write the record with `tld board client set <id> - [--if-version <n>]`; only exit 3 means there is no board. Never skip a record for a dropped tool."
      5. Run `.venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_no_project_words.py -q`.
      Stop condition: a contract test rejects a `tld` call you wrote, or a file this brief names has no "Status record" line where it says: stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_no_project_words.py -q passes
      - grep -n "tld board record-id" playbooks/policies/status-board.md playbooks/implement.md playbooks/make-plan.md playbooks/review.md matches
      - grep -n "tld board client set" playbooks/policies/status-board.md adapters/claude/skills/runtime/SKILL.md matches
  - id: p5b-record-writers
    title: The command playbooks name tld board record-id, the wording test and the baseline
    depends_on: [p5a-status-board-policy, p3-board-gate-core]
    complexity: M
    touches:
      - playbooks/migrate.md
      - playbooks/setup.md
      - playbooks/land.md
      - playbooks/deps.md
      - playbooks/upstream.md
      - playbooks/ci.md
      - playbooks/docs.md
      - tests/core/test_board_record_wording.py
      - evals/baselines/default.json
    brief: |
      Read first: playbooks/policies/status-board.md (as p5a left it), docs/plans/board-record-per-session-plan.md section 3.4, CONTRIBUTING.md (the baseline refresh paragraph). Design: section 3.4.
      1. In migrate.md:15, setup.md:30 and land.md:24 (attended commands) replace the literal ``document id `<project>--<command>` `` with "document id from `tld board record-id --repo <owner>/<repo> --command <name> --session <this session's id>`". In ci.md:24, deps.md:23 and upstream.md:24 (they say `attended: false`) replace it with "document id from `tld board record-id --repo <owner>/<repo> --command <name> --unattended`". docs.md: append the same sentence (`--command docs`, attended or not as that line says: `--unattended` when its Status record line says `attended: false`, else `--session <this session's id>`) to each of its two Status record lines (grep `Status record` and `docs clean` in docs.md).
      2. tests/core/test_board_record_wording.py (new): `test_no_playbook_hand_builds_a_document_id` (no file under playbooks/ or adapters/ contains `<project>--`, `{project}--` or `tkcs-lab-devflow--`, except playbooks/policies/status-board.md, which is exempt as a whole), `test_status_board_policy_names_record_id_in_the_table_row` (the `document id` row contains `tld board record-id`), `test_every_record_writer_names_record_id` (each of implement, make-plan, review, migrate, setup, land, deps, upstream, ci and docs playbooks contains `tld board record-id`), `test_status_board_policy_has_the_fallback_and_resume_rule` (contains `tld board client set`, `Only exit 3`, `keeps writing that one` and `never a reason to skip`), `test_runtime_map_has_the_fallback` (SKILL.md contains `tld board client set`), `test_record_commands_match_the_playbooks` (the set of command names whose playbook contains `tld board record-id` equals `set(board_gate.RECORD_COMMANDS)`; import `tld.guard.board_gate`).
      3. Run `.venv/bin/python -m pytest tests/core/test_board_record_wording.py tests/core/test_contracts.py -q`, then `python3 evals/run.py baseline --refresh-hashes` (a wording change cannot affect the guardrail tasks; say so in the commit message) and `python3 evals/run.py check-baseline`.
      Stop condition: a playbook this brief names has no literal id sentence at the line it says, or p3 is not merged (`tld.guard.board_gate` missing): stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_record_wording.py tests/core/test_contracts.py tests/core/test_evals_baseline.py -q passes
      - python3 evals/run.py check-baseline exits 0
      - grep -rn -- "<project>--" playbooks adapters --exclude=status-board.md prints nothing
  - id: p6-retire
    title: Docs, changelog and retire the plan
    depends_on: [p2-board-page-and-prune, p4-board-gate-adapter, p5b-record-writers]
    complexity: M
    touches:
      - docs/architecture/hooks.md
      - docs/reference/profile-reference.md
      - docs/reference/cli.md
      - docs/guides/maintenance.md
      - CHANGELOG.md
      - docs/plans/board-record-per-session-plan.md
    brief: |
      Read first: docs/README.md, docs/architecture/hooks.md (the `### board-gate` section p4 added, and "What the hooks do not protect"), docs/reference/cli.md, docs/reference/profile-reference.md, docs/guides/maintenance.md, CHANGELOG.md. No other doc.
      1. docs/architecture/hooks.md: extend the `### board-gate` section with the exact block message and the two rejected alternatives of section 3.3 of the plan, and add to "What the hooks do not protect": "`board-gate` is a nudge: a session that can write files can write its state file."
      2. docs/reference/profile-reference.md: add the row `hooks.board_gate.enabled` after the `hooks.plan_gate.enabled` row (no, default `false`; opt in to the `board-gate` Stop hook; link to hooks.md) and add `board-gate` to the `hooks.disable` list.
      3. docs/reference/cli.md: add the row for `tld board record-id` next to `project-slug`, with its flags from section 3.1.
      4. docs/guides/maintenance.md (lines naming `<project>--ci`, `<project>--docs` and `<project>--<command>`, about lines 40, 74 and 142): state the keys of 3.1 (unattended ids unchanged) and the grace window until 1.2.0.
      5. CHANGELOG.md under `## [Unreleased]`: `### Added` a line for the opt-in `board-gate` hook and `tld board record-id`; `### Changed` a line: "Status board: every implement run and every attended command has its own record (`<project>--run--<plan>`, `<project>--<command>--<session tail>`), so two runs or two sessions no longer replace each other's card; the old keys are accepted until 1.2.0, and `/tld:board prune` lists old-key records after 24 hours"; `### Fixed` a line: "A session no longer skips its status record when its runtime's board tools drop: the playbooks fall back to `tld board client set`". Add no version heading.
      6. Delete docs/plans/board-record-per-session-plan.md (`git rm`) and remove any link to it. Run `.venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0 (no new doc is added, so no new row; fix any row the check reports).
      Stop condition: a doc this brief names does not have the section or list it says: stop with `status=blocked` and name it.
    acceptance:
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - grep -n "board-gate" docs/architecture/hooks.md docs/reference/profile-reference.md matches
      - grep -n "record-id" docs/reference/cli.md CHANGELOG.md matches
      - test ! -e docs/plans/board-record-per-session-plan.md
```
