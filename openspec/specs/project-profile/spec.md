# project-profile Specification

## Purpose
The project profile is the repository's tld configuration file; this capability validates it against the schema, checks the tld version it needs, surveys a repository to propose profile blocks, edits blocks as text, and migrates a legacy claude-toolkit repository to tld.

## Requirements

### Requirement: Validate a profile against the schema
The system SHALL, for `tld profile validate [PROFILE]` (default `.tld/toolkit.yaml`), resolve the profile (its own keys, the pinned base and the built-in defaults), print `toolkit.yaml: OK (<path>)` and exit 0 for a valid result, and print one `toolkit.yaml: <error>` line per problem to stderr and exit 1 otherwise. The only key a profile must write is `verify` (`fast` and a non-empty `dod`); a resolved profile with no `git.main_branch` is an error that says it could not be detected.

#### Scenario: Valid minimal profile
- **WHEN** the profile has only `verify.fast` and `verify.dod`
- **THEN** the exit code is 0

#### Scenario: Missing required key
- **WHEN** `verify.fast` is absent
- **THEN** stderr contains `toolkit.yaml: missing required key 'verify.fast'` and the exit code is 1

#### Scenario: Unknown key and wrong type
- **WHEN** a profile has a misspelled key, or `verify.fast` is a string
- **THEN** errors name `unknown key '<key>'` or `must be a list` and the exit code is 1

#### Scenario: No file or bad YAML
- **WHEN** the profile path does not exist or is not valid YAML
- **THEN** stderr explains it (`no profile at` for a missing file) and the exit code is 1

#### Scenario: Old profile without extends
- **WHEN** a profile written for an earlier tld sets every key it needs and has no `tld.extends`
- **THEN** it validates as before and every key it wrote keeps its value; only keys it left out receive the listed defaults

