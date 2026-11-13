# Plan: subscription usage page on the board (Standard vs Max)

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Open the board and click `Usage` (page `#usage`). For the 5-hour window and the weekly window you see two bars, one against the Standard limit and one against the Max limit (Max = 5x Standard), plus a 30-day history of finished windows drawn in Standard percent with a line at 100% (the Standard limit). A verdict line per window kind says whether Standard would have been enough or Max earned its price. Set `TLD_BOARD_PLAN=max` (or `standard`) on the board host once; readings then arrive by themselves when any tld command ends, and every 2 hours if you schedule `/tld:usage`.

**Scope:** New board table and endpoint for rate-limit readings, a `tld board usage` command that sends one, the page, a new runtime action `read_usage()`, a final-write step in the status-board policy, and the unattended command `/tld:usage`. Not changed: status records, asks, the other commands, the MCP tools, API-token cost (this is subscription use only).

**Security:** One new endpoint that sessions may write and only the owner may read; strict input limits (4 KiB body, window times checked against the server clock, 50 samples per window, 20,000 rows).

**Performance:** The scheduled `/tld:usage` runs at the fast level and spends a small amount of the same subscription quota every 2 hours; opt in.

**Review focus:** raw samples converted on read, not on write (section 3.1); the unit of `utilization` is believed to be a fraction and is pinned by a manual step (section 5, mb1) and a fixture (3.2); the verdict rule and its thresholds (3.6); the collection path through the status-board policy (3.8).

## 1. Goal

The owner pays for a Claude subscription, not API tokens, and wants to see on the board how much of the 5-hour and the weekly limit the work uses, as two bars (Standard and Max, Max being 5 times Standard), and to judge by eye whether Max is worth it. Tracking issue: https://github.com/tkcs-lab/tkcs-lab-devflow/issues/43

## 2. Current state

- The board stores status records and asks only (`src/tld/board/store.py:56`, schema version 4 at `store.py:28`); the page has one inbox view and an ask view switched by the URL hash (`src/tld/board/web/board.html`, function `route`).
- Routes and who may call them are the tables `ROUTES` and `POLICY` in `src/tld/board/server.py:56-90`; every route needs a row in `MATRIX` of `tests/core/test_board_server.py:34-52`, and the guide `docs/guides/board-server.md` must name every route, flag and `TLD_BOARD_*` variable (`tests/core/test_board_deploy.py:94-135`).
- The image copies a fixed list of modules (`deploy/board/Dockerfile`, checked by `tests/core/test_board_deploy.py:68`).
- No tld code knows about subscription limits. Every cloud session's event stream carries them: an event of kind `rate_limit_event` holds `rate_limit_info.unifiedWindows.five_hour` and `.seven_day`, each with `utilization`, `resetsAt` (epoch seconds) and `status`. Observed on 2026-11-13 at 10:30:20Z: five_hour utilization 0.26, resetsAt 1794572400; seven_day utilization 0.46, resetsAt 1794978000. The numbers are for the whole account, so any one session sees the use of all work, including the web chat and the phone app.
- The Claude Code status line also exposes these numbers, but the owner works in the browser and the phone app, so it is not used (rejected).

## 3. Design

### 3.1 Data: raw samples, converted on read

Rejected: storing one converted peak per window. A wrong plan or factor at write time would be wrong for ever. Rejected: putting readings in status records (the record schema is closed and prune deletes records).

New module `src/tld/board/usage.py` (no I/O) and schema version 5 of the store with one table:

```
usage_samples(kind TEXT, resets_at INTEGER, observed_at INTEGER, utilization REAL,
              plan TEXT, factor REAL, source TEXT,
              PRIMARY KEY (kind, resets_at, observed_at))
```

`kind` is `five_hour` or `seven_day`. `resets_at` is the window end in epoch seconds, floored to the minute. `observed_at` is the server's clock when the sample arrived (never client input). `utilization` is the raw fraction of the limit of the plan the account had at that time. `plan` (`standard` or `max`) and `factor` are the board's settings when the sample arrived. `source` is `final` or `scheduled`. Inserts use `INSERT OR REPLACE`. Limits: at most 50 samples per (`kind`, `resets_at`) (the oldest by `observed_at` are deleted), rows whose `resets_at` is older than 120 days are deleted on every insert, and at most 20,000 rows (the oldest by `resets_at` are deleted).

