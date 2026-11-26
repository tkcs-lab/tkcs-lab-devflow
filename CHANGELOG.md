# Changelog

User-visible changes of tld (tkcs-lab-devflow). The release workflow (`.github/workflows/release.yml`) puts the
entry of the released version at the top of the GitHub release, above the list of merged pull requests.

## [Unreleased]

### Added

- One org base profile: a repository extends it with `tld.extends: <owner>/<repo>/<path>@<40-hex commit>` and writes only `verify.fast` and `verify.dod` (a minimal profile) plus what is its own. The base takes only allow-listed keys, is pinned by a full commit (a version tag's commit or an ancestor of the default branch head), is cached under the git directory, and is refused when it holds token-like text, anchors or aliases. `tld profile validate` refuses (and the audit reports) a repository that weakens the base's guarded keys (hooks, protect lists, gates, security posture, required roles) unless the base lists them in `tld.allow_override`. A profile with `tld.extends` needs tld 1.7 or later. See docs/guides/org-base.md.
- `tld profile base check FILE`, `fetch [PROFILE] [--ref REF]` and `latest SOURCE` check a base file, fill the cache and print the commit and tag to pin.
- Built-in defaults replace most required profile keys: `git.branch_pattern`, `git.branch_types`, `git.merge_style` (`merge-commit`), `git.main_branch` (from `origin/HEAD`), `docs.must_read`, `stacks`, `land.max_prs` (10), `git_ops.repo` (`<origin owner>/git-ops`), `deps`, `spec`, `sysml` and `release.workflow` inside their sections (an empty `spec:` turns the feature on), and `docs.index`, `docs.adr_*`, `docs.changelog`, `admin.policy` and `docs.website` when their file exists. `false` turns a defaulted feature off.
- `tld profile validate --explain` prints each resolved value with its source, and `--ref REF` reads the profile and the files that decide the defaults from a git ref.
- `tld plan summary-check --changed LIST` requires the `**Security:**` line of a pull request to name every workflow and profile file the pull request changes, and refuses risky markup in the Summary then; `implement` and `quick` pass it.
- `tld migrate . --defaults` finds a docs index, ADR directory or changelog off its default path and asks one batch: rename it (links are rewritten) or keep it with an explicit key. It also lists keys now equal to a default.
- `/tld:setup` takes `--base`, reads `TLD_BASE_PROFILE` or probes `<origin owner>/.github/tld/profile-base.yaml`, writes the pinned `tld.extends`, reads code owners, the version line and audit commands from the repository, and asks at most once (test commands it cannot find, a confirm per blocking role or audit command it proposes); the security posture is no longer asked.
- The org audit checks the base (`profile-no-extends`, `profile-invalid-extends`, `profile-pin-old` with a pin-bump pull request, `profile-guarded-override`), the merge settings against `git.merge_style` (`profile-merge-style`), the central git-ops repository (`git-ops-workflow`, `git-ops-allowlist`, `git-ops-environment`, `git-ops-token`) and where Actions secrets are held (`secrets_scope`).
- The admin audit has a `policy` check for an inherited policy: it reports what the run file or a repository override loosens, override problems, login changes and a whole old policy to convert (a pull request writes the minimal override). With `extends`, a ruleset without `required_status_checks` keeps the live checks, and a release workflow without parameters is neither installed nor rewritten.
- The admin policy can extend a pinned shared base and a private organisation file (`extends: [<owner>/<repo>/<path>@<40-hex commit>, ...]`, read through the API with the owner's token), and each repository keeps a small override file with only its own differences. `tld ops repo-admin validate-policy` takes `--kind`, `--public`, `--resolved`, `--explain`, `--offline` and `--org-policy` with `--repo-name`; `tld ops repo-admin latest-pin <owner>/<repo>/<path>` prints the pin to write. Agent and reviewer logins are derived from the repository's profile (with a `login:derived:` warning), a guarded setting an override loosens is held back and reported unless the run file's `repos.allow_loosen` allows it, and an extended file or override that holds a credential, a per-repository or organisation-level key in the wrong place, or an irreversible switch is refused. The `policy` check proposes, as pull requests, an override written from the repository's merged pull requests, tags and manifest, and converts a whole old policy file; `--no-detect` skips the detection. Policies without `extends` behave as before. See docs/guides/admin.md.

### Changed

- The plan, board and definition-of-done gates are on by default for a repository with a profile; `enabled: false` turns one off (`tld profile validate` refuses that under a base that does not allow it; the hooks do not re-check the base). The dod-gate reads `verify.dod` and `max_attempts` from the default branch's profile when one is available.
- The profile and ordinary workflows are no longer on the default protect list; the release, land and git-ops workflows stay protected in code. A pull request that changes `.tld/toolkit.yaml` or a workflow names it under Security, and the security review treats such a diff as a trust-boundary change. Guarded profile keys are clamped to the default branch's resolved profile, with a warning.
- The messages for `/deps`, `/spec`, `/sysml`, a missing main branch, `/git-ops` and the admin audit changed (an empty section turns a feature on); the profile reference, hooks, setup and admin docs describe the resolved profile.
- `/tld:setup` no longer proposes `git.branch_types` or `git.merge_style`; `tld roles required` stops when the base, or the default branch's base, is not cached.

### Behaviour changes on upgrade

1. **Gates on.** `plan_gate`, `board_gate` and `dod_gate` are on for every repository with a profile and no `hooks` value. A session no tld command started cannot write; an editing session runs `verify.dod` at stop. Turn one off with `enabled: false` (`tld profile validate` refuses it, and the audit reports it, under a base without `tld.allow_override`; the hooks apply the resolved, clamped value).
2. **`docs.plan_dir`** defaults to `docs`, except a repository with a `docs/plans` directory resolves to `docs/plans`, so in-flight plans keep working. `tld migrate --defaults` writes the explicit key.
3. **`land.max_prs` is 10** (was: no cap). Write another number, or `false` for no cap.
4. **Protect list.** The profile and ordinary workflows are no longer protected by default; a repository with its own `hooks.protect_paths` is unchanged; `protect_paths_allow` entries for workflows become moot. Pull requests touching them must name them under Security.
5. **`git.merge_style`** is `merge-commit` unless written; a squash repository must write it. The audit checks the merge settings where its policy says so.
6. **`git.branch_types`** is no longer detected: `[feature, fix, chore]` unless written, and `validate-manifest` always checks it; `tld migrate --defaults` writes the types existing manifests use.
7. **Docs paths** apply when the file exists: an existing `docs/README.md` turns on the index steps, `CHANGELOG.md` the changelog line and version-heading guard, `docs/adr/` the ADR steps, `.tld/admin-policy.yaml` the audit, `scripts/build_site.py` the website. Each is turned off with `false`.
8. **Messages** change (see above); `deps`, `spec`, `sysml` and `release.workflow` default inside their sections.

### Fixed

- The Reflektor change report page is no longer refused when a changed file holds a line or paragraph separator (U+2028, U+2029), U+0085 or a vertical tab, form feed or 0x1c-0x1f control character; a window around each is scanned again the way the viewer shows it, so a credential split around the character is still refused (#105).

## [1.6.0] - 2026-11-25

### Added

- Board cards link the run's tracking issue (`issue #<n>`) for make-plan, implement, quick and a single-session prompt's worker; new optional `tracking_issue` field of a status record, and one rule for a board that does not know an optional field (#100).
- `tld roles page-note` and `tld roles change-report` print the page note and the change-report section with it as first line.
- `/tld:quick` runs one small change end to end without a plan: tracking issue, size check (a large change is refused and sent to `/tld:make-plan`), one worker, the final review, the fix round, dod and one pull request (#88).
- `tld plan summary-check --findings N` checks the pull request's `## Non-blocking findings` section.
- /deps opens one combined pull request per run (chore/deps-<yyyymmdd>) with every green update group, security updates first; red groups are left out and named, Dependabot pull requests are never pushed to or commented on (new: tld ops deps-prepare, tld ops deps-body).
- `tld ops release-check` judges a commit's check runs and status by the rule of the `tld-release` workflow (exit 0 green, 3 still running, 1 red).
- A done make-plan status record may carry an optional `handover` object (the plan Summary, the plan slug, links bound to the record's repository and the `/tld:implement <plan URL>` command). The record validator, and so the board server, checks it; records without it validate as before.
- `tld plan handover` prints the board hand-over of a finished plan or tracking-issue body as JSON: the `## Summary` word for word, the slug, the links and the implement command, checked by the status-record rules and the secret scan (#95).
- When /tld:make-plan finishes, the board shows a "Plan ready" card with the plan's Summary, links to the issue, the plan and the spec change, and the implement command ready to copy; new `tld plan handover` and the optional `handover` field of a make-plan status record (#95).

### Changed

- After an approving final review `/tld:implement` runs one fix round: one worker fixes or declines every non-blocking finding of the final review and the dod roles, and the pull request lists each as fixed or declined with its reason (#88).

### Fixed

- The Reflektor change report page is no longer lost when the branch quotes the secret-scan allow mark: the page check scans every line with the mark's skip turned off and then shows each quoted mark as `[secret-scan mark removed]`. When the page is refused or cannot be stored the dod row says `needs attention (... ; HTML page not stored)` and the `## Change report` section starts with `HTML page not stored: <reason>` (#99).
- The release skill no longer asks for the go while the release commit's checks are running or red: it waits up to an hour, names a red check and asks nothing, asks once when the commit is green, and checks the head again right before the dispatch. The `tld-release.yml` template judges green with the same rule: update installed copies with repo-admin (one pull request per repository, never merged by tld).

## [1.5.0] - 2026-11-23

### Added

- `tld plan record-items`: prints the run record's items from a plan (every phase and `final-review`), or checks that a record lists them all.
- `/tld:spec` builds OpenSpec specs for existing code; with a spec profile block `/tld:make-plan` writes the spec change and `/tld:implement` archives it in the last phase (#71).
- `/tld:sysml` builds an architecture model in tld's SysML v2 subset (a documented subset, not checked against a SysML tool) for existing code and draws it as docs/architecture.svg on docs/architecture.md; with the optional profile block `sysml: {subset: 1}` /tld:make-plan writes the architecture change (manifest key `sysml_change`: only the last phase may touch `sysml/` and the architecture docs) and /tld:implement archives it in the last phase; `tld ops sysml new-change|check|render|archive` does the work and guards it in CI (`check`, `render --check`); `sysml` is a status-record command (`tld board record-id --command sysml`) (#81).
- A new `reflektor` role (Reflektor v0.9.1, pinned, `dod` only) that adds a last `## Change report` section to the pull request and sends an HTML report; new commands `tld roles reflektor-prepare`, `tld roles reflektor-check`, `tld roles reflektor-html` and `tld roles section` ([guide](docs/guides/reflektor.md)).
- The board stores one checked HTML report per record (`PUT`, `GET` and `DELETE /api/records/<id>/report`, `tld board client put-report`, a "Change report" link on the card); database schema version 6: back up before upgrading, an older image refuses the database.

### Changed

- `board-gate` also blocks once per ask that got no timer, and once per change (an ask, a worker start or stop, a pull request, a push) that left the status record unwritten, for every record-writing command.
- The playbooks `make-plan` and `implement` carry a mandatory "Board upkeep" rule set (the status-board policy): first record first, every item up front, extra items at once, every change is a write, every ask has a timer.
- `runtime.md` no longer tells command records to set `next_check_at`; the timer time goes into `last_event`.

### Fixed

- `board-gate`: a record write in the same command as a push no longer leaves a false "unwritten" block; parallel hooks no longer lose state updates (unique temporary file, file lock); deeply nested tool output and hook events no longer crash the hook; only a boolean `isError` marks a tool call failed.
- `tld plan record-items` rejects a `depends_on` entry that is not a phase id, quotes ids in its errors and reports a too deeply nested record with exit 2.
- Board upkeep wording: make-plan step 3 writes the record before its ask, the ask timer sentence of the already-running check sits in its ask branch, `next_check_at` is null while waiting, `--add` titles are quoted session-written labels, and the human-gate item is added only on requested changes. `hooks.md` describes `gh pr create`, the MCP-only `isError` rule and the stop chain bound as built.

## [1.4.0] - 2026-11-16

### Added

- A worker that needs a change to a protected file (the profile, a workflow) reports it; the owner approves the diff on the board and it becomes one pull request to the main branch (#62).
- The `env-check` hook and the profile key `runtime.environments`: a cloud session that runs in an environment the profile does not list gets a warning at its start and when a tld command starts. Set `TLD_ENVIRONMENT=<environment name>` in each working environment's settings, and add the key to a profile only after the release is installed (an older tld rejects it). Every tld command also checks the name through the new runtime action `environment_name()` when it loads the profile, sends one alert and carries on. Switch the hook off with `hooks.disable: [env-check]`.

### Changed

- Worker briefs start with a toolkit preamble (the path of tld, and the line "tld: unavailable" when it is missing); plan-gate opens a worker's session on a "tld-worker:" line (#62).
- tld plan validate-manifest warns about a protected path in a phase's touches, and the protect-paths denial texts point to the protected-change report (#62).

## [1.3.0] - 2026-11-14

### Added

- The board can serve its page and its sessions' API on two ports (`--api-port`, `TLD_BOARD_API_PORT`), so the page can sit behind Cloudflare Access and the API behind an IP allowlist; see `docs/guides/board-cloudflare.md`.
- `/questions` (`/tld:questions`): a weekly unattended command that turns the asks agents put to you into a review document of the questions a better playbook, profile key, role, skill, command or doc would have avoided; the board needs this release (new status-record command `questions`).
- `tld board ask-digest`, and `since`, `limit` and `order` on `GET /api/asks`: the digest groups a project's asks into clusters of similar questions and counts only for other projects.
- A review document may carry a `status_record:` header; `review apply` then closes that record.
- An attended session that asks the owner on the board now watches the ask in the background (`watch_command` with `tld board answers <id> --wait`) and wakes within about 15 seconds of the answer, instead of on its next 10-minute timer; the timer stays, every 60 minutes, as a fallback.

### Changed

- The research prompt states the 3500-character report limit first and as a hard rule, gives the report parts a budget (6 findings of 350 characters, 400 for Unknowns, 300 for the answer), and tells the researcher to count and trim before replying. `tld research report` still rejects a longer report.
- `tld board answers ID --wait S` retries an unreachable board (no connection, HTTP 429 or 5xx) until the wait ends instead of exiting 1 at once.

## [1.2.0] - 2026-11-13

### Added

- The board has a Usage page (`#usage`): for the 5-hour and the weekly window, two bars (Standard and Max, Max = 5x Standard), a 30-day history of finished windows, and a verdict whether Standard would have been enough. Set `TLD_BOARD_PLAN` (`standard` or `max`, no default) and optionally `TLD_BOARD_MAX_FACTOR` on the board host.
- `POST /api/usage` and `GET /api/usage` on the board, and `tld board usage FILE|- [--source final|scheduled]`, which sends the newest rate-limit reading. A tld command that writes a status record sends a reading when its run ends.
- `/usage` (`/tld:usage`): an unattended command at the fast level for a schedule every few hours; it sends the account's 5-hour and weekly use to the Usage page and writes no status record.
- A single-session prompt from /make-plan now shows on the status board: its worker writes a `run` record (`<project>--run--issue-<n>`, no plan link, no phases) from `starting` to `pr_open` with "Review PR #<n>", or a stop that needs you. The record validator accepts a run with `plan_url: null`.
- `/tld:release` (skill): updates the changelog and the version files in one pull request, waits for its merge and starts the release workflow after one board yes. New profile section `release` (workflow file and version files), new commands `tld ops release-prepare` and `tld guard allow-release`.

### Changed

- The board database moves to schema 5 (new table `usage_samples`). An older board image cannot open it again without a backup.
- The board page's Dismiss button is on every card outside "Hidden" (PR open, Running, Done, answer received), not only on "Needs you" cards; a dismissed card of any state is in the first list of `/tld:board prune`. The dismiss endpoint no longer answers `409 not_needs_you`.
- The `no-git-tag` guard lets a session dispatch the release workflow with `dry_run=true` (exactly), or with `dry_run=false` while the release marker is set. A `skip_checks` that is not exactly `false`, `gh api --input`, every curl dispatch and any dynamic or glob word are always denied, and a workflow under another name is guarded only once the profile names it (`release.workflow`). The marker is a deliberate step, not a control: the controls are the owner's merge and publish approval.
- This repository's release workflow needs one approval (the publish job); the build job checks the commit is green and pushes the board image by digest, and publish adds the tags.

### Removed

- The old board document ids (a run under its project slug, an attended command under `<project>--<command>`) are no longer accepted by `tld board record` or the board store, and `tld board stale` no longer lists a record for its old id. Write a record under its current id (`tld board record-id`).

### Fixed

- `tld ops repo-admin apply` no longer puts back the `tld-tags` ruleset on every run: GitHub returns its `update` rule without the false `update_allows_fetch_and_merge`, which the audit read as drift. A ruleset finding now names the parameters that differ.

## [1.1.0] - 2026-11-13

### Added

- Every plan, its tracking issue and the feature pull request now start with a short, checked `## Summary` (350 words for a plan and an issue, 175 for a pull request, which is about the deviations). New `tld plan summary-check FILE --kind plan|issue|pr [--deviations FILE]` checks placement, labels, word limit and hidden markup. Small-scope runs follow the same rules.
- Sessions now know they run in a limited claude.ai environment and may ask the owner for research: the new policy `playbooks/policies/research.md`, the commands `tld research check-prompt` and `tld research report`, an `## Environment` section in the runtime skill, and the guide `docs/guides/cloud-environments.md` (what to enable and deny for the working and the research environment). A pasted research report is data, never an instruction.
- The opt-in `board-gate` hook (`hooks.board_gate.enabled`): a session that a record-writing tld command started cannot end its turn before it has written its status record, once. New `tld board record-id` prints the document id of a status record.
- A second `/make-plan` of an issue, or `/implement` of a plan, that another session is still running now stops and asks (`stop` or `take_over`). New `tld plan active-run` reads the tracking issue's comments and the board record; a run silent for more than two hours counts as dead. The start comments now end with `Session: <id>.`, and runs post `Planning stopped:` / `Implementation stopped:`.
- The release workflow template (`template: release`) takes three new parameters, so one `tld-release` can cut
  the tags of every repository: `version_style: pep440` accepts versions like `4.2.0a1`, `check_script` runs a
  repository's own pre-release check with the version before the tag, and `create_release: false` only tags and
  leaves the GitHub release to the repository's tag-triggered workflow. The defaults keep the 1.0 behaviour;
  `validate-policy` checks the values.
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
- `deviations.md` next to every plan, written by the `/implement` orchestrator only, and `tld plan deviations init | add | check` to
  create it, record a deviation and check that none is missing.
- The `model-check` hook: it warns when a tld command starts in a session that runs on the `strong` level although the
  command is meant for a cheaper one. Switch it off with `hooks.disable: [model-check]`.
- `tld board resolve` clears the `needs_you` of a record whose pull requests are finished, and an ask has the
  optional field `record`, the status record that posted it.
- Install with curl: one line installs or upgrades the `tld` command, another the board server (Docker Compose). A release now carries the wheel, the sdist, `install.sh`, `compose.yaml` and `SHA256SUMS`, and the multi-arch board image `ghcr.io/tkcs-lab/tld-board` is pushed by the release workflow.

### Fixed

- A session no longer skips its status record when its runtime's board tools drop: the playbooks fall back to `tld board client set`.
- `tld plan check-commands` trusts a command through a `verify.after_merge_allow` prefix only when every word after
  the prefix is a safe option of that program with a plain value: tld's own (`--index`, `--json`, ...) and those a
  stack guide lists in an `after-merge-options` block (the python guide: `-q`, `-k`, `--tb=short`, ...); no
  positional word, no glob, no `@file`. Before, `--basetemp=/some/dir`, `-p <module>` or a path into `.git` ran
  without asking. `/implement` takes a start confirmation only from the owner's answer to the recorded ask,
  never from a ledger or issue comment.
- A "needs you" card on the board no longer outlives its reason: one card per wait, `answer received` once you
  answered, Dismiss and Restore on the page, and `/tld:board prune` clears cards whose pull requests are all
  merged or closed.
- The board client and repo-admin send `User-Agent: tld/<version>` instead of urllib's default, which Cloudflare's
  Browser Integrity Check refuses (error 1010), so a board behind Cloudflare is reachable from a session.
- The plan-gate now opens when a slash command reaches the hook expanded (`<command-name>/tld:...</command-name>` after `<system-reminder>` blocks), not only when it is typed as the first characters.

### Changed

- Status board: every implement run and every attended command has its own record (`<project>--run--<plan>`, `<project>--<command>--<session tail>`), so two runs or two sessions no longer replace each other's card; the old keys are accepted until 1.2.0, and `/tld:board prune` lists old-key records after 24 hours.
- `/tld:land` no longer reads its previous record (it has no per-session lookup).
- Plans now live on the feature branch at `docs/plans/<issue>/plan.md` and stay after the merge; `plan/<slug>` plans are
  deprecated for one release.
- `/make-plan` assigns the `fast` worker level to literal phases, and `validate-manifest` requires complexity S for it.
- Board: sending the answers of an ask (or cancelling it) returns to the inbox and confirms it there, instead of
  staying on the answered ask; the "← Inbox" link sits above the ask card.
- `/land` asks only for what only you can fix and lists its pull requests as items of its record.
- The board database moves to schema version 4 (dismissals). An older image refuses it: keep a backup from before
  the upgrade to roll back.
- `/implement` asks the `verify_after_merge` question only for commands the profile does not trust (a
  `verify.fast`/`verify.dod` entry, a new `verify.after_merge_allow` prefix, a `ci.dispatchable` dispatch),
  and asks nothing at the start when there are no manual steps either; new `tld plan check-commands`.
  `/make-plan` no longer adds the standing `mb0-second-user` step: implement already checks the identity.
- The CLI entry script moved from `launcher/tld` (1.0.0; `bin/tld` before) to `cli/tld`: claude.ai refuses to sync a
  plugin with a top-level `bin/` directory. A session that was open during the plugin sync may need a restart. Call
  `cli/tld` from a checkout; the installed `tld` command is unchanged.

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
