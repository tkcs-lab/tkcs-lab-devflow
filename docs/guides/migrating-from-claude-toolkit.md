# Migrating a repository from claude-toolkit

claude-toolkit (the `devflow` plugin) is retired; tld replaces it and reads none of its names. Do this once per
repository that has a `.claude/toolkit.yaml`, then once per Claude Project. Each repository takes about ten
minutes plus your review of one pull request.

## What changes

| claude-toolkit | tld |
|---|---|
| marketplace `claude-toolkit`, plugins `devflow` and `stack-*` | marketplace `tkcs-lab/tkcs-lab-devflow`, one plugin `tld` (the stacks are guides inside it) |
| `/devflow:<cmd>`, skills `devflow:<name>` | `/tld:<cmd>`, `tld:<name>` |
| `.claude/toolkit.yaml` | `.tld/toolkit.yaml` |
| profile `agents:` with `agent:` entries | `roles:` with `role:` entries |
| `models.*`: `opus`, `sonnet` (and `planner`, `orchestrator`) | levels `strong`, `standard`, `fast` (`worker`, `reviewer` only) |
| manifest `worker_model: opus` | `worker_level: strong` |
| `DEVFLOW_*` secrets and variables | `TLD_*` |
| `.github/workflows/devflow-{land,release,git-ops}.yml` | `tld-{land,release,git-ops}.yml` (release only through the `tld-release` environment; git-ops cannot tag) |
| no version pin | `tld.version: ">=1.0,<2"` in the profile |
| `docs.plan_dir` unset meant `docs/` | `docs.plan_dir: docs/` is written explicitly (tld's own default is `docs/plans/`) |

## Per repository

1. **Enable tld for the session you migrate from.** In the repository's Claude Project add the marketplace
   `tkcs-lab/tkcs-lab-devflow` and enable `tld` ([delivery.md](delivery.md)). Leave `devflow` on until every
   repository of the Project is migrated, or migrate them all in one go.
2. **Run `/tld:migrate`** in a session on the repository. It runs `tld migrate .` (a dry run) and shows you the
   plan, the validation of the migrated profile and your checklist. Without a Claude session, run the same from a
   checkout: `pip install git+https://github.com/tkcs-lab/tkcs-lab-devflow` and then `tld migrate .`
   (`tld migrate . --write` applies it and stages the changes; it never commits).
3. **Confirm the ask.** On yes the session writes the migration on `chore/tld-migrate` and opens one pull request.
   It never merges it. The pull request lists what changed, the validator's result and your checklist.
4. **Review and merge the pull request.** Check the profile diff (comments are kept; when a section could not be
   edited in place the pull request says the profile was rewritten from its data) and the workflow files: they are
   the current tld templates, not edits of the old ones.
5. **Work through the checklist** (also posted to the board as an ask you can tick):
   - Claude Project: remove the marketplace `claude-toolkit`, keep `tkcs-lab/tkcs-lab-devflow`, enable `tld`,
     disable `devflow` and the `stack-*` plugins.
   - Secrets: rename `DEVFLOW_*` to `TLD_*`. `TLD_AGENT_TOKEN` goes into the environment `tld-agent` and
     `TLD_RELEASE_TOKEN` into `tld-release`, both limited to the main branch; delete the repository-level copies.
     Other workflows that still read a `DEVFLOW_*` secret are listed by name: rename it there too.
   - Board: deploy the board ([board-server.md](board-server.md)), set `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` in
     the cloud environment, and allow the board's host in its network settings. Until then asks fall back to a
     comment on the tracking issue.
   - GitHub control: with an owner token, `tld ops repo-admin audit --policy <policy>` and then
     `tld ops repo-admin apply --policy <policy> --yes` for the rulesets `tld-main` and `tld-tags` and the
     environments ([admin.md](admin.md#rulesets-the-agent-account-and-the-environments)).
   - Leftovers it found: `.claude/admin-policy.yaml` (move it to `.tld/admin-policy.yaml` and update
     `admin.policy`), the `.claude/devflow` script root, a `.claude/settings.json` that still names devflow, and
     every profile command (for example a `verify.dod` entry) that still runs a script under `plugins/devflow/`
     or `.claude/devflow/`: those are left unchanged, replace each with its `tld` command
     ([cli.md](../reference/cli.md)).
6. **Check:** once the leftover profile commands are replaced (step 5), a new session runs `/tld:dod` cleanly;
   until then a `verify.dod` entry that runs a `plugins/devflow/` script fails. `tld migrate .` now says
   `Nothing to migrate`.

## What `tld migrate` never touches

Prose: only the exact texts `devflow:` (as a command or skill prefix), `.claude/toolkit.yaml` and `DEVFLOW_` are
rewritten, in CLAUDE.md, AGENTS.md, README*, CONTRIBUTING*, `docs/**/*.md`, `.github/**/*.md` and the
`project_steward` file when it is inside the repository. A profile command that runs a claude-toolkit script keeps
its old text, `.claude/toolkit.yaml` included, so the migrated `verify.dod` may still need your edit: the checklist
lists each one. A symbolic link, or a file that resolves outside the repository, is never read or written: the
plan reports it as refused. It never overwrites an existing `.tld/toolkit.yaml` or `tld-*.yml`, never renames a secret, never changes a Claude
Project, a ruleset or an environment, and never commits or pushes by itself. Exit 1 means the migrated profile
does not validate (for example a `docs.must_read` file is missing); the messages name the key.

## Retiring claude-toolkit

When every repository is migrated, the owner replaces claude-toolkit's README with the retirement notice and
archives the repository. The old marketplace keeps working until it is archived; nothing is fixed there.
