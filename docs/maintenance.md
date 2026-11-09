# Maintenance commands and the status board

Three commands keep a repository up to date and tidy without you doing the work: `/deps`, `/upstream`
and `/land`. `/deps` and `/upstream` run unattended from a scheduled task; `/land` is run by you. None
of them ever merges, approves or enables auto-merge. Each writes a status record to the board (see
below) when one exists. What the spike found about what a cloud session can and cannot do is in
[design/maintenance-spike.md](design/maintenance-spike.md).

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
closes again, and installs the workflow `.github/workflows/devflow-land.yml`. After each merge that
workflow updates the next pull request that has auto-merge enabled. You still review and approve every
pull request and enable auto-merge on each. Run `/land` yourself; no schedule runs it.

## Profile sections

All three sections are optional. A command whose section is missing stops with
`toolkit.yaml: missing required key '<key>'`. Reference: [profile-reference.md](profile-reference.md).

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

## Scheduling `/deps` and `/upstream` weekly

Create one scheduled task per repository **in the claude.ai UI, with the repository attached to the
task**, weekly, with the prompt `/deps` or `/upstream`, permission mode **auto**, and an environment
that has the variable `DEVFLOW_BOARD_URL` (see the next section). Both commands ask nothing and stop
cleanly with `needs_you` on the status record when they are unsure. Pick a time outside the hours when
you work in the repository.

Do not create these tasks from a session with `create_trigger` (or any other scheduled-task tool of a
session). Such a task has no repository, no `add_repo` and no GitHub tools, so it cannot open a pull
request and does nothing useful; only a task created in the UI with the repository attached can do the
work.

## The board

`/board` publishes one private page that shows the status record of every project: `/implement` runs and
the three maintenance commands. Run it once, store the printed URL as the environment variable
`DEVFLOW_BOARD_URL` (it is not a secret) in every environment that should write to the board, or set
`status.board_url` in a project's profile to override it for that project. The page reads the records
live, so it is published once and left alone; run `/board` again with the same file path to change the
page and keep the URL. Without a board URL the commands skip every board step.

`/board prune` lists the records the board hides (no update for more than 7 days, or finished earlier;
never one that needs you) and asks one question before it deletes them.

## What `/land` needs from GitHub

- The repository **secret** `DEVFLOW_AGENT_TOKEN`: a fine-grained token of the agent user. The workflow
  uses it instead of the default workflow token, because events caused by the default token do not start
  workflows, and CI must run on the updated branch.
- The repository **setting** "Allow auto-merge" (Settings, General, Pull Requests). `/land` cannot read
  secrets or that setting; it tells you to check both.
- The workflow itself must be merged on the default branch first. If the session's token may not push
  workflow files, `/land` opens no pull request and asks you to add
  `.github/workflows/devflow-land.yml` from the devflow template yourself.
