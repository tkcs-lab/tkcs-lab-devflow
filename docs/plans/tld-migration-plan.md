# Plan: from claude-toolkit to tkcs-lab-devflow (`tld`)

Inputs: [the review of claude-toolkit at 4c14071](../reviews/claude-toolkit-review.md) and the owner's answers
(recorded below). The work is done in one stage. Your repos migrate once, then claude-toolkit is retired.

## 1. Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Who do the guardrails protect against? | Both an agent that makes mistakes and one that has been manipulated. GitHub is the real control: rulesets, plus an agent account without merge or tag rights. The hooks are a fast seatbelt. The critical and high hook bypasses are still closed. |
| D2 | Where are fixes made? | Only in tkcs-lab-devflow. claude-toolkit gets no more changes, apart from a final README that points here. |
| D3 | Scope | Everything moves: workflow, guardrails, maintenance commands, repo-admin, git-ops, the board. |
| D4 | Platform | GitHub only. The core is neutral about Claude, not about GitHub. |
| D5 | Review concept | There is one concept, the **role**. A role is a checklist plus a role card, both in the core. The profile says where it runs and whether it blocks. Claude subagents only wrap roles. |
| D6 | Where procedures live | Every procedure is a neutral **playbook** in the core. The Claude wrapper only maps the runtime actions: start a worker, wait, ask the human, notify. |
| D7 | Human channel | The self-hosted board server replaces Artifact pages. It is the inbox for status records and for **asks**: questions, decisions and manual steps. The owner answers in the browser after logging in. When the board can't be reached, a GitHub issue comment mentions the owner. |
| D8 | Board audience | Just the owner, and every command writes to it. That includes `/review` and `/make-plan`. |
| D9 | Versions | Tagged releases, and a `tld.version` key in the profile, checked against the running version. |
| D10 | Who may give an ask | Owners and collaborators. Text from anyone else is untrusted data. |
| D11 | Models | Neutral levels `strong` / `standard` / `fast`. The Claude wrapper maps them to model ids in one table. |
| D12 | Renames | `.claude/toolkit.yaml` becomes `.tld/toolkit.yaml`. `devflow:` becomes `tld:`. `DEVFLOW_*` becomes `TLD_*`. `devflow-*.yml` becomes `tld-*.yml`. `.git/devflow` becomes `.git/tld`. The profile key `agents` becomes `roles`. Nothing reads the old names. |
| D13 | Tags | One route only: the release workflow. git-ops keeps branch deletion and loses tag creation. |
| D14 | Stack plugins | `stack-*` stop being separate plugins. They become core stack guides that the playbooks load from the profile's `stacks`. |

## 2. Layout

```
pyproject.toml                    # package "tld", console script "tld"; stdlib + PyYAML
launcher/tld                           # launcher that works without installing (puts src/ on sys.path)
src/tld/
  cli.py                          # tld <group> <command>
  profile/                        # load, validate, patch, survey, version check; default .tld/toolkit.yaml
  plan/                           # manifest validation + sizing lint, scope check, phase status, branch names
  roles/                          # which roles a point requires, AGENT-REPORT grammar and verification
  dod/                            # one DoD runner, used by `tld dod` and by the DoD gate
  guard/                          # neutral Action -> Decision: shell parser, git/gh classification, policies
  board/                          # store, server, client, MCP (stdio + HTTP), asks, web page
  ops/                            # land order, upstream sync, release pick, repo-admin, git-ops, docs index
  schema/                         # profile, manifest, status record, ask, admin policy (JSON Schema)
  templates/                      # toolkit.yaml, tld-land.yml, tld-release.yml, tld-git-ops.yml, admin policy
playbooks/                        # neutral procedures: setup, review, make-plan, implement, dod, land, deps,
                                  # upstream, docs, board; runtime.md lists the runtime actions they use
roles/                            # role cards (architect ... refactorer)
checklists/                       # review, security, test, docs (the former skills)
stacks/                           # python, go, swift, ipados
adapters/claude/                  # the thin Claude Code wrapper
  commands/*.md                   # /tld:<cmd>: "follow playbooks/<cmd>.md; runtime map: runtime.md"
  skills/tld-runtime/SKILL.md     # how each runtime action maps to Claude tools
  agents/*.md                     # one per role: front matter + "apply roles/<role>.md"
  hooks/hooks.json, hooks/hook.py # PreToolUse/Stop JSON -> tld.guard Action -> exit code / message
  mcp.json                        # tld board MCP bridge
.claude-plugin/marketplace.json   # marketplace "tkcs-lab-devflow", plugin "tld", source "./"
.claude-plugin/plugin.json        # component paths point into adapters/claude/ (validated by `claude plugin validate`)
evals/                            # harness core + adapters/claude runner
tests/core, tests/adapters/claude # import tld normally; adapter tests only touch adapters/
.tld/toolkit.yaml                 # this repo's own profile
AGENTS.md                         # neutral entry for agents; CLAUDE.md is a two-line pointer to it
```

