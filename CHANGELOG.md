# Changelog

User-visible changes of tld (tkcs-lab-devflow). The release workflow (`.github/workflows/release.yml`) puts the
entry of the released version at the top of the GitHub release, above the list of merged pull requests.

## [1.0.0] - 2026-11-11

The first release as tkcs-lab-devflow. It replaces claude-toolkit (the `devflow` plugin, last at 0.8.0), which
gets no more changes. Migrate a repository with `/tld:migrate` or `tld migrate`; see
[docs/guides/migrating-from-claude-toolkit.md](docs/guides/migrating-from-claude-toolkit.md).

### Renamed (nothing reads the old names)

- Marketplace `tkcs-lab/tkcs-lab-devflow`, one plugin `tld`: `/devflow:<cmd>` is `/tld:<cmd>`, skills and agents
  are `tld:<name>`; the `stack-*` plugins are stack guides in `stacks/`, selected by the profile's `stacks`.
- `.claude/toolkit.yaml` is `.tld/toolkit.yaml`; the profile key `agents` is `roles` (entries `role:`);
  `DEVFLOW_*` variables and secrets are `TLD_*`; `devflow-*.yml` workflows are `tld-*.yml`; hook state lives in
  `.git/tld`; the board's MCP server is `tld-board`.
- `models` takes levels (`strong`, `standard`, `fast`) instead of model names; `models.planner` and
  `models.orchestrator` are gone. A manifest's `worker_model` is `worker_level`.

### Added

- A Python package and one CLI, `tld <group> <command>` (`pip install`, or `bin/tld` from a checkout); every former
  script is a `tld` command ([docs/reference/cli.md](docs/reference/cli.md)). `tld migrate` moves a repository over.
- A neutral core: playbooks (one per command, plus git-ops and repo-admin), ten roles (role card plus checklist),
  checklists, stack guides and policies. The Claude Code plugin is a thin adapter that maps the playbooks' runtime
  actions to Claude tools and levels to models.
- `tld.version` in the profile, checked against the running tld.
- The board as the owner's inbox: asks (questions, decisions, manual steps) answered in the browser after an owner
  login, with a GitHub issue comment as the fallback when the board cannot be reached. Asks replace the
  `/review` decisions page and the `/make-plan` manual-steps page. Every command writes a status record.
- GitHub-side control in repo-admin: the rulesets `tld-main` and `tld-tags`, an agent account with the `write`
  role, and the environments `tld-agent` and `tld-release` for the tokens.
- CI: pytest on Python 3.11 and 3.13 with a branch-coverage floor, required browser tests, `claude plugin validate`,
  the validators on the fixtures, the evals in stub mode, and a weekly mutation check.
- A release workflow for this repository and `/tld:migrate`.

### Changed

- Guardrail hooks: a neutral Action/Decision core with a Claude adapter. The critical and high bypasses found in the
  review are closed (trusted profile from the default branch, dynamic push targets, config injection, wrappers,
  workflow and tag routes, secret scan of redirects and heredocs). The hooks are a seatbelt; the rulesets are the
  control.
- Tags have one route, the release workflow, run by the owner with `TLD_RELEASE_TOKEN`; git-ops only deletes
  branches.
- One status-record model: `attended` instead of "scheduled", final states `done`, `failed`, `pr_open`, the
  project slug from the repository name, kind `command` instead of `maintenance`.
- Roles run at most once per point and in review mode at the final review; `docs.plan_dir` defaults to
  `docs/plans/`; `tracking_issue` is optional everywhere; every playbook follows the untrusted-text policy and
  `/implement` runs only plans from `main` or a `plan/*` branch of the same repository.

### Removed

- The SessionStart delivery route and `toolkit.ref`; the profile key `status`; the Artifact decision and
  manual-steps pages; the MCP tool `board_delete`.
