## ADDED Requirements

### Requirement: Inherit the organisation policy
The system SHALL let an organisation policy name, in `extends`, one to four files pinned by their full commit identifier, each written as owner, repository and path, read through the GitHub API with the run's token, merged in the order listed and then under the policy's own keys, so that mappings merge, lists and scalars of a later file replace those of an earlier one, and the resolved result can be printed with the source of every value.

#### Scenario: Small policy resolves
- **WHEN** `validate-policy` runs on a policy that holds only `org` and `extends`
- **THEN** it reads each pinned file, validates the merged policy and prints `policy: OK (<path>)`, and with `--resolved` it prints the merged policy

#### Scenario: Pin is not a commit
- **WHEN** an `extends` entry is pinned by a tag or branch name, is malformed or is listed twice
- **THEN** `validate-policy` exits 1 with a `policy:` message that names the entry and, for a tag, says to pin the full commit and to run `latest-pin`

#### Scenario: Pin is not on the default branch
- **WHEN** a pinned commit is not reachable from the default branch of its repository
- **THEN** `validate-policy` exits 1 and says the commit was not merged there

#### Scenario: Resolved view
- **WHEN** `validate-policy --explain` runs on a policy with `extends`
- **THEN** it prints one line per value with the source that set it (the policy file, an extended file with its short commit, or a repository override)

#### Scenario: Policy without extends
- **WHEN** a policy has no `extends`
- **THEN** it validates, audits and applies exactly as before, reads no override file and makes no request that the old command did not make

### Requirement: Keep an inherited file safe
The system SHALL refuse an extended file that holds anything credential-like, sets `extends` itself, turns on an irreversible change, or, when its repository is public, holds an organisation-private section, and SHALL never let any file but the policy that is run switch on a deletion or a revocation.

#### Scenario: Token-like text
- **WHEN** an extended file contains a line that looks like a credential or a key whose name looks like one
- **THEN** it is refused with the line number and the kind of finding and never shows the value

#### Scenario: Organisation-private section in a public repository
- **WHEN** an extended file in a public or internal repository sets `org_settings`, `members`, `apps`, `tokens`, `secrets` or `variables`
- **THEN** it is refused and the message says to keep those sections in a file of a private repository

#### Scenario: Irreversible switch in an inherited file
- **WHEN** an extended file sets a deletion or revocation switch to a value that turns it on
- **THEN** it is refused, and token revocation of expired tokens stays off unless the policy that is run sets it

#### Scenario: Chained extends
- **WHEN** an extended file itself sets `extends`
- **THEN** it is refused

### Requirement: Audit with repository override files
The system SHALL, for a policy with `extends`, read each audited repository's override file (default `.tld/admin-policy.yaml`, the path set by `repos.override_path`) from its default branch, apply it to the organisation policy and run the repository-level checks on the effective policy of that repository, where the override may set only repository-level keys, a base may not set per-repository keys, and a repository without an override file is audited with the organisation policy alone.

#### Scenario: Override merged
- **WHEN** a repository's override sets a repository-level key
- **THEN** the checks of that repository use the merged value and the checks of other repositories do not

#### Scenario: No override file
- **WHEN** a repository has no override file
- **THEN** it is audited with the organisation policy alone

#### Scenario: Organisation-level key in an override
- **WHEN** an override sets `org`, `extends`, `repos` or an organisation-level section such as `labels`
- **THEN** the audit reports an error for that repository, audits it with the organisation policy and `validate-policy` on the file exits 1

#### Scenario: Per-repository key in a base
- **WHEN** an extended file sets the required status checks of the default-branch ruleset, `workflow_params` or `config_dirs.known`
- **THEN** it is refused and the message says to set the key in each repository's override file

#### Scenario: Whole legacy file
- **WHEN** a repository's file is a whole policy with `org`
- **THEN** the audit uses it as an override after dropping what the organisation policy already says, and proposes a pull request that replaces it by that minimal override

#### Scenario: Only the checks
- **WHEN** a repository's override holds only the required status checks of the default-branch ruleset
- **THEN** every repository-level check of that repository runs on the inherited values plus those checks

### Requirement: Hold guarded settings against overrides
The system SHALL report, as a warning per setting, an override that loosens a guarded setting of the organisation policy and apply the organisation's value instead, unless the policy that is run allows that setting for that repository, and SHALL leave the dry run, `--yes` and `--allow-delete` rules of `apply` unchanged for inherited policies.

#### Scenario: Loosening held
- **WHEN** an override switches off a security feature the organisation policy requires
- **THEN** the audit warns, names the setting and both values, and `apply` changes the repository to the organisation's value

#### Scenario: Loosening allowed by the run file
- **WHEN** the policy that is run lists the setting for the repository under `repos.allow_loosen`
- **THEN** the override value applies and no warning is made

#### Scenario: Deletion needs the flag
- **WHEN** `apply --yes` runs on an inherited policy without `--allow-delete`
- **THEN** every irreversible change is listed as held back and none is made

### Requirement: Derive the agent and reviewer logins
The system SHALL take the agent login from the repository's resolved profile bot login and the release reviewer from its owner login or its single code owner when the effective policy does not state them, and SHALL report a repository for which no value can be derived instead of stopping.

#### Scenario: Logins derived
- **WHEN** the effective policy has an `agent` and a `release` section without logins and the repository's profile names a bot login and an owner
- **THEN** the agent and release checks use those logins

#### Scenario: Explicit login wins
- **WHEN** the effective policy states a login
- **THEN** it is used and the profile is not read for it

#### Scenario: Login not derivable
- **WHEN** the profile is missing or names no usable login
- **THEN** the audit warns for that repository with the reason, still checks the parts that need no login, and skips the release check

### Requirement: Propose values detected from the repository
The system SHALL propose, as one pull request per repository that writes or amends the repository's override file, required status checks taken from the checks that succeeded on every one of the last merged pull requests, and release parameters taken from existing tags and the manifest, with the excluded checks and the reasons shown in the pull request, and SHALL change nothing that depends on a value until the owner has merged it.

#### Scenario: Checks from merged pull requests
- **WHEN** a repository has at least three recent merged pull requests and some checks succeeded on all of them
- **THEN** the proposal lists exactly those checks, and every check that was skipped, failed, flaky or missing on some pull request is listed as excluded with its reason

#### Scenario: Too few pull requests
- **WHEN** fewer than three merged pull requests exist
- **THEN** no checks are proposed and the audit says why

#### Scenario: Release parameters
- **WHEN** a repository has version-like tags
- **THEN** the proposal sets the tag prefix of the most common tag form and the version style from the tags and the manifest, and never sets the check script

#### Scenario: Own release workflow
- **WHEN** a repository's resolved profile names a release workflow other than the one tld installs
- **THEN** the proposal replaces the workflow list without the release template

#### Scenario: Absent value stands down
- **WHEN** the override has no required status checks or no release parameters yet
- **THEN** the live status-check rule is kept and the release workflow is neither installed nor rewritten
