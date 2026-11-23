## Purpose
The project profile is the repository's tld configuration file; this capability validates it against the schema, checks the tld version it needs, surveys a repository to propose profile blocks, edits blocks as text, and migrates a legacy claude-toolkit repository to tld.

## ADDED Requirements

### Requirement: Validate a profile against the schema
The system SHALL, for `tld profile validate [PROFILE]` (default `.tld/toolkit.yaml`), print `toolkit.yaml: OK (<path>)` and exit 0 for a valid profile, and SHALL print one `toolkit.yaml: <error>` line per problem to stderr and exit 1 otherwise. The required top-level keys are `docs` (with `must_read`), `git` (with `main_branch` and `branch_pattern`), `verify` (with `fast` and a non-empty `dod`) and `stacks`.

#### Scenario: Valid minimal profile
- **WHEN** the profile has only the required keys
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
The system SHALL, with `--resolved`, print the profile as indented JSON with the schema's documented defaults filled in (for example `docs.plan_dir` becomes `docs/plans`, with a trailing slash removed) instead of the OK line.

#### Scenario: Resolved output
- **WHEN** a valid profile without `docs.plan_dir` is validated with `--resolved`
- **THEN** stdout is JSON whose `docs.plan_dir` is `docs/plans` and the exit code is 0

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