### 3.2 Unit, conversion and the fixture

`utilization` is a fraction of 1 (0.26 means 26%). This is believed, not proven: manual step mb1 pins it before work starts, and `usage.py` rejects any value outside 0 to 1.5 so a percent-style value fails loudly. `tests/fixtures/usage-event.json` (new) holds the real event above, cut to `rate_limit_info`; tests read it.

Conversion happens when windows are built, never when stored:

- `standard_pct = utilization * 100 * (factor if plan == "max" else 1)`. A sample taken on Max at 0.26 is 130% of the Standard limit.
- `max_pct = standard_pct / current_factor`, where `current_factor` is the board's present `TLD_BOARD_MAX_FACTOR`.

### 3.3 Configuration on the board host

- `TLD_BOARD_PLAN`: `standard` or `max`. There is no default. Unset: `POST /api/usage` answers 409 `usage_off` and `GET /api/usage` answers `"plan": null`; the page says how to set it. Any other value stops the server at start with `board_server: TLD_BOARD_PLAN must be standard or max` (exit 2).
- `TLD_BOARD_MAX_FACTOR`: a number greater than 1 and at most 20; default 5. Anything else stops the server with `board_server: TLD_BOARD_MAX_FACTOR must be a number above 1 and at most 20` (exit 2). The page shows the factor as an assumption ("Max = 5x Standard").
- Function `usage.parse_plan(env) -> tuple[str | None, float]` does both and raises `ValueError` with those messages. `make_server` takes `usage_plan` (that tuple, default `(None, 5.0)`) and `clock` (default `time.time`).

### 3.4 Endpoint

Route `^/api/usage$`, name `usage`, methods `GET` and `POST`; `POLICY`: `("usage", "POST")` session only, `("usage", "GET")` owner only (a session never needs to read it).

`POST /api/usage` body limit 4096 bytes (`_read_json(4096)`):

```json
{"five_hour": {"utilization": 0.26, "resets_at": 1794572400},
 "seven_day": {"utilization": 0.46, "resets_at": 1794978000},
 "source": "final"}
```

Rules (`usage.validate(body, now) -> (samples, errors)`): the body is an object whose keys are a non-empty subset of `five_hour`, `seven_day` plus the required `source` (`final` or `scheduled`); no other key. Each window is an object with exactly `utilization` (a number, not a boolean, 0 to 1.5) and `resets_at` (an integer with `now < resets_at <= now + length + 600`, length 18000 for `five_hour`, 604800 for `seven_day`). Answers: 200 `{"stored": <n>}`; 409 `{"error": "usage_off"}` (checked first); 422 `{"error": "invalid", "errors": [...]}`; 413 above 4096 bytes.

`GET /api/usage` answers 200:

```json
{"now": 1794570000, "plan": "max", "factor": 5.0,
 "windows": {"five_hour": [<window>, ...], "seven_day": [<window>, ...]}}
```

A `<window>` (built by `usage.windows(rows, factor, now)`, oldest first, at most 60 of each kind) is:

```json
{"resets_at": 1794572400, "start": 1794554400, "samples": 14, "first_seen": 1794554500, "last_seen": 1794570000,
 "plan": "max", "peak_standard": 130.0, "last_standard": 130.0, "peak_max": 26.0,
 "over": true, "blocked_hours": 3.2, "idle": false, "complete": false, "sources": ["final"]}
```

`start = resets_at - length`. `plan` is the plan of the newest sample. `peak_standard` / `last_standard` are the largest / newest sample in Standard percent. `peak_max = peak_standard / factor`. `over` = `peak_standard > 100`. `blocked_hours` is `null` unless `over`; then `(resets_at - first_observed_at_with_standard_pct_above_100) / 3600` rounded to one decimal (a lower bound: only sampled moments are known). `idle` = `peak_standard < 5` (the window holds almost nothing, typically the scheduled task alone). `complete` = `resets_at <= now`. All numbers are rounded to one decimal.

### 3.5 Command `tld board usage`

