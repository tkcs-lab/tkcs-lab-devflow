# Profile reference: `.tld/toolkit.yaml`

The profile is the only place a project's facts live. The playbooks read it as
[`playbooks/policies/profile.md`](../../playbooks/policies/profile.md) says, which runs `tld profile validate` first.
The schema is [`src/tld/schema/profile.schema.json`](../../src/tld/schema/profile.schema.json); a
commented starter is [`src/tld/templates/toolkit.yaml`](../../src/tld/templates/toolkit.yaml). The first project's
profile, [`tests/fixtures/privacyfence-toolkit.yaml`](../../tests/fixtures/privacyfence-toolkit.yaml), is kept as a
regression fixture in the current key names (see [`migrating-privacyfence.md`](../migrating-privacyfence.md)); it is
not a description of that project today.

Rules:

- A **required** key that is missing stops the command with a message that names it, for example
  `toolkit.yaml: missing required key 'verify.fast'`. The commands never fall back to a value of
  their own.
- An **optional** key that is missing means "not used in this project".
- Only two things have defaults, and `tld profile validate --resolved` is where they are applied:
  `docs.plan_dir` (`docs/plans/`) and `models` (`worker: standard`, `reviewer: strong`). The `hooks` section also
  has defaults, but the hook scripts apply those themselves ([hooks.md](../architecture/hooks.md)); `--resolved`
  leaves them out. The `roles` defaults are applied by `tld roles` and are not part of `--resolved`.
- `tld.version`, when set, must be satisfied by the running tld, or validation fails.
- An unknown key is an error, so a typo is never silent.
- A file listed in `docs.must_read` or `project_steward` that does not exist is an error.
- A claude-toolkit profile (`.claude/toolkit.yaml`, `agents`, model names in `models`) is converted by `tld migrate`
  ([migrating-from-claude-toolkit.md](../guides/migrating-from-claude-toolkit.md)); its fixtures are in
  `tests/fixtures/legacy/`.

## Keys

