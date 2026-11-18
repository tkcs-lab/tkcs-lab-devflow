# Keep the board current: make-plan, implement and every ask timer

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Nothing new to type. A `/tld:make-plan` or `/tld:implement` session now puts its work on the board first: implement's very first record lists every manifest phase plus `final-review`, and a revision, a fix or a second review is added to the record before its worker starts. Every ask is followed in the same turn by a timer. A new `tld board items` command builds and checks that item list, and the opt-in `board-gate` hook blocks a turn once when it wrote no record or an ask got no timer.

**Scope:** A new policy section "Board upkeep" in the status-board policy, linked from the top of make-plan and implement; `tld board items`; the `board-gate` guard and its Claude adapter mapping; a wording fix in `runtime.md` (the timer time goes into `last_event`, because `next_check_at` must be null while waiting). Not changed: the record schema, the board server, other playbooks' steps, and make-plan's record, which keeps its five planning items and does not list the plan's phases. The profile line that turns the hook on in this repository is a protected change and goes in its own pull request.

**Security:** The hook only blocks the end of a turn, once; it never denies a tool call and never calls the board.

**Review focus:** the new `board-gate` rules and their false positives (section 3, D3); the `timer` and `ask` tool mapping in the adapter (D4); the wording of the five upkeep rules the playbooks must follow (D1).

## 1. Goal