`tld board usage FILE|- [--source final|scheduled]` (module `tld.board.usage_client`, default source `final`). The input is JSON in any of three shapes: the whole `rate_limit_info`, its `unifiedWindows`, or an object holding `five_hour` / `seven_day` directly. Each window may spell the time `resetsAt` or `resets_at`. Windows whose `resets_at` is not in the future are dropped. Exit codes: 0 sent (stdout `{"stored":n}`) or nothing current to send (stderr `usage: no current window in the reading`); 1 the server refused or the input is not understood (409 prints `usage: the board has usage off: set TLD_BOARD_PLAN on the board host`); 2 usage error; 3 no board configured (as `tld board client`).

### 3.6 The page

Hash `#usage` shows a new section `usageview` (same pattern as `askview`); a link `Usage` (id `usage-link`) sits in the header next to `Log out`, shown when logged in. It loads `api/usage` on entry and every 60 seconds while the view is open (the timer stops when the view closes). Built only with the page's `el()` helpers (`textContent`; the page's CSP forbids anything else).

Texts (exact):

- Title: `Subscription usage`.
- Plan null: `Usage is off. Set TLD_BOARD_PLAN=max (or standard) on the board host and restart it.`
- Plan note: `You are on Max (5x). Max = 5x Standard (assumed).` / `You are on Standard. Use above 100% is invisible here, so this page cannot show whether Max is worth it.`
- No readings: `No readings yet. They arrive when a tld command ends or the /tld:usage task runs.`

For each kind (`5-hour window`, `Weekly window`) a card with the newest window whose `resets_at > now`: two rows `Standard` and `Max`, each a track with a fill of `min(pct, 100)%`; the label is `<pct>%`, and for Standard above 100 the fill uses class `over` and the label is `<pct>% (limit passed)`. Below: `resets in 2 h 14 min` and `last reading 6 min ago`. Each bar carries `role="img"` and an `aria-label` such as `Standard: 130 percent of the limit`.

History (below the cards, per kind): the complete windows of the last 30 days (`five_hour`) or 56 days (`seven_day`) as one column each, height proportional to `peak_standard` on a scale of 0 to `max(120, 1.1 * highest peak)`; a dashed line at 100% labelled `Standard limit`; a second line at `factor * 100` labelled `Max limit` only when it is inside the scale. Columns above 100% use class `over`, idle ones class `idle`. Each column has a `title` such as `12 Nov 03:00 - peak 340% of Standard (68% of Max), 14 readings`.

Verdict per kind, function `usageVerdict(windows)` in `rules.js` (pure). It counts the complete, non-idle windows of the history range whose `plan` is `max`; call that `n`, and `over` the ones with `over` true. Minimum `n`: 6 for `five_hour`, 2 for `seven_day`.

- `n` below the minimum: kind `few`, text `Not enough finished windows yet (<n> of <min> needed).`
- `over / n >= 0.25`: kind `max`, text `Max makes sense: Standard would have run out in <over> of <n> windows (<pct>%).`
- `over == 0` and the 90th percentile of `peak_standard` below 80: kind `standard`, text `Standard would have been enough: it stayed below its limit in all <n> windows (busiest: <peak>% of Standard).`
- otherwise: kind `borderline`, text `Borderline: Standard would have run out in <over> of <n> windows (<pct>%).`

When `over > 0` the text ends with ` Standard would have blocked you for at least <h> h in total.` (`h` the sum of `blocked_hours`, one decimal). The 90th percentile is the value at index `ceil(0.9 * n) - 1` of the ascending list. Rejected: a score or a price comparison; the owner reads the chart.

### 3.7 Neutral runtime action

`playbooks/runtime.md` gets `### read_usage()`: returns the newest account-wide rate-limit reading the runtime has seen in this session (a JSON object with `five_hour` and `seven_day` windows each holding `utilization` and a reset time) or nothing. The Claude Code map (`adapters/claude/skills/runtime/SKILL.md`) says: `list_events` with the own session id, `kinds: ["rate_limit_event"]`, `limit: 50`; the newest event's `rate_limit_info` is the reading; an empty result or a refusal is "nothing". The own session id is the `session_...` id (`get_session`); in an unattended session, `session_` followed by the part of `$CLAUDE_CODE_REMOTE_SESSION_ID` after `cse_`. The reading is written to a scratch file and handed to `tld board usage`.

