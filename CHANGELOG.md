# Changelog

User-visible changes of tld (tkcs-lab-devflow). The release workflow (`.github/workflows/release.yml`) puts the
entry of the released version at the top of the GitHub release, above the list of merged pull requests.

## [Unreleased]

### Added

- `/ci`: an unattended CI watch for a scheduled task. It finds workflows whose newest run on the default branch
  failed (scheduled runs included, which no pull request announces), reads the logs, and sorts each failure into
  repo (reproduced and fixed on `chore/ci-<workflow>-<yyyymmdd>`, never merged), external (a CDN rule, secret or
  service: nothing changes, one issue and `needs_you` name the single thing to check) or transient. New profile
  section `ci`.
- `docs.changelog.policy` and a changelog guard in the `protect-paths` hook. Lines under `section` stay free.
  The release workflow takes the version from the `## [X.Y.Z]` heading, so the default `unreleased` denies a session
  opening a version heading, and `release-only` denies any edit, unless the change touches only the changelog (a
  separate pull request from the code and the version bump). With `release-only`, `section` is optional.
- The opt-in `plan-gate` hook (`hooks.plan_gate.enabled`): a session that no tld command started cannot write into the repository and is told to propose `/tld:make-plan`.
- The `ask` skill (`/tld:ask`): answers without changing anything and turns a change request into a `/tld:make-plan` proposal.
- Answer an ask in the chat: an attended session shows each ask in the conversation too (`tld board ask-text`), reads the owner's reply there (`tld board answers --from-reply`) and cancels the board copy, and checks the board on its own every 10 minutes for an hour, then hourly for 24 hours. Before, a board answer woke nothing and the owner had to message the session anyway.

### Fixed

- The board client and repo-admin send `User-Agent: tld/<version>` instead of urllib's default, which Cloudflare's
  Browser Integrity Check refuses (error 1010), so a board behind Cloudflare is reachable from a session.

### Changed

- `/implement` asks the `verify_after_merge` question only for commands the profile does not trust (a
  `verify.fast`/`verify.dod` entry, a new `verify.after_merge_allow` prefix, a `ci.dispatchable` dispatch),
  and asks nothing at the start when there are no manual steps either; new `tld plan check-commands`.
  `/make-plan` no longer adds the standing `mb0-second-user` step: implement already checks the identity.
- The CLI launcher moved from `bin/tld` to `launcher/tld`: claude.ai refuses to sync a plugin with a top-level `bin/`
  directory. Call `launcher/tld` from a checkout; the installed `tld` command is unchanged.

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

- A Python package and one CLI, `tld <group> <command>` (`pip install`, or `launcher/tld` from a checkout); every former
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
  workflow and tag routes, secret scan of redirects and heredocs). The trusted copy is read from the remote's
  default branch and pinned by commit, and the guards deny writes to the trusted ref, replace objects and `.git`
  internals, repointing origin, directory-level writes over protected paths, and tag or release calls through
  curl. The hooks are a seatbelt; the rulesets are the control.
- The board server caps connections (64) and drops slow clients, never locks the owner out of login (failures only
  slow down), keys IPv6 clients by /64, and keeps a logout across restarts.
- Tags have one route, the release workflow, run by the owner with `TLD_RELEASE_TOKEN`; git-ops only deletes
  branches.
- One status-record model: `attended` instead of "scheduled", final states `done`, `failed`, `pr_open`, the
  project slug from the repository name, kind `command` instead of `maintenance`.
- Roles run at most once per point and in review mode at the final review; `docs.plan_dir` defaults to
  `docs/plans/`; `tracking_issue` is optional everywhere; every playbook follows the untrusted-text policy and
  `/implement` runs only plans from `main` or a `plan/*` branch of the same repository.
- `/implement` checks a merge before pushing it and undoes a red one locally; `tld plan phase-status` ignores a
  reverted phase merge and reads human-gate approvals from `Plan-Gate-Approved` trailers, so a resumed run keeps
  them. `tld plan validate-manifest` rejects unknown keys (with a hint for `worker_model` and `manual_steps_*`).
- The issue fallback of an ask counts only the owner's and admins' replies, never the session's own login
  (`tld board answers --from-issue` needs `--self`), and skips hidden or quoted text in them.
- `tld migrate` writes `docs.plan_dir: docs/` for a profile that relied on the old default, rewrites the
  `project_steward` file, leaves profile commands that run claude-toolkit scripts alone (and lists them), and
  never follows a symbolic link.
- `/setup --accept-proposals` without an answer writes every `blocking` as `false`; `/land` also lands stacked
  pull requests and fetches every head before merging it.

### Removed

- The SessionStart delivery route and `toolkit.ref`; the profile key `status`; the Artifact decision and
  manual-steps pages; the MCP tool `board_delete`.
