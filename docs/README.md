# Docs index

Entry point for every doc in this repository. Read the row that matches your task, then only that doc.
Plans (`<slug>-plan.md`) are transient and not listed; a finished plan's decisions land in the docs below.

## Architecture

- [architecture/design.md](architecture/design.md) - design record: layout, decisions, what was probed and rejected; read before changing the architecture.
- [architecture/hooks.md](architecture/hooks.md) - the guardrail hooks, their configuration and the commands' compatibility; read when changing a hook.
- [architecture/agents.md](architecture/agents.md) - the ten generic agents, the profile's agents block and the points they run at; read when changing an agent or the agents block.
- [architecture/scope-drift.md](architecture/scope-drift.md) - scope-drift monitoring at each /implement merge; read when changing tld plan scope-check.
- [architecture/evals.md](architecture/evals.md) - the eval harness in evals/, tasks, graders, baselines; read when measuring a change to a command, skill or hook.
- [architecture/maintenance-spike.md](architecture/maintenance-spike.md) - what a cloud session can and cannot do; read before changing how the maintenance commands push or comment.

## Guides

- [guides/delivery.md](guides/delivery.md) - how plugins reach a cloud session through the Claude Project; read when installing or upgrading.
- [guides/docs-index.md](guides/docs-index.md) - the CLAUDE.md, index and leaf-doc structure and /docs init, check and tidy; read when touching documentation layout or the docs skills.
- [guides/review.md](guides/review.md) - the /review flow and its decisions page; read when changing /review.
- [guides/setup.md](guides/setup.md) - /setup: how it surveys a repository and writes the profile; read when changing /setup.
- [../CONTRIBUTING.md](../CONTRIBUTING.md) - setup, tests, evals and the plugin-version rule for contributors; read before your first change.
- [guides/maintenance.md](guides/maintenance.md) - /deps, /upstream, /land and /docs tidy, scheduling them, the status board; read when changing or scheduling them.
- [guides/board-server.md](guides/board-server.md) - running the self-hosted status board server; read when deploying or changing the board.
- [guides/admin.md](guides/admin.md) - repo-admin: auditing organisation and repository settings, the rulesets and the agent account; read when changing it.
- [guides/git-ops.md](guides/git-ops.md) - the central git-ops workflow for tags and branch deletion; read when changing it.
- [migrating-privacyfence.md](migrating-privacyfence.md) - how the first project moved onto the toolkit (pinned: linked from outside this repo); read when migrating another project.

## Reference

- [reference/profile-reference.md](reference/profile-reference.md) - every .tld/toolkit.yaml key, defaults and command entries; read when adding or changing a profile key.
- [reference/cli.md](reference/cli.md) - the `tld` command line: every command, its module, and the old script each one replaces; read when calling or adding a toolkit command.
