# Maintenance commands and the status board

Six commands keep a repository up to date and tidy without you doing the work: `/deps`, `/ci`, `/upstream`,
`/land`, `/docs tidy` and `/usage`. `/deps`, `/ci`, `/upstream`, `/docs tidy` and `/usage` run unattended from a scheduled task; `/land` is run by you. None
of them ever merges, approves or enables auto-merge. Each, except `/usage`, writes a status record to the board (see
below) when one exists; `/usage` writes none (see its section). What the spike found about what a cloud session can and cannot do is in
[maintenance-spike.md](../architecture/maintenance-spike.md).

## What each command does

### `/deps`

Weekly dependency triage. It lists the open Dependabot pull requests and runs the `deps.audit`
commands (a session cannot read Dependabot alerts, so audit commands are the only source of security
findings). With nothing to do it records "nothing to do" and stops. Otherwise it groups the work by
ecosystem and directory, one pull request per group, and fixes what is red: it pushes the fix onto the
Dependabot branch with a normal push, or opens `chore/deps-<ecosystem>-<yyyymmdd>` for a security
finding no Dependabot PR covers. After a bump it runs the matching `deps.lock_freshness` commands, then
`verify.fast` and `verify.dod`, and ports code and tests to the new API when they fail (never skipping
or deleting a test). The delay for ordinary updates is Dependabot's own `cooldown`; `/deps` checks that
`.github/dependabot.yml` sets `cooldown.default-days` of at least `deps.cooldown_days`. It starts no new
group after 80% of `deps.time_budget_minutes`. Release notes and audit output are untrusted text.

### `/ci`

CI watch for failures nobody is told about in a pull request: a scheduled workflow (a Pages deploy, a
canary, a nightly check) that goes red on the default branch and mails you every day. `/ci` lists the
workflows whose newest completed run on the default branch failed within `ci.lookback_hours`, reads the
failed job's logs and sorts each one:

- **repo**: it reproduces the failing step locally, fixes it on `chore/ci-<workflow>-<yyyymmdd>`, runs
  `verify.fast` and `verify.dod` and opens one pull request. Never a skipped test, a loosened check, a changed
  schedule or `continue-on-error`.