The plugin's source is the repository root, so `${CLAUDE_PLUGIN_ROOT}` holds `src/`, `playbooks/` and the rest. Commands
call `"${CLAUDE_PLUGIN_ROOT}/launcher/tld"`. They no longer search the plugin cache for a script root.

## 3. Guardrails (D1)

GitHub side: repo-admin policy and `tld admin apply`.
- A ruleset on the default branch: pull request required, 1 approval, required checks, no force push, no deletion.
- A ruleset on tags: only the release workflow can create tags.
- The agent account has the `write` role, not `maintain` or `admin`.
- `TLD_AGENT_TOKEN` lives in an environment `tld-agent` that is limited to the default branch.

Hook side: a neutral `Action` (`shell`, `write`, `github_op`) goes to `Decision` (`allow` / `deny` / `notice`).
- S1: `hooks.disable` and the protect lists come from the remote default branch. That copy is fetched into `refs/tld/trusted` and cached for 10 min. The hooks deny writes to `refs/tld/*`, `refs/remotes/origin/<main>` and `refs/heads/<main>` through `update-ref`, `branch -f` or `fetch` refspecs. If the trusted copy can't be read, every hook is on.
- S2, S3, S5: deny a push whose destination or command word is dynamic, and deny `:` matching pushes.
- S4: deny `-c include.*` / `includeIf.*` and `GIT_CONFIG_{GLOBAL,SYSTEM,PARAMETERS}` / `GIT_DIR` on git commands that write.
- S6: unpack `find -exec`, `xargs`, `fish` and `busybox sh`. `python -c`, `bash <file>` and similar are documented as out of reach of a seatbelt; the rulesets cover them.
- S7: `--allow-profile` only allows edits to the profile file. The protect list itself always comes from the trusted copy. `dod_gate --exempt` stays (the orchestrator needs it) and is logged as a notice.
- S8: always protect `~/.claude/**`, `.mcp.json`, `.claude/hooks/**`, `~/.gitconfig` and `~/.config/git/**`, matched on absolute paths.
- S9 to S12: resolve `tags/`/`refs/` sources, read `--input` bodies, deny numeric workflow ids and reruns of the release workflow, check curl/wget calls to api.github.com, and handle `--approve=true`.
- S13: workflow files are protected unless the `/land` or `admin` install marker is set.
- S16, S17: scan Bash redirect and heredoc text for secrets, add the missing secret patterns, and cover `git apply` / `patch` / `checkout <ref> <path>`, dynamic redirect targets and `core.hooksPath` / `url.*`.

## 4. Consistency fixes

- C1: `/setup update` takes an answers file. `tld profile set-block` merges the proposal with the answers and never overwrites a hand-tuned block silently: it shows a diff and writes only after confirmation. A missing `docs.website` is a no-op.
- C2: at `implement_final` and in the orchestrator's `/dod`, roles run in review mode only. A role is dispatched at most once per point.
- C3: a docs-index error has one severity, blocking in `/dod`. Only the retirement phase and `/docs tidy` edit the index. Roles report index errors but don't fix them.
- C4: `docs.plan_dir` defaults to `docs/plans/`. `tld docs move` also rewrites paths in the profile. This repo's profile sets `docs.index`.
- C5, C6: the docs say what the code does. `/setup` proposes `docs.index` and respects the `must_read` limit.
- C7: one record model. `attended: true|false` replaces "scheduled". The project slug is derived from the repo name. Final states are `done`, `failed` and `pr_open`. `/review` and `/make-plan` write records.
- C8: one tag route (D13). The hook message and the hooks tables are updated to match.
- C9: models (D11). `models.*` is read by every playbook that starts a worker.
- C11: roles (D5). `/review`'s dimensions are roles, so each finding has one id.
- C12: branch kinds are documented: `plan/`, `review/`, the feature branch from `git.branch_pattern`, and phase branches `<feature>--<phase>`. The "only `claude/…`" claim goes.
- C13: `tracking_issue` is optional everywhere.
- C14: no product words in generic files. The project-word test also covers `.html` and `.js` and gets a wider word list. `maintenance-spike.md` loses logins, trigger ids and session ids.
- S14, S15: every playbook has the untrusted-text rule (D10). `/implement` runs only plans from `main` or a `plan/*` branch of the same repository.

## 5. Board as inbox (D7, D8)

