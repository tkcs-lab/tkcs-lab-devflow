# Docs index

Entry point for every doc in this repository. Read the row that matches your task, then only that doc.
Plans (`<n>/plan.md`) and `deviations.md` are kept history, transient and not listed; a finished plan's decisions land in the docs below.

## Architecture

- [architecture/design.md](architecture/design.md) - the design: core and adapter, the concepts (profile, playbooks, runtime actions, roles, stacks, plans, guard, ops, board), rejected alternatives, history; read before changing the architecture.
- [architecture/hooks.md](architecture/hooks.md) - the guardrail hooks, their configuration and the commands' compatibility; read when changing a hook.
- [architecture/hooks-parsing.md](architecture/hooks-parsing.md) - how the guards parse a shell command and the playbook commands they must allow; read when changing the parser or a playbook's git or gh commands.
- [architecture/roles.md](architecture/roles.md) - the ten roles, the profile's roles block, the points and modes they run at; read when changing a role or the roles block.
- [architecture/scope-drift.md](architecture/scope-drift.md) - scope-drift monitoring at each /implement merge; read when changing tld plan scope-check.
- [architecture/evals.md](architecture/evals.md) - the eval harness in evals/ (neutral core, Claude adapter), tasks per command, stub mode, graders, baselines and their staleness; read when measuring a change to a command, playbook or hook.
- [architecture/evals-implement.md](architecture/evals-implement.md) - the design of the stubbed-children /implement eval (not built) and its cost; read before building it.
- [architecture/maintenance-spike.md](architecture/maintenance-spike.md) - historical record of what a cloud session can and cannot do; read before changing how the maintenance commands push or comment.

## Guides

- [guides/delivery.md](guides/delivery.md) - installing the plugin, the CLI and the board with the curl installer, releases and `tld.version` pinning; read when installing or upgrading.
- [guides/migrating-from-claude-toolkit.md](guides/migrating-from-claude-toolkit.md) - the owner's steps to move a repository from claude-toolkit with /migrate and tld migrate; read when migrating a repository.
- [guides/docs-index.md](guides/docs-index.md) - the CLAUDE.md, index and leaf-doc structure and /docs init, check and tidy; read when touching documentation layout or the docs skills.
- [guides/review.md](guides/review.md) - the /review flow and its decisions ask; read when changing /review.
- [guides/setup.md](guides/setup.md) - /setup: how it surveys a repository and writes the profile; read when changing /setup.
- [../CONTRIBUTING.md](../CONTRIBUTING.md) - setup, test rules, coverage gate, mutation check, evals and baseline refresh, versions and releasing; read before your first change.
- [../CHANGELOG.md](../CHANGELOG.md) - what changed in each release; read when upgrading or releasing.
- [../SECURITY.md](../SECURITY.md) - threat model (rulesets are the control, hooks a seatbelt) and how to report; read when changing a guard or a control.
- [guides/maintenance.md](guides/maintenance.md) - /deps, /upstream, /land and /docs tidy, scheduling them, the status board; read when changing or scheduling them.
- [guides/questions.md](guides/questions.md) - the weekly /questions run: how the board's asks become a review document of questions better tld would have avoided, the controls it never removes, privacy and scheduling; read when changing /questions or scheduling it.
- [guides/board-server.md](guides/board-server.md) - deploying and running the board server (the owner's inbox: status records, asks, login); read when deploying or changing the board.
- [guides/cloud-environments.md](guides/cloud-environments.md) - what to enable and deny in the working claude.ai environment and the research environment, and how to run a research request; read when setting up or changing an environment.
- [guides/admin.md](guides/admin.md) - repo-admin: auditing organisation and repository settings, the rulesets and the agent account; read when changing it.
- [guides/git-ops.md](guides/git-ops.md) - the central git-ops workflow for branch deletion; read when changing it.
- [guides/release.md](guides/release.md) - cutting a release with /tld:release: the profile's release section, the flow and the one approval in GitHub; read when releasing or changing the release skill.
- [migrating-privacyfence.md](migrating-privacyfence.md) - historical: how the first project moved onto claude-toolkit (pinned: linked from outside this repo); read for that history only.

## Core content

- [../playbooks/runtime.md](../playbooks/runtime.md) - the runtime actions the playbooks name (workers, roles, asks, GitHub) and the ask format; read when writing a playbook step or mapping one to a runtime.
- [../playbooks/policies/untrusted-text.md](../playbooks/policies/untrusted-text.md) - whose text can be an ask or an instruction; read when a playbook reads issues, comments or files.
- [../playbooks/policies/research.md](../playbooks/policies/research.md) - what a session does with a limited network and how it asks the owner for research; read when a question needs the open web or a playbook step asks the owner for outside facts.

## Reference

- [reference/profile-reference.md](reference/profile-reference.md) - every .tld/toolkit.yaml key, defaults and command entries; read when adding or changing a profile key.
- [reference/cli.md](reference/cli.md) - the `tld` command line: every command (including `tld migrate`), its module, and the old script each one replaces; read when calling or adding a toolkit command.
