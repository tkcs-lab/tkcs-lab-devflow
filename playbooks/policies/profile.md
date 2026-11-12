# The project profile

Everything specific to a repository (paths, commands, branch rules, CI workflows) lives in
`.tld/toolkit.yaml` at the repository root. The playbooks contain no project facts of their own. Two rules
follow from that:

1. **Never guess a value.** If a key you need is missing, say which key and stop. Do not fall back to what a
   similar project does, and do not infer a command from the repository layout.
2. **A missing optional key means "not used here".** No `docs.adr_dir` means no ADRs: leave out every ADR
   step and never mention them. No `docs.index` means no docs index: read `docs.must_read` and leave out
   every index step. No `docs.changelog`, or `docs.changelog.policy: release-only`, means no changelog step. No `ci.dispatchable` means nothing can be
   dispatched. No `tracking_issue` (in a manifest) means no issue comments and no `Closes` lines.

## Loading the profile

1. **Find the toolkit.** `tld --help` must succeed. When it does not, stop and tell the human the project
   needs the tld plugin in its runtime (see `docs/guides/delivery.md` in the tkcs-lab-devflow repo).
2. **Validate and resolve it**, from the repository root: `tld profile validate .tld/toolkit.yaml --resolved`.
   Exit 1 prints one message per problem on stderr, each naming the key (for example
   `toolkit.yaml: missing required key 'verify.fast'`, or a `tld.version` the running tld does not satisfy).
   Show those messages verbatim and stop. Warnings are shown and do not stop you. On success it prints the
   resolved profile as JSON with the schema's defaults (`docs.plan_dir` `docs/plans`, the `models` levels).
   The `roles` defaults are applied by `tld roles`, not here. This is the profile you read from here on.
3. **Load the stack guides.** For each name in `stacks`, read `stacks/<name>.md`. If one does not exist,
   say which and stop.
4. **Load the project's own policy.** If `project_steward` is set, read that file now.

## Keys, in the order the playbooks use them

| Key | Used for |
|---|---|
| `tld.version` | The tld releases the profile is written for; `tld profile validate` checks the running one |
| `docs.must_read` | Read first by the planner; named in every worker brief and in the final review |
| `docs.plan_dir` | Plans `<plan_dir>/<n>/plan.md` with `deviations.md` next to them, and reviews `<plan_dir>/<slug>-review.md` (default `docs/plans/`) |
| `docs.index` | The docs index ([docs.md](docs.md)): read first, then only matching rows |
| `docs.adr_dir`, `adr_index`, `adr_bar` | ADR steps, only when `adr_dir` is set |
| `docs.changelog.file`, `.section` | The changelog line a user-visible change adds |
| `docs.website` | `dir`, `build`, `links` of the website; the `website-maintainer` role |
| `git.main_branch` | Base for plan and review branches, merges and the pull request |
| `git.branch_pattern`, `branch_types` | Feature branch names; checked by `tld plan validate-manifest` |
| `git.merge_style` | Quoted to workers and in [pr-steward.md](pr-steward.md) |
| `git.bot_login` | The login `identity()` must return |
| `git.codeowners` | Logins asked to review the pull requests the playbooks open; mentioned in an ask's fallback |
| `verify.fast` | Run after every merge in implement and by the final reviewer |
| `verify.dod`, `dod_conditional`, `dod_manual`, `dod_doc` | The dod playbook |
| `roles.*` | Which roles are required where, whether a finding blocks, `posture.security`, `disable`, `extra_context`; resolved by `tld roles` ([roles.md](roles.md)) |
| `models.worker`, `models.reviewer` | The level of the workers implement, make-plan and review start |
| `ci.dispatchable` | The dispatch table in [pr-steward.md](pr-steward.md); what is not "manual" in a plan |
| `stacks` | Which `stacks/<name>.md` guides to load |
| `scope.ignore` | Globs implement does not count as scope drift |
| `project_steward` | A project doc with policy that fits none of the keys |
| `deps`, `upstream`, `land`, `admin`, `git_ops`, `hooks` | The playbook or guard of the same name |

A command entry in `verify.*` is a string or `{run, cwd?, narrow?, skip_when_narrowed?}`; a string means
`run` with no options. `cwd` is relative to the repository root.

## Quoting

When a brief or a role's context needs a project fact, write the actual value into it (the real paths and
commands), not "see the profile": workers start from a fresh checkout and should not have to rediscover it.
They do have the profile and the toolkit, so the dod playbook works there.
