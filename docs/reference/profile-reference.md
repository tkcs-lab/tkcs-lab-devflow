# Profile reference: `.tld/toolkit.yaml`

The profile is the only place a project's facts live. The playbooks read it as
[`playbooks/policies/profile.md`](../../playbooks/policies/profile.md) says, which runs `tld profile validate` first.
The schema is [`src/tld/schema/profile.schema.json`](../../src/tld/schema/profile.schema.json); a
commented starter is [`src/tld/templates/toolkit.yaml`](../../src/tld/templates/toolkit.yaml). The first project's
profile, [`tests/fixtures/privacyfence-toolkit.yaml`](../../tests/fixtures/privacyfence-toolkit.yaml), is kept as a
regression fixture in the current key names (see [`migrating-privacyfence.md`](../migrating-privacyfence.md)); it is
not a description of that project today.

Rules:

- Every command reads the **resolved profile**: the repository's own keys, over the keys of the pinned base it
  extends (`tld.extends`), over the built-in defaults below. `tld profile validate --resolved` prints it as JSON and
  `--explain` prints `<dotted key> = <json value>  # <source>` per value, the source being `repo`, `base <owner>/<repo>/<path>@<sha7>`,
  `default`, `default (<path> exists)` or `detected (origin/HEAD)`. `--ref REF` reads the profile and the files that
  decide the defaults from that git ref; without it the working tree is read.
- A **required** key that is still missing from the resolved profile stops the command with a message that names it,
  for example `toolkit.yaml: missing required key 'verify.fast'`. What a command never does is guess a value the
  resolved profile lacks; a base value or a built-in default is part of the profile.
- The only keys a repository must write are `verify.fast` and `verify.dod`. A minimal profile is `tld.extends` plus
  those two; without a base the keys the template marks are written as before.
- An **optional** key that is missing means "not used in this project".
- `false` turns a defaulted feature off: `docs.index`, `docs.adr_dir`, `docs.changelog`, `docs.website`, `admin`,
  `git_ops` and `land.max_prs`. An off switch also stops the defaults that depend on it (`admin: false` stops
  `admin.policy`, `docs.adr_dir: false` stops `adr_index` and `adr_bar`). The resolved profile never contains `false`
  for them. The gates are switched off with `enabled: false`. `null` is not an off switch: an empty `deps:`, `spec:` or
  `sysml:` section means "on with the defaults".
- **Built-in defaults** (`src/tld/profile/defaults.py`; `--explain` shows which ones applied):
  - always: `git.branch_pattern` `<type>/<kebab-case>`, `git.branch_types` `[feature, fix, chore]`, `git.merge_style`
    `merge-commit`, `docs.must_read` and `stacks` empty, `models` (`worker: standard`, `reviewer: strong`), `land.max_prs`
    10, `git_ops.workflow` `tld-git-ops.yml`, `hooks.disable` empty, `hooks.protect_paths` (`.env`, `.env.*`, `*.lock`,
    `package-lock.json`, `go.sum`), `hooks.protect_paths_allow` empty, and the three gates on (`dod_gate` with
    `max_attempts` 3). A repository with no profile at all keeps the gates off.
  - inside a section the repository writes (an empty section counts): `deps` `cooldown_days` 3 and
    `time_budget_minutes` 90, `spec.version` `2.1.0`, `sysml.subset` 1, `release.workflow` `tld-release.yml`
    (`release.version_files` stays required).
  - detected: `git.main_branch` from `origin/HEAD` (else the remote default branch), `git_ops.repo` as
    `<origin owner>/git-ops`.
  - when a file exists: `docs.plan_dir` is `docs/plans` if that directory exists, else `docs`; `docs.index`
    (`docs/README.md`), `docs.adr_dir` and `docs.adr_index` (`docs/adr`, `docs/adr/README.md`), `docs.adr_bar`
    (when `CONTRIBUTING.md` has the heading "Decisions, plans and ADRs"), `docs.changelog` (`CHANGELOG.md`,
    `## [Unreleased]`, policy `unreleased`), `admin.policy` (`.tld/admin-policy.yaml`) and `docs.website`
    (`scripts/build_site.py`; `dir` is `.` because `build` and `links` run from `dir` and name root-relative paths).
    The result differs by mode: pass `--ref` or `--root` so the right files are looked at; `--no-file-checks` skips them.
