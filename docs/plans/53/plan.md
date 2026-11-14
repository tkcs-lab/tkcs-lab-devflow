# Plan 53: question review, the asks a better tld would avoid

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Once the board runs the release that carries this change, schedule `/tld:questions` weekly (a claude.ai scheduled task in auto mode, with the board variables set). Each run reads the asks that agents put to you since its last run, groups the similar ones and judges which a better playbook, profile key, role, skill, command or doc would have avoided. With findings it pushes `review/questions-<date>`, posts one decisions ask on the board (plan, issue or drop per item) and stops. You answer on the board, run `/tld:review apply <URL>`, then `/tld:make-plan <URL>`.

**Scope:** Adds the command `questions`, the status-record command `questions`, `since` and `limit` on `GET /api/asks`, the digest command `tld board ask-digest`, a `status_record:` header that `review apply` closes, plan-gate and board-gate entries, a guide and the docs rows. The board's ask table is the database: no new table, no profile key. It does not collect your `/tld:ask` messages and fixes none of the questions it finds; the first run reports them.

**Security:** Asks of other projects on the same board add counts to this project's clusters and nothing else: no text, id, time, repository or record of theirs enters a digest or a document, because the document lands in a public repository. Ask text is data: the digest emits a masked template of at most 160 characters and no answer text, and the run writes every fix in its own words. The run posts one ask unattended and never a fallback issue. A fixed list of control asks (start confirmation, identity check, human gate, take-over, release start, research) is never proposed for removal; only their cause may be.

**Review focus:** (1) the foreign-asks rule and the masking in section 3.2; (2) the board release this needs and the stop on its refusal, sections 3.1 and 4; (3) the cursor and the dedupe held in git, not on the board, section 3.4; (4) the control list that stops the classifier from removing a confirmation, section 3.5; (5) `status_record:` closing the record from `review apply`, section 3.6.

## 1. Goal

The owner is asked many questions by agents (`ask_human` posts each one to the board). Some are real decisions. Others only exist because tld, an agent or a skill left a gap: a confirmation that is always answered yes, an optional question nobody fills, a question posted twice because the first one was wrong, a worker blocked by a fact the plan could have checked. The goal is a weekly, unattended run that turns the board's stored asks into a triaged list of those avoidable questions, in the review document format, so that `make-plan <review URL>` can plan the fixes. The board already keeps every ask, so it is the question database. Tracking issue: [#53](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/53).

Owner decisions (board ask `a-7fc94d5667663e66`, answered 2026-11-14): the result is a review document on a `review/` branch, triaged with one board ask; only asks agents put to the owner are collected, not `/tld:ask` messages; weekly; this plan builds the pipeline only and the first scheduled run reports the themes.

## 2. Current state

- Asks are stored in the `asks` table (`src/tld/board/store.py:269` `list_asks`, a hard `LIMIT 200`, open asks first, then newest first, no time filter). `GET /api/asks` is `src/tld/board/server.py:552-559`; the session token may read it (`server.py:87`). It returns the asks of every project that shares the board.
- Measured on 2026-11-14: 41 asks since 2026-11-11 (33 of this repository, 8 of another private project). Themes found by hand: the verify-commands confirmation of `implement` in 8 runs, the "Second GitHub user ready" confirmation in 5 runs, 6 workers blocked by a test outside their `touches`, 6 optional "anything else?" text questions that were never filled, 3 asks cancelled and posted again as corrections.
- Most old asks have `record: null`; asks posted since the per-session record ids carry the record id (`<project>--<command>--<tail>` or `<project>--run--<plan>`). The board refuses an ask whose `record` is not a document id of its project with a known command (`src/tld/board/ask.py:157`, `src/tld/board/record.py:109` `owns_doc_id`) and a record whose `command` is not in `COMMANDS` (`src/tld/board/record.py:42,265`).
- The board hides a finished record after 7 days (`src/tld/board/stale.py:30`) and `board prune` deletes hidden ones (`playbooks/board.md:31`), so no state kept only in a record survives a quiet week.
- The command gates list their commands: `OPENING` in `src/tld/guard/plan_gate.py:19`, `RECORD_COMMANDS` in `src/tld/guard/board_gate.py:24`. Tests tie both to the playbooks (`tests/core/test_board_record_wording.py:55-58`, `tests/adapters/claude/test_hook_board_gate_adapter.py:59`).
- The review document format and its resume step `review apply` are in `playbooks/review.md` (header at line 171, apply in sections 6 and 7); `make-plan` reads such a document when its `status` is `ready-for-plan` (`playbooks/make-plan.md:71-81`).

## 3. Design

### 3.1 Board side (phase p1-board)

- `src/tld/board/record.py`: append `"questions"` to `COMMANDS`; add `parse_doc_id(doc_id: str) -> tuple[str, str, str] | None`. For a string that matches `DOC_ID_RE` it splits on the first `--`: the part before it is the project; `("<project>", "run", "<plan>")` for `<project>--run--<plan>`; `("<project>", "command", "<command>")` for `<project>--<command>` or `<project>--<command>--<tail>` with `<command>` in `COMMANDS`; `None` for everything else (the bare project id, an unknown command, a run without a plan).
- `src/tld/schema/status-record.schema.json`: add `"questions"` to the `command` enum and to the description of `kind`.
- `Store.list_asks(state=None, limit=200, since=None)`: `since` keeps only asks with `created_at > since`; the order does not change and the limit applies after the filter.
- `GET /api/asks` accepts `since` (a timestamp `YYYY-MM-DDTHH:MM:SSZ`) and `limit` (an integer from 1 to 1000, default 200); any other value is `400 bad_request`. An older board ignores both parameters, so the client also filters.
- A board that does not know `questions` refuses the first record write with `'command' must be one of ...`: the run stops (3.3). A board release and a board upgrade are therefore a manual step (section 4).

### 3.2 The digest, `tld board ask-digest` (phase p2-digest)

