# claude-toolkit

A plan → implement workflow for Claude Code on the web (claude.ai/code), for any repository in any
language.

- **`/make-plan <what you want>`** (Opus) researches the repo, then writes either a self-contained
  single-session prompt (small scope) or a plan document with a YAML implementation manifest on a
  `plan/<slug>` branch (large scope), plus a step-by-step page for anything only a human can do. It
  opens a tracking issue for the ask and keeps it up to date with the plan in plain words.
- **`/implement <plan URL>`** (Sonnet) orchestrates a plan: one child cloud session per phase,
  periodic check-ins, merges into one feature branch, verification after every merge, one Opus review
  session, and one PR driven to green. It comments its progress on the tracking issue and the PR
  closes it.
- **`/dod`** runs the project's definition of done and reports a table.
- **`/review [scope]`** (Opus) reviews the whole repository, some paths, or a PR in depth: security,
  tests at the unit, integration and e2e levels, and the documentation and website (accuracy,
  validity, completeness, clarity, readability). It verifies every finding, decides itself what to
  fix and what not, and writes a review document on a `review/<slug>` branch. What only you can
  decide goes onto an interactive page (add to the plan, create an issue, or drop); once you have
  chosen, it updates the review and creates the issues. Then run `/make-plan <review URL>`.
- **`/board [prune]`** publishes the status board once: one private page with the status of every
  `/implement` run and every maintenance command. `/board prune` deletes the stale records after you
  confirm.
- **`/deps`** (scheduled, unattended) triages Dependabot pull requests and audit findings, fixes what
  is red and opens pull requests. It never merges.
- **`/upstream`** (scheduled, unattended) syncs a patch-carrying fork to the newest upstream release
  tag as one commit in one pull request.
- **`/land`** orders the bot's open pull requests, resolves conflicts before review, runs CI once on
  the combined set and installs the workflow that updates the next pull request after each merge.

See [docs/review.md](docs/review.md) for the review flow and [docs/maintenance.md](docs/maintenance.md)
for the maintenance commands and the board.

Everything specific to your project lives in one file, `.claude/toolkit.yaml` (docs to read, branch
rules, verify commands, CI workflows a session may dispatch, stacks, models). The commands contain no
project facts and stop with a message naming the missing key.

## Use it in a project

1. Copy [`templates/toolkit.yaml`](templates/toolkit.yaml) to `.claude/toolkit.yaml` and fill it in.
   Reference: [docs/profile-reference.md](docs/profile-reference.md).
2. Add the plugins in your Claude Project's settings (marketplace `andras-tkcs/claude-toolkit`), see
   [docs/delivery.md](docs/delivery.md).
3. Start a session and run `/make-plan <what you want>`.

## What is here

| Path | |
|---|---|
| `plugins/devflow` | the eight commands, the `project-profile`, `pr-steward`, `status-board`, `review-checklist`, `secure-code-review`, `test-review` and `docs-review` skills, the scripts in `scripts/` (manifest, profile and status-record validators, `review_decisions.py` with its page template, `build_board.py`, `board_stale.py`, `pick_release.py`, `upstream_sync.py`, `land_order.py`), `schema/profile.schema.json`, `schema/status-record.schema.json`, `board/` (the status board page) and `templates/` (the `/land` workflow) |
| `plugins/stack-python`, `plugins/stack-go`, `plugins/stack-swift`, `plugins/stack-ipados` | stack skills the profile selects (`ipados` goes with `swift`) |
| `templates/toolkit.yaml` | starter profile |
| `docs/` | profile reference, delivery, design, [the review flow](docs/review.md), [the maintenance commands and the board](docs/maintenance.md), [how PrivacyFence migrated](docs/migrating-privacyfence.md) |
| `tests/` | `python -m pytest tests -q` (Python 3.11+, PyYAML) |

There is no server and nothing long-running: everything runs inside Claude Code sessions.

## Development

```
python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m pytest tests -q
```

The tests include a check that no project-specific word (a particular project's name, test runner
or linter) appears in the generic plugin. Stack-specific words belong in the `plugins/stack-*` skills.