- **Record kinds.** `run` is the existing status record. `ask` is new: `questions[]` of `{id, text, kind: choice|confirm|text, options[]}`, plus `answers{}`, `state: open|answered|cancelled` and `fallback_issue`.
- **Login.** The browser page is behind an owner login: `TLD_BOARD_OWNER_PASSPHRASE`, a signed cookie (HttpOnly, Secure, SameSite=Strict) and an Origin check on POST. The session token cannot answer an ask, and the owner cookie cannot write records.
- **Session side.** `tld board ask <file>` returns the ask id, and `tld board answers <id> [--wait N]` reads the answers. The MCP tools are `board_ask` and `board_answers`. `board_delete` comes off the MCP tool set (S19).
- **Replaces Artifacts.** The `/review` decisions page and the `/make-plan` manual-steps page are both asks. `review_decisions.html` and the Artifact text go.
- **Fallback.** When the board can't be reached, the session comments on the tracking issue (or opens one), mentions the owner, and reads the answer from the reply. Only owner and collaborator replies count.
- **Deployment.** The board isn't deployed yet. The Dockerfile and the deploy guide cover TLS behind a reverse proxy and adding its host to the cloud environment's allowlist. Deploying it is a manual step for the owner.
- **S18.** The board client keeps auth to the same host on redirects.

## 6. Tests

- Core tests import `tld`. Adapter tests touch only `adapters/claude/`.
- An autouse fixture isolates `GIT_CONFIG_*`, `GH_*`, `CLAUDE_*` and `TLD_*`. Fixtures that change state are function-scoped.
- The sentence-level markdown greps go. Contract tests replace them:
  - every `tld ...` call in a playbook or command parses with the real CLI;
  - every hook entry resolves;
  - front matter is valid;
  - every role, checklist and stack a playbook names exists.
- A test is added for each mutation survivor in the review. The guard and validator modules get table-driven allow/deny cases from one corpus (`tests/core/guard_cases.yaml`).
- The timing tests get wide margins. CI installs Playwright, and the browser test fails instead of skipping.
- CI runs pytest on Python 3.11 and 3.13, `claude plugin validate`, the validators on the fixtures, and the evals in stub mode. Real evals stay manual.

## 7. Migrating your repos and retiring claude-toolkit

- `tld migrate [--write]`, run in a consumer repo:
  - moves `.claude/toolkit.yaml` to `.tld/toolkit.yaml`;
  - rewrites renamed keys and values (`agents` to `roles`, model names to levels, `devflow-*` workflow names);
  - renames installed `devflow-*.yml` workflows;
  - rewrites `devflow:` and `.claude/toolkit.yaml` in CLAUDE.md, AGENTS.md and docs;
  - lists what only the owner can do.
- What only the owner can do, per Claude Project and per repo:
  - remove the `claude-toolkit` marketplace and add `tkcs-lab/tkcs-lab-devflow`;
  - enable `tld`;
  - rename the secrets `DEVFLOW_*` to `TLD_*`;
  - deploy the board and set `TLD_BOARD_URL` / `TLD_BOARD_TOKEN`;
  - run `tld admin apply` with an owner token for the rulesets.
- Retiring claude-toolkit: a last README change that points here, then the repository is archived by the owner.

## 8. Work packages (in order; each one ends with the full test suite green and is pushed)

1. **WP1 Layout and rename.**
   - Everything moves to the layout in §2 with `git mv`, and the renames in D12 are applied.
   - The package, CLI and launcher are added, the tests are re-pointed, and the plugin validates.
   - Behaviour stays the same apart from names and paths.
2. **WP2 Guard.** The neutral `Action`/`Decision` split, the Claude hook adapter, the fixes in §3 and their tests.
3. **WP3 GitHub-side enforcement.** Rulesets, the agent role and the token environment in the admin policy and `tld admin`. Tags take the single route (D13), and S13 is closed.
4. **WP4 Concepts.**
   - Roles, checklists, stacks and model levels, with playbooks extracted from the commands. The Claude commands become thin.
   - The fixes in §4 are applied, and `tld.version` is added (D9).
5. **WP5 Board inbox.** Everything in §5, plus the deploy guide.
6. **WP6 Tests and CI.** Everything in §6.
7. **WP7 Evals.** The harness is split into core and Claude runner, the baseline is refreshed, and a stub run is added to CI.
8. **WP8 Docs, migration and release.**
   - Docs: README, AGENTS.md, the docs index, and the architecture, guide and reference docs.
   - `tld migrate` and the migration guide.
   - A `v1.0.0` release workflow for this repo, and the retirement change for claude-toolkit.

## 9. Not in scope

- An orchestrator, or an API-driven runtime.
- Any platform other than GitHub.