### Requirement: Reject removed and renamed sections
The system SHALL reject a profile with a `toolkit` section (removed) or an `agents` section (renamed to `roles`, each entry's `agent` to `role`) with a single message that says what to do.

#### Scenario: Old agents key
- **WHEN** a profile has an `agents` key
- **THEN** the only error says `agents` was renamed to `roles` and the section must be renamed

### Requirement: Apply semantic checks beyond the schema
The system SHALL report inconsistent combinations of profile keys that the schema cannot express as errors, and SHALL report doubtful but workable combinations as warnings that leave the exit code at 0.

#### Scenario: Errors for inconsistent keys
- **WHEN** `docs.adr_index` or `docs.adr_bar` is set without `docs.adr_dir`, `git.codeowners` is set without `git.bot_login`, `upstream.tag_pattern` is not a valid regular expression, or a `release` section has no `docs.changelog`
- **THEN** an error is reported for each and the exit code is 1

#### Scenario: Errors for release patterns
- **WHEN** a release version-file pattern does not compile or does not have exactly one capture group
- **THEN** an error is reported and the exit code is 1

#### Scenario: Errors for roles
- **WHEN** a required role is also in `roles.disable`, `website-maintainer` is used without `docs.website`, `when` is set on a role whose points have no diff, `reflektor` is at a point other than `dod`, or a role at `review` has no review dimension
- **THEN** an error is reported for each and the exit code is 1

#### Scenario: Further warnings
- **WHEN** `git.bot_login` is set without `git.codeowners`, the `ipados` stack is used without `swift`, or more than three `docs.must_read` files are listed while `docs.index` is set
- **THEN** a `toolkit.yaml: warning:` line is printed for each and the exit code stays 0

#### Scenario: Bot as code owner
- **WHEN** `git.codeowners` lists the `git.bot_login` account
- **THEN** an error says the agent cannot be its own code owner

#### Scenario: Warning only
- **WHEN** the `swift` stack is selected and `ci.dispatchable` is empty
- **THEN** a `toolkit.yaml: warning:` line is printed to stderr and the exit code is 0

### Requirement: Check that listed files exist
The system SHALL, unless `--no-file-checks` is given, report `file not found` for each listed `docs.must_read` file, `docs.index`, `project_steward`, `admin.policy`, release workflow file and release version file, checking from the repository root (the profile file's grandparent directory, or `--root DIR`), SHALL refuse a release version file that resolves outside the root, and SHALL require each release pattern to match exactly once in its file.

#### Scenario: Missing must-read file
- **WHEN** `docs.must_read` lists a file that does not exist
- **THEN** an error `file not found: '<path>'` is printed and the exit code is 1

#### Scenario: File checks skipped
- **WHEN** `--no-file-checks` is given
- **THEN** no file-existence error is reported

### Requirement: Print the resolved profile
The system SHALL, with `--resolved`, print the resolved profile as indented JSON (the repository's keys over the base's over the built-in defaults, the whole `hooks` section included), and with `--explain` one line per key, `<dotted key> = <json value>  # <source>`, naming the repository, the base with its commit, a default or a detected value.

#### Scenario: Resolved output
- **WHEN** a valid profile without `docs.plan_dir` is validated with `--resolved`
- **THEN** stdout is JSON with a `docs.plan_dir` of `docs` (or `docs/plans` when the repository has a `docs/plans` directory) and the exit code is 0

#### Scenario: Explained output
- **WHEN** a profile extends a base and `--explain` is given
- **THEN** every line names whether its value came from the repository, the base, a default or a detection

#### Scenario: Resolved at a ref
- **WHEN** `--ref <ref>` is given
- **THEN** the profile and the files that decide the defaults are read from that ref, not from the working tree

### Requirement: Check the required tld version
The system SHALL compare `tld.version`, when set, with the running tld version and report an error when it is not satisfied. A specifier is a comma-separated list of clauses using `==`, `!=`, `>=`, `<=`, `>` or `<` with dotted integer versions; versions are compared as integers padded with zeros, and a development or release-candidate build counts as the release it leads to. An unreadable specifier is reported as an error under `'tld.version'`.

#### Scenario: Satisfied
- **WHEN** `tld.version` is `>=1.0,<2` and the running version is 1.4.2
- **THEN** no version error is reported

#### Scenario: Not satisfied
- **WHEN** the running version is 2.1.0 and `tld.version` is `>=1.0,<2`
- **THEN** the error starts `'tld.version': this profile needs tld >=1.0,<2, but tld 2.1.0 is running`

#### Scenario: Malformed specifier
- **WHEN** `tld.version` is `latest` or `~=1.0`
- **THEN** an error under `'tld.version'` is reported

### Requirement: Survey a repository read-only
The system SHALL, for `tld profile survey [ROOT]` (default `.`), print as JSON the `root`, the `evidence` and a `proposal`, change nothing, and exit 1 with `profile_survey: <path> is not a directory` when ROOT is not a directory.

#### Scenario: Evidence content
- **WHEN** the survey runs on a repository
- **THEN** the evidence covers stacks, other stacks, CI workflows and dispatchable macOS or Windows workflows, verify evidence from CI run steps, Makefile targets and package scripts, git facts, docs and signals

#### Scenario: Partial surveys
- **WHEN** `survey-docs` or `survey-signals` runs
- **THEN** it prints its part of the evidence with the same ROOT rule

#### Scenario: Proposal from evidence
- **WHEN** `survey-proposal EVIDENCE.json` runs on an evidence file or a whole survey output
- **THEN** the proposal built from it is printed, and a wrong argument count or an unreadable file gives exit code 1

#### Scenario: Bare repository
- **WHEN** the survey runs on a directory without stack files or workflows
- **THEN** `stacks` is empty and `ci.workflows` is empty

#### Scenario: Dispatchable workflow
- **WHEN** a workflow has a manual-dispatch trigger and runs on a Windows or macOS runner
- **THEN** it is listed as dispatchable with a use-when text naming the operating system and its inputs

#### Scenario: Not a git repository
- **WHEN** ROOT is not in a git work tree
- **THEN** the git facts have no main branch, no history and no branch prefixes

#### Scenario: Not a directory
- **WHEN** ROOT is a file
- **THEN** the exit code is 1

### Requirement: Diff a proposal against the profile
The system SHALL, for `tld profile patch diff PROFILE PROPOSAL.json [--root DIR]`, print JSON with the keys `new`, `changed`, `same` and `stale`, comparing the proposal's stacks, main branch, docs keys, `ci.dispatchable` and roles with the profile, where `stale` lists profile paths that do not exist and `roles.required[].when` globs that match no file under the root.

#### Scenario: Classification
- **WHEN** a proposal has one key missing from the profile, one with a different value and one equal
- **THEN** they appear under `new`, `changed` (with `from` and `to`) and `same`

#### Scenario: Unreadable input
- **WHEN** the profile or proposal cannot be read or is not valid JSON or YAML
- **THEN** `profile_patch: <message>` goes to stderr and the exit code is 1

### Requirement: Set one profile block as a text edit
The system SHALL, for `tld profile patch set-block PROFILE KEY PROPOSAL.json [--answers F] [--write [--yes]]` with KEY `roles` or `docs.website`, merge the proposal with the answers for KEY (mappings merge key by key, `required` role items merge by `role` and an item with `drop` true removes the role), print the unified diff, and change only that block while keeping all other bytes and comments of the profile.

#### Scenario: Dry run
- **WHEN** `--write` is not given
- **THEN** the diff is printed, nothing is written and the exit code is 0

#### Scenario: New block written
- **WHEN** `--write` is given and the profile does not have the key
- **THEN** the block is written and `profile_patch: wrote '<key>' to <profile>` is printed

#### Scenario: Hand-tuned block
- **WHEN** `--write` is given, the profile already has the key with a different value and `--yes` is absent
- **THEN** the diff is printed, nothing is written and the exit code is 4

#### Scenario: Nothing to set
- **WHEN** neither proposal nor answers have the key
- **THEN** nothing changes and the exit code is 0

#### Scenario: Same value
- **WHEN** the profile already has the merged value
- **THEN** `'<key>' is unchanged` is printed and the exit code is 0

#### Scenario: Errors
- **WHEN** KEY is neither `roles` nor `docs.website`, the profile is missing, an answers item has no `role`, or `docs.website` is set on a profile without a `docs` block
- **THEN** an error is printed to stderr and the exit code is 1

### Requirement: Plan a migration without changing anything
The system SHALL, for `tld migrate [ROOT]` without `--write`, print the plan of changes, the validation result of the migrated profile and an owner checklist, and change nothing.

#### Scenario: Profile changes in the plan
- **WHEN** the plan is built for a legacy profile
- **THEN** it moves the profile to `.tld/toolkit.yaml` (never overwriting an existing one), renames `agents` to `roles`, maps `models` values `opus`, `sonnet` and `haiku` to `strong`, `standard` and `fast`, drops `models.planner`, `models.orchestrator` and the removed sections, adds `tld.version` as `>=1.0,<2`, and adds `docs.plan_dir` as `docs/` when the legacy profile has none

#### Scenario: File changes in the plan
- **WHEN** the plan is built for a legacy repository
- **THEN** it rewrites legacy manifest keys in plan files, replaces legacy land, release and git-ops workflow files with the current tld ones, and rewrites `devflow:`, the legacy profile path and `DEVFLOW_` in the listed Markdown files

#### Scenario: Dry run
- **WHEN** `tld migrate` runs on a legacy repository without `--write`
- **THEN** stdout says `(dry run; --write applies it)`, lists the changes, prints `Validation of .tld/toolkit.yaml (as it will be)` and the checklist, the working tree is unchanged and the exit code is 0

#### Scenario: Legacy script command
- **WHEN** a profile value runs a script under a legacy plugin directory
- **THEN** that value is left as it is and listed in the owner checklist

### Requirement: Apply a migration and stay idempotent
The system SHALL, with `--write`, apply the plan, stage every change in a git repository (moving the profile with `git mv`, removing old workflows with `git rm`) without committing, keep the profile's comments when a text-level edit is provably equal to the intended data (otherwise rewrite it from the data and say comments are lost), validate the migrated profile, and print the owner checklist.

#### Scenario: Second run
- **WHEN** `tld migrate --write` runs again on a migrated repository
- **THEN** it prints `Nothing to migrate: the repository already uses tld.` and changes nothing

#### Scenario: Existing destination
- **WHEN** both the legacy and the new profile exist
- **THEN** the new one is kept and migrated, the old one is left alone and a note says so

### Requirement: Refuse unsafe paths and report migration failures
The system SHALL never follow a symbolic link while migrating and SHALL report a file that is a link or sits under one as refused; it SHALL exit 1 when neither profile exists, when the profile is not a valid YAML mapping, when a profile path is a link, or when the migrated profile does not validate, and exit 2 when ROOT is not a directory.

#### Scenario: No profile
- **WHEN** neither the legacy nor the new profile exists
- **THEN** stderr says there is no profile and the exit code is 1

#### Scenario: Linked profile
- **WHEN** the legacy profile or the `.tld` directory is a symbolic link
- **THEN** the migration is refused and the exit code is 1

#### Scenario: Invalid result
- **WHEN** the migrated profile fails validation
- **THEN** the errors are printed under the validation heading and the exit code is 1

### Requirement: Extend a pinned base profile
The system SHALL accept `tld.extends` as `<owner>/<repo>/<path>@<40-hex commit>` and SHALL reject any other form, including a tag or a branch name. A base profile cannot itself set `tld.extends`, and only a base profile may set `tld.allow_override`.

#### Scenario: Valid pin
- **WHEN** `tld.extends` names a repository file and a 40-hex commit
- **THEN** the profile resolves with that base

#### Scenario: Not a commit
- **WHEN** `tld.extends` ends in `@v1` or `@main`
- **THEN** an error under `'tld.extends'` says the base must be pinned by its full 40-hex commit, names the command that finds it, and the exit code is 1

#### Scenario: Malformed source
- **WHEN** the source has an empty or dotted path segment, a backslash, a path that is not a YAML file, or an owner or repository name GitHub does not allow
- **THEN** an error under `'tld.extends'` is printed and the exit code is 1

#### Scenario: Base chains refused
- **WHEN** the fetched base itself sets `tld.extends`
- **THEN** an error says a base cannot extend another profile

#### Scenario: Repository sets allow_override
- **WHEN** the repository's own profile sets `tld.allow_override`
- **THEN** an error says only a base profile may set it

### Requirement: Fetch and cache the base
The system SHALL fetch the base by its commit over git from `https://github.com/<owner>/<repo>.git` into a cache under the git directory, store the exact bytes with their hash, and read the cache before any network call. A commit is never fetched twice. The fetch SHALL accept a pin only when its commit is the commit of a version tag or an ancestor of the default branch head, so a commit that only a pull request holds is refused.

#### Scenario: First fetch is cached
- **WHEN** a profile with a pinned base is loaded for the first time with network access
- **THEN** the base is stored in the cache and the next load reads it without any network call

#### Scenario: Offline after caching
- **WHEN** the base is cached and the network is unavailable
- **THEN** the profile resolves and the result does not change during the session

#### Scenario: Fetch fails without a cache
- **WHEN** the base is not cached and cannot be fetched
- **THEN** an error under `'tld.extends'` names the base and its commit, says to run again with network access, and the exit code is 1

#### Scenario: Pin held only by a pull request
- **WHEN** the pinned commit is neither a version tag's commit nor an ancestor of the default branch head
- **THEN** the fetch is refused, nothing is cached and the exit code is 1

#### Scenario: Corrupt cache entry
- **WHEN** a cached base does not match its recorded hash
- **THEN** it is treated as missing and fetched again

### Requirement: Base commands
The system SHALL provide `tld profile base check FILE` (check a file as a base), `tld profile base fetch [PROFILE]` (fill the cache) and `tld profile base latest SOURCE` (print the newest tagged commit, or the default branch head, as JSON).

#### Scenario: Latest pin
- **WHEN** `tld profile base latest <source>` runs against a repository with tags
- **THEN** it prints the commit and tag of the newest version tag whose commit has the file

#### Scenario: Latest without tags
- **WHEN** the repository has no tag
- **THEN** it prints the default branch head commit and a null tag

#### Scenario: Check a base file
- **WHEN** `tld profile base check FILE` runs on a file a base may not be
- **THEN** it prints the refusal and exits 1

### Requirement: Refuse an unsafe base
The system SHALL refuse a base that holds token-like text (even on a line carrying an allow mark), a secret-like key name, a YAML anchor or alias, a non-mapping top level, nesting deeper than 8, or more than 65536 bytes, and SHALL never print the offending value.

#### Scenario: Token-like text
- **WHEN** a base line looks like a credential
- **THEN** the base is refused with a message naming the line number and the kind, without the value

#### Scenario: Anchors and size
- **WHEN** a base uses a YAML alias or exceeds the size limit
- **THEN** the base is refused

### Requirement: Limit the keys a base may set
The system SHALL refuse a base that sets a key other than `tld.version`, `tld.allow_override`, `git.bot_login`, `git.codeowners`, `git.branch_pattern`, `roles.posture`, `roles.required`, `hooks`, `models`, `runtime.environments` and `verify.dod_manual`.

#### Scenario: Key a base may not set
- **WHEN** a base sets `verify.fast`, `roles.extra_context` or a feature section such as `deps`
- **THEN** the base is refused and the message lists the keys a base may set

### Requirement: Merge a repository over its base
The system SHALL merge mappings key by key with the repository's scalars and lists replacing the base's, and SHALL run validation, including the rule that the bot is not a code owner, on the merged result.

#### Scenario: Repository overrides a scalar
- **WHEN** the base sets `git.bot_login` and the repository sets another value
- **THEN** the resolved profile has the repository's value

#### Scenario: Lists replace
- **WHEN** the base and the repository both set `git.codeowners`
- **THEN** the resolved list is the repository's

#### Scenario: Merged bot as code owner
- **WHEN** the base sets `git.bot_login` and the repository lists that login in `git.codeowners`
- **THEN** the error says the agent cannot be its own code owner

### Requirement: Merge required roles and manual rows additively
The system SHALL merge `roles.required` entries by `role`, adding the repository's `at` points and `when` globs to the base's and making `blocking` true if either says so, SHALL add a repository entry for a role the base lacks, and SHALL list the base's `verify.dod_manual` rows before the repository's without duplicates.

#### Scenario: Required roles merge by role
- **WHEN** the base requires `security-reviewer` at one point and the repository requires it at another and adds `ux-reviewer`
- **THEN** the resolved entry for `security-reviewer` has both points and `ux-reviewer` is added

#### Scenario: Manual rows append
- **WHEN** the base and the repository each list manual rows
- **THEN** the resolved list has the base rows first, then the repository's, without duplicates

### Requirement: Keep guarded keys from weakening
The system SHALL refuse a repository profile that weakens a guarded key compared with its base (or the built-in values), unless the base lists that exact key in `tld.allow_override`. Without `tld.extends` nothing is refused.

#### Scenario: Hook disable refused
- **WHEN** the repository sets `hooks.disable: [secret-scan]` under a base that does not allow it
- **THEN** an error under `'hooks.disable'` names the hook and the base and the exit code is 1

#### Scenario: Weaker posture refused
- **WHEN** the base sets `roles.posture.security: critical` and the repository sets `standard` (critical is above standard, standard above low)
- **THEN** an error under `'roles.posture.security'` is printed

#### Scenario: Required role dropped
- **WHEN** the repository lists a base-required role in `roles.disable`
- **THEN** an error names the role, the points and the base

#### Scenario: Protect list widened
- **WHEN** the repository's `hooks.protect_paths` leaves out a pattern the base protects, or `protect_paths_allow` adds an exemption the base does not list
- **THEN** an error names the pattern

#### Scenario: Gate switched off
- **WHEN** the repository sets `hooks.plan_gate.enabled: false` under a base or default that turns it on
- **THEN** an error is printed

#### Scenario: Allowed by the base
- **WHEN** the base lists `hooks.disable.secret-scan` in `tld.allow_override`
- **THEN** the repository may disable that hook

#### Scenario: Strengthening allowed
- **WHEN** the repository adds a role, raises the posture or adds a protected pattern
- **THEN** no error is reported

### Requirement: Apply static built-in defaults
The system SHALL fill, for every key the repository and the base leave out, `git.branch_pattern` `<type>/<kebab-case>`, `git.branch_types` `[feature, fix, chore]`, `git.merge_style` `merge-commit`, `docs.must_read` and `stacks` empty, `land.max_prs` 10, `git_ops.workflow` `tld-git-ops.yml`, `git.main_branch` detected from the repository, and the hook settings.

#### Scenario: Static defaults
- **WHEN** a profile sets only `verify`
- **THEN** the resolved profile has the branch types, merge style, `land.max_prs` and the gate settings (the plan, board and definition-of-done gates on, `max_attempts` 3, protect list `.env`, `.env.*`, `*.lock`, `package-lock.json`, `go.sum`)

#### Scenario: Git-ops repository
- **WHEN** the repository's origin belongs to an owner and the profile has no `git_ops`
- **THEN** `git_ops.repo` resolves to `<owner>/git-ops`

#### Scenario: Plan directory of an existing repository
- **WHEN** the repository has a `docs/plans` directory and the profile has no `docs.plan_dir`
- **THEN** `docs.plan_dir` resolves to `docs/plans`, otherwise to `docs`

### Requirement: Apply section defaults
The system SHALL default, inside a section the repository writes, `deps.cooldown_days` 3, `deps.time_budget_minutes` 90, `spec.version` `2.1.0`, `sysml.subset` 1 and `release.workflow` `tld-release.yml`, and SHALL treat an empty section (YAML null) as present.

#### Scenario: Empty section turns the feature on
- **WHEN** a profile has an empty `deps:` block
- **THEN** `deps.cooldown_days` is 3 and `deps.time_budget_minutes` is 90

#### Scenario: Release version files stay required
- **WHEN** a profile has a `release` section without `version_files`
- **THEN** the missing-key error is reported

### Requirement: Apply file-checked defaults
The system SHALL apply `docs.index` `docs/README.md`, `docs.adr_dir` `docs/adr` with `docs.adr_index` `docs/adr/README.md`, `docs.changelog` (`CHANGELOG.md`, `## [Unreleased]`, `unreleased`), `admin.policy` `.tld/admin-policy.yaml` and `docs.website` only when their file exists, and `docs.adr_bar` `CONTRIBUTING.md#decisions-plans-and-adrs` only when that heading exists.

#### Scenario: File-checked defaults
- **WHEN** `CHANGELOG.md` and `docs/README.md` exist and `docs/adr` does not
- **THEN** the resolved profile has the changelog and index defaults and no `docs.adr_dir`

#### Scenario: Website default
- **WHEN** `scripts/build_site.py` exists
- **THEN** `docs.website` has `dir` `.`, `build` `python3 scripts/build_site.py --out _site` and `links` `python3 -m pytest tests/unit/test_website_links.py -q`

#### Scenario: Turned off with false
- **WHEN** a profile sets `docs.changelog: false` (or `docs.index`, `docs.adr_dir`, `docs.website`, `admin`, `git_ops` or `land.max_prs`) and the file exists
- **THEN** the resolved profile has no such key

### Requirement: Survey reads repository facts for setup
The system SHALL make `tld profile survey` report, as read-only evidence and proposal, the GitHub logins in the CODEOWNERS file, a `release.version_files` entry from a manifest's version line, `deps.audit`, `deps.lock_freshness` and `docs.adr_bar`, and SHALL no longer propose `git.branch_types` or `git.merge_style`.

#### Scenario: Code owners differ from the base
- **WHEN** the CODEOWNERS file lists a login the base does not and a base is given
- **THEN** the proposal has an explicit `git.codeowners` without the bot

#### Scenario: Version line
- **WHEN** exactly one of `pyproject.toml`, `package.json` and `Cargo.toml` has a version line
- **THEN** the proposal has a `release.version_files` entry with an anchored pattern for it

#### Scenario: Lock script
- **WHEN** the repository has no lock script
- **THEN** the proposal has no `deps.lock_freshness`

#### Scenario: Decisions heading
- **WHEN** `CONTRIBUTING.md` has a heading about decisions
- **THEN** the proposal's `docs.adr_bar` is that file and the heading's anchor

#### Scenario: Dependency commands
- **WHEN** a runtime lockfile and a `package-lock.json` in a subdirectory exist
- **THEN** the proposal has a Python audit command naming the lockfile and an npm audit with that directory as `cwd`

#### Scenario: Values the base sets are left out
- **WHEN** a base is given and it sets the posture and the required roles
- **THEN** the proposal does not repeat them

### Requirement: Ask at most one batch in setup
The system SHALL make the setup command ask only for what the survey could not derive, in one ask, which in practice is `verify.fast` and `verify.dod`.

#### Scenario: Nothing to ask
- **WHEN** the survey finds the test and gate commands
- **THEN** setup asks nothing and opens one pull request

#### Scenario: One batch
- **WHEN** no test command is found
- **THEN** the only questions are `verify.fast` and `verify.dod`, in one ask

### Requirement: Migrate files found off their default path
The system SHALL, for `tld migrate --defaults`, list a docs index, ADR directory or changelog found at `docs/index.md`, `docs/adrs`, `docs/decisions`, `doc/adr`, `adr`, `CHANGES.md`, `HISTORY.md` or with another Unreleased spelling, offer for each to rename it to the default path (updating links) or to keep it by writing the explicit key, and change nothing without `--write` and the answers.

#### Scenario: Off-default changelog
- **WHEN** the repository has `CHANGES.md` with `## Unreleased`
- **THEN** the plan offers renaming the file and the heading, or writing `docs.changelog` explicitly

#### Scenario: Nothing off the default
- **WHEN** every such file is at its default path or absent
- **THEN** the command prints that nothing is off and asks nothing
