# Profile reference: `.claude/toolkit.yaml`

The profile is the only place a project's facts live. The commands read it through the
`project-profile` skill, which runs `validate_profile.py` first. The schema is
[`plugins/devflow/schema/profile.schema.json`](../plugins/devflow/schema/profile.schema.json); a
commented starter is [`templates/toolkit.yaml`](../templates/toolkit.yaml); a complete worked example
for a real project is PrivacyFence's profile, [`tests/fixtures/privacyfence-toolkit.yaml`](../tests/fixtures/privacyfence-toolkit.yaml) (see [`migrating-privacyfence.md`](migrating-privacyfence.md)).

Rules:

- A **required** key that is missing stops the command with a message that names it, for example
  `toolkit.yaml: missing required key 'verify.fast'`. The commands never fall back to a value of
  their own.
- An **optional** key that is missing means "not used in this project".
- Only two things have defaults, and `validate_profile.py --resolved` is where they are applied:
  `docs.plan_dir` (`docs`) and `models` (`opus / sonnet / sonnet / opus`).
- An unknown key is an error, so a typo is never silent.
- A file listed in `docs.must_read` or `project_steward` that does not exist is an error.

## Keys

| Key | Required | Meaning |
|---|---|---|
| `project.name` | no | Name used in prose; default is the repository name |
| `docs.must_read` | **yes** (may be `[]`) | Files the planner reads first, every worker brief names, and the final reviewer reads |
| `docs.plan_dir` | no (default `docs`) | Plan documents are `<plan_dir>/<slug>-plan.md`, with `<slug>-plan-manual-steps.html` beside it |
| `docs.adr_dir` | no | If set, the project uses ADRs and the commands plan, write and check them |
| `docs.adr_index` | no (needs `adr_dir`) | File that must list every new ADR |
| `docs.adr_bar` | no (needs `adr_dir`) | Where the criteria for needing an ADR are written (`path` or `path#anchor`) |
| `docs.changelog.file`, `docs.changelog.section` | no | A user-visible change adds a line under this heading; never a version heading |
| `git.main_branch` | **yes** | Base of plan branches, the merge target and the PR base |
| `git.branch_pattern` | **yes** | Human-readable branch rule, quoted into prompts, for example `<type>/<kebab-case>` |
| `git.branch_types` | no | Allowed `<type>` values; `/implement` rejects a manifest whose `feature_branch` uses another |
| `git.merge_style` | no | `merge-commit` or `squash`; only quoted to workers and the steward |
| `git.codeowners` | no (needs `git.bot_login`) | GitHub logins of the code owners (at least one). `/implement` requests their review on the pull request it opens and sets `needs_you` (`Review PR #<n>`); it never approves or merges |
| `git.bot_login` | no | Login of the second GitHub user the agent acts as. `/implement` calls `get_me` at the start and stops when the login differs. Must not be listed in `git.codeowners` |
| `verify.fast` | **yes** | Commands run after every merge by `/implement` and by the final reviewer. Seconds to a minute |
| `verify.dod` | **yes** | The blocking definition-of-done gate `/dod` runs, in order |
| `verify.dod_conditional` | no | `{when: [globs], do: text}`: checked against the diff by `/dod` |
| `verify.dod_manual` | no | Judgement rows `/dod` reports `ok / needs attention / n/a` |
| `verify.dod_doc` | no | Pointer to the project's human-readable DoD, quoted in the `/dod` report |
| `ci.dispatchable` | no | `{workflow, use_when, notes?}`: workflows a session may dispatch against its own branch for work the container cannot do |
| `stacks` | **yes** (may be `[]`) | Stack skills to load: `python` loads `stack-python`, `go` loads `stack-go`, `swift` loads `stack-swift`, `ipados` loads `stack-ipados` (list it with `swift`) |
| `models.planner`, `models.orchestrator`, `models.worker`, `models.reviewer` | no | `opus` or `sonnet`. `worker` and `reviewer` pick the model of child sessions; planner and orchestrator document intent (the command front matter sets them) |
| `status.board_url` | no | URL of the published status board; `/implement` writes its status record there. When unset the environment variable `DEVFLOW_BOARD_URL` is used; with neither, no board is written |
| `deps.cooldown_days` | **yes** (in `deps`) | Integer 0..30: the Dependabot cooldown (days) the project's `.github/dependabot.yml` must set. `/deps` needs the `deps` section and stops with a missing-key message when it is absent |
| `deps.time_budget_minutes` | **yes** (in `deps`) | Integer 10..480: `/deps` starts no new update group after 80% of this |
| `deps.audit` | no | List of `{ecosystem, run, cwd?}`: commands that list vulnerable packages (sessions cannot read Dependabot alerts). Exit 0 = nothing found; non-zero = findings in the output. `cwd` is relative to the repo root |
| `deps.lock_freshness` | no | List of `{when, run, lockfiles}`, run after a manifest change so lockfiles stay consistent (see below) |
| `upstream.repo` | **yes** (in `upstream`) | The upstream repository as `owner/name`. `/upstream` needs the `upstream` section |
| `upstream.tag_pattern` | **yes** (in `upstream`) | Regular expression a release tag must match; must compile |
| `upstream.version_file` | **yes** (in `upstream`) | File in the fork that records the synced tag |
| `land.max_prs` | no | Integer 1..50: most pull requests one `/land` run orders. `/land` works without the `land` section |
| `admin.policy` | **yes** (in `admin`) | Path, relative to the repo root, of the policy file the `repo-admin` skill audits and applies (see [admin.md](admin.md)). The file must exist. The skill needs the `admin` section and stops with a missing-key message when it is absent |
| `scope.ignore` | no | List of globs. `/implement` checks at each merge which files the phase changed outside its `touches` and reports them (see [scope-drift.md](scope-drift.md)); paths matching these globs are not counted. Default: none. The changelog file (`docs.changelog.file`) is always ignored when the profile has `docs.changelog`. Same glob semantics as `touches` (`*` and `**` match across `/`; an entry ending in `/` is a directory). The check never blocks a merge |
| `project_steward` | no | Path to a project skill or doc with policy that fits no other key; read after `pr-steward` and wins where more specific |

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
8. Open a session and ask it to call `get_me`; it must print the second login, not the owner's.

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

The planner treats anything one of these covers as a phase task, never a manual step; `pr-steward`
dispatches it instead of skipping the row; a swift or ipados project with an empty list gets a warning.
The workflow file must be on the default branch to be dispatchable (see `pr-steward`).

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

`/make-plan` and `/implement` run `scripts/validate_manifest.py <plan.md> --profile .claude/toolkit.yaml`.
The manifest format is the one described in `commands/make-plan.md`; the validator checks required
keys, unique phase ids, known `depends_on`, no cycles, `brief` and `acceptance` on every phase,
`complexity` of `S` or `M`, `worker_model_reason` for `worker_model: opus`, honest manual-step
entries, `feature_branch` against `git.branch_types`, and that phases which can run at the same
time share no path in `touches` (globs included).
