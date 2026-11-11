# The `tld` command line

Every toolkit script is reached through one command, `tld <group> <command> [args...]`. Each command hands
its arguments unchanged to the `main(argv)` of one module in `src/tld/`, so the arguments, output and exit
codes are those documented in the module's docstring. `tld --help` lists the commands and
`tld <group> <command> --help` prints a command's own help.

How to run it:

- From a checkout: `launcher/tld ...` (puts `src/` on `sys.path`; Python 3.11+ and PyYAML).
- Installed: `pip install .` gives the console script `tld`.
- In the Claude Code plugin: `"${CLAUDE_PLUGIN_ROOT}/launcher/tld" ...` (the plugin is sourced from the repository
  root). The hooks run `adapters/claude/hooks/<name>.py`, thin shims over the same modules.

The playbooks call these commands as `tld ...`; `tests/core/test_contracts.py` checks that every call in
`playbooks/` and `adapters/` names a command below with flags its `--help` lists. `tld <group> <command> --help` never
runs the command, also for the commands without their own argument parser (`dod exempt`, `guard allow-*`, the survey
modules). `tld --version` prints the running version, the one a profile's `tld.version` is checked against.

## Commands

| Command | Module | What it does |
|---|---|---|
| `tld profile validate [PROFILE] [--resolved] [--no-file-checks] [--root DIR]` | `tld.profile.validate` | validate a profile (default `.tld/toolkit.yaml`) against `schema/profile.schema.json` |
| `tld profile patch set-block PROFILE roles\|docs.website PROPOSAL [--answers F] [--write [--yes]]` | `tld.profile.patch` | merge the survey's proposal with the human's answers into one block; prints the diff, writes a changed block only with `--yes` (exit 4 otherwise), a block neither has is a no-op |
| `tld profile patch diff PROFILE PROPOSAL [--root DIR]` | `tld.profile.patch` | new, changed, same and stale keys of a proposal |
| `tld profile survey [ROOT]` | `tld.profile.survey` | the survey and proposal behind `/setup` |
| `tld profile survey-docs [ROOT]` | `tld.profile.survey_docs` | the docs part of the survey |
| `tld profile survey-signals [ROOT]` | `tld.profile.survey_signals` | the signals part of the survey |
| `tld profile survey-proposal SIGNALS.json` | `tld.profile.survey_proposal` | turn survey signals into a proposal |
| `tld plan validate-manifest PLAN [--profile P]` | `tld.plan.manifest` | validate a plan's implementation manifest |
| `tld plan scope-check check\|disposition\|record\|section ...` | `tld.plan.scope` | scope-drift checks of `/implement` |
| `tld plan check-url URL [--repo O/N] [--main B]` | `tld.plan.phases` | accept a plan URL only from this repository's main branch or a `plan/<slug>` branch (S14); prints owner, repo, ref, path |
| `tld plan branch-name --plan-slug S \| --review-slug S \| --manifest PLAN [--phase ID [--rev N] \| --fix N]` | `tld.plan.phases` | the branch names of the playbooks (C12) |
| `tld plan phase-status PLAN [--ref R] [--running ID]... [--approved ID]... [--repo DIR]` | `tld.plan.phases` | done (by `Plan-Phase` trailers on the branch's own, unreverted commits), approved (`Plan-Gate-Approved` trailers or `--approved`), gated, ready, waiting phases and the ones to start, as JSON |
| `tld roles required --profile P --at POINT [--changed F]` | `tld.roles.dispatch` | the roles required at a point, with their mode, as JSON |
| `tld roles verify --required F --report F` | `tld.roles.dispatch` | check a report against `tld roles required` |
| `tld dod exempt` | `tld.dod.gate` | mark this checkout's session exempt from the dod-gate hook |
| `tld guard allow-profile` | `tld.guard.protect_paths` | let the session edit the profile for the next 2 hours |
| `tld guard allow-workflow-install FILE...` | `tld.guard.protect_paths` | let the session write `tld-land.yml` / `tld-release.yml` for the next 15 minutes |
| `tld guard allow-git-ops` | `tld.guard.protect_paths` | let a git-ops dispatch with `dry_run` false through for the next 10 minutes |
| `tld guard end-allow` | `tld.guard.protect_paths` | end every allow marker: the profile, workflow installs, git-ops |
| `tld board server [--host H] [--port N] [--db F] [--insecure-cookie] ...` | `tld.board.server` | serve the board: status records, asks, the owner's page ([board-server.md](../guides/board-server.md)) |
| `tld board client health\|list\|get\|set\|delete ...` | `tld.board.client` | status records on the board server |
| `tld board ask FILE\|- [--fallback-issue O/R[#N]] [--mention LOGIN] [--profile P]` | `tld.board.inbox` | post an ask and print its id; exit 3 no board, 5 the fallback comment body is on stdout |
| `tld board answers ID [--wait S] [--interval S]` | `tld.board.inbox` | print the answers JSON; exit 3 still open, 4 cancelled |
| `tld board answers --from-issue COMMENTS.json --ask FILE --self LOGIN [--owner LOGIN]... [--repo O/R] [--profile P]` | `tld.board.inbox` | the answers in the owner's (`--owner`, else `git.owner_login`, else the repository owner) or an admin's replies to a fallback comment, never `--self`'s (required); exit 3 incomplete, 2 no `--self` or no owner |
| `tld board cancel ID` | `tld.board.inbox` | cancel an open ask |
| `tld board validate-ask FILE` | `tld.board.ask` | validate an ask (`schema/ask.schema.json`) |
| `tld board mcp-stdio` | `tld.board.mcp_stdio` | MCP stdio bridge to the board server (the `tld-board` MCP server) |
| `tld board stale [FILE] [--now T]` | `tld.board.stale` | print the ids of hidden status records |
| `tld board build --title T --out F ...` | `tld.board.build` | build the self-contained board page |
| `tld board validate-record FILE [--doc-id ID]` | `tld.board.record` | validate a status record |
| `tld board project-slug OWNER/NAME` | `tld.board.record` | the project slug of a repository, the only `project` a record may have |
| `tld ops land-order [FILE] [--max N]` | `tld.ops.land_order` | order the open pull requests for `/land` |
| `tld ops pick-release --pattern RE ...` | `tld.ops.pick_release` | pick the newest eligible release tag |
| `tld ops upstream-sync plan\|prepare ...` | `tld.ops.upstream_sync` | sync a fork to an upstream release |
| `tld ops repo-admin validate-policy\|whoami\|audit\|apply ...` | `tld.ops.repo_admin` | audit and update organisation and repository settings |
| `tld ops docs-index check\|inventory\|move ...` | `tld.ops.docs_index` | the docs index rules and doc moves (`move` also rewrites the profile's paths; a dry run unless `--apply`) |
| `tld migrate [ROOT] [--write]` | `tld.ops.migrate` | move a claude-toolkit (devflow) repository to tld: prints the plan, `--write` applies and stages it, then validates the profile and prints the owner's checklist; it never follows a symbolic link ([migrating-from-claude-toolkit.md](../guides/migrating-from-claude-toolkit.md)) |
| `tld version show`, `tld --version` | `tld.cli` | print the running tld version |

## Migration from devflow

The scripts of the former `devflow` plugin (claude-toolkit) map to these commands:

| Old script | New command | New module |
|---|---|---|
| `scripts/validate_profile.py` | `tld profile validate` | `src/tld/profile/validate.py` |
| `scripts/profile_patch.py` | `tld profile patch` | `src/tld/profile/patch.py` |
| `scripts/profile_survey.py` | `tld profile survey` | `src/tld/profile/survey.py` |
| `scripts/survey_docs.py` | `tld profile survey-docs` | `src/tld/profile/survey_docs.py` |
| `scripts/survey_signals.py` | `tld profile survey-signals` | `src/tld/profile/survey_signals.py` |
| `scripts/survey_proposal.py` | `tld profile survey-proposal` | `src/tld/profile/survey_proposal.py` |
| `scripts/validate_manifest.py` | `tld plan validate-manifest` | `src/tld/plan/manifest.py` |
| `scripts/scope_check.py` | `tld plan scope-check` | `src/tld/plan/scope.py` |
| `scripts/agents.py required\|verify` | `tld roles required\|verify` | `src/tld/roles/dispatch.py` |
| `hooks/dod_gate.py --exempt` | `tld dod exempt` | `src/tld/dod/gate.py` |
| `hooks/protect_paths.py --allow-profile` / `--end-allow` | `tld guard allow-profile` / `end-allow` | `src/tld/guard/protect_paths.py` |
| `scripts/board_server.py` | `tld board server` | `src/tld/board/server.py` |
| `scripts/board_client.py` | `tld board client` | `src/tld/board/client.py` |
| `scripts/board_mcp_stdio.py` | `tld board mcp-stdio` | `src/tld/board/mcp_stdio.py` |
| `scripts/board_stale.py` | `tld board stale` | `src/tld/board/stale.py` |
| `scripts/build_board.py` | `tld board build` | `src/tld/board/build.py` |
| `scripts/validate_status_record.py` | `tld board validate-record` | `src/tld/board/record.py` |
| `scripts/board_store.py`, `scripts/board_mcp.py` | (library) | `src/tld/board/store.py`, `src/tld/board/mcp.py` |
| `scripts/land_order.py` | `tld ops land-order` | `src/tld/ops/land_order.py` |
| `scripts/pick_release.py` | `tld ops pick-release` | `src/tld/ops/pick_release.py` |
| `scripts/upstream_sync.py` | `tld ops upstream-sync` | `src/tld/ops/upstream_sync.py` |
| `scripts/repo_admin.py` | `tld ops repo-admin` | `src/tld/ops/repo_admin.py` |
| `scripts/docs_index.py` | `tld ops docs-index` | `src/tld/ops/docs_index.py` |
| `scripts/review_decisions.py` (+ `.html`) | removed: the decisions are a board ask (`tld board ask`) | |
| `hooks/no_merge.py`, `no_force_push.py`, `no_git_tag.py`, `secret_scan.py`, `protect_paths.py` | hook entries `adapters/claude/hooks/<name>.py` | `src/tld/guard/<name>.py` |
| `hooks/dod_gate.py` | hook entry `adapters/claude/hooks/dod_gate.py` | `src/tld/dod/gate.py` |
| `hooks/_common.py`, `_shell.py`, `_gitgh.py`, `_gitcfg.py`, `_ansi.py`, `_wrappers.py` | (library) | `src/tld/guard/_<name>.py` |
| `schema/*.json`, `templates/*`, `board/board.html`, `board/rules.js` | (data) | `src/tld/schema/`, `src/tld/templates/`, `src/tld/board/web/` |
| `board/Dockerfile` | (image) | `deploy/board/Dockerfile` |

The names changed with the move: `.claude/toolkit.yaml` is now `.tld/toolkit.yaml`, the plugin and skill
namespace `devflow:` is `tld:`, the environment variables `DEVFLOW_*` are `TLD_*`, the workflow templates
`devflow-*.yml` are `tld-*.yml`, the hooks' state lives under `.git/tld`, and the MCP server is `tld-board`.
Nothing reads the old names; `tld migrate` rewrites them in a repository that still uses them.
