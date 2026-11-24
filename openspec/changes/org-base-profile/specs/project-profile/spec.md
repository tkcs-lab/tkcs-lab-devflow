## MODIFIED Requirements

### Requirement: Validate a profile against the schema
The system SHALL, for `tld profile validate [PROFILE]` (default `.tld/toolkit.yaml`), resolve the profile (its own keys, the pinned base it extends and the built-in defaults), print `toolkit.yaml: OK (<path>)` and exit 0 for a valid result, and SHALL print one `toolkit.yaml: <error>` line per problem to stderr and exit 1 otherwise. The only key a profile must write is `verify` (with `fast` and a non-empty `dod`); `docs.must_read`, `stacks`, `git.main_branch` and `git.branch_pattern` are resolved when absent, and a resolved profile that still has no `git.main_branch` is an error that says it could not be detected.

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

### Requirement: Print the resolved profile
The system SHALL, with `--resolved`, print the resolved profile as indented JSON instead of the OK line: the repository's keys over the base's keys over the built-in defaults, with `docs.plan_dir` carrying no trailing slash and the whole `hooks` section included. With `--explain` it SHALL print one line per resolved key, `<dotted key> = <json value>  # <source>`, where the source is the repository, the base (with its source and the first seven characters of its commit), a built-in default or a detected value.

#### Scenario: Resolved output
- **WHEN** a valid profile without `docs.plan_dir` is validated with `--resolved`
- **THEN** stdout is JSON with a `docs.plan_dir` of `docs` (or `docs/plans` when the repository has a `docs/plans` directory) and the exit code is 0

#### Scenario: Explained output
- **WHEN** a profile extends a base and `--explain` is given
- **THEN** every line names whether its value came from the repository, the base, a default or a detection

#### Scenario: Resolved at a ref
- **WHEN** `--ref <ref>` is given
- **THEN** the profile and the files that decide the defaults are read from that ref, not from the working tree

## ADDED Requirements

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
The system SHALL fetch the base by its commit over git from `https://github.com/<owner>/<repo>.git` into a cache under the git directory, store the exact bytes with their hash, and read the cache before any network call. A commit is never fetched twice.

#### Scenario: First fetch is cached
- **WHEN** a profile with a pinned base is loaded for the first time with network access
- **THEN** the base is stored in the cache and the next load reads it without any network call

#### Scenario: Offline after caching
- **WHEN** the base is cached and the network is unavailable
- **THEN** the profile resolves and the result does not change during the session

#### Scenario: Fetch fails without a cache
- **WHEN** the base is not cached and cannot be fetched
- **THEN** an error under `'tld.extends'` names the base and its commit, says to run again with network access, and the exit code is 1

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