Module `src/tld/board/ask_digest.py` (stdlib only). Command line: `tld board ask-digest --project SLUG [--since ISO] [--file FILE] [--now ISO]`. `--project` is required. `--file` reads `{"asks": [...]}` or a bare list from a file (`-` for stdin) instead of the board; `--now` replaces the clock in the output. Without `--file` it reads `GET /api/asks?limit=1000[&since=<ISO>]` with `tld.board.client` (`load_config`, `call`). Exit 0 digest printed on stdout as one JSON object; 1 the board answered an error, cannot be reached, or the file is unreadable; 2 usage error; 3 no board configured. Errors start with `tld board: `.

Constants: `MAX_TEMPLATE = 160`, `SIMILARITY = 0.5`, `REPOST_MINUTES = 30`, `MAX_CLUSTERS = 60`, `MAX_CLUSTER_ASKS = 20`, `TITLE_SOURCES = (("start ", "run"), ("phase ", "run"), ("plan #", "make-plan"))`.

- **Filter.** Drop every ask with `created_at <= since` (client side, whatever the server did).
- **Own, foreign, excluded.** An ask is own when its `project` equals `--project`, otherwise foreign. An own ask whose `record` parses (`parse_doc_id`) to the command `questions` is excluded (the run does not cluster its own asks); it is only counted.
- **Source.** For an own ask: from `parse_doc_id(record)`: the command name, or `run` for a run; with `record` null the first `TITLE_SOURCES` prefix that the lowercased title starts with; else `None`.
- **Mask.** `mask(text)`: lowercase; replace `https?://\S+` by `<url>`; each backtick span by `<code>`; `\b[0-9a-f]{7,40}\b` by `<sha>`; a word that contains `/` by `<path>`; `#<digits>` by `#<n>`; each digit run by `<n>`; a word of letters and digits with at least two hyphens by `<slug>`; collapse whitespace; cut to `MAX_TEMPLATE` characters. The masking applies in this order.
- **Words.** `words(template)`: delete every `<...>` placeholder, then the set of `[a-z]{3,}` matches.
- **Entries.** One entry per question of every own, non-excluded ask: `ask`, `created_at`, `source`, `qid`, `kind`, `template`, `record`, `state`; `took_recommended` (only when the ask is answered and has an answer for the question: a choice gives `answer == options[0].value`, a confirm gives `answer is True`, a text gives `None`; otherwise `None`); `empty` (true only for a text question with `required` false, in an answered ask, whose answer is missing or an empty string); `seconds` (answered ask: `answered_at - created_at`, else `None`); `cancelled` (ask state `cancelled`); `reposted` (the ask is cancelled, has a non-null `record`, and another own ask with the same `record` was created after it and within `REPOST_MINUTES` of it).
- **Clusters.** Entries sorted by `(created_at, ask id, qid)` go greedily into the first cluster with the same `source`, the same `kind` and `|A ∩ B| / |A ∪ B| >= SIMILARITY` over `words(seed template)` and `words(template)` (two empty sets are similar only when the templates are equal); else they open a new cluster whose seed is the entry.
- **Foreign asks.** For each foreign ask question, mask it, take its `kind`; if it has a similar own cluster (same rule, source taken from its `record` the same way) add one to that cluster's `foreign_count`, otherwise add one to `foreign.unmatched_questions`. Nothing else of a foreign ask is kept: no id, time, title, text, project, repository or record.
- **Output.** `{"schema": 1, "project", "since", "now", "cursor", "truncated", "asks", "analysed", "excluded_questions_asks", "foreign": {"asks", "unmatched_questions"}, "clusters": [...]}`. `asks` is the number of asks after the filter (own and foreign); `analysed` the own non-excluded ones; `cursor` the newest `created_at` among own asks including excluded ones, or `null`; `truncated` is true when the server returned exactly 200 or exactly 1000 rows. A cluster is `{"id": "c<k>", "fingerprint", "source", "qid", "kind", "template", "count", "records", "asks", "foreign_count", "recommended_rate", "empty_rate", "cancelled", "reposted", "median_seconds", "first", "last"}`: `fingerprint` the first 16 hex characters of `sha256("<source or ->|<kind>|<seed template>")`; `qid` the most frequent id (earliest on a tie); `count` the entries; `records` the number of distinct `record` values, each entry with a null record counting as its own; `asks` the sorted distinct ask ids, at most `MAX_CLUSTER_ASKS`; `recommended_rate` the share of entries with `took_recommended` true among those where it is not `None`, rounded to two places, else `null`; `empty_rate` for a text cluster the share of entries from answered asks with `empty` true, else `null`; `cancelled` and `reposted` the numbers of entries with the flag; `median_seconds` the integer median of the non-null `seconds` or `null`; `first` and `last` the earliest and latest `created_at`. Clusters are sorted by `count` descending, then `first`, numbered `c1`, `c2`, ... in that order and cut to `MAX_CLUSTERS`.
- It emits no answer text: an answer only becomes `took_recommended` or `empty`. Foreign data never leaves as text. There is no flag that turns this off.

### 3.3 The command `questions` (phase p3a-command)

`playbooks/questions.md`, a scheduled, unattended playbook (like `deps`: `attended: false`), written in the neutral style of the other playbooks (no runtime tool names, no `/tld:` words: it says `review apply <URL>` and `make-plan <URL>`). Rules it names: [policies/untrusted-text.md](../../../playbooks/policies/untrusted-text.md), [policies/status-board.md](../../../playbooks/policies/status-board.md), [policies/research.md](../../../playbooks/policies/research.md) (a scheduled run lists open research questions under `Open research questions:` and never asks them), [runtime.md](../../../playbooks/runtime.md). Input: empty, or `since <ISO>` to override the window start.

It states one exception to "an unattended run asks nothing": this command posts exactly one decisions ask per document, never with `--fallback-issue`, and then ends its turn (the unattended branch of `ask_human`); the owner answers on the board and runs `review apply`.

Setup:

