## ADDED Requirements

### Requirement: Combine dependency update groups without merging lockfiles
The system SHALL provide `tld ops deps-prepare --base REF --branch NAME --group REF...`, which creates branch NAME from REF, applies in order each group ref's changes since its merge base with REF except lockfiles, and prints JSON naming each group's outcome and the lock commands of the trusted profile that must run. It never pushes and never runs a profile command.

#### Scenario: Groups applied, lockfiles left for the lock command
- **WHEN** two group refs each change a manifest and its lockfile, and the profile has a lock entry whose `when` matches the manifests and whose `lockfiles` match the lockfiles
- **THEN** the branch holds both manifest changes in one commit per group, every lockfile is byte-equal to the one at REF, the output lists both groups as `applied` and that lock entry once under `lock_commands`, and the exit code is 0

#### Scenario: What counts as a lockfile
- **WHEN** a changed path matches a `lockfiles` glob of a `deps.lock_freshness` entry of the resolved trusted profile, or a built-in lockfile name
- **THEN** it is treated as a lockfile and is never taken from the group ref

#### Scenario: Lock entries from defaults and explicit values alike
- **WHEN** the lock entries come from the resolved profile, whether written in the profile or filled in by the profile's defaults
- **THEN** the same groups are applied and the same lock commands are listed

#### Scenario: The profile comes from the remote default branch
- **WHEN** REF resolves to neither the commit the guards trust nor the current commit of the remote default branch, or no trusted copy of the profile can be read
- **THEN** `deps: <message>` is printed on stderr, no branch is created and the exit code is 1

#### Scenario: A lockfile no entry covers
- **WHEN** a group ref changes a built-in lockfile name that no lock entry lists
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `lock-uncovered` and that file

#### Scenario: Only lockfiles changed
- **WHEN** a group ref changes nothing but lockfiles
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `lockfile-only`

#### Scenario: A group ref with a commit not carrying the dependency bot's identity
- **WHEN** a group ref that is not a local work branch has a commit since its merge base whose author is not the dependency bot or whose committer is neither the bot nor GitHub's own
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `not-bot-authored`

#### Scenario: Workflow files only as action version bumps
- **WHEN** a group ref changes a file under `.github/workflows/` in any way other than moving the ref of an action it already uses (another action, a local or docker action, a pinned commit replaced by a movable ref, an added or removed line)
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `workflow-not-a-bump`

#### Scenario: Other protected paths
- **WHEN** a group ref changes the profile, an environment file, a git or adapter guardrail path or a workflow that only the toolkit installs
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `protected-path` and that file

#### Scenario: Unexpected kinds of change
- **WHEN** a group ref adds a symbolic link or a submodule, or changes a file mode
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `unexpected-change` and that file

#### Scenario: A group that does not apply
- **WHEN** the changes of a group ref conflict with REF or with the groups already applied
- **THEN** the branch stays at the previous group's commit, the group is listed as `left_out` with reason `does-not-apply`, and the remaining groups are still tried

#### Scenario: Nothing applied
- **WHEN** no group ref could be applied
- **THEN** the JSON is still printed, no branch is left and the exit code is 3

#### Scenario: Errors
- **WHEN** the working tree has uncommitted tracked changes, the branch already exists locally or on the remote, a ref does not resolve or is not a plain ref name, or the trusted profile is invalid
- **THEN** `deps: <message>` is printed on stderr, no branch is created and the exit code is 1

### Requirement: Render the combined dependency pull request body
The system SHALL provide `tld ops deps-body FILE`, which reads a JSON object with a list of update entries and prints a pull request body: a `## Summary` that passes `tld plan summary-check --kind pr`, a `## Updates` table with security entries first, a `## Left out` list when any entry is left out, and a closing line that the dependency-bot pull requests stay open.

#### Scenario: Security first
- **WHEN** the file lists an ordinary update and a security update
- **THEN** the security update's row comes first in `## Updates`, each row names the ecosystem, the directory, the dependency-bot pull request number (or `audit`), the package, the old and the new version and `yes` or `no` for security, and the Summary has a `**Security:**` line

#### Scenario: Versions not known
- **WHEN** an entry has a pull request number and no package updates
- **THEN** its row names the pull request and says `see #<n>` instead of the package and versions

#### Scenario: Workflow files and action moves named
- **WHEN** an included entry lists changed files under `.github/workflows/` and action moves
- **THEN** the `**Security:**` line names each of those files and each move

#### Scenario: A left-out group is named
- **WHEN** an entry is left out with a reason
- **THEN** it is not in `## Updates`, `## Left out` names its ecosystem, directory, pull request number and the fixed text for that reason, and `**Deviations:**` names it

#### Scenario: Nothing left out
- **WHEN** every entry is included
- **THEN** `**Deviations:** None.` is printed and there is no `## Left out` section

#### Scenario: No closing keyword
- **WHEN** any body is rendered
- **THEN** it contains no `closes`, `fixes` or `resolves` followed by `#` and a number, so merging it closes no dependency-bot pull request

#### Scenario: Untrusted values refused
- **WHEN** a package name, a version, an ecosystem, a directory, a file or a reason does not match its allowed form, a pull request number is not a positive integer, or no entry is included
- **THEN** `deps: <message>` naming the entry and the key is printed on stderr, nothing is printed on stdout and the exit code is 1
