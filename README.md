# tkcs-lab-devflow (`tld`)

A plan → implement → review workflow for coding agents, for any repository in any language, on GitHub. A plan is
researched once, split into phases with an implementation manifest, built by one worker session per phase on one
feature branch, reviewed, and delivered as one pull request that a person merges.

Everything specific to a repository lives in one file, its **profile** `.tld/toolkit.yaml`: the docs to read, the
branch rules, the verify commands, the CI workflows a session may dispatch, the stacks, the roles and the worker
levels. The procedures contain no project facts and stop with a message naming a missing key.

## Core and adapter

- **The core** is neutral about the agent runtime: a Python package with one command line, `tld`
  (`src/tld/`: profile, plan, roles, dod, guard, board, ops), and the content the agents follow: **playbooks**
  (one procedure per command, `playbooks/`), ten **roles** (a role card in `roles/` plus a checklist in
  `checklists/`), **stack guides** (`stacks/`: python, go, swift, ipados) and shared **policies**.
- **The Claude Code adapter** (`adapters/claude/`) is the plugin `tld`: each command is a few lines that say
  "follow `playbooks/<cmd>.md`", the `tld:runtime` skill maps the playbooks' runtime actions (start a worker, wait,
  ask the human, notify, GitHub) to Claude tools and the levels `strong` / `standard` / `fast` to models, one agent
  wraps each role, and the hooks call the guard.

[docs/architecture/design.md](docs/architecture/design.md) describes the concepts and why they are split this way.

## Install

In claude.ai, open the settings of the Claude Project your repository's sessions belong to, add the marketplace
`tkcs-lab/tkcs-lab-devflow` and enable the plugin `tld` (a cloud session ignores plugins a repository enables in
its own settings). In a local Claude Code:

```
/plugin install tld --marketplace tkcs-lab/tkcs-lab-devflow
```

The command line alone, for scripts, CI or a migration from a plain checkout (Python 3.11+), and the board server (Docker):

```
curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh              # the tld command
curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board  # the board (Docker)
tld --help
```

What the checksum does and does not prove: [SECURITY.md](SECURITY.md). To read the script first, download it with `curl -fsSLO <url>`, then `sh install.sh`.
Running the same line again upgrades to the latest release. To pin a version, run that release's own installer
(`curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download/vX.Y.Z/install.sh | sh`), which installs its own version.
Uninstall with `... | sh -s -- uninstall`. Without the installer:
`pip install https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download/vX.Y.Z/tld-X.Y.Z-py3-none-any.whl`. Do not `pip install tld`: that name on PyPI is
another package.

Then run `/tld:setup` in a session to create `.tld/toolkit.yaml` (one pull request, never merged), or copy
[`src/tld/templates/toolkit.yaml`](src/tld/templates/toolkit.yaml) and fill it in. The profile's `tld.version`
(`">=1.0,<2"`) says which releases it is written for. Details: [docs/guides/delivery.md](docs/guides/delivery.md).
Coming from claude-toolkit: [docs/guides/migrating-from-claude-toolkit.md](docs/guides/migrating-from-claude-toolkit.md).

## Commands

| Command | What it does |
|---|---|
| `/tld:setup [create \| update]` | surveys the repository and writes or updates the profile, including the `roles` block; asks you the posture; one pull request ([guide](docs/guides/setup.md)) |
| `/tld:make-plan <what you want>` | researches the repository, then writes a single-session prompt (small scope) or a plan with an implementation manifest on its feature branch (large scope); manual steps become an ask |
| `/tld:implement <plan URL>` | one worker session per phase, merges into one feature branch, verification after every merge, scope-drift monitoring, one final review, one pull request driven to green ([scope drift](docs/architecture/scope-drift.md)) |
| `/tld:review [scope]` | deep review of security, tests (unit, integration, e2e) and docs by the roles; verified findings in a review document on a `review/<slug>` branch; your decisions are one ask ([guide](docs/guides/review.md)) |
| `/tld:dod` | runs the profile's definition of done and reports a table |
| `/tld:land` | orders the bot's open pull requests, resolves conflicts before review, runs CI once on the set, installs the land workflow |
| `/tld:ci` | daily or weekly, unattended: finds workflows failing on the default branch, fixes what the repository can fix, reports what it cannot |
| `/tld:deps` | weekly, unattended: triages Dependabot pull requests and audit findings, fixes what is red, opens pull requests |
| `/tld:upstream` | weekly, unattended: syncs a patch-carrying fork to the newest upstream release tag, one pull request |
| `/tld:docs [check \| init \| tidy]` | a thin CLAUDE.md, one docs index, docs read only when a row matches ([guide](docs/guides/docs-index.md)) |
| `/tld:board [prune]` | checks the connection to your board, or prunes its stale records and clears cards whose pull requests are done, after you confirm |
| `/tld:migrate` | moves a repository from claude-toolkit to tld: shows the plan, writes it on a branch after you confirm, one pull request |

