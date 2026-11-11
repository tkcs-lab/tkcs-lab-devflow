---
name: project-profile
description: How the tld commands (/review, /make-plan, /implement, /dod) find, validate and quote the project profile .tld/toolkit.yaml. Load it first in any of those commands, or whenever you need a project fact such as the main branch, the verify commands or the must-read docs.
user-invocable: false
---

# The project profile

Everything specific to a repository (paths, commands, branch rules, CI workflows) lives in
`.tld/toolkit.yaml` at the repo root. The commands contain no project facts of their own. Two
rules follow from that:

1. **Never guess a value.** If a key you need is missing, say which key and stop. Do not fall back
   to what a similar project does, and do not infer a command from the repository layout.
2. **A missing optional key means "not used here".** No `docs.adr_dir` means no ADRs: leave out
   every ADR step and never mention them. No `docs.index` means no docs index: read `docs.must_read` as before and leave out every index step.
   No `docs.changelog` means no changelog step. No
   `ci.dispatchable` means nothing can be dispatched.

## Loading the profile

1. **Find the toolkit.** One rule: every toolkit call is `"${CLAUDE_PLUGIN_ROOT}/bin/tld" <group> <command>`,
   and the templates sit in `${CLAUDE_PLUGIN_ROOT}/src/tld/templates/`. Check it once:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/tld" --help >/dev/null && echo ok
   ```

   No `ok` means the toolkit is not installed in this session. Stop and tell the user: the
   project needs the tld plugin in its Claude Project (see `docs/guides/delivery.md` in the
   tkcs-lab-devflow repo).

2. **Validate and resolve it**, from the repo root:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/tld" profile validate .tld/toolkit.yaml --resolved
   ```

   Exit 1 prints one message per problem on stderr, each naming the key (for example
   `toolkit.yaml: missing required key 'verify.fast'`). Show those messages verbatim and stop.
   Warnings are shown to the user and do not stop you. On success it prints the resolved profile as
   JSON: the `--resolved` defaults are `docs.plan_dir` (`docs`) and the `models` table. The `agents`
   defaults are applied by `tld roles`, not here. This is the profile you read from here on.

3. **Load the stack skills.** For each name in `stacks`, load the skill `stack-<name>`. If one is
   not installed, tell the user which and stop.

4. **Load the project's own policy.** If `project_steward` is set, read that file now.

## Keys, in the order the commands use them

| Key | Used for |
|---|---|
| `docs.must_read` | Read first by the planner; named in every worker brief and in the final review |
| `docs.plan_dir` | Plan document `<plan_dir>/<slug>-plan.md` and its manual-steps HTML |
| `docs.index` | The entry-level docs index: the planner reads it first and then only matching rows; workers get Read first lists; /docs and tld ops docs-index use it |
| `docs.adr_dir`, `adr_index`, `adr_bar` | ADR steps, only when `adr_dir` is set |
| `docs.changelog.file`, `.section` | The changelog line a user-visible change adds |
| `git.main_branch` | Base for plan branches, merges and the PR |
| `git.branch_pattern`, `branch_types` | Names of feature branches; checked by `tld plan validate-manifest` |
| `git.merge_style` | Quoted to workers and to `pr-steward` |
| `git.bot_login` | `/implement` checks at the start that `get_me` returns this login |
| `git.codeowners` | Logins `/implement` requests a review from on the pull request it opens |
| `verify.fast` | Run after every merge in `/implement` and by the final reviewer |
| `verify.dod`, `dod_conditional`, `dod_manual`, `dod_doc` | `/dod` |
| `docs.website` | `dir`, `build`, `links` of the project's website; the `website-maintainer` agent and its `Website build` and `Website links` prompt fields |
| `agents.*` | Which agents are required at which point (`required`), whether a finding blocks, `posture.security`, `disable`, `extra_context`; resolved and checked by `tld roles` through the `agent-dispatch` skill |
| `ci.dispatchable` | The dispatch table in `pr-steward`; what is not "manual" in a plan |
| `stacks` | Which `stack-*` skills to load |
| `models` | `planner`, `orchestrator` (documentation of intent; the command front matter fixes them), `worker`, `reviewer` (used in `create_session`) |
| `scope.ignore` | Globs `/implement` does not count as scope drift (default none; the changelog file is always ignored) |
| `project_steward` | A project skill or doc with policy that fits none of the keys |

A command entry in `verify.*` is a string or `{run, cwd?, narrow?, skip_when_narrowed?}`; a string
means `run` with no options. `cwd` is relative to the repo root.

## Quoting

When a prompt or a brief needs a project fact, write the actual value into it (the real paths and
commands), not "see the profile": child sessions start from a fresh checkout and should not have to
rediscover it. They do have the profile and the toolkit in their own session, so `/dod` works there.
