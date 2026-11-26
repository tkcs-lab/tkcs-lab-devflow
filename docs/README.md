# Docs index

Entry point for every doc in this repository. Read the row that matches your task, then only that doc.
Plans (`<n>/plan.md`) and `deviations.md` are kept history, transient and not listed; a finished plan's decisions land in the docs below.

## Architecture

- [architecture/design.md](architecture/design.md) - the design: core and adapter, the concepts (profile and its resolver and base, playbooks, runtime actions, roles, stacks, plans, guard, ops, board), rejected alternatives, history; read before changing the architecture.
- [architecture/hooks.md](architecture/hooks.md) - the guardrail hooks, their configuration and the commands' compatibility; read when changing a hook.
- [architecture/hooks-parsing.md](architecture/hooks-parsing.md) - how the guards parse a shell command and the playbook commands they must allow; read when changing the parser or a playbook's git or gh commands.
- [architecture/roles.md](architecture/roles.md) - the eleven roles, the profile's roles block, the points and modes they run at; read when changing a role or the roles block.
- [architecture/scope-drift.md](architecture/scope-drift.md) - scope-drift monitoring at each /implement merge; read when changing tld plan scope-check.
- [architecture/evals.md](architecture/evals.md) - the eval harness in evals/ (neutral core, Claude adapter), tasks per command, stub mode, graders, baselines and their staleness; read when measuring a change to a command, playbook or hook.
- [architecture/evals-implement.md](architecture/evals-implement.md) - the design of the stubbed-children /implement eval (not built) and its cost; read before building it.
- [architecture/maintenance-spike.md](architecture/maintenance-spike.md) - historical record of what a cloud session can and cannot do; read before changing how the maintenance commands push or comment.
- [architecture.md](architecture.md) - the architecture model and its diagram, generated from sysml/model; read when you change how the parts of the system relate.

## Guides

- [guides/delivery.md](guides/delivery.md) - installing the plugin, the CLI and the board with the curl installer, releases and `tld.version` pinning; read when installing or upgrading.
- [guides/migrating-from-claude-toolkit.md](guides/migrating-from-claude-toolkit.md) - the owner's steps to move a repository from claude-toolkit with /migrate and tld migrate; read when migrating a repository.
- [guides/docs-index.md](guides/docs-index.md) - the CLAUDE.md, index and leaf-doc structure and /docs init, check and tidy; read when touching documentation layout or the docs skills.
- [guides/review.md](guides/review.md) - the /review flow and its decisions ask; read when changing /review.
- [guides/setup.md](guides/setup.md) - /setup: how it learns the org base, surveys a repository and writes the profile in one pull request; read when changing /setup.
- [guides/org-base.md](guides/org-base.md) - the org base profile: its content and allowed keys, pinning and bumping, the guarded keys, the behaviour changes on upgrade and the owner's manual steps; read when creating or changing a base or upgrading to 1.7.

- [../CONTRIBUTING.md](../CONTRIBUTING.md) - setup, test rules, coverage gate, mutation check, evals and baseline refresh, versions and releasing; read before your first change.
- [../CHANGELOG.md](../CHANGELOG.md) - what changed in each release; read when upgrading or releasing.
- [../SECURITY.md](../SECURITY.md) - threat model (rulesets are the control, hooks a seatbelt) and how to report; read when changing a guard or a control.
- [guides/maintenance.md](guides/maintenance.md) - /deps, /upstream, /land and /docs tidy, scheduling them, the status board; read when changing or scheduling them.
- [guides/questions.md](guides/questions.md) - the weekly /questions run: how the board's asks become a review document of questions better tld would have avoided, the controls it never removes, privacy and scheduling; read when changing /questions or scheduling it.
- [guides/spec.md](guides/spec.md) - specs with OpenSpec: the profile's spec block, /spec init and check, the spec change a plan carries and its archive; read when setting up specs or changing the spec commands.
- [guides/sysml.md](guides/sysml.md) - architecture with SysML: the profile's sysml block, /sysml init and check, the architecture change a plan carries and its archive, the subset and the generated docs/architecture.md; read when setting up the architecture model or changing the sysml commands.
- [guides/board-server.md](guides/board-server.md) - deploying and running the board server (the owner's inbox: status records, asks, login); read when deploying or changing the board.
- [guides/board-cloudflare.md](guides/board-cloudflare.md) - the board as a page host behind Cloudflare Access and an API host limited to Claude's IP ranges (--api-port); read when exposing the board through Cloudflare or changing --api-port.
- [guides/cloud-environments.md](guides/cloud-environments.md) - what to enable and deny in the working claude.ai environment and the research environment, and how to run a research request; read when setting up or changing an environment.
- [guides/reflektor.md](guides/reflektor.md) - the reflektor role: the change report in the pull request and the HTML file, how to turn it on, its safety rules and how to refresh the pin; read when using or changing the reflektor role.
- [guides/admin.md](guides/admin.md) - repo-admin: auditing organisation and repository settings, the rulesets, the agent account, the base pin, git-ops and secret scope; read when changing it.
- [guides/git-ops.md](guides/git-ops.md) - the central git-ops workflow for branch deletion; read when changing it.
- [guides/release.md](guides/release.md) - cutting a release with /tld:release: the profile's release section, the flow and the one approval in GitHub; read when releasing or changing the release skill.
- [migrating-privacyfence.md](migrating-privacyfence.md) - historical: how the first project moved onto claude-toolkit (pinned: linked from outside this repo); read for that history only.

## Core content

- [../playbooks/runtime.md](../playbooks/runtime.md) - the runtime actions the playbooks name (workers, roles, asks, GitHub) and the ask format; read when writing a playbook step or mapping one to a runtime.
- [../playbooks/policies/untrusted-text.md](../playbooks/policies/untrusted-text.md) - whose text can be an ask or an instruction; read when a playbook reads issues, comments or files.
- [../playbooks/policies/research.md](../playbooks/policies/research.md) - what a session does with a limited network and how it asks the owner for research; read when a question needs the open web or a playbook step asks the owner for outside facts.
- [../playbooks/policies/protected-changes.md](../playbooks/policies/protected-changes.md) - how a change to a protected file (secrets, lockfiles and any path a repository or base adds; the guarded workflows are never part of the flow) is reported by a worker, shown to the owner as a diff and applied as one pull request to the main branch; read when a guard denies an edit or a plan touches a protected path.
- [../playbooks/policies/findings-fix.md](../playbooks/policies/findings-fix.md) - the one fix round for the non-blocking findings after an approved final review (the list, the single worker, the diff-only re-check, what happens when it fails, the pull request section); read when changing implement's Finishing or the quick playbook.

## Reference

- [reference/profile-reference.md](reference/profile-reference.md) - every .tld/toolkit.yaml key, the built-in defaults, the base and command entries; read when adding or changing a profile key.
- [reference/cli.md](reference/cli.md) - the `tld` command line: every command (including `tld migrate`), its module, and the old script each one replaces; read when calling or adding a toolkit command.