No command merges, approves, tags or force-pushes. Three skills run on request:
`tld:repo-admin` (audit and apply organisation and repository settings, rulesets, environments and workflows from
a policy file; [guide](docs/guides/admin.md)) and `tld:git-ops` (delete a remote branch through a central workflow;
[guide](docs/guides/git-ops.md)) and `tld:ask` (invoked as `/tld:ask`: answers a question or discusses an idea without changing anything and proposes `/tld:make-plan` for a change). The maintenance commands and scheduling: [docs/guides/maintenance.md](docs/guides/maintenance.md).

## Guardrails: seatbelt and control

- **Control: GitHub.** `tld ops repo-admin` sets up the rulesets `tld-main` (pull request with one approval,
  required checks, no force push, no deletion) and `tld-tags` (no workflow token can tag), an agent account with
  the `write` role, and the environments `tld-agent` and `tld-release` that hold `TLD_AGENT_TOKEN` and
  `TLD_RELEASE_TOKEN`. Tags have one route: the release workflow, run by the owner.
- **Seatbelt: the hooks.** `no-merge`, `no-force-push`, `no-git-tag`, `secret-scan`, `protect-paths` and the opt-in
  `dod-gate` deny the action before it runs and tell the agent what to do instead; `model-check` only warns when a session runs on the most expensive level. The protect lists and
  `hooks.disable` are read from the profile on the remote default branch. They need `python3` 3.11+ and PyYAML in
  the session, and every repository in a Project that enables `tld` needs at least `git.main_branch` in its profile.

See [docs/architecture/hooks.md](docs/architecture/hooks.md) and [SECURITY.md](SECURITY.md).

## The board: your inbox

A small server you host ([docs/guides/board-server.md](docs/guides/board-server.md)) holds a status record of every
run and the **asks**: questions, decisions and manual steps a playbook puts to you. You answer in the browser after
logging in; a session cannot answer for you. When you started the session yourself, the ask also shows in the chat and you can answer there; the session also checks the board on its own, so an answer there is picked up within minutes. Without a board, an ask becomes a comment on the tracking issue that
mentions you, and only replies by you (the repository owner or `git.owner_login`) or an admin count; the agent's own
account never does.

## Repository

| Path | |
|---|---|
| `src/tld/`, `cli/tld` | the core package and its CLI script ([CLI reference](docs/reference/cli.md)); `schema/` holds the JSON schemas of the profile, the status record, the ask and the admin policy (the implementation manifest is checked in code by `tld plan validate-manifest`), and `templates/` the starter files |
| `playbooks/`, `roles/`, `checklists/`, `stacks/` | the neutral procedures (with `runtime.md` and `policies/`), role cards, checklists and stack guides |
| `adapters/claude/` | the Claude Code plugin: commands, agents, the runtime skill, hooks, `mcp.json` |
| `.claude-plugin/` | the marketplace `tkcs-lab-devflow` and the plugin manifest (sourced from the repository root) |
| `deploy/board/` | the board server image |
| `evals/`, `tests/` | the eval harness ([docs](docs/architecture/evals.md)) and the tests |
| `docs/` | everything else, through [the docs index](docs/README.md); the profile keys are in [docs/reference/profile-reference.md](docs/reference/profile-reference.md) |

Changes per release: [CHANGELOG.md](CHANGELOG.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
Licence: Apache-2.0.