### 3.8 Collection

- Piggyback: `playbooks/policies/status-board.md` gets a bullet under "When to write": after the final write of a run (`done`, `failed`, `pr_open`), call `read_usage()` and, when it returns a reading, run `tld board usage <file>`. Best effort: an error is never reported and never stops the run. The `usage` playbook itself is excluded.
- Scheduled: playbook `playbooks/usage.md` and the command `/tld:usage` (`adapters/claude/commands/usage.md`, frontmatter `model: haiku`, the fast level). Unattended, writes no status record (a record every 2 hours would bury the board). Steps: find the toolkit, `read_usage()`, `tld board usage <file> --source scheduled`, one-line final reply. Rejected: a status-line collector and a manual entry form (the owner's tools cannot run the first; the second invites wrong numbers). Each scheduled run uses a little of the same quota and can itself start a 5-hour window when the owner is idle; the `idle` rule keeps such windows out of the verdict, and the guide states the cost.

### 3.9 What can make the data wrong (shown in the guide)

Few samples make the peak a lower bound (the page shows reading counts in the column titles). Readings stop near 100% when a limit is hit, so on Standard the real need is invisible (the page says so). The weekly factor may not be exactly 5 (shown as an assumption, configurable). A window whose `resets_at` jitters by less than a minute is merged by the flooring to the minute; a larger drift creates a second row, a known and accepted blemish.

## 4. ADRs

None: the profile has no `docs.adr_dir`.

## 5. Manual steps

### mb1-confirm-unit: confirm the unit of `utilization` (about 3 minutes)

**Before implementation**

1. Open https://claude.ai/settings/usage while logged in.
2. Note the percentage shown for the current session (the 5-hour window) and for the weekly limit.
3. Compare with the values the plan was built on: 5-hour `utilization` 0.26 and weekly 0.46 at 10:30 UTC on 2026-11-13. The page's percentages today will differ by some points; what matters is whether 26% and 46% (not 0.26% and 0.46%) was the scale of the numbers on that day, for example by checking that the weekly bar was about half full.
4. Answer the start question of `implement` with yes when the percent on the page and the fraction match (percent divided by 100), no otherwise.

Done when: you see a usage page whose percentages are of the same size as the fractions times 100.

### ma1-deploy-and-plan: update the board host and set the plan (about 10 minutes)

**After implementation** (after the feature pull request is merged and a release is cut)

1. On the board host run the installer line again (https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/usage-monitor/docs/guides/delivery.md describes upgrading). The new image upgrades the database to schema 5; an older image cannot open it afterwards, so keep a backup from before (https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/usage-monitor/docs/guides/board-server.md, section Backup and restore).
2. Add the line `TLD_BOARD_PLAN=max` to `~/tld-board/.env` (and `TLD_BOARD_MAX_FACTOR=5` if you want it explicit).
3. Run `docker compose up -d` in `~/tld-board`.
4. Open the board, click `Usage`. Expect the plan note `You are on Max (5x)...` and, after the next tld command has ended, a first reading.

Report back: pass/fail line `usage page shows plan Max and a reading`.

### ma2-schedule-usage: schedule `/tld:usage` (optional, about 5 minutes)

1. In claude.ai open the scheduled tasks of your Project and add a task that runs `/tld:usage` every 2 hours (cron `7 */2 * * *`), at the fast level.
2. Leave connectors empty; the task needs only the board variables the environment already has.

Report back: pass/fail line `scheduled usage task created`.

### ma3-compare: compare with the app (about 5 minutes, one day later)

1. Open the board `Usage` page and https://claude.ai/settings/usage side by side.
2. Check that the 5-hour and weekly percentages of the Max bars are within 5 points of the app's.

Report back: pass/fail line `board matches the usage page`.

## 6. Risks and open questions

- The unit of `utilization` (fraction vs percent) is believed to be a fraction. If mb1 says no, stop: every phase's conversion is wrong. A worker that sees a fixture or test value above 1.5 for a real reading stops with `status=blocked`.
- `list_events` may refuse a scheduled session reading its own stream, or the `cse_` to `session_` id mapping may be wrong. Then `read_usage()` returns nothing and `/tld:usage` reports `usage: no reading`; nothing breaks. The first scheduled run is the check (ma2).
- A zero-token collector (a hook that sees rate-limit data) was not researched; it would remove the quota cost of the scheduled task. Open for later.
- Schema 5 makes a rollback to an older board image impossible without restoring the backup (stated in the guide).
- A worker that finds `test_contracts.py` or the structure tests listing commands in a form this plan did not foresee updates the list the same way the existing commands do; if a test needs a design change instead, it stops with `status=blocked`.

## Implementation manifest

```yaml
plan_slug: usage-monitor
feature_branch: feature/usage-monitor
tracking_issue: 43
max_parallel: 2
manual_before:
  - id: mb1-confirm-unit
    title: Confirm that utilization is a fraction (percent divided by 100)
    why: p1 converts utilization * 100 and rejects values above 1.5; if the unit were percent every number would be 100 times too small
    done_when: you compared https://claude.ai/settings/usage with the plan's values and the scales match
manual_after:
  - id: ma1-deploy-and-plan
    title: Update the board host and set TLD_BOARD_PLAN=max
    why: the endpoint and the page only exist in the new image, and usage stays off without the plan
  - id: ma2-schedule-usage
    title: Schedule /tld:usage every 2 hours (optional)
    why: CI cannot run a scheduled task or show whether a scheduled session may read its own stream
  - id: ma3-compare
    title: Compare the Max bars with the app's usage page
    why: only the owner can read the app's numbers
verify_after_merge:
  - .venv/bin/python -m pytest -q -k usage
  - .venv/bin/python -m pytest -q -k board
final_checks:
  - tld plan deviations check --file docs/plans/43/deviations.md --plan docs/plans/43/plan.md --all exits 0
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
phases:
  - id: p1-store-api
    title: Usage table, validation, endpoint and board settings
    depends_on: []
    complexity: M
    touches:
      - src/tld/board/usage.py
      - src/tld/board/store.py
      - src/tld/board/server.py
      - deploy/board/Dockerfile
      - docs/guides/board-server.md
      - tests/fixtures/usage-event.json
      - tests/core/test_board_usage.py
      - tests/core/test_board_server.py
      - tests/core/test_board_store.py
    brief: |
      Read first: docs/guides/board-server.md, src/tld/board/store.py, src/tld/board/server.py, tests/core/test_board_server.py.
      Design: section 3.1 to 3.4 of docs/plans/43/plan.md (read it).
      1. Create tests/fixtures/usage-event.json with exactly this content: {"isUsingOverage": false, "rateLimitType": "five_hour", "resetsAt": 1794572400, "status": "allowed", "unifiedWindows": {"five_hour": {"resetsAt": 1794572400, "status": "allowed", "utilization": 0.26}, "seven_day": {"resetsAt": 1794978000, "status": "allowed", "utilization": 0.46}}}
      2. Create src/tld/board/usage.py, standard library only, no I/O, with: constants KINDS = {"five_hour": 18000, "seven_day": 604800}, SOURCES = ("final", "scheduled"), MAX_BODY = 4096, MAX_PER_WINDOW = 50, MAX_ROWS = 20000, RETENTION_DAYS = 120, SLACK = 600; parse_plan(env) -> tuple[str | None, float] with the messages of section 3.3; validate(body, now) -> tuple[list[dict], str, list[str]] returning the samples [{"kind", "resets_at" (floored to the minute), "utilization"}], the source and the error list, with the rules and error texts of 3.4 (each error names the key, for example "five_hour.utilization must be a number from 0 to 1.5"); windows(rows, factor, now) -> dict[str, list[dict]] building the window dicts of 3.4 from rows (kind, resets_at, observed_at, utilization, plan, factor, source), oldest first, last 60 per kind.
      3. In store.py raise SCHEMA_VERSION to 5; add to _migrate the table usage_samples of 3.1 with CREATE TABLE IF NOT EXISTS (step "5"); add Store.add_usage(samples, source, plan, factor, now: int) (INSERT OR REPLACE for each sample, then the three trims of 3.1 in one transaction) and Store.list_usage() -> list of row tuples ordered by kind, resets_at, observed_at. Update the module docstring (five tables).
      4. In server.py import usage, add the route and the POLICY entries of 3.4, MAX_USAGE_BODY use through usage.MAX_BODY, add make_server parameters usage_plan and clock (stored as server.usage_plan and server.clock), a method _do_usage for GET and POST following _do_asks, and in main() call usage.parse_plan(os.environ), printing "board_server: <message>" to stderr and returning 2 on ValueError, and pass usage_plan to make_server. Update the module docstring's environment line with TLD_BOARD_PLAN and TLD_BOARD_MAX_FACTOR.
      5. In deploy/board/Dockerfile add src/tld/board/usage.py to the COPY line of the board modules.
      6. In docs/guides/board-server.md: add TLD_BOARD_PLAN and TLD_BOARD_MAX_FACTOR rows to the Configuration table; add the two rows `GET /api/usage` (owner cookie only) and `POST /api/usage` (session token only) to the HTTP API table with their errors; change "schema version 4"/"schema 4" in the Security notes and Backup sections to schema 5 only where they describe the current schema (the dismissals and revoked_sessions sentences keep "schema version 4" as the version that added them); add a short section "Usage readings" (what is stored, the 120-day and 20,000-row limits, that a rollback to an older image needs the backup, that the factor is an assumption). The guide must not contain a 32-character token-like string.
      7. Tests: new tests/core/test_board_usage.py covering parse_plan (unset, standard, max, bad plan, factor 1, 21, "x"), validate (the fixture's windows accepted; utilization -0.1, 1.6, True, "0.2"; resets_at in the past, beyond length + 600, a float; unknown key; empty body; bad source), windows (peak, last, over, blocked_hours, idle, complete, conversion for a plan-standard row versus a plan-max row, factor change affects only peak_max), the store (trims: 51st sample deletes the oldest; row older than 120 days removed; 20,001st row removes the oldest; a second store open at schema 4 migrates to 5 and keeps records), and the endpoint with the running() helper of tests/board_helpers.py (POST 200 then GET shows the window; 409 usage_off without a plan; 422 with errors; 413 above 4096 bytes; GET with the session token is 403). In tests/core/test_board_server.py add to MATRIX the rows ("GET", "/api/usage", None, (401, 403, 200)) and ("POST", "/api/usage", "usage", (401, 200, 403)), a "usage" body in _body (a payload with five_hour utilization 0.3 and resets_at int(time.time()) + 3600, source "final"), and pass usage_plan=("max", 5.0) to running(...) in the matrix_server fixture. In tests/core/test_board_store.py change the three assertions of schema 4 to 5.
      Stop conditions: if the matrix test or the deploy tests need a change beyond the ones above, or the existing board tests fail for a reason not named here, stop with status=blocked and say which test.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_usage.py tests/core/test_board_server.py tests/core/test_board_store.py tests/core/test_board_deploy.py -q passes
      - grep -n "usage.py" deploy/board/Dockerfile matches
      - grep -n "POST /api/usage" docs/guides/board-server.md matches
      - .venv/bin/python -m pytest tests -q passes

  - id: p2-cli
    title: The tld board usage command
    depends_on: [p1-store-api]
    complexity: S
    touches:
      - src/tld/board/usage_client.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_board_usage_client.py
    brief: |
      Read first: docs/reference/cli.md, src/tld/board/client.py, tests/core/test_board_client.py.
      Design: section 3.5 of docs/plans/43/plan.md.
      1. Create src/tld/board/usage_client.py (standard library only) with main(argv) -> int: argparse positional file ("-" is standard input) and --source final|scheduled (default final); read the JSON; find the windows by looking for a key "unifiedWindows", else "rate_limit_info" then "unifiedWindows", else the object itself; for each of five_hour and seven_day present, take utilization and resetsAt/resets_at, drop a window whose resets_at is not later than the current time, build the body of 3.4 with the source; reuse load_config and call from tld.board.client; exit codes exactly as 3.5 with the stderr texts given there.
      2. Register ("board", "usage") in COMMANDS of src/tld/cli.py with module tld.board.usage_client, no fixed arguments and the help "send the newest rate-limit reading to the board".
      3. Add the row `tld board usage FILE|- [--source final|scheduled]` to the board table of docs/reference/cli.md.
      4. Tests in tests/core/test_board_usage_client.py: with the running() helper and the environment variables TLD_BOARD_URL / TLD_BOARD_TOKEN set by monkeypatch, run main() on tests/fixtures/usage-event.json with the clock of the server set (make_server clock) to 1794570000 and assert exit 0 and the stored windows; the three input shapes give the same body; resetsAt spelled resets_at works; an expired window is dropped and exit is 0 with the stderr text; a server without a plan gives exit 1 with the usage_off text; no TLD_BOARD_URL gives exit 3; invalid JSON gives exit 1.
      Stop condition: if p1's endpoint answers differently from section 3.4, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_board_usage_client.py tests/core/test_cli_reference.py -q passes
      - .venv/bin/python cli/tld board usage --help exits 0

  - id: p3-page
    title: The Usage page and its rules
    depends_on: [p1-store-api]
    complexity: M
    touches:
      - src/tld/board/web/board.html
      - src/tld/board/web/rules.js
      - tests/board_usage_check.js
      - tests/board_usage_page_check.js
      - tests/core/test_board_usage_page.py
    brief: |
      Read first: src/tld/board/web/board.html, src/tld/board/web/rules.js, tests/board_rules_check.js, tests/board_links_page_check.js, tests/core/test_board_page.py.
      Design: section 3.4 and 3.6 of docs/plans/43/plan.md.
      1. In rules.js add pure functions and export them in module.exports: usageBar(pct) -> {fill: Math.min(pct, 100), over: pct > 100}; usageNow(windows, nowSec) -> the window with the largest resets_at that is greater than nowSec, else null; usageVerdict(windows, kind, nowSec, factor) -> {kind, text} following 3.6 exactly (range 30 days for five_hour and 56 for seven_day counted back from nowSec, minimum n 6 and 2, percent rounded to a whole number, hours to one decimal); usageAgo(seconds) -> "6 min ago"/"2 h 14 min" style strings: below 60 s "just now", below 3600 s "<m> min", else "<h> h <m> min".
      2. In board.html add the section usageview (hidden-view), the header link #usage-link, the CSS for .track, .fill, .fill.over, .col, .col.over, .col.idle, .limit-line using the existing colour variables (--run for the fill, --need for over, --line for idle), and the code: extend route() to show usageview for the hash "#usage" (hide main and askview), render with only el()/add() helpers, fetch api/usage on entry and every 60 000 ms while open, clear the timer when the hash changes. Texts are the exact strings of 3.6. The chart is built from div elements (no SVG, no innerHTML).
      3. tests/board_usage_check.js (node, assert, same style as tests/board_rules_check.js) covers: usageBar at 0, 50, 100, 130; usageNow with two windows and none; usageVerdict kinds few/max/standard/borderline with built windows (including idle and non-max-plan windows being ignored, the 90th percentile index, the blocked hours sentence); usageAgo.
      4. tests/core/test_board_usage_page.py: runs the node check (need_tool("node") as test_board_rules.py does); asserts board.html contains "usage-link" and the exact plan-null text; and a browser test marked like the others with need_browser() that starts running(tmp_path, usage_plan=("max", 5.0)) with the server clock fixed by clock=lambda: 1794570000, posts two readings from tests/fixtures/usage-event.json with the session token, logs in as tests/board_poll_check.js does, opens #usage and asserts the texts "Subscription usage", "Standard" and "Max" are shown, "(limit passed)" is shown for the 130% Standard bar, and that no console error occurred. The browser script is the new file tests/board_usage_page_check.js, with the Playwright launch code copied from tests/board_links_page_check.js; the pytest function runs it as test_board_page.py runs its scripts.
      Stop condition: if the page's content-security-policy blocks the new code, stop with status=blocked and quote the console message.
    acceptance:
      - node tests/board_usage_check.js prints OK
      - .venv/bin/python -m pytest tests/core/test_board_usage_page.py tests/core/test_board_page.py tests/core/test_board_rules.py -q passes
      - grep -c "innerHTML" src/tld/board/web/board.html prints 0

  - id: p4-collect
    title: read_usage action, final-write step, usage playbook and command
    depends_on: [p2-cli]
    complexity: M
    touches:
      - playbooks/runtime.md
      - playbooks/policies/status-board.md
      - playbooks/usage.md
      - adapters/claude/commands/usage.md
      - adapters/claude/skills/runtime/SKILL.md
      - docs/guides/maintenance.md
      - tests/core/test_contracts.py
      - tests/adapters/claude/test_structure.py
      - tests/core/test_usage_playbook.py
    brief: |
      Read first: playbooks/runtime.md, playbooks/policies/status-board.md, playbooks/deps.md, adapters/claude/commands/deps.md, adapters/claude/skills/runtime/SKILL.md, docs/guides/maintenance.md, tests/core/test_contracts.py.
      Design: section 3.7 and 3.8 of docs/plans/43/plan.md.
      1. playbooks/runtime.md: add a new group "## Usage" after "## Time" holding a section "### read_usage()" with the neutral text of 3.7. It must not name any tool, model or host (the neutrality test lists the forbidden words).
      2. playbooks/policies/status-board.md: add the bullet of 3.8 (piggyback) to "When to write", worded in neutral terms, naming `read_usage()` and `tld board usage <file>`.
      3. playbooks/usage.md: "# Playbook: usage", the steps of 3.8 (scheduled), links to policies/untrusted-text.md as `(policies/untrusted-text.md)` and to runtime.md, states attended false, no status record and why, the final reply forms `usage: five_hour <p>% (resets <ISO time>), seven_day <p>% (resets <ISO time>)` and `usage: no reading`, and that it never asks, never opens a pull request and posts nothing on GitHub.
      4. adapters/claude/commands/usage.md: frontmatter `description` and `model: haiku`, body like adapters/claude/commands/deps.md for usage.md including the sentence that it runs from a scheduled task.
      5. SKILL.md: add the row `read_usage()` to the right table with the mapping of 3.7 and the own-id rule.
      6. docs/guides/maintenance.md: add a section "/usage" (what it sends, the cost in quota, that the window it starts when idle is kept out of the verdict, the cron line 7 */2 * * *), and add the command to the first paragraph's list of unattended commands.
      7. tests: in tests/core/test_contracts.py add "usage" to COMMANDS and to the tuple at the status-record test that exempts "dod" and "board" (comment: a reading, no record); in tests/adapters/claude/test_structure.py assert the usage command's model is the alias of the fast level (see test_commands_that_must_run_on_a_level); new tests/core/test_usage_playbook.py asserts playbooks/usage.md names read_usage and `tld board usage`, status-board.md names both, runtime.md defines read_usage, and the wrapper delegates to the playbook.
      Stop condition: if the contract tests reject a form this brief gives (for example an action-like word), fix the wording, not the test; if a test must change in another way, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_usage_playbook.py tests/adapters/claude -q passes
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - grep -n "read_usage" playbooks/runtime.md playbooks/usage.md playbooks/policies/status-board.md adapters/claude/skills/runtime/SKILL.md matches

  - id: p5-retire
    title: Changelog and command table
    depends_on: [p3-page, p4-collect]
    complexity: S
    touches:
      - CHANGELOG.md
      - README.md
    brief: |
      Read first: CHANGELOG.md, README.md.
      1. CHANGELOG.md: under `## [Unreleased]` (no version heading) add `### Added` with one bullet per user-visible change: the Usage page of the board (two bars Standard and Max for the 5-hour and weekly windows, history, verdict; settings TLD_BOARD_PLAN and TLD_BOARD_MAX_FACTOR); the endpoint and `tld board usage`; `/usage` (unattended, fast level); and under `### Changed` that the board database moves to schema 5 and an older board image cannot open it.
      2. README.md: add the row `/tld:usage` to the Commands table (description: "unattended, every few hours: sends the account's 5-hour and weekly subscription use to the board's Usage page") and append `/usage` to the sentence listing the maintenance commands only if that sentence lists them; otherwise leave it.
      3. Run .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml and the full tests; no docs were added, moved or deleted, so no index row changes.
    acceptance:
      - grep -n "Usage page" CHANGELOG.md matches
      - grep -n "tld:usage" README.md matches
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - .venv/bin/python -m pytest tests -q passes
```