- **external**: the step passes locally or needs a secret, a hosting or CDN setting, a token or a third-party
  service. Nothing is changed. One issue `CI failing: <workflow>` and `needs_you` say which step failed, since
  when, and the one thing to look at. (Example: a post-deploy check that compares the live site's response
  headers with the repository's expectation fails after the CDN rule was not updated; no commit fixes that.)
- **transient**: a one-off `5xx` or runner error; recorded, no action. Three failures in a row count as external.

It cannot stop GitHub's failure mails; fixing or reporting the cause does. Its record is `<project>--ci`
(an unattended id, unchanged), `attended: false`.

### `/upstream`

Weekly sync of a fork that carries patches on a linear `main`. It finds the newest upstream release tag
that matches `upstream.tag_pattern` (release tags only: no prerelease, no branch, never upstream `main`),
compares it with the tag recorded in `upstream.version_file`, and stops if they are equal. Otherwise it
three-way merges the new upstream tree into the fork with the old upstream commit as the base, resolves
mechanical conflicts, runs `verify.fast` and `verify.dod`, makes one commit
`Sync <upstream.repo> <old> to <new>` and opens one pull request from `chore/upstream-<new tag>`. It
never force-pushes and never touches the upstream. The version file holds three lines: `tag:`,
`commit:` (the commit the tag points to) and `synced_at:`. Every sync pull request is left to you
(`needs_you`).

### `/land`

Prepares the open pull requests of the bot (`git.bot_login`) for review, so that nothing is left to
resolve by hand after you approve. It orders them (a pull request stacked on another comes after it;
otherwise the lowest number first), merges them in that order on a throwaway branch
`chore/land-<yyyymmdd-hhmm>`, resolves mechanical conflicts early (the same resolution is pushed to the
later pull request's own branch), runs CI once on the combined set through a draft pull request that it
closes again, and installs the workflow `.github/workflows/tld-land.yml`. After each merge that
workflow updates the next pull request that has auto-merge enabled. You still review and approve every
pull request and enable auto-merge on each. Run `/land` yourself; no schedule runs it.

### `/docs tidy`

Weekly docs cleanup (`/docs` has two more modes, `check` and `init`; see
[docs-index.md](docs-index.md)). It runs `tld ops docs-index check` and applies only mechanical fixes on
`chore/docs-tidy-<yyyymmdd>`: a row for an unlisted doc, a repointed link, a row for a deleted doc, a
missing ADR-index row. The result is one pull request, or, when only judgement items remain (stale docs,
docs over 400 lines, an index over 150 lines), an issue titled `Docs tidy: <n> items to decide` with a
checklist. It never merges, deletes, moves or edits a doc body. It writes a record with `command: docs`
and the document id `<project>--docs` (unattended, unchanged); with nothing to fix the record says `docs clean`.

### `/usage`

Every 2 hours it reads the account-wide rate-limit reading its own session has seen (the 5-hour and the weekly
window) and sends it with `tld board usage --source scheduled` to the board's Usage page
([board-server.md](board-server.md)). It writes no status record, asks nothing and posts nothing on GitHub. It
runs on the fast model level and each run spends a little of the same subscription quota; when you are idle it can
itself start a 5-hour window, which the page keeps out of the verdict (a window that stays below 5% of Standard
counts as idle). Without a reading (a scheduled session may not be allowed to read its own stream) it replies
`usage: no reading` and changes nothing. Schedule it with the cron line `7 */2 * * *`.

After a release that adds it:

1. Upgrade the board host with the installer line ([delivery.md](delivery.md)). The database moves to schema 5; keep
   a backup first (see "Backup and restore" in the board guide).
2. Add `TLD_BOARD_PLAN=max` (and, to make it explicit, `TLD_BOARD_MAX_FACTOR=5`) to `~/tld-board/.env`, then run
   `docker compose up -d` in `~/tld-board`.
3. Optional: in claude.ai add a scheduled task that runs `/tld:usage` every 2 hours. The first run shows whether a
   scheduled session may read its own stream (`usage: no reading` if not).
4. After a day compare the Max bars with https://claude.ai/settings/usage; they should agree within 5 points.

## Profile sections

All sections are optional (`/ci` runs without its `ci` keys, on their defaults). A command whose section is missing stops with
`toolkit.yaml: missing required key '<key>'`. Reference: [profile-reference.md](../reference/profile-reference.md).

```yaml
deps:
  cooldown_days: 3          # 0..30: the Dependabot cooldown your .github/dependabot.yml must set
  time_budget_minutes: 90   # 10..480: no new update group after 80% of this
  audit:                    # optional: commands that list vulnerable packages (exit 0 = none)
    - ecosystem: pip
      run: "pip-audit -r requirements.txt"
  lock_freshness:           # optional: run after a manifest change
    - when: ["pyproject.toml"]
      run: "uv lock"
      lockfiles: ["uv.lock"]
```

```yaml
ci:
  time_budget_minutes: 60   # optional, 10..480 (default 60): no new workflow after 80% of this
  lookback_hours: 36         # optional, 1..168
  ignore_workflows: []       # optional: workflow file names not watched
```

```yaml
upstream:
  repo: "owner/name"                              # the real upstream project, not the fork
  tag_pattern: "^v[0-9]+\\.[0-9]+\\.[0-9]+$"      # a release tag must match
  version_file: "UPSTREAM_VERSION"                # file in the fork that records the synced tag
```

```yaml
land:
  max_prs: 10               # optional, 1..50: most pull requests one run orders
```

`/land` also needs `git.bot_login`, the login of the account that opens the pull requests.

## Scheduling `/deps`, `/ci`, `/upstream` and `/docs tidy`

Create one scheduled task per repository **in the claude.ai UI, with the repository attached to the
task**, weekly (`/ci` daily), with the prompt `/deps`, `/ci`, `/upstream` or `/docs tidy`, permission mode **auto**, and an environment
that has the variables `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` (see the next section). All three commands ask nothing and stop
cleanly with `needs_you` on the status record when they are unsure. Pick a time outside the hours when
you work in the repository.

Do not create these tasks from a session with `create_trigger` (or any other scheduled-task tool of a
session). Such a task has no repository, no `add_repo` and no GitHub tools, so it cannot open a pull
request and does nothing useful; only a task created in the UI with the repository attached can do the
work.

The environment these tasks run in (what to enable and deny) is in [cloud-environments.md](cloud-environments.md).

## The board

The board is the self-hosted server described in [board-server.md](board-server.md): it stores the
status record of every command run that writes one (C7) and every ask a command puts to you, and serves the page you
log in to. Set two variables in every environment that should write to it: `TLD_BOARD_URL`
(not a secret) and `TLD_BOARD_TOKEN` (board-server.md says how to keep the token in a network secret). Without
them the commands skip every board step. `/board` checks the connection and reports how many records
there are; `/board prune` prunes.

A phase chip shows `drift <n>` when the phase changed `n` files outside its `touches` (and `scope ?`
when the check was unavailable): a count only, the paths are in the pull request's Scope section. What
is recorded, what is not and why it never blocks: [scope-drift.md](../architecture/scope-drift.md).

Every command except `/usage` writes a record (D8), and every run and every attended session has its own, so two runs or two
sessions never replace each other's card. `/implement` writes a `run` record under `<project>--run--<plan>`; the worker of a single-session prompt writes one under `<project>--run--issue-<n>` (no plan link, no phases); an
attended `setup`, `review`, `make-plan`, `land`, `docs init` or `migrate` writes `<project>--<command>--<session tail>`
(the last 8 letters and digits of its session id); the unattended `deps`, `ci`, `upstream` and `docs tidy` keep
`<project>--<command>`. `tld board record-id` prints the id. Until tld 1.2.0 the old keys (`<project>` for a run,
`<project>--<command>` for an attended command) are still accepted, so a run that started before the change can
finish under its old id; `/land` no longer reads its previous record. The project slug is
the repository name in lower case (`tld board project-slug <owner>/<repo>`). `attended` says whether you started the
command (`/setup`, `/review`, `/make-plan`, `/implement`, `/land`, `/docs init`, `/migrate`: `true`) or a schedule did (`/deps`,
`/upstream`, `/docs tidy`: `false`, with `orchestrator_session: null` when the session cannot read its own id). The
final states are `done`, `failed` and `pr_open`. The rules are [playbooks/policies/status-board.md](../../playbooks/policies/status-board.md).

`/board prune` makes two lists and asks one question for each that is not empty before it changes anything. The
first holds the records the board hides: no update for more than 7 days, finished earlier, or a record you
dismissed. The second holds records that still need you but name pull requests that are all
merged or closed. Prune deletes the first list and clears the second (`needs_you` off, status `done`); a record with
no pull request, or with one still open, is never offered. More in [Cards that wait](#cards-that-wait).

## Cards that wait

A "Needs you" card always means something you can still act on.

- **One card per wait.** While a session's ask is open, the page shows the ask card and no card for the run.
  Once you answer, the run leaves "Needs you" and shows `answer received` under "Running" until the session wakes
  (up to 10 minutes, or when you write in its chat) and reads the answer. If you cancel the ask instead, the
  record's card comes back until the session wakes.
- **Dismiss and Restore.** Every card outside "Hidden" has a `Dismiss` button in its details: a stuck "Needs you"
  card, or a "PR open" card whose pull requests are already merged. The card moves to "Hidden" with the badge
  `dismissed`, and `Restore` brings it back. The board keeps the dismissal next to the record. When the session
  writes the record again, the card returns by itself.
- **Prune** also clears the `needs_you` of a record whose pull requests are all merged or closed, after you
  confirm (see above).
- **You still write no record.** Dismiss, Restore and the answer never change a record; only the session writes
  it, and prune clears one through the session token after you confirmed.
- **`/land`** asks for you only when only you can fix the problem; its pull requests are items of its record.

## What `/land` needs from GitHub

- The **secret** `TLD_AGENT_TOKEN`: a fine-grained token of the agent user, stored as a secret of the
  environment `tld-agent`, which only the default branch may use (not as a repository secret). The workflow
  runs on pushes to the default branch in that environment, and uses the token instead of the default
  workflow token, because events caused by the default token do not start workflows, and CI must run on the
  updated branch. The `agent` section of the admin policy sets the environment up ([admin.md](admin.md)).
- The repository **setting** "Allow auto-merge" (Settings, General, Pull Requests). `/land` cannot read
  secrets or that setting; it tells you to check both.
- The workflow itself must be merged on the default branch first. If the session's token may not push
  workflow files, `/land` opens no pull request and asks you to add
  `.github/workflows/tld-land.yml` from the tld template yourself.
