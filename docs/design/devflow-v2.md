# devflow v2: design brief

Status: brief, from the phase 0 experiments of 2026-11-08; all five decisions in section 11 are
resolved, and F8 and F18 are verified. Nothing in this document is built yet.
It is written to be handed to `/make-plan`. Open decisions are in section 11; section 10 is the
phase outline.

Notation: **[V]** verified by an experiment in phase 0. **[D]** stated in a tool's own
documentation but not exercised. **[A]** assumed; the phase outline says where it gets checked.

## 1. Problem statement

The owner runs Claude Code only on the web and the mobile app, with several projects at once, each
with its own `/implement` orchestrator. In priority order:

1. **Visibility.** From a phone the owner cannot tell, across all projects, which session needs
   them, what is finished, and which has opened a PR. Overnight runs overflow and get lost.
2. **Dead waiting.** An orchestrator wakes only on a `send_later` timer (about 20 minutes) and polls
   `get_session`. A phase that finishes in 6 minutes idles for 14.
3. **Identity.** Everything Claude does on GitHub is done as the owner, so the owner's review of
   Claude's PR is not a real gate. The owner wants Claude to act as a second GitHub user so that a
   codeowner review by the owner is enforced.

## 2. What phase 0 found (and where it changes the proposed direction)

| # | Finding | Evidence |
|---|---|---|
| F1 | A child that finishes cleanly does **not** wake its parent. | [V] Control child A finished 19:36:47; nothing arrived. |
| F2 | A child calling `send_message` with `session_id: "@parent"` (or the explicit id) reaches the parent as a notification in about 5 s, with the text intact. | [V] Child B sent 19:36:45, queued 19:36:50. Child D used the `@parent` alias: `{"status":"delivered"}`. |
| F3 | `send_later` fires as a notification, roughly 14 s after its minute. | [V] Set for 19:39:00, fired 19:39:14. |
| F4 | A PR subscription wakes on **check-suite completion** for a pushed head SHA (about 30 s after the push), not on the push itself, and only if CI exists. | [V] Child C pushed 19:36:56, `check_suite.completed` arrived 19:37:28, no push event. |
| F5 | An unsigned POST to a `watch_url` webhook is rejected (401). A child cannot use it as a wake path. | [V] curl returned 401. |
| F6 | `create_session` documents a `<child-session-event>` wake for a **failed** turn or a restarted worker. | [D] Not triggered in phase 0. |
| F7 | Republishing or commenting on a watched artifact wakes the watching session. | [D] The watch registered ("already registered"); no wake was triggered. |
| F8 | A child's `send_message` to `@parent` **wakes an idle orchestrator**. The orchestrator ended its turn at 20:01:30 with nothing pending; the message (sent by a child at 20:03:54) started a new turn there, before a 5-minute control timer set for 20:07. | [V] Run on 2026-11-08 after the first brief; it was [A] before. The F2 to F4 wakes had all arrived mid-turn. |
| F9 | `list_sessions` returns every session of the account, across projects, with `title`, `status_bucket` (working / blocked / review_ready / completed / failed), `post_turn_summary.recent_action`, `task_summary`, `parent_session_id`, `updated_at`, `unread`. Tag filtering is not available to in-session callers. | [V] Fields seen on live rows. Tag filter: [D]. |
| F10 | A session can rename itself with `set_session_title`. | [V] Renamed and restored this session. |
| F11 | `peek_upload_page` needs a human approval popup every call. `check_policy` says `requires_review`; the PII scan applies; `begin_unattended_session` is refused because the admin has not enabled unattended sessions. An auto-accept rule for page slug `devflow-status` (`peek.page`, verb `add`) can be proposed, but a human approves it. | [V] |
| F12 | The `Artifact` tool publishes and republishes to a stable URL with **no** approval step. `ArtifactData` writes to a page's database with **no** approval step, from the parent and from a child session. A page can render those rows live (`db` capability, `onSnapshot`). | [V] Publish, `set`, `list`, and a child `set` all succeeded unprompted, in permission mode `auto`. Live rendering on the owner's iPhone: [V] (screenshot, both rows incl. the one written by a child session). |
| F13 | A published page **cannot** use the `Claude Code Remote` connector's `list_sessions` today. The viewer shows a consent dialog, "Couldn't load this connector", and the call fails with `upstream_error: connector access isn't confirmed for this artifact right now`. | [V] Owner's iPhone, 20:43. Not retried after consent. |
| F14 | `PushNotification` exists in orchestrator and child sessions, returns "Mobile push requested", and the owner's phone buzzed. | [V] |
| F15 | Every GitHub action goes out as the owner: `get_me` returns `andras-tkcs`, the PR created through the MCP tools has author `andras-tkcs`, files committed through the MCP tools are authored `AT`, and merge commits on `main` show `AT`. | [V] |
| F16 | A session cannot delete a remote branch: `git push origin --delete` returns 403 and the GitHub MCP server has no delete-branch tool. `implement.md` section 4 step 5 ("delete the phase branch on origin") cannot work as written. | [V] |
| F17 | Tools present in a child session (Haiku, `permission_mode` inherited): `ArtifactData`, `Artifact`, `PushNotification`, `SendMessage`, `send_message`, `set_session_title`, `list_sessions`, `create_session`, `mcp__github__*`, and the PrivacyFence tools (under a different server prefix than in the orchestrator). | [V] |
| F18 | A session in a **different repository and a different environment** can write to the board's `ArtifactData` and the orchestrator can read the record back. A Haiku child on `privacyfence/.github` in the "Swift" environment wrote `projects/crossrepo-test` (version 1) with no approval prompt; the orchestrator, in `claude-toolkit` in the "Default" environment, read it back with the same content. | [V] Run on 2026-11-08; it was [A] before. Permission mode `auto` in both; other modes still untested (section 9). |

