# Keep the board current: make-plan, implement and every ask timer

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Nothing new to type. A `/tld:make-plan` or `/tld:implement` session now puts its work on the board first: implement's very first record lists every manifest phase plus `final-review`, and a revision, a fix or a second review is added to the record before its worker starts. Every ask is followed in the same turn by a timer. A new `tld plan record-items` command builds and checks that item list. With `hooks.board_gate.enabled`, the `board-gate` hook also blocks the end of a turn once when an ask got no timer, and once when an ask, a worker start or stop, a pull request or a push left the record unwritten. This holds for every record-writing command, not only make-plan and implement.

**Scope:** A new policy section "Board upkeep" in the status-board policy, linked from the top of make-plan and implement; `tld plan record-items`; the `board-gate` guard and its Claude adapter mapping; a wording fix in `runtime.md` (the timer time goes into `last_event`, because `next_check_at` must be null while waiting). Not changed: the record schema, the board server, other playbooks' steps, and make-plan's record, which keeps its five planning items and does not list the plan's phases. The profile line that turns the hook on in this repository is a protected change and goes in its own pull request.

**Security:** The hook only blocks the end of a turn, each rule once per event; it never denies a tool call and never calls the board.

**Review focus:** the `board-gate` event model and its false positives (D3); the tool-name mapping in the adapter (D4); the mandatory `--check` before every implement record write and the five upkeep rules the playbooks must follow (D1, D2).

## 1. Goal