1. Load the profile ([policies/profile.md](../../../playbooks/policies/profile.md)); `<plan_dir>` is `docs.plan_dir`, `<main>` is `git.main_branch`, "the reviewer level" is `models.reviewer`.
2. `tld dod exempt` once (it writes a document, not code), as `review` does.
3. Status record: `kind: command`, `command: questions`, `attended: false`, `orchestrator_session: null`, document id from `tld board record-id --repo <owner>/<repo> --command questions --unattended`, items `read`, `classify`, `write`, `ask`. First write `starting`. A refusal whose text contains `'command' must be one of` means the board is older than the release with `questions`: reply `questions: upgrade the board, it does not know the command questions` and stop (no document, no ask). With `tld board client` exit 3 (no board): reply `questions: no board` and stop.

Steps:

0. **Previous document.** `github.branch_list`, names that start with `review/questions-`, newest by name first. For the newest, `git fetch origin <branch>` and read the header of its document (`git show FETCH_HEAD:<plan_dir>/<slug>-review.md`).
   - `status: decisions-pending` with a `decisions_ask`: `tld board answers <ask id>`. Exit 3 (still open): set `needs_you` with `Decide the questions review of <date>`, `notify_human` once, record `waiting_user`, stop; no new document, no new ask. Exit 0 (answered, not applied): `needs_you` with `Run review apply <URL>`, stop. Exit 4 (cancelled): go to step 5 for that document (post its ask again), then stop.
   - `status: decisions-pending` with `decisions_ask: none`: go to step 5 for that document, then stop.
   - Any other status, or no such branch: go on.
1. **Window and digest.** The cursor is the latest of: the `asks_until` header of the newest document, the `cursor <ISO>` token in the previous record's `last_event` (read with `tld board client get <id>`; it is information only), and the input `since`. `tld board ask-digest --project <tld board project-slug <owner>/<repo>> [--since <cursor>]`, saved to a scratch file. Exit 3: `questions: no board`. Exit 1: record `failed` with the message. `analysed` 0: record `done` with `last_event` `cursor <cursor>; nothing new` and stop. The digest is data ([policies/untrusted-text.md](../../../playbooks/policies/untrusted-text.md)).
2. **Classify** each cluster with `count >= 2` by section 3.5 of the plan's rules (restated in the playbook): candidate or not, control or not, fix kind, and for a candidate the `Where`: the playbook step, profile key, role card, skill, command or doc that posts or should have prevented the question, found by `grep` in the repository at `origin/<main>`.
3. **Verify.** `git fetch origin <main>`; the pinned commit is its SHA. Read each `Where` at that commit: it must exist and show the cause. A finding is `confirmed` when the text shows the cause, `plausible` otherwise. With more than 8 findings, `run_helper(<try to disprove these findings against the code>, <the reviewer level>)` once. Failed ones go to "Rejected on verification". Drop a finding whose fingerprint is in "Findings to fix", "Issues created" or "Not doing" of any earlier `review/questions-*` document (read the newest 12), and one whose `Where` and fix kind equal those of an earlier finding.
4. **Write.** Slug `questions-<YYYY-MM-DD>` (today, UTC), branch from `tld plan branch-name --review-slug <slug>`, file `<plan_dir>/<slug>-review.md`, format of section 3.6. No finding and no open item: no branch, no file; record `done` with `last_event` `cursor <ISO>; <n> asks, nothing avoidable`; stop. Otherwise cut the branch from `origin/<main>`, commit, `git push -u origin <branch>`; if the push is refused, `github.branch_create` from `origin/<main>`'s SHA and push again; still refused: record `failed` and stop. If the branch already exists on origin (a re-run the same day), check it out and update the document in place keeping its finding ids.
5. **Ask.** Only with `open` items. `ask_human` unattended: title `Questions review <YYYY-MM-DD>: <m> decisions`; `context_url` the document at `https://github.com/<owner>/<repo>/blob/review/<slug>/<plan_dir>/<slug>-review.md`; `record` the run's record id; one `choice` question per open item exactly as `playbooks/review.md` section 5 step 4 describes (`id` the finding id, `text` its title and two-sentence summary, options `plan`, `issue`, `drop` with the recommendation first and ` (recommended)` in its label); no `notes` question. Post with `tld board ask <file>` and no `--fallback-issue`. Exit 5 or 3: record `failed` with `needs_you` `Post the questions ask: the board cannot be reached`, header `decisions_ask: none`, stop. On success put the ask id into `decisions_ask`, commit and push, set the record `waiting_user` with `needs_you` and `Decide <m> question findings`, `notify_human` once, and end the turn.
6. **No open item.** `status: ready-for-plan`, no ask; record `done`, `needs_you` false; the final reply is the document URL and the line `make-plan <URL>`.