- A base profile takes only allow-listed keys (`tld.version`, `tld.allow_override`, `git.bot_login`, `git.codeowners`,
  `git.branch_pattern`, `roles.posture`, `roles.required`, `hooks.*`, `models`, `runtime.environments`,
  `verify.dod_manual`) and is checked before anything reads it ([org-base.md](../guides/org-base.md)). The repository
  overrides scalars and lists of the base, except `verify.dod_manual` (rows are appended) and `roles.required`
  (merged by `role`: `at` is the union, `blocking` is base OR repository, `when` the union). The **guarded keys**
  (`hooks.disable`, the protect lists, the three gates, `roles.posture.security` and `roles.required`/`roles.disable`)
  are refused by `tld profile validate` (and reported by the audit) when a repository weakens them, unless the base lists them in
  `tld.allow_override`; at run time every guarded key is
  also clamped to the stricter of the working copy and the default branch's resolved profile, with a warning.
- `tld.version`, when set, must be satisfied by the running tld, or validation fails. A profile with `tld.extends`
  needs `>=1.7`; an older tld rejects the unknown key.
- An unknown key is an error, so a typo is never silent.
- A file listed in `docs.must_read` or `project_steward` that does not exist is an error.
- `tld profile base check FILE | fetch [PROFILE] [--ref REF] | latest SOURCE` check a base file, fill the cache of the
  pinned base (`fetch --ref REF` fills the pin of that ref's profile) and print the commit and tag to pin.
- A claude-toolkit profile (`.claude/toolkit.yaml`, `agents`, model names in `models`) is converted by `tld migrate`
  ([migrating-from-claude-toolkit.md](../guides/migrating-from-claude-toolkit.md)); its fixtures are in
  `tests/fixtures/legacy/`.


## Keys

| Key | Required | Meaning |
|---|---|---|
| `tld` | no | Holds `version` |
| `tld.version` | no | A version specifier such as `>=1.0,<2` (clauses `==`, `!=`, `>=`, `<=`, `>`, `<`, joined by commas). `tld profile validate` fails when the running tld does not satisfy it; a development build (`1.0.0.dev0`) counts as the release it leads to. `/setup` writes `>=<major>.<minor>,<<major+1>` |
| `tld.extends` | no | The org base profile this repository extends: `<owner>/<repo>/<path>@<40-hex commit>`. Only a full commit is accepted (a tag or branch can move); `tld profile base latest` prints the commit to use and `/setup` writes it with the tag as a trailing comment. The commit must be a version tag's commit or an ancestor of the base repository's default branch head. See [org-base.md](../guides/org-base.md) |
| `tld.allow_override` | no (base only) | Set in the base profile, never in a repository (an error there). A closed list of guarded keys a repository that extends the base may weaken: `hooks.disable.<hook>`, `hooks.protect_paths`, `hooks.protect_paths_allow`, `hooks.dod_gate.enabled`, `hooks.plan_gate.enabled`, `hooks.board_gate.enabled`, `roles.posture.security`, `roles.required.<role>` |
| `project.name` | no | Name used in prose; default is the repository name |
| `docs.must_read` | no (default `[]`) | Files the planner reads first, every worker brief names, and the final reviewer reads |
| `docs.plan_dir` | no (default `docs/plans` when that directory exists, else `docs`) | Plans are `<plan_dir>/<n>/plan.md` on the feature branch (`<n>` = the tracking issue number) and stay after the merge; reviews are `<plan_dir>/<slug>-review.md`. The resolved value has no trailing slash |
| `docs.index` | no (default `docs/README.md` when that file exists; `false` turns it off) | The entry-level docs index: the one file sessions read first, then only the rows that match the task. `/docs init` builds it, `/docs` checks it, `/setup` proposes it when it finds one. With it, `docs.must_read` keeps at most three files (a warning otherwise) |
| `docs.adr_dir` | no (default `docs/adr` when that directory exists; `false` turns ADRs off) | If set, the project uses ADRs and the commands plan, write and check them |
| `docs.adr_index` | no (default `docs/adr/README.md` when `docs/adr` exists) | File that must list every new ADR |
| `docs.adr_bar` | no (default `CONTRIBUTING.md#decisions-plans-and-adrs` when the ADR directory was defaulted and `CONTRIBUTING.md` has the heading "Decisions, plans and ADRs") | Where the criteria for needing an ADR are written (`path` or `path#anchor`) |
| `docs.changelog.file`, `docs.changelog.section` | no (default `CHANGELOG.md` and `## [Unreleased]` when `CHANGELOG.md` exists; `docs.changelog: false` turns the changelog off) | A user-visible change adds a line under this heading; never a version heading |
| `docs.changelog.policy` | no (default `unreleased`) | `unreleased`: a user-visible change adds a line under `section`; the `protect-paths` hook denies a session opening a version heading in the file unless the change touches only the changelog. `release-only`: the changelog is written when a release is cut; the hook denies every session edit of the file unless the change touches only the changelog, `section` is not needed, and no playbook adds a changelog line |
| `docs.website` | no (default, when `scripts/build_site.py` exists: `dir` `.`, `build` `python3 scripts/build_site.py --out _site`, `links` `python3 -m pytest tests/unit/test_website_links.py -q`; `false` turns it off) | The project's website; present means the `website-maintainer` role can run. Keys: `dir`, `build`, `links` |
| `docs.website.dir` | **yes** (in `docs.website`) | Directory relative to the repo root (`.` for the root); `build` and `links` run from there |
| `docs.website.build` | **yes** (in `docs.website`) | Command that builds the site |
| `docs.website.links` | no | Command that checks the site's links |
| `git.main_branch` | no (default: the branch `origin/HEAD` names, else the remote default branch) | Base of feature branches, the merge target and the PR base. A resolved profile that still has none stops with `missing required key 'git.main_branch' (it could not be detected: ...)` |
| `git.branch_pattern` | no (default `<type>/<kebab-case>`) | Human-readable branch rule, quoted into prompts |
| `git.branch_types` | no (default `[feature, fix, chore]`) | Allowed `<type>` values; `/implement` rejects a manifest whose `feature_branch` uses another. A repository that uses other types writes them |
| `git.merge_style` | no (default `merge-commit`) | `merge-commit` or `squash`; quoted to workers and the steward, and the audit's `profile-merge-style` check compares it with the repository's merge settings. A squash repository writes it |
| `git.codeowners` | no (needs `git.bot_login`) | GitHub logins of the code owners (at least one). `/implement` requests their review on the pull request it opens and sets `needs_you` (`Review PR #<n>`); it never approves or merges |
| `git.bot_login` | no | Login of the second GitHub user the agent acts as. `/implement` checks `identity()` at the start and stops when the login differs. Must not be listed in `git.codeowners` |
| `git.owner_login` | no | GitHub login of the owner. When the board cannot be reached, `tld board ask --fallback-issue` mentions it in the issue comment that carries the questions (default: the repository owner). See [board-server.md](../guides/board-server.md) |
| `verify.fast` | **yes** | Commands run after every merge by `/implement` and by the final reviewer. Seconds to a minute |
| `verify.dod` | **yes** | The blocking definition-of-done gate `/dod` runs, in order |
| `verify.dod_conditional` | no | `{when: [globs], do: text}`: checked against the diff by `/dod` |
| `verify.dod_manual` | no | Judgement rows `/dod` reports `ok / needs attention / n/a`. With a base, the base's rows come first and the repository's follow, without duplicates |
| `verify.dod_doc` | no | Pointer to the project's human-readable DoD, quoted in the `/dod` report |
| `verify.after_merge_allow` | no | Command prefixes (`npm test`) whose `verify_after_merge` commands `/implement` runs without asking (S14); read from the main branch's profile, never a plan branch's. Name read-only checks only, never a whole tool whose subcommands can change state or lift a guard. No positional word may follow the prefix: every word after it must be a safe option of the program, with a plain value (no glob, no `@`, no leading `-`; a path value has no leading `/` and no segment that starts with `.`). tld's own options are `--json --strict --no-file-checks --index <path> --ref <word>`; a stack guide adds its tools' options in an `after-merge-options` block (the python guide: pytest `-q -x -v -vv -k -m --tb`); a program no table names takes none. Anything else makes the command unknown, so the owner is asked; see `tld plan check-commands` |
| `ci.dispatchable` | no | `{workflow, use_when, notes?}`: workflows a session may dispatch against its own branch for work the container cannot do |
| `stacks` | no (default `[]`) | Stack guides to load: `python` loads `stacks/python.md`, `go`, `swift` and `ipados` likewise (list `ipados` with `swift`) |
| `models` | no | The levels of the workers the playbooks start: `strong`, `standard` or `fast`. The adapter maps a level to a model (Claude: the `tld:runtime` skill) |
| `models.worker` | no (default `standard`) | `/implement`'s phase, fix and conflict workers (a phase's `worker_level` overrides it) |
| `models.reviewer` | no (default `strong`) | `/implement`'s final reviewer, `/make-plan`'s plan reviewer, `/review`'s roles and verifiers |
| `ci.time_budget_minutes` | no | Integer 10..480 (default 60): `/ci` starts no new workflow after 80% of this |
| `ci.lookback_hours` | no | Integer 1..168 (default 36): how far back `/ci` looks at workflow runs on the default branch |
| `ci.ignore_workflows` | no | List of workflow file names `/ci` does not watch (for example a canary that is red on purpose) |
| `deps.cooldown_days` | no (default 3, applied when the `deps` section is written) | Integer 0..30: the Dependabot cooldown (days) the project's `.github/dependabot.yml` must set. `/deps` needs the `deps` section: an empty `deps:` switches it on with the defaults, and without the section it stops with `toolkit.yaml: /deps needs a 'deps' section (...)` |
| `deps.time_budget_minutes` | no (default 90, applied when the `deps` section is written) | Integer 10..480: `/deps` starts no new update group after 80% of this |
| `deps.audit` | no | List of `{ecosystem, run, cwd?}`: commands that list vulnerable packages (sessions cannot read Dependabot alerts). Exit 0 = nothing found; non-zero = findings in the output. `cwd` is relative to the repo root |
| `deps.lock_freshness` | no | List of `{when, run, lockfiles}`, run after a manifest change so lockfiles stay consistent (see below) |
| `upstream.repo` | **yes** (in `upstream`) | The upstream repository as `owner/name`. `/upstream` needs the `upstream` section |
| `upstream.tag_pattern` | **yes** (in `upstream`) | Regular expression a release tag must match; must compile |
| `upstream.version_file` | **yes** (in `upstream`) | File in the fork that records the synced tag |
| `land.max_prs` | no (default 10; `false` removes the cap) | Integer 1..50: most pull requests one `/land` run orders |
| `spec` | no | Section for the spec commands and the spec change `/make-plan` writes. Absent means the repository does not use specs; an empty `spec:` switches them on with the defaults |
| `spec.version` | no (default `2.1.0`, applied when the `spec` section is written) | Exact OpenSpec release as MAJOR.MINOR.PATCH; the wrapper installs @fission-ai/openspec@<version> and re-checks the format with a full match (the schema pattern alone would let a trailing newline through). Guide: [docs/guides/spec.md](../guides/spec.md) |
| `sysml` | no | Section for the architecture commands and the architecture change /make-plan writes. Absent means the repository has no architecture model; an empty `sysml:` switches it on with the defaults |
| `sysml.subset` | no (default 1, applied when the `sysml` section is written) | Integer, only 1 today: the version of the tld SysML subset (see [docs/guides/sysml.md](../guides/sysml.md)). A new grammar is a new number |
| `admin.policy` | no (default `.tld/admin-policy.yaml` when that file exists; `admin: false` turns the audit off) | Path, relative to the repo root, of the policy file the repo-admin playbook audits and applies (see [admin.md](../guides/admin.md)). An explicit path must exist. Without the key and the file the audit stops with `the admin audit is off (no .tld/admin-policy.yaml; ...)` |
| `git_ops.repo` | no (default `<origin owner>/git-ops` when the repository has an origin; `git_ops: false` turns it off) | Owner/name of the central repository that holds the `tld-git-ops` workflow. With `git_ops: false` the git-ops playbook stops with `/git-ops is switched off`; see [git-ops.md](../guides/git-ops.md) |
| `git_ops.workflow` | no (default `tld-git-ops.yml`) | File name of the workflow in that repository |
| `release` | no | Section for the release skill. Needs `docs.changelog` (the skill turns its unreleased section into a version heading). If present it needs `version_files` (`workflow` defaults to `tld-release.yml`) |
| `release.workflow` | no (default `tld-release.yml`, applied when the `release` section is written) | File name of the release workflow in `.github/workflows`. It takes the boolean input `dry_run`; the release skill dispatches it with `dry_run` false after the owner's yes. The file must exist |
| `release.version_files` | **yes** (in `release`) | Files that hold the version, a non-empty list of `{path, pattern}`; the release skill edits only the version captured by the pattern. The pattern is a multiline regular expression with exactly one capture group (the version) and must match exactly once in the file. The pattern is trusted input: keep it simple and anchored, without nested quantifiers (a catastrophic pattern hangs the validator) |
| `hooks.disable` | no (default none) | Names of guardrail hooks to switch off in this repository: any of `no-merge`, `no-force-push`, `no-git-tag`, `secret-scan`, `protect-paths`, `dod-gate`, `plan-gate`, `model-check`, `board-gate`, `env-check`. Read from the default branch's resolved profile, so a branch cannot switch a hook off for itself; it must be a list. A base that switches a hook on forbids switching it off unless it lists `hooks.disable.<hook>` in `tld.allow_override`. The escape hatch; see [hooks.md](../architecture/hooks.md) |
| `hooks.protect_paths` | no (default `.env`, `.env.*`, `*.lock`, `package-lock.json`, `go.sum`) | Globs of repo-relative paths `protect-paths` refuses to edit. A list here replaces the default (a base's list must stay included unless the base allows otherwise). `.tld/toolkit.yaml` and `.github/workflows/**` are **not** in the default: the release, land and git-ops workflows (and the profile's `release.workflow`) stay protected in code (the profile's `release.workflow` only with a trusted copy; see hooks.md), and a pull request that changes the profile or a workflow must name it under Security. A pattern without a slash matches the file name at any depth; `**` crosses directories. `*` and `?` do **not** cross `/` (unlike `touches` and `scope.ignore`) |
| `hooks.protect_paths_allow` | no (default none) | Globs exempt from `protect_paths`, on top of the built-in exceptions (`.env.example`, `.env.sample`, `.env.template`, `.env.dist`, the workflow files `/land` and `repo-admin` install). Entries for workflows that are no longer on the default list are moot |
| `hooks.dod_gate.enabled` | no (default `true`) | The `dod-gate` Stop hook: the session cannot stop while `verify.dod` fails. Not applied to sessions that marked themselves exempt, such as the `/implement` orchestrator. `false` switches it off. `tld profile validate` refuses `false` (and the audit reports it) when a base turns the gate on without listing it in `tld.allow_override`; the hook applies the resolved, clamped value and does not re-check the base (see [hooks.md](../architecture/hooks.md#disabling-a-hook)) |
| `hooks.dod_gate.max_attempts` | no (default `3`) | Integer 1..10: failed attempts after which the gate lets the session stop and tells the user why. The gate reads it, and `verify.dod`, from the default branch's copy when one is available |
| `hooks.plan_gate.enabled` | no (default `true`) | The `plan-gate` hook: a session that no tld command started cannot write into the repository; it is told to answer and to propose `/make-plan`. See [hooks.md](../architecture/hooks.md) |
| `hooks.board_gate.enabled` | no (default `true`) | The `board-gate` Stop hook: a session that a record-writing tld command started cannot end its turn before it has written its status record once, after an ask, a worker start or stop, a pull request or a push left the record unwritten, or after an ask without an armed timer; each rule blocks once per event. See [hooks.md](../architecture/hooks.md) |
| `runtime` | no | Facts about where this repository's sessions run |
| `runtime.environments` | no | Non-empty list of environment names (1 to 100 characters, no control or format characters) this repository's sessions are meant to run in. The `env-check` hook warns in a cloud session whose `TLD_ENVIRONMENT` is missing or not in the list, and every command's profile loading warns when the runtime reports another name; names are compared after trimming, ignoring case. Warnings only, nothing stops. An older tld rejects this key. See [hooks.md](../architecture/hooks.md) |
| `scope.ignore` | no | List of globs. `/implement` checks at each merge which files the phase changed outside its `touches` and reports them (see [scope-drift.md](../architecture/scope-drift.md)); paths matching these globs are not counted. Default: none. The changelog file (`docs.changelog.file`) is always ignored when the profile has `docs.changelog`. Same glob semantics as `touches` (`*` and `**` match across `/`; an entry ending in `/` is a directory). The check never blocks a merge |
| `roles` | no | Which roles are mandatory and how they run; see [`roles`](#roles) below |
| `roles.posture` | no | Holds `security` |
| `roles.posture.security` | no (default `standard`) | `critical`, `standard` or `low`: how deep `security-reviewer` goes |
| `roles.disable` | no (default none) | Role names that are never run. A role the base requires cannot be disabled unless the base lists `roles.required.<role>` in `tld.allow_override` |
| `roles.required` | no (default none) | List of `{role, at, blocking?, when?}`: roles that must run at the listed points. `at` is a non-empty list of `make_plan`, `implement_phase`, `implement_final`, `review`, `dod`; `blocking` (default `false`); `when` is a non-empty list of globs matched against the changed files. With a base the lists merge by `role` (see below) |
| `roles.extra_context` | no | List of non-empty strings added to every role's context |
| `project_steward` | no | Path to a project doc with policy that fits no other key; read after the pr-steward policy and wins where more specific |

### roles

The eleven roles are `architect`, `code-reviewer`, `security-reviewer`, `test-architect`, `ux-reviewer`,
`dependency-auditor`, `tech-writer`, `website-maintainer`, `debugger`, `refactorer` and `reflektor` (role cards in `roles/`,
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
  `test-architect`, `tech-writer` and `website-maintainer` can run at `review`; `reflektor` can only run at `dod`.

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
goes away until the connection is swapped back. The owner does these steps once per repository. Plans do not repeat them; `/implement` checks step 8 at
every start by comparing `identity()` with `git.bot_login`:

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

`when` and `lockfiles` are globs as in `hooks.protect_paths`: without a `/` a glob matches the file name at any depth, `**` crosses directories. A changed lockfile that no entry lists keeps its group out of the combined `/deps` pull request only when its name is built in (`*.lock`, `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `go.sum`); any other lockfile is seen only when an entry lists it.

### `verify.dod_conditional`

`when` globs are matched against `git diff --name-only origin/<main_branch>...HEAD`.

## The manifest

`/make-plan` and `/implement` run `tld plan validate-manifest <plan.md> --profile .tld/toolkit.yaml`.
The manifest format is the one described in `playbooks/make-plan.md`; the validator checks required
keys, unique phase ids, known `depends_on`, no cycles, `brief` and `acceptance` on every phase,
`complexity` of `S` or `M`, a `worker_level` of `strong`, `standard` or `fast` and a `worker_level_reason` for
`strong`, honest manual-step entries, `feature_branch` against `git.branch_types`, and that phases which can run
at the same time share no path in `touches` (globs included). `tracking_issue` is optional everywhere.
`spec_change` (optional) names the OpenSpec change the plan carries; the profile needs a `spec` block and only the last phase may touch `openspec/`.
`sysml_change` (optional) names the architecture change the plan carries; the profile needs a `sysml` block and only the last phase may touch `sysml/`, `docs/architecture.md` and `docs/architecture.svg`; with a `sysml` block and no `sysml_change` no phase may touch them.
`/implement` also runs `tld plan check-url` (a plan only from `<main>` or a feature branch of the same repository, at `<plan_dir>/<n>/plan.md`),
`tld plan branch-name` and `tld plan phase-status`.