Make the board upkeep of `/tld:make-plan` and `/tld:implement` impossible to forget, as asked in [#67](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/67): the work is on the board as early as possible, every phase is on it from the first write, extra items such as `fix-<n>` are added as they appear, and every ask has its timer armed in the same turn. The owner chose three layers: clear playbook rules, a `tld` command that makes the item list mechanical, and a stronger `board-gate` hook.

## 2. Current state

- `playbooks/policies/status-board.md:68-82` says when to write a record, but never says that all items go in the first write or that late items (fix, revision) must be added. It is read by link, not at the top of the playbook.
- `playbooks/implement.md:446-455` ("Status record") sits at the very end of a 463-line playbook; the first record is described only there. `playbooks/make-plan.md:35-41` (Setup step 3) is one dense paragraph.
- `playbooks/runtime.md` (`ask_human`, attended branch) says to "put its time in `next_check_at`". `src/tld/board/record.py:50` (`NO_TIMER`) and `:310` reject `next_check_at` for status `waiting_user` and for every command record, so a make-plan card can never show its timer (found while writing this plan: the board answered `'next_check_at' must be null for a command record`).
- `src/tld/guard/board_gate.py` blocks one turn end per session until the first record write (`_evaluate`, lines 127-161). It has no notion of an ask, a timer, a worker or a push, and `a.continuing` lets a second stop through. `adapters/claude/hooks/claude_adapter.py:180-196` turns only `Bash` and `board_set` tool results into actions. `adapters/claude/hooks/hooks.json` registers the PostToolUse matcher `Bash|mcp__.*tld-board.*__board_set`.
- `.tld/toolkit.yaml` does not enable `hooks.board_gate`.

## 3. Design

The architect, test-architect and a plan reviewer read the first draft. The first draft had a per-turn "wrote no record" rule; it was replaced by the event model of D3 because the per-turn rule blocked chat-only turns, the "already running?" check, an unreachable board, and every turn after `pr_open`.

### D1. Policy: "Board upkeep" (`playbooks/policies/status-board.md`)

Insert a new section `## Board upkeep` directly after `## Where the board is` and before `## The write path`. Exact text:

```
## Board upkeep

The board is part of the work, not a report written after it. A run that is not on the board does not exist for the owner. These five rules hold for every playbook that writes a record and are mandatory for make-plan and implement:

1. **First record first.** Write the first record (`starting`) before any step that can take more than a minute. In make-plan and implement that is before the research, before the first worker and before the first ask, except the "already running?" check, which asks before any record exists (see "When to write"); never "after the plan is understood".
2. **Every item up front.** The first record lists every item the run will have. In implement that is every phase of the manifest plus `final-review`, printed by `tld plan record-items <plan file>`; never a short list that grows later.
3. **Extra items at once.** A revision (`<phase id>-rev<n>`), a fix (`fix-<n>`) and a second final review (`final-review-2`) become items in the same record write that starts them, before their worker exists. Before every record write of implement, save the record to a scratch file and run `tld plan record-items <plan file> --check <record file>` with one `--add <id>=<title>` for every extra item so far; it must exit 0.
4. **Every change is a write.** Every state change, every check-in, every ask and every answer is a record write, also when only `updated_at` changes. A session that asks, starts or stops a worker, opens a pull request or pushes without writing the record afterwards has forgotten the board.
5. **Every ask has a timer.** In the same turn that posts an ask: write the record with `needs_you` (no record during the "already running?" check), show the ask in the conversation (attended), start the watch (attended, with a board) and arm `schedule_wakeup` (60 minutes with the watch, else 10 minutes). Write the timer's time into `last_event` as `timer <ISO time>`: `next_check_at` must be null while the status is `waiting_user` and in every command record. Never end the turn of an ask without the timer. On every wake cancel the armed timer before arming the next one, and cancel it when the ask closes.
```

Also, in `## When to write`, the second bullet begins `The first record is written before the first ask`: replace its final full stop with ` (Board upkeep, rule 1).`

### D2. `tld plan record-items` (`src/tld/plan/record_items.py`)

```
tld plan record-items PLAN [--add ID[=TITLE]]... [--check RECORD]
```

`PLAN` is a plan file with an implementation manifest. Load it exactly as `tld.plan.manifest.main` does (`extract_manifest`, then `yaml.safe_load`); a missing file, a missing manifest, invalid YAML, a manifest that is not a mapping or has no `phases` list of mappings with a string `id`, `title` and list `depends_on` prints `tld plan record-items: <message>` to stderr and exits 2. The module imports nothing from `tld.board`.

- Without `--check` it prints one JSON list (`json.dumps`, one line) of run-record items: one per manifest phase in manifest order, then `final-review` (title `Final review`, `depends_on` every phase id, `complexity` null), then one per `--add` in the order given. A phase item is `{"id", "title", "depends_on", "complexity", "state": "pending", "session": null, "branch": null, "started_at": null, "finished_at": null}` with `title`, `depends_on` and `complexity` copied from the phase (`complexity` is `"S"`, `"M"` or null). An added item has the same shape with `depends_on` `[]`, `complexity` null and the title after the first `=` (the id when there is no `=` or the text after it is empty). Exit 0.
- An id must match `^[a-z0-9][a-z0-9-]{0,63}$` and be unique among all items (manifest phases, `final-review`, added); otherwise `tld plan record-items: <message>` on stderr and exit 2.
- With `--check RECORD` (`RECORD` is a status record JSON file, or `-` for stdin) it prints only the verdict: for every expected id (the same list as above) that is not the `id` of an entry of the record's `phases`, one line `items: missing <id>` on stdout, and exit 1; otherwise `items: ok (<n> expected)` and exit 0. Extra ids in the record are fine. A record that cannot be read, is not JSON, has no `phases` list, or has a `phases` entry that is not a mapping with a string `id`: `tld plan record-items: <message>` on stderr and exit 2 (never exit 1, which means "missing").

It is registered as `("plan", "record-items")` in `src/tld/cli.py` and documented in `docs/reference/cli.md`. It lives in `tld.plan` because it parses the manifest and owns the extra-item naming next to `branch-name --rev/--fix`.

### D3. `board-gate` rules (`src/tld/guard/board_gate.py`)

Still opt-in (`hooks.board_gate.enabled`) and still a nudge. It applies to every command in `RECORD_COMMANDS`. The state file gains these fields (a missing, wrongly typed or negative value loads as the default): `write_seq` (int, 0), `dirty_seq` (int, 0), `dirty_blocked_seq` (int, 0), `ask_seq` (int, 0), `timer_seq` (int, 0), `timer_blocked_seq` (int, 0). The state's `opened_at` is refreshed whenever the state is saved, so a long run is not discarded after 24 hours of activity.

Events:

- **prompt** (`UserPromptSubmit`): unchanged (a prompt of a record-writing command opens the state).
- **tool_result**, each saved when it changed the state:
  - a record write (`is_record_write`, unchanged): `written` becomes true and `write_seq = dirty_seq`.
  - an ask post: `ask_seq += 1` and `dirty_seq += 1`. An ask post is any of: `op == "board_ask"` whose output is JSON object with a string `id` starting with `a-`; a shell command matching `\bboard\s+ask(?![-\w])` whose output has a line that is exactly an id (`a-` then hex digits) or starts with the ask marker; `op == "ask_comment"` whose `args["body"]` is a string that starts with the ask marker (`tld.board.inbox.MARKER`, the text `<!-- tld-ask -->`), no text before it.
  - a timer: `op == "timer"` sets `timer_seq = ask_seq`.
  - any other change of the run: `dirty_seq += 1` for `op` in `worker_start`, `worker_stop`, `pr_create`, and for a shell command matching `\bgit\s+push\b` or `\bgh\s+pr\s+create\b`.
- **stop**: `ctx.disabled(NAME)` and "no state" return `None` as today. `a.continuing` is no longer a reason to allow: every rule below blocks once per sequence number, so a chain of stops ends after at most three blocks. In this order the first rule that fires blocks and records that it did:
  1. the timer rule: `ask_seq > timer_seq and timer_blocked_seq < ask_seq` → `timer_blocked_seq = ask_seq`, `TIMER_MESSAGE`. It needs no configured board.
  2. only with a configured board (`client.load_config()` not `None`): the first-record rule, unchanged: `written` false and `blocked` false → `blocked = true`, `MESSAGE`.
  3. only with a configured board and only when `written` is true (a session that never wrote a record is covered by rule 2 alone, so the "already running?" check is not blocked three times): the dirty rule: `dirty_seq > write_seq and dirty_blocked_seq < dirty_seq` → `dirty_blocked_seq = dirty_seq`, `DIRTY_MESSAGE`.

A state file is still discarded after 24 hours without any save. A plain chat turn changes nothing, so it never blocks.

Messages (the guard runner puts `tld board-gate: ` in front):

- `MESSAGE`: unchanged.
- `DIRTY_MESSAGE`: `this session was started by /tld:{command} and has changed things since its last status record: it asked a question, started or stopped a worker, opened a pull request or pushed. Write the record now: use the board_set tool, or when that tool is missing or fails run "tld board client set <id> - " with the record on stdin. Set updated_at, the state of every item that changed, and every extra item (a fix, a revision, a second review) that started. If the board cannot be reached, say so in your final reply and stop. If the playbook says to write no record yet, say so and stop. This check blocks only once per change.`
- `TIMER_MESSAGE`: `this session posted an ask and armed no timer after it. Arm it now with schedule_wakeup (60 minutes when the answer watch runs, else 10 minutes), write its time into last_event as "timer <ISO time>" and write the record, unless the playbook says to write no record yet. If this run is unattended (no person started it), a timer is not needed: say so and stop. This check blocks only once per ask.`

Rejected: a "wrote no record this turn" rule (false positives, see the top of this section); closing the gate on a final status (the hook cannot read the record that `tld board client set -` takes on stdin); reading the board from the hook (needs the network and a token inside a hook, see `docs/architecture/hooks.md`); a staleness timer (misses "asked, then no write").

### D4. Adapter mapping (`adapters/claude/hooks/claude_adapter.py`, `hooks.json`)

`to_action` (PostToolUse) gains these mappings after the `board_set` case, each `Action("tool_result", project, cwd, op=<op>, args=dict(ti), output=<result text>, session_id=_sid(payload))`. A tool response that is a mapping with `isError` or `is_error` true gives `None` for all of them.

| tool name pattern | op |
|---|---|
| `^mcp__.*tld-board.*__board_ask$` | `board_ask` |
| `^(ScheduleWakeup\|CronCreate)$` or `^mcp__.*__(send_later\|create_trigger)$` | `timer` |
| `^mcp__.*__(add_issue_comment\|issue_write)$` | `ask_comment` |
| `^mcp__.*__create_session$` | `worker_start` |
| `^mcp__.*__archive_session$` | `worker_stop` |
| `^mcp__.*__create_pull_request$` | `pr_create` |

The PostToolUse matcher in `hooks.json` becomes `Bash|mcp__.*tld-board.*__(board_set|board_ask)|ScheduleWakeup|CronCreate|mcp__.*__(send_later|create_trigger|add_issue_comment|issue_write|create_session|archive_session|create_pull_request)`. The runtime tool names live only in the adapter; the core guard sees only the ops. These names were checked against this runtime's tool list while planning (`ScheduleWakeup`, `CronCreate`, `mcp__claude-code-remote__send_later`, `mcp__claude-code-remote__create_trigger`, `mcp__claude-code-remote__create_session`, `mcp__claude-code-remote__archive_session`, `mcp__github__add_issue_comment`, `mcp__github__issue_write`, `mcp__github__create_pull_request`).

### D5. Playbook edits (`make-plan.md`, `implement.md`, `runtime.md`)

- Both playbooks get, directly after their `Rules that hold throughout:` paragraph, this paragraph: `**Board upkeep is mandatory.** Follow "Board upkeep" in [policies/status-board.md](policies/status-board.md): the first record before any other work, every item in it, extra items added the moment they start, a record write after every change, and a timer armed in the same turn as every ask.`
- `make-plan.md`: Setup step 3 gets the sentences `The five items are in the first write. Mark each running when its step starts and done when it ends, writing the record at each change. The record never lists the plan's phases.` Section 0 step 3 and the "Is it already being planned?" paragraph each get the sentence `Arm the ask timer in the same turn (Board upkeep, rule 5), except that this check writes no record.`
- `implement.md`: after section 0 step 4 a new step `4a` (text in p4) writes the first record; section 1's `Resumed` bullet runs `tld plan record-items <plan file> --check <live record file>` and adds every missing item; section 2's ledger sentence names the items `final-review` and `final-review-2` next to `fix-<n>` and `<phase id>-rev<n>`; section 4 step 8 (requested changes) and section 5's `changes` bullet each get the sentence `Add the item first (Board upkeep, rule 3).`; the `Status record` section is rewritten to point to `tld plan record-items`.
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

- **False positives of the dirty rule.** A session that pushes or asks without a board (an unreachable board) is blocked once per change; the message says to report the board and stop. A worker that finds the hook blocking an unrelated phase reports `status=blocked` with the message.
- **No playbook behaviour test.** Playbook wording cannot be unit-tested; p4's wording tests pin the exact text, and no eval proves that a model follows it. The owner can run `python3 evals/run.py run --task make-plan-small --repeats 1` after the merge.
- **Evals baseline.** p4 refreshes the baseline hashes only; the commit message says the change adds board-upkeep rules and affects no graded behaviour.
- **Unattended runs.** An unattended run that asks gets one TIMER block, and the message tells it to say so and stop.
- **Changes after the final record.** A `review`, `land` or `setup` session that pushes, or an implement session that archives its workers after its last record, gets one DIRTY block per change; the message lets it write the record or say why not and stop.
- **Lost updates.** The state file is replaced atomically, but two hooks that run at the same moment can still lose one update; the cost is one missed or one extra block.
- **Runtime tool names.** If the runtime renames a timer, ask or worker tool, only the table and matcher in D4 change.
- **No mutants.** `tests/mutation/mutants.yaml` is not extended; the unit tests of D3 and D2 carry the state machine and the verdict.
- **Plugin update.** The hook behaviour reaches sessions only after the plugin is released and updated; until then the playbook rules apply alone.
- **How a worker recognises a wrong brief.** If a test outside the brief fails for a reason the brief does not mention, the worker stops with `status=blocked` and quotes the failing test.

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
  - .venv/bin/python -m pytest
final_checks:
  - "`tld plan deviations check --file docs/plans/67/deviations.md --plan docs/plans/67/plan.md --all` exits 0"
  - "`tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
  - "`python3 evals/run.py check-baseline` exits 0"
  - "the changelog has entries under docs.changelog.section and no version heading"
phases:
  - id: p1-items-cli
    title: tld plan record-items command
    depends_on: []
    complexity: S
    touches:
      - src/tld/plan/record_items.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_plan_record_items.py
    brief: |
      Read first: docs/reference/cli.md, src/tld/plan/manifest.py (extract_manifest and main), src/tld/plan/phases.py (how a plan command registers its prefix and parses arguments).
      Implement the command exactly as plan section 3, D2 specifies (plan: docs/plans/67/plan.md).
      1. Create src/tld/plan/record_items.py: a module docstring with the usage line and the exit codes (0 ok, 1 missing items, 2 usage or unreadable input), `from __future__ import annotations`, stdlib plus yaml only, no import from tld.board, and `main(argv: list[str] | None = None) -> int` using argparse with `plan`, `--add` (action append, default []) and `--check`. Load the manifest the way tld.plan.manifest.main does: `extract_manifest(text)` then `yaml.safe_load`. Every unreadable or malformed input of D2 prints `tld plan record-items: <message>` to stderr and returns 2.
      2. Build the items with one helper `build_items(manifest, adds) -> list[dict]`: phase items in manifest order, then `final-review`, then the added ones; every item has exactly the keys id, title, depends_on, complexity, state ("pending"), session, branch, started_at, finished_at. Validate every id with `re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", id)` and uniqueness; raise ValueError with the message `invalid item id '<id>'` or `duplicate item id '<id>'`, which main prints as in step 1 and returns 2.
      3. `--add ID[=TITLE]`: split on the first `=`; the title is the text after it, and the id when there is no `=` or that text is empty.
      4. Without --check print `json.dumps(items)` and return 0. With --check read the record JSON from the file, or from stdin when the value is `-`. For each expected id that no `phases[].id` equals print `items: missing <id>` to stdout; return 1 when any is missing, else print `items: ok (<n> expected)` and return 0. A record that cannot be read, is not a JSON object, has no `phases` list, or has a `phases` entry that is not a dict with a string `id` returns 2 with the stderr message of step 1, never 1.
      5. Register it in src/tld/cli.py in COMMANDS after the `("plan", "phase-status")` entry, in the form of its neighbours: `("plan", "record-items"): ("tld.plan.record_items", (), "print the run record's items from a plan, or check a record lists them all")`.
      6. Add a row for `tld plan record-items PLAN [--add ID[=TITLE]]... [--check RECORD]` to the table in docs/reference/cli.md after the `tld plan phase-status` row, module `tld.plan.record_items`, with a one-sentence description of both modes and the exit codes. Do not edit CHANGELOG.md (the last phase does) or docs/README.md.
      7. Create tests/core/test_plan_record_items.py with pytest functions and a fixture writing a small plan file (a `## Implementation manifest` heading followed by a yaml block with plan_slug `x` and two phases p1-a (S, depends_on []) and p2-b (M, depends_on [p1-a])) into tmp_path. Tests: the whole printed list equals the exact expected JSON (p1-a, p2-b, final-review in that order, state pending, the exact key set, final-review depends_on both phase ids and complexity null); `--add fix-1=Fix one` appends an item titled `Fix one`; `--add fix-1` uses the id as title; `--add fix-1=a=b` titles it `a=b`; `--add fix-1=` titles it `fix-1`; duplicate `--add fix-1 --add fix-1`, `--add final-review` and `--add p1-a` exit 2; id `Bad_Id` and id `=T` exit 2; a missing plan, a plan without a manifest and a manifest without phases exit 2; `--check` exits 1 and prints `items: missing final-review` for a record whose phases list only p1-a and p2-b; exits 0 with `items: ok (3 expected)` when all three are present; extra ids in the record are accepted; non-JSON record, a JSON list, a record without `phases`, a phases entry that is not a dict, a phases entry without `id` and an unreadable record path each exit 2; a 64-character id is accepted and a 65-character id exits 2; a manifest whose phase id is invalid, duplicated or `final-review` exits 2; a record read from stdin works (use subprocess with `cli/tld plan record-items ...` for one test to prove the registration).
      8. Run `.venv/bin/python -m pytest tests/core/test_plan_record_items.py tests/core/test_cli_reference.py tests/core/test_contracts.py -q`; all pass. Stop condition: if test_cli_reference demands a different row format, copy the format of the neighbouring row; if it still fails, stop with status=blocked and quote the failure.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_plan_record_items.py -q passes"
      - ".venv/bin/python -m pytest tests/core/test_cli_reference.py tests/core/test_contracts.py -q passes"
      - ".venv/bin/python cli/tld plan record-items docs/plans/67/plan.md | .venv/bin/python -c 'import json,sys; assert json.load(sys.stdin)[-1][\"id\"]==\"final-review\"' exits 0"
  - id: p2-gate-core
    title: board-gate ask, timer and dirty rules
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/board_gate.py
      - tests/core/test_hook_board_gate.py
    brief: |
      Read first: src/tld/guard/board_gate.py, tests/core/test_hook_board_gate.py, docs/architecture/hooks.md (the board-gate section only), src/tld/guard/action.py, src/tld/board/inbox.py (the MARKER constant at line 60).
      Implement plan section 3, D3 exactly (plan: docs/plans/67/plan.md). Do not edit docs/architecture/hooks.md (the last phase does).
      1. In src/tld/guard/board_gate.py extend `_load` and `_save`: `_load` returns the four existing keys plus `write_seq`, `dirty_seq`, `dirty_blocked_seq`, `ask_seq`, `timer_seq`, `timer_blocked_seq`, each an int that is not a bool and is at least 0, else 0. Every `_save` also sets `opened_at` to `time.time()` (the TTL then counts from the last activity) and writes the file atomically: write `<name>.tmp` next to it, then `os.replace` it onto the state file. The state a prompt opens sets the six ints to 0.
      2. Add `from tld.board.inbox import MARKER as ASK_MARKER`, `ASK_COMMAND = re.compile(r"\bboard\s+ask(?![-\w])")`, `ASK_ID_LINE = re.compile(r"^a-[0-9a-f]+$")`, `GIT_PUSH = re.compile(r"\bgit\s+push\b|\bgh\s+pr\s+create\b")`, `DIRTY_OPS = ("worker_start", "worker_stop", "pr_create")`, and the constants `DIRTY_MESSAGE` and `TIMER_MESSAGE` with the exact texts of D3.
      3. Add `is_ask_post(action: Action) -> bool` implementing the three cases of D3, only for `action.kind == "tool_result"` and never raising (a JSON parse error, a non-dict, a None output or a non-string body gives False). Add `is_timer(action) -> bool` (kind `tool_result` and `op == "timer"`) and `is_change(action) -> bool` (kind `tool_result` and `op` in DIRTY_OPS, or a command matching GIT_PUSH).
      4. In `_evaluate`: the tool_result branch loads the state once and applies, in this order and each independently: record write (`written = True`, `write_seq = dirty_seq`), ask post (`ask_seq += 1`, `dirty_seq += 1`), timer (`timer_seq = ask_seq`), change (`dirty_seq += 1`); it saves when anything changed. The stop branch keeps `ctx.disabled(NAME)` returning None and the no-state return, drops the `a.continuing` early return, then applies the three stop rules of D3 in the order timer, first record, dirty; the timer rule runs before `client.load_config()`; the other two return None when `client.load_config()` raises ConfigError or returns None, and the dirty rule also returns None while `state["written"]` is false. A record write always sets `write_seq = dirty_seq`, also when `written` was already true.
      5. Update the existing tests that rely on `a.continuing` allowing a stop: a stop with `continuing=True` after a block now evaluates the next rule; adjust only those assertions and name each in your report under Deviations.
      6. Extend tests/core/test_hook_board_gate.py (copy its fixtures `repo`, `board`, `decide`, `prompt`; read how it builds tool_result and stop actions) with tests: an ask post (op board_ask, output `{"id":"a-1f","state":"open"}`) then stop blocks with TIMER_MESSAGE once and the next stop is not blocked by it; ask, timer, ask blocks again (`ask_seq == 2`); an op timer after the ask means no TIMER_MESSAGE; a timer before the ask does not count; the timer rule blocks without a configured board (use `repo`, not `board`); a Bash `tld board ask f.json` result with output `a-9c` counts as an ask, `tld board ask-text f.json` and `grep 'board ask' x` do not; an op ask_comment with body starting with the marker counts, one with text before the marker or a non-string body does not; a parametrized `test_is_ask_post_rejects` with: board_ask output that is non-JSON, a JSON list, None, an error text, an `id` that is not a string, an `id` without `a-`; none of them raises; with a configured board, op worker_start, worker_stop, pr_create and a Bash `git push origin x` each make the stop block with DIRTY_MESSAGE once, and a record write after the change clears it; a change after the record write blocks again; a plain stop with no change after the first record write is not blocked; the timer rule precedes the first-record rule (an ask with no record gives TIMER_MESSAGE, then MESSAGE on the next stop, then DIRTY_MESSAGE); a state file with only the four old keys loads with the six new ones at 0; bad types (`"ask_seq": true`, `-1`, `"x"`) load as 0; `_save` round-trips all ten keys and refreshes `opened_at`; the first-record rule still blocks once; with no record ever written an ask then stop gives TIMER_MESSAGE and then MESSAGE but never DIRTY_MESSAGE; a change, a first record write, another change, a second write: the second write clears the block; a Bash `gh pr create` result counts as a change; a half-written (truncated) state file loads as no state and a `_save` leaves no `.tmp` file; `test_stop_chain_ends`: with a configured board, an ask, a worker_start and no record, successive stops with `continuing=True` return TIMER_MESSAGE, MESSAGE, DIRTY_MESSAGE, then None; ask, record write, timer, stop gives no block; an ask followed by a record write clears the dirty rule; a second prompt does not reset the six counters; the state survives when it was saved 23h59m ago and re-saved, and is discarded after 24h without a save (patch `time.time`); boundary tests that fail on `>=` for `ask_seq > timer_seq` and `dirty_seq > write_seq` (equal values do not block); more ask-detection negatives: a Bash `tld board ask f.json` with error output and no id line, `grep 'board ask' x` with an id-like output line, an ask_comment body with leading whitespace before the marker, output lines `a-` and `a-xyz`.
      7. Run `.venv/bin/python -m pytest tests/core/test_hook_board_gate.py tests/core/test_guard_markers.py -q`; all pass. Stop condition: if an existing test asserts the exact state file content, update only that assertion to include the new default fields and say so in your report under Deviations.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_hook_board_gate.py -q passes"
      - ".venv/bin/python -m pytest tests/core/test_hook_board_gate.py::test_is_ask_post_rejects -q passes"
      - ".venv/bin/python -m pytest tests/core -q passes"
  - id: p3-gate-adapter
    title: adapter mapping for ask, timer and worker tools
    depends_on: [p2-gate-core]
    complexity: S
    touches:
      - adapters/claude/hooks/claude_adapter.py
      - adapters/claude/hooks/hooks.json
      - tests/adapters/claude/test_hook_board_gate_adapter.py
      - tests/adapters/claude/test_hooks_config.py
    brief: |
      Read first: adapters/claude/hooks/claude_adapter.py, adapters/claude/hooks/hooks.json, tests/adapters/claude/test_hook_board_gate_adapter.py, tests/adapters/claude/test_hooks_config.py.
      Implement plan section 3, D4 exactly (plan: docs/plans/67/plan.md). The core guard of the previous phase already understands the ops `board_ask`, `timer`, `ask_comment`, `worker_start`, `worker_stop` and `pr_create`.
      1. In claude_adapter.py next to BOARD_SET add one compiled regex per row of the D4 table (`BOARD_ASK`, `TIMER`, `ASK_COMMENT`, `WORKER_START`, `WORKER_STOP`, `PR_CREATE`) and a tuple `NEW_OPS` pairing each with its op.
      2. In `to_action`, inside the PostToolUse branch, make the existing BOARD_SET case also return None when `payload.get("tool_response")` is a dict whose `isError` or `is_error` is true (a failed write is not a record write). Then, after the BOARD_SET case, add a loop over NEW_OPS: for the first regex that matches the tool name, return None when `payload.get("tool_response")` is a dict whose `isError` or `is_error` is true, else return `Action("tool_result", project, cwd, op=<op>, args=dict(ti), output=output, session_id=_sid(payload))`. Other tools still return None.
      3. In hooks.json replace the PostToolUse matcher with `Bash|mcp__.*tld-board.*__(board_set|board_ask)|ScheduleWakeup|CronCreate|mcp__.*__(send_later|create_trigger|add_issue_comment|issue_write|create_session|archive_session|create_pull_request)`.
      4. In tests/adapters/claude/test_hooks_config.py add rows to the matcher test list, True for: `mcp__plugin_tld_tld-board__board_ask`, `ScheduleWakeup`, `CronCreate`, `mcp__claude-code-remote__send_later`, `mcp__claude-code-remote__create_trigger`, `mcp__github__add_issue_comment`, `mcp__github__issue_write`, `mcp__claude-code-remote__create_session`, `mcp__claude-code-remote__archive_session`, `mcp__github__create_pull_request`; and False for: `CronDelete`, `ScheduleWakeupX`, `mcp__plugin_tld_tld-board__board_answers`, `mcp__github__create_issue`, `mcp__github__add_issue_comment_x`. Keep every existing row. Add one test asserting the PostToolUse matcher of board_gate.py in hooks.json equals the D4 string exactly.
      5. In tests/adapters/claude/test_hook_board_gate_adapter.py add tests: each of the six op kinds becomes a tool_result action with the expected op, args and output, using the real MCP result shape (`{"content": [{"type": "text", "text": ...}]}`, as the existing real-result test does); a tool_response with `isError` true gives None for each of the six; `CronDelete` and `mcp__plugin_tld_tld-board__board_get` give None; an end-to-end test with run_script (copy the existing end-to-end test's setup, with the board environment set as that test does): prompt `/tld:make-plan x`, a board_ask PostToolUse with response text `{"id":"a-1f"}`, then Stop is blocked with a reason containing `armed no timer`; after a send_later PostToolUse the Stop is no longer blocked by the timer rule; a second end-to-end case: a `git push` Bash PostToolUse then Stop is blocked with a reason containing `changed things`, then a successful board_set PostToolUse and the Stop is allowed; a failed (`isError` true) board_set changes neither the first-record rule nor the dirty rule (Stop still blocked), a failed board_ask leaves no ask counted (Stop not blocked by the timer rule) and a failed send_later leaves the timer unarmed after an ask (Stop still blocked by the timer rule). PostToolUseFailure is not registered in hooks.json, so Claude Code does not send failed calls to the gate; the isError check is a second defence.
      6. Run `.venv/bin/python -m pytest tests/adapters/claude -q`; all pass. Stop condition: if the matcher test fails on an existing row after your change, stop with status=blocked and quote the failing row.
    acceptance:
      - ".venv/bin/python -m pytest tests/adapters/claude/test_hook_board_gate_adapter.py tests/adapters/claude/test_hooks_config.py -q passes"
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
      Read first: playbooks/policies/status-board.md, playbooks/make-plan.md (Setup and section 0), playbooks/implement.md (sections 0, 1, 2, 4 step 8, 5 and the "Status record" section), playbooks/runtime.md (ask_human), tests/core/test_board_record_wording.py, tests/core/test_contracts.py.
      Implement plan section 3, D1 and D5 (plan: docs/plans/67/plan.md). Playbooks name runtime actions (`schedule_wakeup`, `watch_command`, `ask_human`) and never a runtime tool or model name.
      1. playbooks/policies/status-board.md: insert the section `## Board upkeep` with the exact text of the D1 code block directly after the `## Where the board is` section and before `## The write path`. In the second bullet under `## When to write` (it begins `The first record is written before the first ask`) replace the final full stop with ` (Board upkeep, rule 1).`
      2. playbooks/make-plan.md: directly after the `Rules that hold throughout:` paragraph (the one ending `Runtime actions: [runtime.md](runtime.md).`) add a blank line and the D5 paragraph `**Board upkeep is mandatory.** ...` verbatim. In Setup step 3 append the three sentences of D5. In section 0 step 3, at the end of the sentence that begins `If a decision is genuinely the human's`, and at the end of the paragraph `**Is it already being planned?**`, append the D5 sentence `Arm the ask timer in the same turn (Board upkeep, rule 5), except that this check writes no record.`
      3. playbooks/implement.md: directly after its `Rules that hold throughout:` paragraph add the D5 paragraph (link path `policies/status-board.md`). After the last bullet of section 0 step 4 (the one beginning `With tracking_issue, post Implementation started`) add this new numbered item, renumbering nothing: `4a. **Write the first record now** (Board upkeep, rules 1 and 2): kind run, status starting, phases from tld plan record-items <plan file> (every phase and final-review, all pending), written before the start question of step 5 and before any worker.` In section 1, at the end of the `Resumed` bullet add: `Then save the live record to a scratch file and run tld plan record-items <plan file> --check <record file>; add every item it reports as missing, and every extra item the ledger lists, before the next record write.` In section 2 add to the sentence that begins `Keep a **ledger**` the clause: `the extra items are named final-review-2, fix-<n> and <phase id>-rev<n> (Board upkeep, rule 3)`. At section 4 step 8, after the sentence `On requested changes start a worker on`, and in section 5 at the start of the `changes` bullet, add the sentence `Add the item first (Board upkeep, rule 3).` Rewrite the first paragraph of the `## Status record` section so that it says the first record is written at step 4a (not "before any worker starts"), its `phases` are the output of `tld plan record-items <plan file>` plus every extra item added so far, and every record write is preceded by the `--check` of rule 3. Keep the needs_you list at the end unchanged.
      4. playbooks/runtime.md: in the attended branch of `ask_human`, replace the words ``put its time in `next_check_at` `` with ``write its time into `last_event` as `timer <ISO time>` (`next_check_at` is null while the status is `waiting_user` and in every command record) ``; read the lines first and keep the rest of the sentence.
      5. tests/core/test_board_record_wording.py: add tests that (a) status-board.md contains the heading `## Board upkeep` and the five bold rule names `First record first.`, `Every item up front.`, `Extra items at once.`, `Every change is a write.` and `Every ask has a timer.`, and the heading comes after `## Where the board is` and before `## The write path`; (b) make-plan.md and implement.md contain the exact paragraph `**Board upkeep is mandatory.**`; (c) implement.md contains `tld plan record-items`, `4a.`, `final-review-2` and `--check`; (d) runtime.md contains the exact replacement sentence of step 4 and does not contain ``put its time in `next_check_at` ``; (e) status-board.md contains `(Board upkeep, rule 1).`; (f) make-plan.md contains `except that this check writes no record` twice.
      6. Run `.venv/bin/python -m pytest tests -q`. The eval baseline test fails because the playbook hashes changed: run `python3 evals/run.py baseline --refresh-hashes` and then `python3 evals/run.py check-baseline` (exit 0). Say in the final commit message: `Refresh eval baseline hashes: board-upkeep wording only; no graded behaviour changes.` Do not edit CHANGELOG.md or docs/.
      Stop condition: if a contract test rejects a sentence (a runtime tool name or an unknown tld command), rewrite the sentence with the runtime action name; if it still fails, stop with status=blocked and quote the failure.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_board_record_wording.py tests/core/test_contracts.py tests/core/test_evals_baseline.py -q passes"
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
      - tests/core/test_hooks_doc_board_gate.py
    brief: |
      Read first: docs/architecture/hooks.md (the table row at line 43 and the section `### board-gate`), docs/reference/profile-reference.md (the `hooks.board_gate.enabled` row), CHANGELOG.md (the `## [Unreleased]` section), docs/plans/67/plan.md (sections 3 and 6), src/tld/guard/board_gate.py (the message constants).
      This is the retirement phase. There is no ADR directory and no new doc, so the docs index docs/README.md needs no row.
      1. docs/architecture/hooks.md, section `### board-gate`: replace the intro sentence that contains `session that one of them started must write its status record` so that it also says the gate blocks once per ask that got no timer and once per change (an ask, a worker start or stop, a pull request, a push) that left the record unwritten, and that it applies to every record-writing command. In the `Three events` bullet replace the matcher text with the D4 matcher string and list the new facts: a successful `board_ask`, a `tld board ask` command, or an issue comment or issue body that starts with `<!-- tld-ask -->` counts an ask; a timer tool (ScheduleWakeup, CronCreate, send_later, create_trigger) arms the timer; create_session, archive_session, create_pull_request and `git push` count a change; a record write clears the changes before it. In `State` list the six new fields and say `opened_at` is refreshed on every save. Replace `The block message` with the three messages of plan section 3 D3 (`MESSAGE`, `DIRTY_MESSAGE`, `TIMER_MESSAGE`) verbatim. In `Fails open` add that the timer rule needs no board and the other two rules do, and that `stop_hook_active` no longer lets a stop through because every rule blocks once per sequence. Add to `Rejected alternatives`: a per-turn "wrote no record" rule, closing the gate on a final status, and a staleness timer. In the table row at line 43 replace the event column text with `UserPromptSubmit, PostToolUse (Bash, the board_set, board_ask, timer, worker, pull-request and issue-comment tools), Stop (opt-in)` and the third column with `ending a turn before the status record is written, or after an ask, a worker change, a pull request or a push left it unwritten, or an ask before its timer is armed, once each`.
      2. docs/reference/profile-reference.md: replace the description cell of the `hooks.board_gate.enabled` row with `Opt in to the `board-gate` Stop hook: a session that a record-writing tld command started cannot end its turn before it has written its status record once, after an ask, a worker start or stop, a pull request or a push left the record unwritten, or after an ask without an armed timer; each rule blocks once per event. See [hooks.md](../architecture/hooks.md)`.
      3. CHANGELOG.md under `## [Unreleased]` (create the subheadings only when the section has none; follow the file's existing style): Added `tld plan record-items`; Changed: `board-gate` also blocks an ask without a timer and a change left unwritten; the playbooks make-plan and implement carry a mandatory "Board upkeep" rule set; `runtime.md` no longer tells command records to set `next_check_at`. Never add a version heading.
      4. Create tests/core/test_hooks_doc_board_gate.py with one test that reads docs/architecture/hooks.md and asserts that the text of `board_gate.MESSAGE`, `board_gate.DIRTY_MESSAGE` and `board_gate.TIMER_MESSAGE` (formatted with `command` left as the literal `{command}` where the constant has it) each appears in the doc verbatim; adjust the doc's quoting so the test passes.
      5. Run `.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` (exit 0), `python3 evals/run.py check-baseline` (exit 0) and `.venv/bin/python -m pytest tests -q` (passes).
      Stop condition: if the docs-index check exits non-zero, stop with status=blocked and quote the error.
    acceptance:
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - ".venv/bin/python -m pytest tests/core/test_hooks_doc_board_gate.py -q passes"
      - "python3 evals/run.py check-baseline exits 0"
      - ".venv/bin/python -m pytest tests -q passes"
```
