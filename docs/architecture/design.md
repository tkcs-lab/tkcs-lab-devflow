# Design

tld is a plan → implement → review workflow for coding agents on GitHub. This document describes the design as
built in 1.0: the concepts, how they fit, what is neutral and what is the Claude adapter, and the alternatives that
were rejected. The decisions D1 to D14 it cites are recorded in
[the migration plan](../plans/tld-migration-plan.md#1-decisions).

## 1. Two halves

- **The core** knows nothing about an agent runtime. It is the Python package `tld` with one command line
  (`src/tld/`, `cli/tld`, [cli.md](../reference/cli.md)) and plain-text content: playbooks, roles, checklists,
  stacks and policies. It is neutral about Claude, not about GitHub (D4): issues, pull requests, workflows,
  rulesets and environments are GitHub's.
- **The adapter** maps the core to one runtime. The only one is Claude Code, `adapters/claude/`: commands,
  agents, the `runtime` skill, the hook entries and `mcp.json`. A second runtime would add a sibling directory,
  not change the core.

The plugin is sourced from the repository root (`.claude-plugin/marketplace.json`, `source: "./"`), so
`${CLAUDE_PLUGIN_ROOT}` holds the whole core and a command calls `"${CLAUDE_PLUGIN_ROOT}/cli/tld"` directly.
`tests/core/test_contracts.py` keeps the two halves honest: every `tld` call in a playbook or command parses with the
real CLI, every runtime action a playbook uses is defined, every role, checklist, stack and policy it names exists,
and no runtime tool or model name appears in the core content.

## 2. Concepts

### Profile

`.tld/toolkit.yaml` holds every project fact ([profile-reference.md](../reference/profile-reference.md)); the schema
is `src/tld/schema/profile.schema.json`, checked by a small hand-rolled validator (`tld profile validate`, no
`jsonschema` dependency). Required keys are few (`docs.must_read`, `git.main_branch`, `git.branch_pattern`,
`verify.fast`, `verify.dod`, `stacks`); a missing optional key means "not used here", and an unknown key is an
error so that a typo is never silent. A playbook never guesses a value: it names the missing key and stops
([policies/profile.md](../../playbooks/policies/profile.md)). `tld.version` (D9) is a version specifier checked
against the running tld, so a profile written for 1.x stops cleanly under 2.0. `/setup` writes the profile from a
survey, at text level (`tld profile patch`), so comments survive; the survey proposes and a person decides.

### Playbooks

Every procedure is a neutral playbook in `playbooks/` (D6): `setup`, `review`, `make-plan`, `implement`, `dod`,
`land`, `deps`, `upstream`, `docs`, `board`, `migrate`, and `git-ops`, `repo-admin` and `ask` (`/tld:ask`: answers without changing anything and proposes `/make-plan`), which run on request. A
playbook is plain steps: git, shell, `tld` commands, and named **runtime actions** for what only the runtime can do.
Rules that several playbooks share live once in `playbooks/policies/`: the profile, untrusted text (D10), pull
request stewardship, the status board, roles and docs.

### Runtime actions

[playbooks/runtime.md](../../playbooks/runtime.md) defines the actions a playbook may name: workers
(`start_worker`, `read_worker`, `message_worker`, `stop_worker`, `wait_for_workers` / `check_in`), roles and helpers
(`run_role`, `run_helper`), the human (`ask_human`, `notify_human`, `show_human`, `secrets_help`), time
(`schedule_wakeup`), GitHub (`github.*`, `identity`). An adapter maps each to its tools; for Claude that map is the
`tld:runtime` skill, which also holds the one table of models for the levels `strong`, `standard` and `fast`
(D11). The profile's `models.worker` / `models.reviewer` and a manifest phase's `worker_level` are levels.

### Roles and checklists

A role is the one review concept (D5): a role card `roles/<role>.md` (purpose, inputs, method, report, modes,
default level) and, for most roles, a checklist in `checklists/` (review, security, test, docs). The profile's
`roles` block says which roles are mandatory at which point (`make_plan`, `implement_phase`, `implement_final`,
`review`, `dod`), whether their findings block, and the security posture; `tld roles required` resolves it and
`tld roles verify` checks the `AGENT-REPORT` line every role ends with, so a required role that did not run fails
visibly. A role runs at most once per point, and only in review mode at the final review (C2). The Claude adapter
wraps each role as an agent. Details: [roles.md](roles.md).

### Stacks

Language and platform conventions are stack guides in `stacks/` (python, go, swift, ipados; D14), loaded by the
playbooks from the profile's `stacks`. They are the only place a tool name of a stack may appear; the
project-words test keeps the rest generic.

### Plans and manifests

A large change is a plan document with an implementation manifest: phases with `depends_on`, `touches`, `brief`,
`acceptance`, `verify_after_merge` and an optional `worker_level`, plus manual steps before and after. `tld plan
validate-manifest` checks it (cycles, unknown dependencies, overlapping `touches` within a wave, the reason for a
`strong` worker). `/implement` runs only plans of the same repository that sit on `main` or on the plan's own feature branch
(`<plan_dir>/<n>/plan.md`, S14); the owner's start confirmation is pinned by a `Plan-Started` commit trailer holding the
plan's full blob id, so a plan that changed afterwards is not run without a new start ask. Old-layout plans on
`plan/<slug>` are still accepted, with a deprecation warning. It starts
one worker per ready phase, merges each into one feature branch after a scope-drift check
([scope-drift.md](scope-drift.md)), runs `verify.fast` after every merge, and ends with one final review and one
pull request. Branch names come from `tld plan branch-name` (C12).

The orchestrator alone writes `<plan_dir>/<n>/deviations.md` next to the plan, after each merge has passed its
verification (`tld plan deviations`): one section per phase, worker text summarised and never pasted, and `check`
fails while a section still says `- pending` or an out-of-scope path is unrecorded. A phase may set `worker_level:
fast` (cheapest level) only with complexity `S`; its fix, revision and conflict workers run at `standard`. The plan
and its deviations stay in the repository as a historical record after the merge.

The Summary is the first thing a human reads in a plan, in its tracking issue and in the feature pull request, so
four decisions fix it (`tld plan summary-check`): the limits are fixed in the tool, 350 words for a plan and an
issue body and 175 for a pull request, with no profile key; the placement depends on the kind (the first `## `
section of a plan and a pull request, the `Closes` lines staying above it, and right after `## Request` in an issue
body); the labels are a closed set in a fixed order, `None.` allowed only for Deviations, Security and Performance;
and `implement` does not check a plan's Summary, because older plans have none.

### Guard

The guardrails are a neutral policy, `src/tld/guard/`: an `Action` (`shell`, `write`, `github_op`, `stop`, `prompt`) goes in,
a `Decision` (`allow`, `deny`, `error`) comes out. The Claude hooks are thin shims over it. They are a seatbelt, not
the control (D1): they deny merges, pushes to the main branch, force pushes, tags, credential-like writes and edits
of protected paths before the call runs, and they read the protect lists from the profile on the remote default
branch (the branch the remote reports, not the working tree's `git.main_branch`), pinned by commit SHA and origin
URL, so a branch, a local ref or a repointed origin cannot switch them off. What a parser cannot see (`python -c`, a script file) is out of their
reach by design. Details: [hooks.md](hooks.md).

### Ops and GitHub-side control

`src/tld/ops/` holds what talks to GitHub or the repository at large: `land-order`, `upstream-sync`,
`pick-release`, `docs-index`, `migrate` and `repo-admin`. repo-admin audits and applies a policy file and is where
the real control lives: the rulesets `tld-main` and `tld-tags`, an agent account with the `write` role (it can merge
a pull request only after `tld-main` is satisfied: the owner's approval, green required checks, stale approvals
dismissed and the last push approved by someone else; so it cannot land its own unreviewed change), and the
environments `tld-agent` and `tld-release` that hold the tokens ([admin.md](../guides/admin.md)). Tags have one
route, the release workflow `tld-release`, approved by the owner in GitHub (`TLD_RELEASE_TOKEN`); the release skill starts it after the
owner's yes, and the hook only makes that a deliberate step (D13); the central git-ops
workflow only deletes branches ([git-ops.md](../guides/git-ops.md)).

### Board

The board is a server the owner hosts (`src/tld/board/`, [board-server.md](../guides/board-server.md)) and the owner's
inbox (D7, D8): every command writes a status record (one model: `attended`, final states `done`, `failed`,
`pr_open`; C7), and every question, decision or manual step is an **ask**. The session token writes records and
posts asks; only the owner, logged in on the page, answers one (D10). When the board cannot be reached,
`tld board ask` prints a GitHub comment that mentions the owner, and only replies of the owner or a collaborator
count. Sessions reach it through `tld board client` / `ask` / `answers` or the `tld-board` MCP bridge.

## 3. Rejected alternatives

- **A SessionStart hook that installs the toolkit into `~/.claude/`.** It worked in a probe, but it needs a pin in
  every repository and a fetch at every start; plugins in the Claude Project are the one delivery route
  ([delivery.md](../guides/delivery.md)). (The `model-check` hook does use a SessionStart event, but only to record the
  session's model; it installs or fetches nothing.)
- **Separate plugins per stack, or for the agents.** One plugin and one version keep the playbooks, roles and
  guides in step.
- **Hooks as the security boundary.** A manipulated agent can run code the hooks cannot read; GitHub rulesets
  cannot be talked out of a rule (D1).
- **A second tag route through git-ops.** One route (the release workflow, approved by the owner in GitHub), one
  environment, one reviewer (D13).
- **Artifact pages for the board and for decisions.** The board must not depend on claude.ai, and an agent must not
  be able to answer for the owner. Also rejected for the board: a remote `type: http` MCP entry (its credential
  variables are read as empty), an SDK or web framework (the repository is stdlib plus PyYAML), push channels
  (records change a few times an hour), per-project tokens, and automatic expiry (pruning asks the owner once).
- **Round-tripping the profile through a YAML library.** It would drop the comments that make it readable;
  `tld profile patch` and `tld migrate` edit text and prove the result loads as intended.
- **A generated docs index.** The "read when" condition of a row cannot be derived; the index is written by hand and
  checked by `tld ops docs-index` ([docs-index.md](../guides/docs-index.md)).
- **A mutation generator.** Hand-written mutants stand for the bypasses that matter and run in minutes
  (CONTRIBUTING.md).

## 4. History

tld started as claude-toolkit: PrivacyFence's `/make-plan`, `/implement` and `/dod` lifted into a plugin
marketplace with every project fact moved into a profile ([migrating-privacyfence.md](../migrating-privacyfence.md)).
It grew the maintenance commands, the self-hosted board, the agents and `/setup`, and the docs index. A review of
claude-toolkit at 4c14071 ([../reviews/claude-toolkit-review.md](../reviews/claude-toolkit-review.md)) led to the move
into this repository in eight work packages: the layout and renames, the guard fixes, the GitHub-side control,
the neutral concepts, the board inbox, tests and CI, the evals, and the docs, migration and release. The early
design record (the delivery probe, the PrivacyFence key mapping) is in git history before 1.0.0. What a cloud
session can and cannot do, which shaped the maintenance commands, is in [maintenance-spike.md](maintenance-spike.md).
