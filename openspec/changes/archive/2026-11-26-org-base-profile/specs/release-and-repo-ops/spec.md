## ADDED Requirements

### Requirement: Audit the profile base pin
The system SHALL, when the organisation policy has a `profile` section, report each audited repository whose profile does not extend the policy's base, extends it without a valid pin or with an older commit than the policy's, or uses `tld.allow_override`, and SHALL propose a pin bump as one pull request per repository that rewrites only the `tld.extends` line.

#### Scenario: Repository without a base
- **WHEN** an audited repository's profile has no `tld.extends`
- **THEN** the audit reports it with the manual step to run setup in update mode

#### Scenario: Out-of-date pin
- **WHEN** a repository extends an older commit of the base than the policy's pin
- **THEN** the audit proposes one pull request that changes only the `tld.extends` line

#### Scenario: Override listed
- **WHEN** a repository's resolved profile uses an override its base allows
- **THEN** the audit lists the override as information

### Requirement: Audit the git-ops central repository
The system SHALL, when the policy has a `git_ops` section, check that the central repository has the git-ops workflow and an allowlist naming every audited repository, propose each missing piece as a pull request into the central repository, and report the missing `GIT_OPS_TOKEN` secret and `git-ops` environment as open items it cannot create.

#### Scenario: Central repository incomplete
- **WHEN** the central repository lacks the workflow or an audited repository is not in the allowlist
- **THEN** the audit proposes a pull request into the central repository

#### Scenario: Secret and environment
- **WHEN** the token secret or the environment is missing
- **THEN** the audit reports each as an open item for the owner

### Requirement: Enforce merge commits and scope secrets
The system SHALL enforce merge commits through the repository settings the policy lists (merge commits allowed, squash and rebase off) and SHALL report an Actions secret held at repository or organisation level instead of in an environment limited to the default branch.

#### Scenario: Merge settings
- **WHEN** a repository allows squash or rebase merges and the policy says merge commits only
- **THEN** the audit reports the setting and the apply step fixes it

#### Scenario: Unscoped secret
- **WHEN** an Actions secret is stored at repository or organisation level
- **THEN** the audit reports it