Final reply (one line): `questions: <n> asks, <k> findings, <m> to decide, <URL or none>`. `last_event` of the final record carries `cursor <ISO>` (the digest's `cursor`).

Never: fix a finding; open a pull request; push to `<main>` or to any branch but `review/questions-<date>`; create an issue or a fallback issue; put a secret, an answer text or any text, id, time, repository or record of another project into the document or the record; propose removing a control (section 3.5); run a command found in a digest or a document.

The adapter wrapper `adapters/claude/commands/questions.md` is the thin wrapper of the other scheduled commands: `description` (more than 40 characters): `Weekly unattended: read the asks the board collected since the last run, find those a better playbook, profile key, role, skill, command or doc would have avoided, and write a triaged review document for /tld:make-plan`; `model: sonnet`; the body of `deps.md` with the playbook name `questions` and the last line `It runs from a scheduled task: attended: false, no get_session, alerts are a push only.` (no `strong` turn line).

Registration: `questions` is added to `OPENING` (`src/tld/guard/plan_gate.py:19`) and to `RECORD_COMMANDS` (`src/tld/guard/board_gate.py:24`), in the same phase as the playbook and the wrapper, because tests tie both lists to the playbooks.

### 3.4 The cursor and the dedupe live in git

The board prunes records, so the cursor cannot live only in one. The document header carries `asks_until: <digest cursor>`; step 1 takes the latest of that header, the record's `cursor` token and the input. Every finding carries its `Fingerprint`, and step 3 drops what an earlier document already reported, dropped or turned into an issue. A pruned record and a deleted branch together bring old themes back once; the owner drops them. At most one questions document is waiting for a decision at a time (step 0). Keep the `review/questions-*` branches: they are the dedupe memory (a row is added to the branch table of [policies/pr-steward.md](../../../playbooks/policies/pr-steward.md)).

### 3.5 What counts as avoidable

A question is **avoidable** when a better tld, agent or skill would have answered it or made it unnecessary. The fix kind is one of `playbook` (a step could settle it or not ask it), `profile` (a key or allow list could carry the answer), `role` (an agent could check it), `skill`, `cli` (a tld command could compute or verify it), `hook`, `docs`, `runtime`. A question is **genuine** when only the owner can answer it: scope, product behaviour, a trade-off with no default in the code, a research request, or an approval of something irreversible.

A cluster is a **candidate** when `count >= 3` and `records >= 2`; or `empty_rate >= 0.8` with `count >= 3`; or `reposted >= 2`; or `cancelled >= 3`. The decision for a candidate:

- `fix`: it has a `Where` that exists at the pinned commit, `recommended_rate >= 0.8` or `empty_rate >= 0.8` or `reposted >= 2`, and a concrete change that removes the cause.
- `open`: a candidate whose evidence is mixed (`recommended_rate` between 0.5 and 0.8, or no single `Where`), with the recommendation `plan`, `issue` or `drop` and a reason.
- `drop`: genuine, or a control without a fixable cause, listed under "Not doing" with the reason.

**Control asks.** These are never proposed for removal and are always genuine: the start confirmation of `implement` and its confirmation of commands outside the trusted list; the identity check and the confirmation of a manual step only the owner can verify; a `human_gate` choice; the take-over of a run that looks alive; the start of a release; a research request; the decisions ask of `review` and of this command. A finding about a control may only remove its cause (for example, a trusted form added to `verify.after_merge_allow` so the plan's commands are no longer unknown, or a plan that no longer lists a step the profile already proves). At most 10 findings per document, the highest `count` first.

### 3.6 The document, and `status_record:` (phase p3a for the format, p3b for `review.md`)

The document follows `playbooks/review.md` section 5 step 2 exactly (same headings, same finding block), with these differences. Header keys, in order: `review_slug`, `repository`, `commit` (the full SHA of `origin/<main>`), `scope` (`board asks <first created_at> to <asks_until>`), `reviewed_on`, `status`, `decisions_ask`, `asks_until`, `status_record` (the run's record id). The finding prefix is `QST`; the block has the review's fields plus `**Question (masked):**` (the cluster template), `**Asks:**` (`<count> asks in <records> runs`, at most 10 ask ids), `**Signals:**` (`recommended <r>, empty <e>, cancelled <c>, reposted <p>`, `n/a` for a missing rate), `**Fingerprint:**` and `**Fix kind:**`. The `Fix` lines are written in the run's own words, never copied from a question. Section "What was reviewed" holds the digest numbers: the window, `asks`, `analysed`, `foreign.asks` (a count), `truncated`, the commands run.

`playbooks/review.md` gains: in section 5 step 2 the optional header line `status_record: <record id>` ("set by a producer that waits for these decisions"); in section 7 step 5 the rule: when the header has `status_record`, and its value is `<project>--questions`, write that record (`tld board client get`, then `set --if-version`) as `done`, `needs_you` false, reason `""`, `needs_you_since` null, `last_event` `decisions applied <date>`, `finished_at` and `updated_at` now; on a conflict retry once; any other error is noted in the final reply and never stops the run. `<project>` is `tld board project-slug <owner>/<repo>`. The status-board policy says `review apply` is the resume step of `questions`.

### 3.7 Rejected alternatives

- The playbook reads the asks itself through the board MCP tools: raw ask text, other projects' included, would enter the context of a session that can push, with nothing deterministic to test.
- A server-side digest endpoint: analysis logic in the server and a heavier redeploy for something a client computes.
- The cursor in the record's `last_event` only: pruned within a week (section 2).
- Recording the run as `command: review, attended: false` to avoid a board release: the card would say "review" and the record table of the status-board policy would bend.
- A `source` field on every ask: the `record` id already carries the command, and a title table covers the old asks.
- A flag that emits foreign text: it would make a leak one option away; it does not exist.
- Collecting the owner's `/tld:ask` messages: not wanted (owner decision), and it would need a new table.
- A fallback GitHub issue when the board is unreachable: an unattended session never creates a public issue.

## 4. Manual steps

### Before implementation

None.

### After implementation

The board host must run a release that contains phase p1, because the running board refuses the command `questions`. These steps happen after the pull request is merged and a release is cut.

**ma1-release-and-upgrade-board** (about 20 minutes).

1. After the pull request is merged, run `/tld:release` in a session on this repository ([release guide](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/question-review/docs/guides/release.md)) and approve the publish job in GitHub when it asks.
2. On the board host, back up the database as the [board guide](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/question-review/docs/guides/board-server.md) (section "Backup and restore") says.
3. On the board host run the installer line of the [delivery guide](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/question-review/docs/guides/delivery.md) for the board: `curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board`.
4. You should see the new image pulled and the board restarted. Report back: `curl -s https://<your board host>/healthz` prints `{"ok": true}` (pass or fail).

**ma2-schedule-questions** (about 10 minutes). Needs ma1 first.

1. Open <https://claude.ai/code> and open the scheduled tasks list of your account (the same place where `/tld:deps` is scheduled).
2. Create a task: the repository `tkcs-lab/tkcs-lab-devflow` attached, permission mode **auto**, the environment that has `TLD_BOARD_URL` and `TLD_BOARD_TOKEN`, weekly, at a time outside 06:00 to 09:00 Pacific, prompt `/tld:questions`. Where the variables are stored: [maintenance guide](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/question-review/docs/guides/maintenance.md), section "Scheduling".
3. Start the task once by hand. You should see a record `questions` on the board. Report back: the final reply line of the run (`questions: <n> asks, <k> findings, ...`) and whether the board shows a "Decide ..." card (pass or fail).

## 5. Risks and open questions

- **The board refuses `questions` (an older board).** A worker or the first scheduled run sees `'command' must be one of ...`: the playbook stops with the upgrade message (3.3). A worker that sees it in a phase test means a fixture is stale: stop `blocked`.
- **A leak of another project's asks.** The digest drops every field of a foreign ask except counts; the tests use only the synthetic corpus of phase p2. A worker that sees a real project slug, plan slug or ask text in a fixture or a document stops `blocked`.
- **Prompt injection through ask text.** Ask text is written by agents and can quote untrusted text. The digest masks and cuts it; the document quotes only the masked template; each `Where` is read at the pinned commit; `Fix` is the run's own wording.
- **The classifier removes a control.** The list in 3.5 is the guard; the review focus names it; the playbook's Never line repeats it.
- **A lost cursor.** Held in git (3.4). If every `review/questions-*` branch is deleted, old themes return once.
- **`foreign_count` can count one foreign ask in two runs** (the cursor follows own asks only). It only informs; it never changes a decision.
- **Truncation.** The board returns at most 1000 rows; at about 70 asks a week this holds for years. A first run on an older board sees at most 200 and says `truncated: true`; the document states it.
- **Tests that list every command.** A test that lists all commands and was not named in the briefs fails in p3a: the worker adds `questions` to that list. A test that needs a new eval task or fixture is a stop (`blocked`).
- **Existing gap, not fixed here:** `ci` is missing from `OPENING` (`src/tld/guard/plan_gate.py:19`), so with the plan gate on a scheduled `/tld:ci` run cannot write; file it as its own issue.

## Implementation manifest

```yaml
plan_slug: question-review
feature_branch: feature/question-review
tracking_issue: 53
max_parallel: 2
manual_before: []
manual_after:
  - id: ma1-release-and-upgrade-board
    title: Cut a release and upgrade the board host
    why: the running board refuses the status-record command questions and the ask record ids that name it; CI cannot upgrade the owner's board host
  - id: ma2-schedule-questions
    title: Schedule /tld:questions weekly and start it once
    why: only the owner can create a scheduled task with the board variables; the first run shows that the pipeline works on the live board
verify_after_merge:
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - "`tld plan deviations check --file docs/plans/53/deviations.md --plan docs/plans/53/plan.md --all` exits 0"
  - "the changelog has entries under docs.changelog.section and no version heading"
  - "`tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
phases:
  - id: p1-board
    title: Board side, the command questions, parse_doc_id, since and limit on the ask list
    depends_on: []
    complexity: M
    touches:
      - src/tld/board/record.py
      - src/tld/schema/status-record.schema.json
      - src/tld/board/store.py
      - src/tld/board/server.py
      - docs/guides/board-server.md
      - tests/core/test_board*.py
      - tests/core/test_contracts.py
    brief: |
      Read first: docs/plans/53/plan.md section 3.1, src/tld/board/record.py, src/tld/board/store.py, src/tld/board/server.py, docs/guides/board-server.md (the API table near line 292).
      1. In src/tld/board/record.py append "questions" to COMMANDS (line 42).
      2. In src/tld/schema/status-record.schema.json add "questions" at the end of the "command" enum and to the list in the description of "kind" (setup, review, make-plan, deps, upstream, ci, land, docs, migrate, questions).
      3. In src/tld/board/record.py add parse_doc_id(doc_id) as plan section 3.1 specifies, next to owns_doc_id, with a docstring, type hints and no change to owns_doc_id.
      4. In src/tld/board/store.py change list_asks to list_asks(self, state=None, limit=200, since=None). When since is not None add the SQL condition created_at > ? (keep the existing ordering and apply LIMIT after the filter).
      5. In src/tld/board/server.py, in _do_asks for GET, read the query parameters since and limit with parse_qs as the code already does for state. since must match the TIMESTAMP regex of tld.board.record (import it the way the module already imports from tld.board.record); limit must be a string of digits whose integer value is from 1 to 1000. A value that fails gives self._error(400, "bad_request"). Pass both to store.list_asks.
      6. In docs/guides/board-server.md change the GET /api/asks table row to `GET /api/asks[?state=open&since=<ISO>&limit=<n>]`, say that since keeps asks created after it, that limit is 1 to 1000 (default 200), and add `400 for an unknown state, a bad since or a bad limit` to the error column.
      7. Tests (extend, do not create files): in tests/core/test_board_store.py add test_list_asks_since_keeps_only_newer_asks and test_list_asks_limit_applies_after_since (copy the setup of the nearest existing list_asks test: `grep -n list_asks tests/core/test_board_store.py`); in tests/core/test_board_server.py add test_get_asks_since_and_limit and test_get_asks_rejects_bad_since_and_limit (copy the nearest GET /api/asks test); in the test file that already tests owns_doc_id (`grep -rln owns_doc_id tests/core`) add test_parse_doc_id_run, test_parse_doc_id_command_with_and_without_tail, test_parse_doc_id_rejects_unknown_command_and_bare_project; in tests/core/test_contracts.py add "questions" to the expected set of test_record_commands_cover_the_playbooks (line 271) and in the same phase to any other test that compares the schema's command enum with COMMANDS.
      8. Run `.venv/bin/python -m pytest tests -q`. A test that lists the record commands and fails only because questions is new: add questions to its expectation. Stop with status=blocked when a failing test needs a playbook or a wrapper named questions to exist: that belongs to p3a.
      Stop condition: if tests/core/test_contracts.py or a board test fails for a reason other than the new command, since or limit, stop with status=blocked and quote the failure.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_board_store.py tests/core/test_board_server.py -q passes and its output names test_list_asks_since_keeps_only_newer_asks and test_get_asks_since_and_limit when run with -v"
      - "grep -n '\"questions\"' src/tld/board/record.py src/tld/schema/status-record.schema.json prints one line in each file for the command list or enum"
      - "grep -n 'def parse_doc_id' src/tld/board/record.py prints one line"
      - ".venv/bin/python -m pytest tests -q passes"
  - id: p2-digest
    title: The digest command tld board ask-digest
    depends_on: [p1-board]
    complexity: M
    touches:
      - src/tld/board/ask_digest.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_board_ask_digest.py
      - tests/fixtures/ask-digest-corpus.json
    brief: |
      Read first: docs/plans/53/plan.md section 3.2, src/tld/board/client.py (load_config, call, ConfigError), src/tld/board/record.py (parse_doc_id, TIMESTAMP, project_slug), src/tld/cli.py (the COMMANDS table), docs/reference/cli.md (the tld board rows), stacks/python.md.
      1. Create src/tld/board/ask_digest.py with a module docstring in the style of src/tld/board/usage_client.py, and implement section 3.2 exactly: the constants, mask, words, source_of(ask), digest(asks, project, since, now) -> dict (pure, no network), fetch(config, since) -> list[dict] (GET /api/asks?limit=1000 plus &since=<ISO> when given, using tld.board.client.call; a status other than 200 raises OSError with the status), and main(argv) with the options and exit codes of section 3.2. Use only the standard library. Timestamps parse with datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").
      2. In src/tld/cli.py add after the ("board", "usage") row: ("board", "ask-digest"): ("tld.board.ask_digest", (), "digest the board's asks into clusters of similar questions for /questions"). It needs no DOC_HELP entry because main uses argparse.
      3. In docs/reference/cli.md add a row after the `tld board usage` row: `| `tld board ask-digest --project SLUG [--since ISO] [--file FILE\|-] [--now ISO]` | `tld.board.ask_digest` | digest the asks of one project into clusters of similar questions (counts only for other projects); exit 3 no board, 1 the board or the file cannot be read |`.
      4. Create tests/fixtures/ask-digest-corpus.json: {"asks": [...]} holding these 12 synthetic asks. Every ask has schema 1, kind "ask", created_by "demo", fallback_issue null, context_url null, id "a-" plus the number in 16 lowercase hex digits, a state, answers, answered_at (created_at plus the seconds named) or null. Own project "demo-app", repo "acme/demo-app". A1 to A10 are numbers 1 to 10; F1 and F2 are 17 and 18.
         A1 2026-01-05T10:00:00Z answered +60s record demo-app--run--alpha title "Start alpha": confirm id verify, text "These commands run on this machine after each merge. Run them? 1. pytest tests/core -q", answer true.
         A2 2026-01-06T10:00:00Z answered +120s record demo-app--run--beta title "Start beta": same question with "1. pytest tests/adapters -q", answer true.
         A3 2026-01-07T10:00:00Z answered +180s record demo-app--run--gamma title "Start gamma": same question with "1. pytest -x", answer true.
         A4 2026-01-08T10:00:00Z answered +30s record demo-app--make-plan--abc123 title "Plan #12: size": choice id limits, text "Which word limit should the summary have?", options w350 and w500, answer w350; text id notes, required false, text "Anything else the plan should know? One line.", no answer.
         A5 2026-01-09T10:00:00Z answered +90s record demo-app--make-plan--def456 title "Plan #13: scope": choice id scope, text "Should the scope include the website?", options no and yes, answer yes; the same notes question, answer "".
         A6 2026-01-10T10:00:00Z answered +10s record demo-app--make-plan--ghi789 title "Plan #14: names": only the notes question, answers {}.
         A7 2026-01-11T10:00:00Z cancelled, answers {}, record demo-app--review--r1 title "Review scope: decisions": confirm id d1, text "Apply the review?".
         A8 2026-01-11T10:10:00Z answered +40s record demo-app--review--r1 same title and question, answer d1 true.
         A9 2026-01-12T10:00:00Z open, answers {}, record demo-app--questions--q1 title "Questions review: 2 decisions": choice id QST-1, text "Apply this finding?", options plan and drop.
         A10 2026-01-13T10:00:00Z answered +20s record null title "Start delta": the verify confirm with "1. pytest -k fast", answer true.
         F1 2026-01-06T11:00:00Z answered +30s project other-app repo acme/other-app record other-app--run--zeta title "Start zeta": the verify confirm with "1. make test", answer true.
         F2 2026-01-09T11:00:00Z answered +30s project other-app repo acme/other-app record other-app--run--eta title "Unrelated": choice id vendor, text "Which cloud vendor account holds the staging database?", options a and b, answer a.
      5. Create tests/core/test_board_ask_digest.py (load the module the way the other board tests do: `grep -n "_load" tests/core/conftest.py tests/conftest.py`). Tests, one behaviour each: test_mask_replaces_urls_paths_numbers_slugs_and_cuts_to_160; test_digest_counts_and_cursor (asks 12, analysed 9, excluded_questions_asks 1, foreign {"asks": 2, "unmatched_questions": 1}, cursor "2026-01-13T10:00:00Z", truncated false); test_digest_groups_the_verify_confirmations (cluster c1: source "run", kind "confirm", count 4, records 4, foreign_count 1, recommended_rate 1.0, empty_rate None, median_seconds 90, first 2026-01-05T10:00:00Z, last 2026-01-13T10:00:00Z); test_digest_reports_unfilled_optional_text (the notes cluster: source "make-plan", kind "text", count 3, empty_rate 1.0, records 3); test_digest_flags_cancelled_and_reposted (the "Apply the review?" cluster: count 2, cancelled 1, reposted 1, records 1, recommended_rate 1.0, median_seconds 40); test_digest_orders_clusters_by_count (counts 4, 3, 2, 1, 1; ids c1 to c5); test_digest_since_drops_older_asks_and_keeps_foreign_rules (since 2026-01-09T10:00:00Z: A1 to A5 and F1 are gone, c1 has count 2); test_digest_emits_nothing_of_foreign_asks (the serialized digest contains none of: other-app, acme/other-app, zeta, eta, staging, vendor); test_digest_emits_no_answer_text (an answer string "SECRET-ANSWER" placed in a copy of A6 does not appear in the serialized digest); test_main_file_prints_json_and_exit_0; test_main_without_board_exits_3 (environment without TLD_BOARD_URL); test_main_unreadable_file_exits_1; test_fetch_passes_since_and_limit (monkeypatch tld.board.client.call to record the path).
      6. Run `.venv/bin/python -m pytest tests -q` (tests/core/test_cli_reference.py and tests/core/test_no_project_words.py must stay green; the module may not contain project words: the test lists them).
      Stop condition: if a fixture value above does not give the numbers in test names (for example the verify cluster has count other than 4), stop with status=blocked and quote the digest output; never change a number to make it fit.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_board_ask_digest.py -q passes"
      - ".venv/bin/python cli/tld board ask-digest --project demo-app --file tests/fixtures/ask-digest-corpus.json prints one JSON line whose clusters[0].count is 4"
      - ".venv/bin/python -m pytest tests/core/test_cli_reference.py tests/core/test_no_project_words.py -q passes"
      - ".venv/bin/python -m pytest tests -q passes"
  - id: p3a-command
    title: The playbook and wrapper for questions, the gates, the policy lines and the baseline
    depends_on: [p1-board, p2-digest]
    complexity: M
    touches:
      - playbooks/questions.md
      - adapters/claude/commands/questions.md
      - src/tld/guard/plan_gate.py
      - src/tld/guard/board_gate.py
      - docs/architecture/hooks.md
      - playbooks/policies/status-board.md
      - playbooks/policies/pr-steward.md
      - tests/core/test_contracts.py
      - tests/core/test_board_record_wording.py
      - tests/core/test_evals_fixtures.py
      - tests/adapters/claude/test_structure.py
      - tests/adapters/claude/test_hooks_compat.py
      - tests/adapters/claude/test_hooks_config.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/53/plan.md sections 3.3 to 3.6, playbooks/deps.md, playbooks/review.md (sections 0 to 5), adapters/claude/commands/deps.md, playbooks/policies/status-board.md, playbooks/policies/pr-steward.md, docs/architecture/hooks.md (lines 242-280), docs/architecture/evals.md ("Baselines and staleness").
      1. Create playbooks/questions.md: the playbook of plan section 3.3, in the structure of playbooks/deps.md (title line `# Playbook: questions`, a one-paragraph purpose, `Input:`, the rules line, the unattended exception, Setup 1 to 3, Steps 0 to 6, the final reply, Never). Include section 3.5 (avoidable, genuine, candidate thresholds, the three decisions, the control list, the 10-finding cap) as a section `## What counts as avoidable` and section 3.6 (the document format) as `## The document`. Use the exact strings of section 3.3 for replies, titles and reasons. The text must pass tests/core/test_contracts.py: no runtime tool or model name, no `/tld:`, `claude.ai`, `Artifact`, `subagent`, `get_me`, `mcp__` words; link the policies as `policies/untrusted-text.md`, `policies/status-board.md`, `policies/research.md`, `policies/profile.md` and `runtime.md` by relative Markdown links the way playbooks/deps.md does; it must contain the line `kind: command`, the text `` `attended: false` `` and the phrase `tld board record-id`; it must include a line `Open research questions:` as playbooks/deps.md does.
      2. Create adapters/claude/commands/questions.md: copy adapters/claude/commands/deps.md, replace the description by the one in plan section 3.3, add the line `model: sonnet` after it in the front matter, replace deps.md by questions.md in the playbook path and keep `$ARGUMENTS` and the sentence naming the `tld:runtime` skill; the last line is `It runs from a scheduled task: `attended: false`, no `get_session`, alerts are a push only.` The file stays under 1500 bytes.
      3. In src/tld/guard/plan_gate.py add "questions" to OPENING after "upstream". In src/tld/guard/board_gate.py add "questions" to RECORD_COMMANDS after "ci".
      4. In docs/architecture/hooks.md add `questions` to the list of opening commands (line 249) and to the list of record commands (line 278), keeping each sentence's grammar.
      5. In playbooks/policies/status-board.md add `questions` to the list of commands in line 5 (after `docs`), to the `command` row values in line 30 and to the `kind` row (the `command` kind list in line 29). Add one sentence at the end of the "When to write" bullets: `` `review apply` is the resume step of `questions`: it writes the questions record `done` when the document names it in `status_record`. ``
      6. In playbooks/policies/pr-steward.md add to the branch table (the "Kind" table) a row: `| questions | `review/questions-<yyyy-mm-dd>` | questions (kept: they are the dedupe memory of the next run) |`.
      7. Tests: add "questions" to COMMANDS (line 25) of tests/core/test_contracts.py and to each of its lists and parametrizations that already name `deps`, `ci`, `upstream` and `docs` together as scheduled playbooks (RESEARCH_PLAYBOOKS at line 303 and the parametrization at line 311); add "questions" to WRITERS in tests/core/test_board_record_wording.py; add "questions" to the tuple in tests/adapters/claude/test_structure.py (line 64-65); add ("questions", True) to the parametrization in tests/adapters/claude/test_hooks_config.py (line 196-199); in tests/adapters/claude/test_hooks_compat.py add a "questions" entry shaped like the existing "review" entry: its rows are the commands the playbook runs, with the branch `review/questions-2026-01-05`: `tld plan branch-name --review-slug questions-2026-01-05`, `git fetch origin review/questions-2026-01-05`, `git checkout -b review/questions-2026-01-05 origin/main` and `git push -u origin review/questions-2026-01-05` (copy the shape and the second column of the review rows: `grep -n "review" tests/adapters/claude/test_hooks_compat.py`). Run `.venv/bin/python -m pytest tests -q` and add `questions` to every other list that names the commands and fails only for that reason (tests/core/test_evals_fixtures.py is the one most likely).
      8. Refresh the baseline: `python3 evals/run.py baseline --refresh-hashes`, then `python3 evals/run.py check-baseline` must exit 0 and evals/baselines/default.json must now contain the key "questions.md" in command_hashes. Say in the commit message that only hashes were refreshed.
      9. Run `.venv/bin/python cli/tld ops docs-index check` (the doc rows come in p4; a warning for hooks.md length is expected, an error is not).
      Stop conditions: a test that needs a new eval task, a new fixture builder or a change outside the touches list: stop with status=blocked and quote it. If `tld board record-id --command questions` is refused (p1 not merged): stop with status=blocked.
    acceptance:
      - ".venv/bin/python -m pytest tests -q passes"
      - "python3 evals/run.py check-baseline exits 0"
      - "grep -c questions evals/baselines/default.json prints a number of 1 or more"
      - "grep -n '\"questions\"' src/tld/guard/plan_gate.py src/tld/guard/board_gate.py prints one line in each file"
      - ".venv/bin/python cli/tld plan summary-check --help exits 0 (the CLI still loads)"
  - id: p3b-review-header
    title: review apply closes the record named by status_record
    depends_on: [p3a-command]
    complexity: S
    touches:
      - playbooks/review.md
      - tests/core/test_contracts.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/53/plan.md section 3.6, playbooks/review.md sections 5 and 7.
      1. In playbooks/review.md section 5 step 2, in the yaml header block add after the `decisions_ask:` line the line `status_record: <record id, optional: set by a producer that waits for these decisions, none for review itself>`.
      2. In playbooks/review.md section 7 step 5 (`Write the final status record (done).`) append, as new sentences of the same step: `When the header has a status_record whose value is "<project>--questions" (<project> from tld board project-slug <owner>/<repo>), also write that record: tld board client get it, then set it with --if-version as done, needs_you false, needs_you_reason "", needs_you_since null, last_event "decisions applied <date>", finished_at and updated_at now. On a version conflict retry once; any other error is noted in the final reply and stops nothing.`
      3. In tests/core/test_contracts.py add test_review_playbook_closes_the_questions_record: it reads playbooks/review.md and asserts that the strings `status_record` and `--questions` both appear in it.
      4. Refresh the baseline hashes as in p3a step 8 and say so in the commit message.
      5. Run `.venv/bin/python -m pytest tests -q`.
      Stop condition: if section 7 of playbooks/review.md has no line `Write the final status record`, stop with status=blocked and quote the section's numbered steps.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_contracts.py -q passes"
      - "grep -n status_record playbooks/review.md prints two lines or more"
      - "python3 evals/run.py check-baseline exits 0"
      - ".venv/bin/python -m pytest tests -q passes"
  - id: p4-retire
    title: Retirement, the guide, the docs rows, the changelog and the plugin descriptions
    depends_on: [p3b-review-header]
    complexity: M
    touches:
      - docs/guides/questions.md
      - docs/guides/maintenance.md
      - docs/README.md
      - docs/architecture/design.md
      - README.md
      - CHANGELOG.md
      - .claude-plugin/plugin.json
      - .claude-plugin/marketplace.json
    brief: |
      Read first: docs/plans/53/plan.md sections 1, 3 and 4, docs/guides/maintenance.md, docs/README.md, playbooks/policies/docs.md, CHANGELOG.md (the top).
      1. Create docs/guides/questions.md (at most 150 lines, starts with `# Questions review` and a summary of at most 3 lines): what the weekly run does in six short steps (read, digest, classify, verify, write, ask); `tld board ask-digest` and a sample of its output fields; the fix kinds and the control list of plan section 3.5 as a table; what it never puts in a document (plan section 3.2 foreign rule); the owner's flow (answer on the board, `/tld:review apply <URL>`, `/tld:make-plan <URL>`); the stop messages (`questions: no board`, `questions: upgrade the board, it does not know the command questions`); the manual setup of plan section 4 (board upgrade, scheduled task) with the same links; why the cursor lives in git (plan section 3.4).
      2. In docs/guides/maintenance.md: change the first paragraph's `Six commands` to `Seven commands` and add `/questions` to the list and to the unattended list; add a section `### /questions` after `### /usage` (6 to 10 lines: purpose, weekly, record id `<project>--questions` unattended, needs the board release, link to guides/questions.md); in the scheduling section add `/questions` (weekly) to the list of prompts.
      3. In docs/README.md add under `## Guides`, after the `guides/maintenance.md` row, exactly: `- [guides/questions.md](guides/questions.md) - the weekly /questions run: how the board's asks become a review document of questions better tld would have avoided, the controls it never removes, privacy and scheduling; read when changing /questions or scheduling it.`
      4. In README.md add a row to the Commands table after the `/tld:usage` row: `| `/tld:questions` | weekly, unattended: reads the asks agents put to you since its last run, finds those a better playbook, profile key, role, skill, command or doc would have avoided, and writes a triaged review document for `/tld:review apply` and `/tld:make-plan` ([guide](docs/guides/questions.md)) |`.
      5. In docs/architecture/design.md, in the Playbooks paragraph add `questions` after `usage` if `usage` is listed, otherwise after `board`.
      6. In CHANGELOG.md under `## [Unreleased]` add `### Added` with two lines: `- `/questions` (`/tld:questions`): a weekly unattended command that turns the asks agents put to you into a review document of the questions a better playbook, profile key, role, skill, command or doc would have avoided; the board needs this release (new status-record command `questions`).` and `- `tld board ask-digest`, and `since` and `limit` on `GET /api/asks`: the digest groups a project's asks into clusters of similar questions and counts only for other projects.`
      7. In .claude-plugin/plugin.json and .claude-plugin/marketplace.json add `/questions` after `/usage` or, where `/usage` is not listed, after `/docs` in every description string that lists the commands.
      8. Run `.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0 (warnings about length are allowed) and `.venv/bin/python -m pytest tests -q`.
      Stop condition: if the docs-index check reports an error for a file outside the touches list, stop with status=blocked and quote it.
    acceptance:
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - "grep -c questions docs/README.md prints 1 or more"
      - "grep -n 'Unreleased' -A 6 CHANGELOG.md shows the two new lines"
      - ".venv/bin/python -m pytest tests -q passes"
```