Make the board upkeep of `/tld:make-plan` and `/tld:implement` impossible to forget, as asked in [#67](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/67): the work is on the board as early as possible, every phase is on it from the first write, extra items such as `fix-<n>` are added as they appear, and every ask has its timer armed in the same turn. The owner chose three layers: clear playbook rules, a `tld` command that makes the item list mechanical, and a stronger `board-gate` hook.

## 2. Current state

- `playbooks/policies/status-board.md:68-82` says when to write a record, but never says that all items go in the first write or that late items (fix, revision) must be added. It is read by link, not at the top of the playbook.
- `playbooks/implement.md:446-455` ("Status record") sits at the very end of a 463-line playbook; the first record is described only there. `playbooks/make-plan.md:35-41` (Setup step 3) is one dense paragraph.
- `playbooks/runtime.md` (`ask_human`, attended branch) says to "put its time in `next_check_at`". `src/tld/board/record.py:50` (`NO_TIMER`) and `:310` reject `next_check_at` for status `waiting_user` and for every command record, so a make-plan card can never show its timer (found while writing this plan: the board answered `'next_check_at' must be null for a command record`).
- `src/tld/guard/board_gate.py` blocks one turn end per session until the first record write (`_evaluate`, lines 120-161). It has no notion of a turn, of an ask or of a timer. `adapters/claude/hooks/claude_adapter.py:180-196` turns only `Bash` and `board_set` tool results into actions. `adapters/claude/hooks/hooks.json` registers the PostToolUse matcher `Bash|mcp__.*tld-board.*__board_set`.
- `.tld/toolkit.yaml` does not enable `hooks.board_gate`.

## 3. Design

The architect role reviewed this design (see Risks for what it changed).

### D1. Policy: "Board upkeep" (`playbooks/policies/status-board.md`)

Insert a new section `## Board upkeep` directly after `## Where the board is`. Exact text:

```
## Board upkeep

The board is part of the work, not a report written after it. A run that is not on the board does not exist for the owner. These five rules hold for every playbook that writes a record and are mandatory for make-plan and implement:

1. **First record first.** Write the first record (`starting`) before any step that can take more than a minute. In make-plan and implement that is before the research, before the first worker and before the first ask; never "after the plan is understood".
2. **Every item up front.** The first record lists every item the run will have. In implement that is every phase of the manifest plus `final-review`, printed by `tld board items <plan file>`; never a short list that grows later.
3. **Extra items at once.** A revision (`<phase id>-rev<n>`), a fix (`fix-<n>`) and a second final review (`final-review-2`) become items in the same record write that starts them, before their worker exists. Before every record write of implement, save the record to a scratch file and run `tld board items <plan file> --check <record file> --add <id>=<title>` with one `--add` for every extra item so far; it must exit 0.
4. **Every change is a write.** Every state change, every check-in, every ask and every answer is a record write, also when only `updated_at` changes. A turn that ends without a record write is a turn that forgot the board.
5. **Every ask has a timer.** In the same turn that posts an ask: write the record with `needs_you`, show the ask in the conversation (attended), start the watch (attended, with a board) and arm `schedule_wakeup` (60 minutes with the watch, else 10 minutes). Write the timer's time into `last_event` as `timer <ISO time>`: `next_check_at` must be null while the status is `waiting_user` and in every command record. Never end the turn of an ask without the timer. On every wake cancel the armed timer before arming the next one, and cancel it when the ask closes.
```

Also change the sentence in `## When to write` that begins `- The first record is written before the first ask` to end with `(Board upkeep, rule 1)`, and add to `## Best effort` nothing.

### D2. `tld board items` (`src/tld/board/items.py`)

```
tld board items PLAN [--add ID[=TITLE]]... [--check RECORD]
```

`PLAN` is a plan file with an implementation manifest. Load it exactly as `tld.plan.manifest.main` does (`extract_manifest`, then `yaml.safe_load`); a missing file, a missing manifest or invalid YAML prints `tld board items: <message>` to stderr and exits 2.

- Without `--check` it prints one JSON list (`json.dumps`, one line) of run-record items: one per manifest phase in manifest order, then `final-review` (title `Final review`, `depends_on` every phase id, `complexity` null), then one per `--add` in the order given. A phase item is `{"id", "title", "depends_on", "complexity", "state": "pending", "session": null, "branch": null, "started_at": null, "finished_at": null}` with `title`, `depends_on` and `complexity` copied from the phase (`complexity` is `"S"`, `"M"` or null). An added item has the same shape with `depends_on` `[]`, `complexity` null and the title after `=` (the id when there is no `=`). Exit 0.
- An id must match `^[a-z0-9][a-z0-9-]{0,63}$` and be unique among all items (manifest phases, `final-review`, added); otherwise `tld board items: <message>` on stderr and exit 2.
- With `--check RECORD` (`RECORD` is a status record JSON file, or `-` for stdin) it prints nothing but the verdict: for every expected id (the same list as above) that is not the `id` of an entry of the record's `phases`, one line `items: missing <id>` on stdout, and exit 1; otherwise `items: ok (<n> expected)` and exit 0. Extra ids in the record are fine. A record that is not JSON or has no `phases` list: stderr `tld board items: <message>`, exit 2.

It belongs to `tld.board` (it builds board items), registered as `("board", "items")` in `src/tld/cli.py` and documented in `docs/reference/cli.md`.

### D3. `board-gate` rules (`src/tld/guard/board_gate.py`)

Still opt-in (`hooks.board_gate.enabled`) and still a nudge. The state file gains six fields (defaults when absent, so an older state file loads): `turn_written` (bool, false), `turn_blocked` (bool, false), `closed` (bool, false), `ask_seq` (int, 0), `timer_seq` (int, 0), `timer_blocked_seq` (int, 0).

Events:

- **prompt** (`UserPromptSubmit`): as today, a prompt of a record-writing command opens the state. Every prompt, when a state exists, also sets `turn_written` and `turn_blocked` to false (a new turn).
- **tool_result**:
  - a record write (`is_record_write`, unchanged): `written` and `turn_written` become true; when the action is `op == "board_set"` and `args["data"]` is a mapping whose `status` is `done` or `failed`, `closed` becomes true.
  - an ask post: `ask_seq += 1`. An ask post is any of: `op == "board_ask"` whose output is JSON with a string `id` starting with `a-`; a shell command matching `\bboard\s+ask(?![-\w])` whose output has a line that is exactly an id (`a-` and hex digits) or starts with `<!-- tld-ask -->`; `op == "add_issue_comment"` whose `args["body"]` starts with `<!-- tld-ask -->` (the issue fallback).
  - a timer: `op == "timer"` sets `timer_seq = ask_seq`.
- **stop**: unchanged for `ctx.disabled`, `a.continuing` and "no state" (return `None`). Then, in this order, the first rule that fires blocks and records that it did:
  1. the timer rule: `ask_seq > timer_seq and timer_blocked_seq < ask_seq` → `timer_blocked_seq = ask_seq`, message `TIMER_MESSAGE`. It does not need a configured board.
  2. only with a configured board (`client.load_config()` not `None`): the first-record rule as today (`written` false and `blocked` false → `blocked = true`, message `MESSAGE`).
  3. only with a configured board: the turn rule: `closed` false, `turn_written` false and `turn_blocked` false → `turn_blocked = true`, message `TURN_MESSAGE`.

A state file is still discarded after 24 hours. `continuing` still lets the second stop of a chain through, so one block per stop chain is the most the hook ever causes.

Messages (the guard runner puts `tld board-gate: ` in front):

- `MESSAGE`: unchanged.
- `TURN_MESSAGE`: `this session was started by /tld:{command} and wrote no status record in this turn. Write it now: use the board_set tool, or when that tool is missing or fails run "tld board client set <id> - " with the record on stdin. Set updated_at, the state of every item that changed, and every extra item (a fix, a revision, a second review) that started. If the board cannot be reached, say so in your final reply and stop. If this turn only answers a chat message and changes nothing, say so and stop. This check blocks only once per turn.`
- `TIMER_MESSAGE`: `this session posted an ask and armed no timer after it. Arm it now with schedule_wakeup (60 minutes when the answer watch runs, else 10 minutes), write its time into last_event as "timer <ISO time>" and write the record. If this run is unattended (no person started it), a timer is not needed: say so and stop. This check blocks only once per ask.`

Rejected: blocking every stop without a limit (a loop the owner cannot leave); blocking only on the first turn (the actual failure is a later turn that forgets); reading the board from the hook (needs the network and a token inside a hook, see `docs/architecture/hooks.md`).

### D4. Adapter mapping (`adapters/claude/hooks/claude_adapter.py`, `hooks.json`)

`to_action` (PostToolUse) gains three mappings, each an `Action("tool_result", project, cwd, ..., session_id=_sid(payload))`:

- a tool matching `^mcp__.*tld-board.*__board_ask$` → `op="board_ask"`, `output=<result text>`;
- a tool matching `^(ScheduleWakeup|CronCreate)$` or `^mcp__.*__(send_later|create_trigger)$` → `op="timer"`, `args=dict(ti)`, `output=<result text>`;
- a tool matching `^mcp__.*__add_issue_comment$` → `op="add_issue_comment"`, `args=dict(ti)`, `output=<result text>`.

The PostToolUse matcher in `hooks.json` becomes `Bash|mcp__.*tld-board.*__(board_set|board_ask)|ScheduleWakeup|CronCreate|mcp__.*__(send_later|create_trigger|add_issue_comment)`. The runtime tool names live only in the adapter; the core guard sees `board_ask`, `timer` and `add_issue_comment`.

### D5. Playbook edits (`make-plan.md`, `implement.md`, `runtime.md`)

- Both playbooks get, directly after their `Rules that hold throughout:` paragraph, this paragraph: `**Board upkeep is mandatory.** Follow "Board upkeep" in [policies/status-board.md](policies/status-board.md): the first record before any other work, every item in it, extra items added the moment they start, a record write in every turn, and a timer armed in the same turn as every ask.`
- `make-plan.md` Setup step 3: the five items `research`, `decide`, `write`, `review`, `hand-over` are in the first write; each is `running` when its step starts and `done` when it ends, each change written at once. make-plan's record never lists the plan's phases (owner decision). `ask_human` uses in section 0 step 3 and in the "already being planned" check name the timer rule.
- `implement.md`: after section 0 step 4 a new step `4a` (below) writes the first record; the "Status record" section is rewritten to point to `tld board items` and rule 3; sections 4 and 5 name the item to add before each revision, fix and second review worker.
- `runtime.md` (`ask_human`, attended branch): `put its time in next_check_at` becomes `write its time into last_event as "timer <ISO time>" (next_check_at is null while the status is waiting_user and in every command record)`.

### D6. The profile line (not a phase)

`.tld/toolkit.yaml` is protected. After the plan is pushed, this session runs the protected-changes flow for exactly this diff (one ask `protected-1`, one pull request `chore/protected-toolkit-profile-<yyyymmdd>`, never merged by the agent): under `hooks:`, after the `plan_gate:` block, add

```
  board_gate:
    enabled: true
```

The owner decided this (ask `a-dac9d820c10c0d1b`, question `hook`: "yes make it on here").

## 4. ADRs

None: this repository's profile has no `docs.adr_dir`.

## 5. Manual steps

None before implementation and none after. The one human action outside the plan is merging the protected-change pull request of D6 (the owner's normal review).

## 6. Risks and open questions

- **False positives of the turn rule.** A turn that only answers a chat message is blocked once. The message says how to dismiss it. A worker that finds the hook blocking an unrelated phase turn reports `status=blocked` with the message.
- **Unattended runs.** An unattended command that never asks is not affected by the timer rule; one that does ask is told once that no timer is needed.
- **Runtime tool names.** If the runtime renames its timer or ask tools, only the three regexes in the adapter change (D4).
- **Old state files.** `_load` defaults the six new fields, so a state written by the old hook still loads.
- **Evals.** Playbook text changes make the eval baseline hashes stale; p4 refreshes the hashes only (`python3 evals/run.py baseline --refresh-hashes`), and the commit message says the change adds board-upkeep rules and affects no graded behaviour. A real run of `make-plan-small` and `make-plan-large` is not part of this plan.
- **Plugin update.** The hook behaviour reaches sessions only after the plugin is released and updated; until then the playbook rules apply alone.
- **How a worker recognises a wrong brief.** If `tests/core/test_hook_board_gate.py` or the contract tests fail for a reason the brief does not mention, the worker stops with `status=blocked` and quotes the failing test.

## Implementation manifest

```yaml
plan_slug: board-upkeep-enforcement
feature_branch: feature/board-upkeep-enforcement
tracking_issue: 67
max_parallel: 2
manual_before: []
manual_after: []
verify_after_merge:
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - "`tld plan deviations check --file docs/plans/67/deviations.md --plan docs/plans/67/plan.md --all` exits 0"
  - "`tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
  - "`python3 evals/run.py check-baseline` exits 0"
  - "the changelog has entries under docs.changelog.section and no version heading"
phases:
  - id: p1-items-cli
    title: tld board items command
    depends_on: []
    complexity: S
    touches:
      - src/tld/board/items.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_board_items.py
    brief: |
      Read first: docs/reference/cli.md, src/tld/plan/manifest.py (extract_manifest and main), src/tld/board/usage_client.py (module shape).
      Implement the command exactly as plan section 3, D2 specifies (plan: docs/plans/67/plan.md).
      1. Create src/tld/board/items.py: a module docstring with the usage line and the exit codes (0 ok, 1 missing items, 2 usage or unreadable input), `from __future__ import annotations`, stdlib plus yaml only, `main(argv: list[str] | None = None) -> int` using argparse with `plan`, `--add` (action append, default []) and `--check`. Load the manifest the way tld.plan.manifest.main does: `extract_manifest(text)` then `yaml.safe_load`; a missing file, a ValueError or a YAMLError prints `tld board items: <message>` to stderr and returns 2.
      2. Build the items with one helper `build_items(manifest, adds) -> list[dict]`: phase items in manifest order, then `final-review`, then the added ones; every item has exactly the keys id, title, depends_on, complexity, state ("pending"), session, branch, started_at, finished_at. Validate every id with `re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", id)` and uniqueness; raise ValueError with the message `invalid item id '<id>'` or `duplicate item id '<id>'`, which main prints as in step 1 and returns 2.
      3. `--add ID[=TITLE]`: split on the first `=`; the title is the part after it, else the id.
      4. Without --check print `json.dumps(items)` and return 0. With --check read the record JSON from the file, or from stdin when the value is `-`; a non-JSON text or a record without a `phases` list prints `tld board items: <message>` to stderr and returns 2. For each expected id that no `phases[].id` equals print `items: missing <id>` to stdout; return 1 when any is missing, else print `items: ok (<n> expected)` and return 0.
      5. Register it in src/tld/cli.py in COMMANDS next to the other board entries: `("board", "items"): ("tld.board.items", (), "print the run record's items from a plan, or check a record lists them all")`.
      6. Add a row for `tld board items PLAN [--add ID[=TITLE]]... [--check RECORD]` to the table in docs/reference/cli.md next to the `tld board validate-record` row, module `tld.board.items`, with a one-sentence description of both modes and the exit codes. Do not edit CHANGELOG.md (the last phase does) or docs/README.md.
      7. Create tests/core/test_board_items.py with pytest functions: a fixture writing a small plan file (a `## Implementation manifest` heading followed by a yaml block with plan_slug `x`, two phases p1-a (S, depends_on []) and p2-b (M, depends_on [p1-a])) into tmp_path; tests for: the printed list has p1-a, p2-b, final-review in that order with state pending and the exact key set; final-review depends_on both phase ids; `--add fix-1=Fix one` appends an item titled `Fix one`; `--add fix-1` uses the id as title; duplicate id exits 2; id `Bad_Id` exits 2; a missing plan exits 2; `--check` exits 1 and names `final-review` for a record whose phases list only p1-a and p2-b; exits 0 with `items: ok (3 expected)` when all three are present; extra ids in the record are accepted; a record read from stdin works (use subprocess with `cli/tld board items ...` for one test to prove the registration).
      8. Run `.venv/bin/python -m pytest tests/core/test_board_items.py tests/core/test_cli_reference.py tests/core/test_contracts.py -q`; all pass. Stop condition: if test_cli_reference demands a different row format, copy the format of the neighbouring row; if it still fails, stop with status=blocked and quote the failure.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_board_items.py -q passes"
      - ".venv/bin/python -m pytest tests/core/test_cli_reference.py tests/core/test_contracts.py -q passes"
      - "grep -n 'tld board items' docs/reference/cli.md matches"
      - "grep -n '(\"board\", \"items\")' src/tld/cli.py matches"
  - id: p2-gate-core
    title: board-gate turn and timer rules
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/board_gate.py
      - tests/core/test_hook_board_gate.py
    brief: |
      Read first: src/tld/guard/board_gate.py, tests/core/test_hook_board_gate.py, docs/architecture/hooks.md (the board-gate section only), src/tld/guard/action.py.
      Implement plan section 3, D3 exactly (plan: docs/plans/67/plan.md). Do not edit docs/architecture/hooks.md (the last phase does).
      1. In src/tld/guard/board_gate.py extend `_load` and `_save` users: `_load` returns the four existing keys plus `turn_written`, `turn_blocked`, `closed` (each `data.get(key) is True`) and `ask_seq`, `timer_seq`, `timer_blocked_seq` (each an int that is not a bool and is at least 0, else 0). The state written when a prompt opens a session sets all new bool fields to False and all new int fields to 0.
      2. Add the constants `ASK_COMMAND = re.compile(r"\bboard\s+ask(?![-\w])")`, `ASK_ID_LINE = re.compile(r"^a-[0-9a-f]+$")` and `ASK_MARKER = "<!-- tld-ask -->"`, and the two messages `TURN_MESSAGE` and `TIMER_MESSAGE` with the exact texts of D3.
      3. Add `is_ask_post(action: Action) -> bool` implementing the three cases of D3 (op `board_ask`: parse the output as JSON, an object whose `id` is a str starting with `a-`; a command matching ASK_COMMAND: some output line stripped equals an ASK_ID_LINE match or starts with ASK_MARKER; op `add_issue_comment`: `str(action.args.get("body", "")).lstrip().startswith(ASK_MARKER)`); only for `action.kind == "tool_result"`. Add `is_timer(action) -> bool`: kind `tool_result` and `op == "timer"`.
      4. In `_evaluate`: the prompt branch also resets `turn_written` and `turn_blocked` to False in an existing state and saves it. The tool_result branch loads the state once and, for each of: record write (set `written` and `turn_written` true; also set `closed` true when `action.op == "board_set"` and `isinstance(action.args.get("data"), dict)` and its `status` is `done` or `failed`), ask post (`ask_seq += 1`), timer (`timer_seq = ask_seq`), saves when anything changed. The stop branch keeps `ctx.disabled(NAME) or a.continuing` returning None and the no-state return, then applies the three stop rules of D3 in the order timer, first record, turn; the timer rule runs before `client.load_config()`; the other two return None when `client.load_config()` raises ConfigError or returns None.
      5. Extend tests/core/test_hook_board_gate.py (copy its fixtures `repo`, `board`, `decide`, `prompt`; read how it builds tool_result and stop actions) with tests: an ask post (op board_ask with output `{"id":"a-1f","state":"open"}`) then stop blocks with TIMER_MESSAGE once, the next stop allowed; an op timer after the ask means stop is not blocked by the timer rule; a timer before the ask does not count; a Bash `tld board ask f.json` result with output `a-9c` counts as an ask, `tld board ask-text f.json` does not; an add_issue_comment with body starting `<!-- tld-ask -->` counts and one without does not; the timer rule blocks without a configured board (use the `repo` fixture, not `board`); a second prompt after a record write resets the turn so a stop without a write blocks with TURN_MESSAGE once; a record write in the turn means no TURN_MESSAGE; `board_set` with data status `done` sets closed so later turns are not blocked; a state file written by the old hook (only the four old keys) still loads and behaves as before; the first-record rule still blocks once and wins over the turn rule in the same stop.
      6. Run `.venv/bin/python -m pytest tests/core/test_hook_board_gate.py tests/core/test_guard_markers.py -q`; all pass. Stop condition: if an existing test asserts the exact state file content, update only that assertion to include the new default fields and say so in your report under Deviations.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_hook_board_gate.py -q passes"
      - "grep -n 'TURN_MESSAGE' src/tld/guard/board_gate.py matches"
      - "grep -n 'TIMER_MESSAGE' src/tld/guard/board_gate.py matches"
      - ".venv/bin/python -m pytest tests/core -q passes"
  - id: p3-gate-adapter
    title: adapter mapping for ask and timer tools
    depends_on: [p2-gate-core]
    complexity: S
    touches:
      - adapters/claude/hooks/claude_adapter.py
      - adapters/claude/hooks/hooks.json
      - tests/adapters/claude/test_hook_board_gate_adapter.py
      - tests/adapters/claude/test_hooks_config.py
    brief: |
      Read first: adapters/claude/hooks/claude_adapter.py, adapters/claude/hooks/hooks.json, tests/adapters/claude/test_hook_board_gate_adapter.py, tests/adapters/claude/test_hooks_config.py.
      Implement plan section 3, D4 exactly (plan: docs/plans/67/plan.md). The core guard of the previous phase already understands the ops `board_ask`, `timer` and `add_issue_comment`.
      1. In claude_adapter.py next to BOARD_SET add `BOARD_ASK = re.compile(r"^mcp__.*tld-board.*__board_ask$")`, `TIMER = re.compile(r"^(ScheduleWakeup|CronCreate)$|^mcp__.*__(send_later|create_trigger)$")` and `ADD_COMMENT = re.compile(r"^mcp__.*__add_issue_comment$")`.
      2. In `to_action`, inside the PostToolUse branch after the BOARD_SET case, add the three cases of D4, each returning `Action("tool_result", project, cwd, op=<op>, args=dict(ti), output=output, session_id=_sid(payload))` with ops `board_ask`, `timer` and `add_issue_comment`. Other tools still return None.
      3. In hooks.json replace the PostToolUse matcher with `Bash|mcp__.*tld-board.*__(board_set|board_ask)|ScheduleWakeup|CronCreate|mcp__.*__(send_later|create_trigger|add_issue_comment)`.
      4. In tests/adapters/claude/test_hooks_config.py add rows to the matcher test list: ("board_gate.py", "mcp__plugin_tld_tld-board__board_ask", True), ("board_gate.py", "ScheduleWakeup", True), ("board_gate.py", "CronCreate", True), ("board_gate.py", "mcp__claude-code-remote__send_later", True), ("board_gate.py", "mcp__claude-code-remote__create_trigger", True), ("board_gate.py", "mcp__github__add_issue_comment", True). Keep every existing row; the row ("board_gate.py", "mcp__plugin_tld_tld-board__board_get", False) must still pass.
      5. In tests/adapters/claude/test_hook_board_gate_adapter.py add tests: each of the three new tool kinds becomes a tool_result action with the expected op, args and output; `mcp__plugin_tld_tld-board__board_get` and `mcp__github__push_files` still give None; an end-to-end test with run_script (copy the existing end-to-end test's setup): prompt `/tld:make-plan x`, a board_ask PostToolUse with response text `{"id":"a-1f"}`, then Stop is blocked with a reason containing `armed no timer`; after a send_later PostToolUse the Stop is not blocked by the timer rule.
      6. Run `.venv/bin/python -m pytest tests/adapters/claude -q`; all pass. Stop condition: if the matcher test fails on the existing rows after your change, stop with status=blocked and quote the failing row.
    acceptance:
      - ".venv/bin/python -m pytest tests/adapters/claude/test_hook_board_gate_adapter.py tests/adapters/claude/test_hooks_config.py -q passes"
      - "grep -n 'board_ask' adapters/claude/hooks/hooks.json matches"
      - ".venv/bin/python -m pytest tests/adapters -q passes"
  - id: p4-playbooks
    title: Board upkeep rules in the playbooks
    depends_on: [p1-items-cli]
    complexity: M
    touches:
      - playbooks/policies/status-board.md
      - playbooks/make-plan.md
      - playbooks/implement.md
      - playbooks/runtime.md
      - tests/core/test_board_record_wording.py
      - evals/baselines/default.json
    brief: |
      Read first: playbooks/policies/status-board.md, playbooks/make-plan.md (Setup and section 0), playbooks/implement.md (section 0, section 4 and the "Status record" section), playbooks/runtime.md (ask_human), tests/core/test_board_record_wording.py, tests/core/test_contracts.py.
      Implement plan section 3, D1 and D5 (plan: docs/plans/67/plan.md). Playbooks name runtime actions (`schedule_wakeup`, `watch_command`, `ask_human`) and never a runtime tool or model name.
      1. playbooks/policies/status-board.md: insert the section `## Board upkeep` with the exact text of D1 directly after the `## Where the board is` section; in the first bullet under `## When to write` that begins `The first record is written before the first ask`, replace the final full stop with ` (Board upkeep, rule 1).`
      2. playbooks/make-plan.md: directly after the `Rules that hold throughout:` paragraph (the one ending `Runtime actions: [runtime.md](runtime.md).`) add a blank line and the paragraph of D5 (`**Board upkeep is mandatory.** ...`). In Setup step 3 append the sentences: `The five items are in the first write. Mark each running when its step starts and done when it ends, writing the record at each change. The record never lists the plan's phases.` In section 0 step 3 append to the `ask_human` sentence: `Arm the ask timer in the same turn (Board upkeep, rule 5).`
      3. playbooks/implement.md: directly after its `Rules that hold throughout:` paragraph add the same D5 paragraph (link path `policies/status-board.md`). After the last bullet of section 0 step 4 (the one beginning `With tracking_issue, post Implementation started`) add this new numbered step, renumbering nothing: `4a. **Write the first record now** (Board upkeep, rules 1 and 2): kind run, status starting, items from tld board items <plan file> (every phase and final-review, all pending), written before the start question of step 5 and before any worker.` In section 4 at the bullet that starts a retry worker add the sentence `A revision, fix or second review worker gets its own item first (Board upkeep, rule 3).` Rewrite the `## Status record` section's first paragraph so that it says the first record is written at step 4a (not "before any worker starts"), its `phases` are the output of `tld board items <plan file>` plus every extra item added so far, and every record write is preceded by the `--check` of rule 3. Keep the needs_you list at the end unchanged.
      4. playbooks/runtime.md: in the attended branch of `ask_human`, replace `put its time in `next_check_at`` with `write its time into `last_event` as `timer <ISO time>` (`next_check_at` is null while the status is `waiting_user` and in every command record)`; read the line first and keep the rest of the sentence.
      5. tests/core/test_board_record_wording.py: add tests that (a) status-board.md has the heading `## Board upkeep` and the five bold rule names `First record first`, `Every item up front`, `Extra items at once`, `Every change is a write`, `Every ask has a timer`; (b) make-plan.md and implement.md contain `Board upkeep is mandatory`; (c) implement.md contains `tld board items` and `4a.`; (d) runtime.md does not contain `put its time in` followed by next_check_at on the same line and contains `timer <ISO time>`.
      6. Run `.venv/bin/python -m pytest tests -q`. The eval baseline test fails because the playbook hashes changed: run `python3 evals/run.py baseline --refresh-hashes` and then `python3 evals/run.py check-baseline` (exit 0). Say in the final commit message: `Refresh eval baseline hashes: board-upkeep wording only; no graded behaviour changes.` Do not edit CHANGELOG.md or docs/.
      Stop condition: if a contract test rejects a sentence (a runtime tool name or an unknown tld command), rewrite the sentence with the runtime action name; if it still fails, stop with status=blocked and quote the failure.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_board_record_wording.py tests/core/test_contracts.py tests/core/test_evals_baseline.py -q passes"
      - "grep -c 'Board upkeep' playbooks/policies/status-board.md playbooks/make-plan.md playbooks/implement.md matches a count of at least 1 for each file"
      - "python3 evals/run.py check-baseline exits 0"
      - ".venv/bin/python -m pytest tests -q passes"
  - id: p5-retire
    title: Docs, changelog and final checks
    depends_on: [p3-gate-adapter, p4-playbooks]
    complexity: S
    touches:
      - docs/architecture/hooks.md
      - docs/reference/profile-reference.md
      - CHANGELOG.md
    brief: |
      Read first: docs/architecture/hooks.md (the board-gate row at line 43 and the section `### board-gate`), docs/reference/profile-reference.md (the `hooks.board_gate.enabled` row), CHANGELOG.md (the `## [Unreleased]` section), docs/plans/67/plan.md (sections 3 and 6).
      This is the retirement phase. There is no ADR directory and no new doc, so the docs index docs/README.md needs no row.
      1. docs/architecture/hooks.md, section `### board-gate`: replace the intro sentence that starts `A session that one of them started must write its status record` so that it also says the gate blocks once per turn that wrote no record and once per ask that got no timer. In the `Three events` bullet list the new facts: a prompt starts a new turn; a successful `board_ask` (or a `tld board ask` command, or an issue comment that starts with `<!-- tld-ask -->`) counts an ask; a timer tool (ScheduleWakeup, CronCreate, send_later, create_trigger) arms the timer; a `board_set` whose data status is `done` or `failed` stops the turn rule for the rest of the session. In `State` list the six new fields. Replace `The block message` with the three messages of plan section 3 D3 (`MESSAGE`, `TURN_MESSAGE`, `TIMER_MESSAGE`) verbatim. In `Fails open` add that the timer rule needs no board and the other two rules do. Add to `Rejected alternatives`: blocking every stop without a limit, and blocking only the first turn. Update the table row at line 43 (`ending a turn before the status record is written, once`) to `ending a turn before the status record is written, or an ask before its timer is armed, once each`.
      2. docs/reference/profile-reference.md: extend the `hooks.board_gate.enabled` row's description with `and, once per turn without a record write or per ask without a timer`.
      3. CHANGELOG.md under `## [Unreleased]` (create the `### Added` and `### Changed` subheadings only if the section has none; follow the file's existing style): Added `tld board items`; Changed: `board-gate` also blocks a turn that wrote no record and an ask without a timer; the playbooks make-plan and implement carry a mandatory "Board upkeep" rule set; `runtime.md` no longer tells command records to set `next_check_at`. Never add a version heading.
      4. Run `.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` (exit 0), `python3 evals/run.py check-baseline` (exit 0) and `.venv/bin/python -m pytest tests -q` (passes).
      Stop condition: if the docs-index check reports an error, report it as `docs-changed:` is not applicable here and stop with status=blocked quoting the error.
    acceptance:
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - "grep -n 'TIMER_MESSAGE\\|armed no timer' docs/architecture/hooks.md matches"
      - "grep -n 'tld board items' CHANGELOG.md matches"
      - "python3 evals/run.py check-baseline exits 0"
      - ".venv/bin/python -m pytest tests -q passes"
```