**Verdict on the proposed direction.** The split between state and view is right. Three parts
change:

- **Drop the scheduled aggregator and Peek.** Peek needs an approval per publish (F11) and the
  unattended switch is off. A scheduled aggregator session is also the thing most likely to be
  stale or to die silently. An `Artifact` page with a `db` store needs neither (F12): each
  orchestrator writes **its own document**, the page reads them live. There is no single writer to
  race, and nothing to schedule.
- **Do not build a push-to-wake channel from PR events.** `/implement` opens one PR at the very end,
  so phase completion never produces a PR event (F4).
- **The wake path exists and is cheap**: the child tells its parent (F2). Timers stay as a safety
  net only.

## 3. Goals and non-goals

Goals: one phone-readable board listing every project, led by what needs the owner; an orchestrator
that moves the moment a phase ends; a PR gate that is enforced by GitHub.

Non-goals for v2: control from the board (read-only), a comment-based command channel, replacing
`/implement`'s merge logic, cost accounting.

## 4. Status record schema

One database document per project, in collection `projects`, document id = the project slug
(`git.main_branch`'s repo name, lowercase, `[a-z0-9-]`). Written only by that project's
orchestrator, with `if_version` pinned, using `ArtifactData` `set` (whole document). Schema version
1.

```json
{
  "schema": 1,
  "project": "claude-toolkit",
  "repo": "andras-tkcs/claude-toolkit",
  "plan_slug": "devflow-v2",
  "plan_url": "https://github.com/andras-tkcs/claude-toolkit/blob/plan/devflow-v2/docs/plans/devflow-v2-plan.md",
  "feature_branch": "feature/devflow-v2",
  "orchestrator_session": "session_01...",
  "status": "running",
  "needs_you": false,
  "needs_you_reason": "",
  "needs_you_since": null,
  "phases": [
    {
      "id": "p1-wake",
      "title": "Child tells parent when done",
      "depends_on": [],
      "complexity": "S",
      "state": "merged",
      "session": "session_01...",
      "branch": "feature/devflow-v2--p1-wake",
      "started_at": "2026-11-08T20:00:00Z",
      "finished_at": "2026-11-08T20:06:10Z"
    }
  ],
  "pr": { "number": null, "url": null, "state": null, "ci": null, "awaiting": null },
  "last_event": "p1-wake merged",
  "next_check_at": "2026-11-08T20:30:00Z",
  "finished_at": null,
  "updated_at": "2026-11-08T20:06:40Z"
}
```

Field rules:

- `status`: `starting`, `running`, `waiting_user`, `reviewing`, `pr_open`, `done`, `failed`.
  `blocked` is not a status; it is `needs_you: true`.
- `needs_you` is `true` exactly when the orchestrator has asked the owner a question or has stopped
  on a failure (manual_before confirmation, a `human_gate`, a failed phase after retry, a second
  `changes` review, a PR waiting for the codeowner). `needs_you_reason` is one line, 140 characters
  at most, starting with the verb the owner must do ("Approve p2 screenshots", "Review PR #12").
- `phases[].state`: `pending`, `running`, `merged`, `failed`, `gate`.
- `pr.awaiting`: `ci`, `codeowner`, `none`.
- `next_check_at` is the time of the safety-net timer the orchestrator has armed. It is `null`
  whenever no timer is armed: status `waiting_user`, `pr_open`, `done` or `failed`, and the moment
  before the first phase starts.
- `updated_at` is written on every state change **and** on every check-in even if nothing changed
  (heartbeat).
- `finished_at` (top level, not the per-phase one) is `null` until `status` becomes `done` or
  `failed`, then the time that happened. It is written once and never changed.
- **Silent rule.** The page shows the red "silent" badge on a record only when **all** of these hold:
  `next_check_at` is not `null`; `status` is not `waiting_user`, `pr_open` or `done`; and `now -
  updated_at` is more than twice `max(next_check_at - updated_at, 5 min)`. Otherwise there is no
  badge: a record with no timer armed, or one that is waiting on the owner or on a PR, is not
  expected to heartbeat. This replaces a watchdog job.
- **Stale rule.** A record whose `updated_at` is more than 7 days old is auto-hidden from every
  section of the board, **unless `needs_you` is `true`** (an open question to the owner never
  disappears). The page shows "Hidden: n" under the Done list; tapping it lists them. Hiding only
  changes the view: the document stays in the database until the owner deletes it with
  `ArtifactData` `delete`.
- No secrets, no file contents, no commit messages. Records are readable by everyone who can open
  the board; the board is private to the owner.
- The document stays well under 1 MiB (50 phases at about 300 bytes).

A JSON Schema for this document ships with the plugin (`plugins/devflow/schema/status-record.schema.json`)
and a script validates example records in the test suite.

## 5. Wake-mechanism decision

**Decision: child-reports-parent, with a long timer as a safety net.**

1. The child brief in `implement.md` section 3 gains one rule: after the final `PHASE-REPORT` line,
   call `send_message` with `session_id: "@parent"` and the text `PHASE-REPORT <phase id>
   status=<done|blocked> head=<sha>` (the same first line). F2.
2. The orchestrator, on that wake, reads the child's session with `get_session` as today and merges.
   The `PHASE-REPORT` line stays the authority; the message is only the doorbell, so a lost or
   forged message cannot cause a merge. The orchestrator ignores a doorbell whose `session_id`
   is not one of its recorded children.
3. Failure path stays as documented (F6): a failed turn or restarted worker sends
   `<child-session-event>`. Not yet observed; phase 1 provokes one.
4. Timers become a safety net, not the clock. While a phase is `running`, arm `send_later` for
   `complexity`-sized intervals: **S: 15 min, M: 30 min**, from the child's start; re-arm after each
   check-in; on a wake from a doorbell, cancel and re-arm for the remaining running phases. If a
   child never calls `send_message` (it crashed, or ignored the rule) the timer finds it, as today.
5. Do not use PR events (F4), `watch_url` (F5) or artifact watches (F7) as phase wakes. The PR
   subscription stays for the final PR only, as in `pr-steward`.

Expected effect: a 6-minute phase is merged about 6 minutes after it starts (plus merge time),
instead of at the next 20-minute tick.

F8 is verified: an idle orchestrator is woken by the child's message, so the doorbell works while the
orchestrator waits. **If F8 ever fails** (for example after a platform change, found by a phase that
sees no wake from a message it knows was sent), the 5-minute fallback timer overrides the S and M
timers above for as long as any phase is running.

## 6. Page layout (the status board)

One `Artifact` page, private to the owner, stable URL, published once and then left alone. It does
not republish itself: it reads the `projects` collection live (`db` capability, `onSnapshot`), so a
new record appears in seconds without any publish.

Phone first (about 400 px wide), single column, light and dark.

1. **Header**: board name, a counts strip (needs you · running · PR open · done), time since the
   newest update.
2. **Needs you** (always first, hidden only when empty, in which case it says "Nothing needs you"):
   one row per project with `needs_you`, oldest first: project, one-line reason, how long it has
   waited, link to the orchestrator session.
3. **PR open**: project, PR number as a link, CI state, "awaiting codeowner" or "awaiting CI".
4. **Running**: one card per project: plan slug, phase chips in dependency order coloured by state
   (pending, running, merged, failed, gate), a "silent" badge by the silent rule in section 4 (never
   on `waiting_user`, `pr_open` or `done` records, nor when `next_check_at` is `null`).
5. **Done**: collapsed list of records with `finished_at` in the last 7 days, newest first. Below
   it, "Hidden: n" for records hidden by the stale rule in section 4.
6. **Per-project detail** (tap a card): the phase DAG as columns by dependency depth, each phase
   showing title, state, complexity, elapsed time, session link and branch; plan and PR links.

State is encoded by shape and word as well as colour. Nothing on the page writes; no buttons that
change anything.

No session list on the page: the probe (F13) failed, so the board shows only what orchestrators
write. A session that dies before it ever writes a record is invisible on the board; the "silent"
badge covers one that dies after. The board declares only `db`, so viewers never see a connector
consent dialog.

Free, no-build companion (F10): the orchestrator also renames its own session to
`[NEEDS YOU] <project> · <reason>` when it sets `needs_you`, and back when it clears it. The
claude.ai session list then shows it on the phone with no page at all.

## 7. Unattended publishing

- **Board page**: published once by a new command (`/board`, phase 3) with the `Artifact` tool,
  `capabilities: {db: {}}`. Artifact publish needs no approval [V]. The owner stores the URL once as
  the environment variable `DEVFLOW_BOARD_URL` (section 11, item 2); a project's profile may override
  it with `status.board_url`.
- **Records**: orchestrators write with `ArtifactData` (`set`/`update`, `if_version`). No approval
  was asked in `auto` permission mode [V]. Not tested in `default` mode; if `ArtifactData` prompts
  there, the orchestrator must be started in `auto`, and the profile validator warns about it [A].
- **Peek is not used.** If the owner still wants a Peek copy later, the path is a PrivacyFence
  auto-accept rule for the single slug `devflow-status` (proposed through
  `privacyfence_propose_policy_change`, approved by the owner at the PrivacyFence companion app) plus
  an administrator enabling unattended sessions. That is two manual steps for no gain over the
  Artifact page, so it is not in the plan.
- **Push alert**: on `needs_you` going from false to true, the orchestrator calls `PushNotification`
  (under 200 characters, starting with the project). Delivery to the phone is [V]: the owner's phone
  buzzed for the phase 0 test.
- **Failure of the board is never a failure of the run.** Every board write is best-effort: on any
  error the orchestrator notes it once in its own reply and carries on.

## 8. Identity changes

What the commands assume today (all of it is "the session acts as the owner", F15):

| Where | What it does | Change for a second user |
|---|---|---|
| `implement.md` intro and section 1 | Pushes the feature branch and merge commits; falls back to MCP `create_branch` when the proxy refuses | None in code. Verify the second account can push `feature/*` (write access) and cannot push `main`. |
| `implement.md` section 2 | Ledger comment on `tracking_issue` | Comment now carries the second account's name; fine, and clearer. |
| `implement.md` section 4 step 5 | "delete the phase branch on origin" | Already broken (F16). Replace with "list phase branches in the PR body for deletion"; also a manual step. |
| `implement.md` section 6 steps 3 to 4 | Opens the one PR; subscribes; drives to green | The PR author is now the second account. Add: request review from the codeowner login (`git.codeowners` in the profile), and never approve or merge. |
| `make-plan.md` sections 1 and 5 | Pushes `plan/<slug>`; creates it via MCP `create_branch` on a refused push | None in code. The plan branch is authored by the second account. |
| `pr-steward` "Which pull requests to follow" | "A PR this session opened is this session's to drive" | Add: a review requested from the owner is waiting on a person; `needs_you` is true with reason "Review PR #n". Never re-request the owner more than once per push. |
| Profile (`toolkit.yaml`) | No identity keys | Add `git.codeowners: [login]` and `git.bot_login: login` (used for a sanity check: `get_me` must equal `bot_login`, else the orchestrator stops and says so). |

Decision (section 11, item 1): sessions keep running in the owner's own claude.ai seat; only the
GitHub account connected to it changes. The owner's phone keeps seeing every session, the board and
`list_sessions`. The cost: the owner's own GitHub access from that seat goes away, so anything the
owner wants Claude to do as themselves needs the connection swapped back.

Manual checklist for the owner (goes into `/make-plan`'s `manual_before` and its HTML page):

GitHub:
1. Create the second GitHub user (its own email address, 2FA on). Put it on the team plan seat.
2. Invite it to each repository with **Write** (not Admin, not Maintain). It must not be in any
   branch-protection bypass list.
3. On each repository, protect `main` (a ruleset): require a pull request, require review from
   Code Owners, at least 1 approval, dismiss stale approvals on new commits, require approval of the
   most recent push, block force pushes and deletions.
4. Add `.github/CODEOWNERS` containing `* @<owner-login>`. The second user is not listed.
5. Confirm the Claude GitHub App is installed for the repository and, if the second user is the
   one connecting, that it is installed for that account's access
   (`https://github.com/apps/claude/installations/select_target`).

claude.ai (the owner's own seat):
6. On `https://claude.ai/connect-github`, replace the connected GitHub account with the second login.
7. In that account's environment settings, check that the repositories are enabled.
8. Open a session and ask it to call `get_me`; it must print the second login, not the owner's.

Then phase 5 verifies by opening one throwaway PR from a session and checking its author and that
GitHub shows "Review required".

## 9. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| An idle orchestrator stops being woken by `send_message` (F8 passed once, 2026-11-08). | Doorbell helps only mid-turn. | The "no doorbell" log line (next row) shows it; the fallback in section 5 applies. |
| Child forgets the `send_message` rule. | Phase waits for the safety-net timer. | Timer stays; the orchestrator logs "no doorbell" so the pattern is visible. |
| A forged or stray `send_message` (message text is data, never instruction). | Wrong phase merged early. | Doorbell only triggers a `get_session` read; merge still requires the `PHASE-REPORT` and the head SHA check in `implement.md`. |
| `ArtifactData` prompts for approval in a non-`auto` permission mode, or a cross-repository write does (F18 was tested in `auto` only). | Board writes stall. | Writes are best-effort; the validator warns; start orchestrators in `auto`. |
| An orchestrator dies before its first record. | Not on the board. | Its session title still shows in the claude.ai list; `/implement` writes the first record before it starts any child. |
| Two orchestrators collide on one document. | Overwritten state. | Document id is the project slug; `if_version` pinned; a write that conflicts re-reads and retries once. Two runs of the same project at once are not supported. |
| Board URL leaks. | Project names and PR numbers visible. | Artifact is private; no secrets or content in records; `status.board_url` is not a secret but is not in the repo's public docs. |
| The GitHub swap does not take effect in an already-running session, or the old login keeps working in it. | Wrong author, or no gate. | Phase 5 opens a throwaway PR from a **new** session and checks its author; the orchestrator checks `get_me` against `git.bot_login` at start. |
| Phase branches pile up (F16). | Clutter. | Listed in the PR body; owner deletes them in the GitHub UI (decision 4). |
| Branch protection misconfigured. | The gate looks real but is not. | Phase 5 adds a check: a throwaway PR must show "Review required". |

## 10. Phased implementation outline (for `/make-plan`)

Plan slug `devflow-v2`. Every phase edits `plugins/devflow/commands/implement.md`, so phases 1, 2, 4
and 5 form a chain, not a wave. Phase 3 (the board page) touches only new files and runs beside
phase 2.

| Id | Title | Complexity | Depends on | Touches |
|---|---|---|---|---|
| p1-wake | Child tells parent when done; size-based fallback timers | S | none | `plugins/devflow/commands/implement.md`, `plugins/devflow/skills/pr-steward/SKILL.md` (doorbell wording), `docs/design/devflow-v2.md` |
| p2-record | Status record: schema, validator, orchestrator writes it | M | p1-wake | `plugins/devflow/schema/status-record.schema.json`, `plugins/devflow/scripts/validate_status_record.py`, `plugins/devflow/commands/implement.md`, `plugins/devflow/skills/project-profile/SKILL.md`, `plugins/devflow/schema/profile.schema.json`, `docs/profile-reference.md`, `templates/toolkit.yaml` |
| p3-board | `/board` command and the page | M | none | `plugins/devflow/commands/board.md`, `plugins/devflow/board/board.html`, `plugins/devflow/scripts/build_board.py`, tests under the plugin's test directory |
| p4-alerts | `needs_you`: title rename and push | S | p2-record | `plugins/devflow/commands/implement.md` |
| p5-identity | Second GitHub user: profile keys, reviewer request, steward rule, manual steps page | M | p4-alerts | `plugins/devflow/commands/implement.md`, `plugins/devflow/commands/make-plan.md`, `plugins/devflow/skills/pr-steward/SKILL.md`, `plugins/devflow/schema/profile.schema.json`, `docs/profile-reference.md`, `templates/toolkit.yaml`, `docs/delivery.md` |
| p6-retire | Docs, changelog, delete this brief | S | p3-board, p5-identity | `docs/design.md`, `docs/delivery.md`, `docs/design/devflow-v2.md`, plugin version files |

Per phase notes (the planner writes the briefs):

- **p1-wake.** F8 is already verified, so the phase does not re-test it. Acceptance: `implement.md`
  contains the `send_message` rule with `@parent`; contains S/M timer values; `validate_manifest.py`
  still passes on the toolkit's own example plan.
- **p2-record.** Acceptance: the validator accepts the example in section 4 and rejects a record with
  `needs_you: true` and an empty reason, an unknown `status`, a missing `updated_at`, a `done` or
  `failed` record with `finished_at: null`, and a `running` record with `finished_at` set.
  `implement.md` gets a "Status board" section: when to write (each state change, each check-in),
  what to write, that failures are best-effort. The orchestrator reads `DEVFLOW_BOARD_URL`, or the profile's optional `status.board_url` when set;
  neither present means "no board, skip silently".
- **p3-board.** `board.html` is a template; `build_board.py` fills in the title and capability
  block and writes the file; `/board` publishes it with `Artifact` (`capabilities: {db: {}}`) and
  prints the URL. Acceptance: opens in the artifact emulator against a fixture of 8 records (every
  status, plus the two below), no console errors, "Needs you" is first, no horizontal scroll at
  400 px, both themes; and:
  - a fixture record with `updated_at` 8 days old and `needs_you: false` is absent from every
    section and counted in "Hidden: 1"; the same record with `needs_you: true` is shown in "Needs
    you";
  - a fixture `done` record with `finished_at` 3 days old is in Done, one with `finished_at` 8 days
    old is not;
  - the silent badge shows on a `running` record 3 hours past its heartbeat, and on none of: a
    `waiting_user`, a `pr_open`, a `done`, or a `running` record with `next_check_at: null`.
- **p4-alerts.** Wording only plus a table of exact title strings. Acceptance: grep for each string.
- **p5-identity.** `git.codeowners` and `git.bot_login`; `implement.md` section 6 requests the
  review; `pr-steward` rule; `make-plan.md` gets a standing optional `manual_before` item
  ("second GitHub user ready") when the profile has `git.bot_login`. The HTML steps page from
  `make-plan` section 3 covers section 8's checklist. Acceptance includes `get_me` equals
  `bot_login` check written into the orchestrator's start.
- **p6-retire.** Per the toolkit's own convention for retirement phases.

`manual_before` for the plan: decision 1 resolved and the identity checklist in section 8 done up
to step 5. `manual_after`: open the board on the phone once; confirm the push arrived; open a
throwaway PR from the second user and confirm "Review required".

## 11. Open decisions

Ask the owner one at a time, in this order.

1. ~~Which Claude account runs the sessions?~~ Resolved by the owner: the same claude.ai seat, with
   its connected GitHub account replaced by the second user. Still [A] until phase 5 confirms that
   the swap takes effect in new sessions (`get_me` prints the second login) and that the old
   login's access is gone from them.
2. ~~Where does the board URL live?~~ Resolved by the owner: a claude.ai environment variable
   `DEVFLOW_BOARD_URL`, set once in the environment settings (not in the repo). The profile key
   `status.board_url` stays as an optional per-project override. Variables are read at session start,
   so a session started before the variable was set has none; it skips the board silently.
3. ~~Does the board show `list_sessions` orphans?~~ Resolved: no. The probe failed (F13).
4. ~~Phase branches.~~ Resolved by the owner: leave them on origin and list them in the PR body; the
   owner deletes them in the GitHub UI. `implement.md` section 4 step 5 loses its "delete the phase
   branch" clause and section 6 step 3 gains a "Branches left on origin" list in the PR body.
5. ~~Timer values.~~ Resolved by the owner: S 15 min, M 30 min. The F8 fallback is in section 5.

## 12. Cleanup left behind by phase 0

- Throwaway PR #5 (closed) and branches `spike/wake-base`, `spike/wake-head` on origin: session
  cannot delete them (F16). Delete in the GitHub UI.
- Spike artifact "Spike Status" (https://claude.ai/artifact/DTJ79b6pxEX5k7UCZrB6yE): the probe has
  been run; delete it whenever you like.
- All four child sessions are archived.