| Key | Required | Meaning |
|---|---|---|
| `tld` | no | Holds `version` |
| `tld.version` | no | A version specifier such as `>=1.0,<2` (clauses `==`, `!=`, `>=`, `<=`, `>`, `<`, joined by commas). `tld profile validate` fails when the running tld does not satisfy it; a development build (`1.0.0.dev0`) counts as the release it leads to. `/setup` writes `>=<major>.<minor>,<<major+1>` |
| `project.name` | no | Name used in prose; default is the repository name |
| `docs.must_read` | **yes** (may be `[]`) | Files the planner reads first, every worker brief names, and the final reviewer reads |
| `docs.plan_dir` | no (default `docs/plans/`) | Plans are `<plan_dir>/<slug>-plan.md` and reviews `<plan_dir>/<slug>-review.md` |
| `docs.index` | no | The entry-level docs index: the one file sessions read first, then only the rows that match the task. `/docs init` builds it, `/docs` checks it, `/setup` proposes it when it finds one. With it, `docs.must_read` keeps at most three files (a warning otherwise) |
| `docs.adr_dir` | no | If set, the project uses ADRs and the commands plan, write and check them |
| `docs.adr_index` | no (needs `adr_dir`) | File that must list every new ADR |
| `docs.adr_bar` | no (needs `adr_dir`) | Where the criteria for needing an ADR are written (`path` or `path#anchor`) |
| `docs.changelog.file`, `docs.changelog.section` | no | A user-visible change adds a line under this heading; never a version heading |
| `docs.changelog.policy` | no (default `unreleased`) | `unreleased`: a user-visible change adds a line under `section`; the `protect-paths` hook denies a session opening a version heading in the file unless the change touches only the changelog. `release-only`: the changelog is written when a release is cut; the hook denies every session edit of the file unless the change touches only the changelog, `section` is not needed, and no playbook adds a changelog line |
| `docs.website` | no | The project's website; present means the `website-maintainer` role can run. Keys: `dir`, `build`, `links` |
| `docs.website.dir` | **yes** (in `docs.website`) | Directory relative to the repo root (`.` for the root); `build` and `links` run from there |
| `docs.website.build` | **yes** (in `docs.website`) | Command that builds the site |
| `docs.website.links` | no | Command that checks the site's links |
| `git.main_branch` | **yes** | Base of plan branches, the merge target and the PR base |
| `git.branch_pattern` | **yes** | Human-readable branch rule, quoted into prompts, for example `<type>/<kebab-case>` |
| `git.branch_types` | no | Allowed `<type>` values; `/implement` rejects a manifest whose `feature_branch` uses another |
| `git.merge_style` | no | `merge-commit` or `squash`; only quoted to workers and the steward |
| `git.codeowners` | no (needs `git.bot_login`) | GitHub logins of the code owners (at least one). `/implement` requests their review on the pull request it opens and sets `needs_you` (`Review PR #<n>`); it never approves or merges |
| `git.bot_login` | no | Login of the second GitHub user the agent acts as. `/implement` checks `identity()` at the start and stops when the login differs. Must not be listed in `git.codeowners` |
| `git.owner_login` | no | GitHub login of the owner. When the board cannot be reached, `tld board ask --fallback-issue` mentions it in the issue comment that carries the questions (default: the repository owner). See [board-server.md](../guides/board-server.md) |
| `verify.fast` | **yes** | Commands run after every merge by `/implement` and by the final reviewer. Seconds to a minute |
| `verify.dod` | **yes** | The blocking definition-of-done gate `/dod` runs, in order |
| `verify.dod_conditional` | no | `{when: [globs], do: text}`: checked against the diff by `/dod` |
| `verify.dod_manual` | no | Judgement rows `/dod` reports `ok / needs attention / n/a` |
| `verify.dod_doc` | no | Pointer to the project's human-readable DoD, quoted in the `/dod` report |
| `ci.dispatchable` | no | `{workflow, use_when, notes?}`: workflows a session may dispatch against its own branch for work the container cannot do |
| `stacks` | **yes** (may be `[]`) | Stack guides to load: `python` loads `stacks/python.md`, `go`, `swift` and `ipados` likewise (list `ipados` with `swift`) |
| `models` | no | The levels of the workers the playbooks start: `strong`, `standard` or `fast`. The adapter maps a level to a model (Claude: the `tld:runtime` skill) |
| `models.worker` | no (default `standard`) | `/implement`'s phase, fix and conflict workers (a phase's `worker_level` overrides it) |
| `models.reviewer` | no (default `strong`) | `/implement`'s final reviewer, `/make-plan`'s plan reviewer, `/review`'s roles and verifiers |
| `ci.time_budget_minutes` | no | Integer 10..480 (default 60): `/ci` starts no new workflow after 80% of this |
| `ci.lookback_hours` | no | Integer 1..168 (default 36): how far back `/ci` looks at workflow runs on the default branch |
| `ci.ignore_workflows` | no | List of workflow file names `/ci` does not watch (for example a canary that is red on purpose) |
| `deps.cooldown_days` | **yes** (in `deps`) | Integer 0..30: the Dependabot cooldown (days) the project's `.github/dependabot.yml` must set. `/deps` needs the `deps` section and stops with a missing-key message when it is absent |
| `deps.time_budget_minutes` | **yes** (in `deps`) | Integer 10..480: `/deps` starts no new update group after 80% of this |
| `deps.audit` | no | List of `{ecosystem, run, cwd?}`: commands that list vulnerable packages (sessions cannot read Dependabot alerts). Exit 0 = nothing found; non-zero = findings in the output. `cwd` is relative to the repo root |
| `deps.lock_freshness` | no | List of `{when, run, lockfiles}`, run after a manifest change so lockfiles stay consistent (see below) |
| `upstream.repo` | **yes** (in `upstream`) | The upstream repository as `owner/name`. `/upstream` needs the `upstream` section |
| `upstream.tag_pattern` | **yes** (in `upstream`) | Regular expression a release tag must match; must compile |
| `upstream.version_file` | **yes** (in `upstream`) | File in the fork that records the synced tag |
| `land.max_prs` | no | Integer 1..50: most pull requests one `/land` run orders. `/land` works without the `land` section |
| `admin.policy` | **yes** (in `admin`) | Path, relative to the repo root, of the policy file the repo-admin playbook audits and applies (see [admin.md](../guides/admin.md)). The file must exist. It needs the `admin` section and stops with a missing-key message when it is absent |
| `git_ops.repo` | **yes** (in `git_ops`) | Owner/name of the central repository that holds the `tld-git-ops` workflow. The git-ops playbook needs the section and stops with a missing-key message when it is absent; see [git-ops.md](../guides/git-ops.md) |
| `git_ops.workflow` | no | File name of the workflow in that repository. Default `tld-git-ops.yml` |
| `hooks.disable` | no (default none) | Names of guardrail hooks to switch off in this repository: any of `no-merge`, `no-force-push`, `no-git-tag`, `secret-scan`, `protect-paths`, `dod-gate`, `plan-gate`. Read from the committed `<main>` profile, so a branch cannot switch a hook off for itself; it must be a list. The escape hatch; see [hooks.md](../architecture/hooks.md) |
| `hooks.protect_paths` | no | Globs of repo-relative paths `protect-paths` refuses to edit. Default `.tld/toolkit.yaml`, `.env`, `.env.*`, `*.lock`, `package-lock.json`, `go.sum`, `.github/workflows/**`. A list here replaces the default. A pattern without a slash matches the file name at any depth; `**` crosses directories. `*` and `?` do **not** cross `/` (unlike `touches` and `scope.ignore`) |
| `hooks.protect_paths_allow` | no | Globs exempt from `protect_paths`, on top of the built-in exceptions (`.env.example`, `.env.sample`, `.env.template`, `.env.dist`, the workflow files `/land` and `repo-admin` install) |
| `hooks.dod_gate.enabled` | no (default `false`) | Opt in to the `dod-gate` Stop hook: the session cannot stop while `verify.dod` fails. Not applied to sessions that marked themselves exempt, such as the `/implement` orchestrator |
| `hooks.dod_gate.max_attempts` | no (default `3`) | Integer 1..10: failed attempts after which the gate lets the session stop and tells the user why |
| `hooks.plan_gate.enabled` | no (default `false`) | Opt in to the `plan-gate` hook: a session that no tld command started cannot write into the repository; it is told to answer and to propose `/make-plan`. See [hooks.md](../architecture/hooks.md) |
| `scope.ignore` | no | List of globs. `/implement` checks at each merge which files the phase changed outside its `touches` and reports them (see [scope-drift.md](../architecture/scope-drift.md)); paths matching these globs are not counted. Default: none. The changelog file (`docs.changelog.file`) is always ignored when the profile has `docs.changelog`. Same glob semantics as `touches` (`*` and `**` match across `/`; an entry ending in `/` is a directory). The check never blocks a merge |
| `roles` | no | Which roles are mandatory and how they run; see [`roles`](#roles) below |
| `roles.posture` | no | Holds `security` |
| `roles.posture.security` | no (default `standard`) | `critical`, `standard` or `low`: how deep `security-reviewer` goes |
| `roles.disable` | no (default none) | Role names that are never run |
| `roles.required` | no (default none) | List of `{role, at, blocking?, when?}`: roles that must run at the listed points. `at` is a non-empty list of `make_plan`, `implement_phase`, `implement_final`, `review`, `dod`; `blocking` (default `false`); `when` is a non-empty list of globs matched against the changed files |
| `roles.extra_context` | no | List of non-empty strings added to every role's context |
| `project_steward` | no | Path to a project doc with policy that fits no other key; read after the pr-steward policy and wins where more specific |

### roles

The ten roles are `architect`, `code-reviewer`, `security-reviewer`, `test-architect`, `ux-reviewer`,
`dependency-auditor`, `tech-writer`, `website-maintainer`, `debugger` and `refactorer` (role cards in `roles/`,
see [roles.md](../architecture/roles.md)). A profile without `roles` means all of them are available and none is
mandatory. The key was `agents` (with `agent` in each entry) before tld 1.0; nothing reads the old name.

- **Points** (the only values `at` accepts): `make_plan`, `implement_phase`, `implement_final`, `review`, `dod`.
  `make_plan` and `review` have no diff, so `when` has no effect there.
- **Mandatory** means an entry in `roles.required`: the role must run at that point, and a required role
  that did not run (no report line, or verdict `n/a`) fails the gate.
- **Blocking** (`blocking: true`) means a finding the role grades `blocking` fails the gate too: at
  `implement_phase` the phase is sent back, at `implement_final` the review verdict is `changes`, at `dod`
  the row is `FAIL`. With `blocking: false` the findings are reported but do not fail the gate.
- **Defaults** (applied by `tld roles`): `posture.security` is `standard`, `disable` and `required`
  are empty, `blocking` is `false`.
- **Modes**: `tld roles required` gives each item a `mode`; only an edit role at `implement_phase` gets `edit`.
- **Checked by the validator**: a role is not both disabled and required; `website-maintainer` needs
  `docs.website`; `when` needs an `at` point with a diff; only `security-reviewer`, `dependency-auditor`,
  `test-architect`, `tech-writer` and `website-maintainer` can run at `review`.

### Command entries

Every entry of `verify.fast` and `verify.dod` is a string, or a mapping:

```yaml
- run: npm test            # required
  cwd: web                 # relative to the repo root
  narrow: "npm test -- {args}"   # /dod <args>: run this instead of `run`, with {args} replaced
  skip_when_narrowed: true # /dod <args>: report n/a (partial run) instead of running
```

### Second GitHub user

Set `git.bot_login` and `git.codeowners` when the agent should open pull requests as its own GitHub
account and the owner's review is the gate. Sessions keep running in the owner's claude.ai seat;
only the GitHub account connected to it changes, so the owner's own GitHub access from that seat
goes away until the connection is swapped back. The owner does these steps once (`/make-plan` adds
them to `manual_before` as `mb0-second-user`):

GitHub:

1. Create the second GitHub user (its own email address, 2FA on). Put it on the team plan seat.
2. Invite it to each repository with **Write** (not Admin, not Maintain). It must not be in any
   branch-protection bypass list.
3. On each repository, protect `main` (a ruleset): require a pull request, require review from Code
   Owners, at least 1 approval, dismiss stale approvals on new commits, require approval of the most
   recent push, block force pushes and deletions.
4. Add `.github/CODEOWNERS` containing `* @<owner-login>`. The second user is not listed.
5. Confirm the Claude GitHub App is installed for the repository and, if the second user is the one
   connecting, that it is installed for that account's access
   (`https://github.com/apps/claude/installations/select_target`).

claude.ai (the owner's own seat):

6. On `https://claude.ai/connect-github`, replace the connected GitHub account with the second login.
7. In that account's environment settings, check that the repositories are enabled.
8. Open a session and ask it for its GitHub identity (`identity()`; in Claude Code `get_me`); it must print the second login, not the owner's.

Then open one throwaway pull request from a session and check that its author is the second login
and that GitHub shows "Review required".

### `ci.dispatchable`

```yaml
ci:
  dispatchable:
    - workflow: macos-tests.yml
      use_when: Build or test an iOS/macOS target
      notes: No inputs.
```

The planner treats anything one of these covers as a phase task, never a manual step; the pr-steward policy
dispatches it instead of skipping the row; a swift or ipados project with an empty list gets a warning.
The workflow file must be on the default branch to be dispatchable.

### `deps.lock_freshness`

```yaml
deps:
  lock_freshness:
    - when: ["pyproject.toml"]   # globs matched against changed files
      run: "uv lock"             # one command, run from the repo root
      lockfiles: ["uv.lock"]     # the only files it may change besides the matched ones
```

All three keys are required; `when`, `run` and `lockfiles` entries are non-empty strings.

### `verify.dod_conditional`

`when` globs are matched against `git diff --name-only origin/<main_branch>...HEAD`.

## The manifest

`/make-plan` and `/implement` run `tld plan validate-manifest <plan.md> --profile .tld/toolkit.yaml`.
The manifest format is the one described in `playbooks/make-plan.md`; the validator checks required
keys, unique phase ids, known `depends_on`, no cycles, `brief` and `acceptance` on every phase,
`complexity` of `S` or `M`, a `worker_level` of `strong`, `standard` or `fast` and a `worker_level_reason` for
`strong`, honest manual-step entries, `feature_branch` against `git.branch_types`, and that phases which can run
at the same time share no path in `touches` (globs included). `tracking_issue` is optional everywhere.
`/implement` also runs `tld plan check-url` (a plan only from `<main>` or `plan/<slug>` of the same repository),
`tld plan branch-name` and `tld plan phase-status`.
