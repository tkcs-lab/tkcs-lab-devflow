# release-and-repo-ops Specification

## Purpose
The `tld ops` commands land-order, pick-release, release-prepare, upstream-sync, repo-admin and docs-index, and the `tld research` gate, give unattended playbooks deterministic, testable steps for ordering pull requests, choosing and preparing releases, syncing a fork, auditing an organisation, keeping the docs index in order and vetting research hand-offs.

## Requirements

### Requirement: Order pull requests for landing
The system SHALL, for `tld ops land-order [FILE|-] [--max N]`, read a JSON list of objects with a positive integer number and non-empty head and base, and print the pull request numbers one per line so that a pull request whose base equals another listed pull request's head comes after it, the smallest ready number first.

#### Scenario: Stacked pull requests
- **WHEN** pull request 5 has a base equal to the head of pull request 9, and 7 is independent
- **THEN** the output is 7, 9, 5 on separate lines and the exit code is 0

#### Scenario: Unknown base
- **WHEN** a base is not the head of any listed pull request
- **THEN** it adds no ordering constraint and the numbers come out ascending

#### Scenario: Limit
- **WHEN** `--max 2` is given
- **THEN** only the first two lines of the order are printed; a value below 1 is refused with exit 1

#### Scenario: Cycle or bad input
- **WHEN** two pull requests are each other's base, or the input is not a JSON list, has a duplicate number, a boolean or non-positive number, or a missing head or base
- **THEN** `land_order: <message>` is printed on stderr (a cycle names the two numbers) and the exit code is 1; an unreadable file also exits 1

### Requirement: Pick the newest eligible release tag
The system SHALL, for `tld ops pick-release --pattern REGEX [--lines] [FILE|-]`, print the eligible tag with the highest numeric version, where a tag is eligible only if it matches the pattern, is not marked prerelease and consists of an optional v or V followed by digits and dots.

#### Scenario: Numeric order
- **WHEN** the tags include 1.9.0 and 1.10.0
- **THEN** 1.10.0 is printed and the exit code is 0

#### Scenario: Excluded tags
- **WHEN** a tag is marked prerelease in the JSON input or has a suffix such as -rc1
- **THEN** it is never printed, even if the pattern allows it

#### Scenario: Line input
- **WHEN** `--lines` is given and the input holds bare tags or raw remote tag listing lines (peeled `^{}` lines are dropped)
- **THEN** the tag names are extracted and judged the same way

#### Scenario: No tag, bad pattern or bad input
- **WHEN** nothing is eligible
- **THEN** `pick_release: no eligible release` is printed and the exit code is 3
- **WHEN** the pattern does not compile or the JSON is invalid
- **THEN** `pick_release: <message>` is printed and the exit code is 1

### Requirement: Prepare a release
The system SHALL, for `tld ops release-prepare` run from the repository root, read the profile's release version files and changelog section, and with no version option print JSON with the current version, the patch, minor and major candidates, a suggested bump and a preview of the unreleased entry.

#### Scenario: Suggested bump
- **WHEN** the unreleased section has a Removed or Breaking heading, else an Added heading, else neither
- **THEN** the suggested bump is major, minor or patch respectively

#### Scenario: Dry run
- **WHEN** `--version X.Y.Z` or `--bump patch|minor|major` is given without `--write`
- **THEN** the JSON also holds the next version, the files, the new changelog heading and `written` false, and no file changes

#### Scenario: Write
- **WHEN** `--write` is given with a version or bump
- **THEN** only the version text in each version file changes, a heading with the version and date (default today, UTC) is opened under the unreleased section, line endings of the changelog are kept, and the exit code is 0

#### Scenario: Refusals
- **WHEN** the version is not higher than the current one, is not X.Y.Z, already has a changelog heading, the unreleased section is empty, the version files disagree, a version pattern matches zero or several times, or a path lies outside the repository
- **THEN** `release-prepare: <problem>` is printed on stderr, nothing is written and the exit code is 1

#### Scenario: Usage errors
- **WHEN** `--version` and `--bump` are combined, `--write` has no version or bump, `--base` lacks `--check`, `--check` lacks `--version` or is combined with `--write` or `--bump`, or `--date` is not a real YYYY-MM-DD date
- **THEN** the exit code is 2

### Requirement: Verify a prepared release
The system SHALL, for `tld ops release-prepare --check --version X.Y.Z [--base REF]`, print `release-prepare: ok X.Y.Z` and exit 0 only when every version file holds that version and the changelog has a non-empty entry for it and still has the unreleased section.

#### Scenario: Before and after writing
- **WHEN** `--check` runs before and after a `--write` of the same version
- **THEN** it exits 1 listing the problems before, and 0 after

#### Scenario: Nothing else changed
- **WHEN** `--base REF` is given
- **THEN** it also fails (exit 1) if any file other than the changelog and the version files changed since the merge base with REF (renames and uncommitted changes included), if a version file is untracked, if a changed line is not a version line, or if a version file differs from its base in more than the version; a REF starting with a dash or a failing git call is reported as a problem

### Requirement: Sync a fork to an upstream release
The system SHALL provide `tld ops upstream-sync plan` and `prepare` for a fork whose version file has exactly three lines (tag, a 40-character lowercase hex commit, a synced date).

#### Scenario: Plan
- **WHEN** `plan --upstream-url URL --version-file F --pattern RE` runs
- **THEN** it prints JSON with the current tag, the newest eligible upstream tag chosen as `pick-release` does, and whether they are equal, with exit 0

#### Scenario: No eligible release
- **WHEN** no upstream tag is eligible
- **THEN** `upstream_sync: no eligible release` is printed and the exit code is 3

#### Scenario: Clean prepare
- **WHEN** `prepare --upstream-url URL --version-file F --tag T --branch B --base REF` runs on a clean working tree
- **THEN** branch B is created from REF, the recorded upstream commit, the fork and tag T are three-way merged, the version file records T, the tag's peeled commit and today's date, nothing is committed or pushed, `clean` is printed and the exit code is 0

#### Scenario: Conflicts
- **WHEN** the merge leaves conflicts
- **THEN** the conflicted paths are printed one per line, markers stay in the working tree and the exit code is 2

#### Scenario: Errors
- **WHEN** the version file is missing or malformed, the working tree has uncommitted tracked changes, the branch already exists, or the recorded upstream commit cannot be found upstream
- **THEN** `upstream_sync: <message>` is printed and the exit code is 1

### Requirement: Docs index check
The system SHALL, for `tld ops docs-index check`, report errors and warnings one per line as `error: ...` or `warning: ...`, end with `docs index: <e> error(s), <w> warning(s)`, and exit 1 on an error (or on a warning with `--strict`), else 0.

#### Scenario: Errors
- **WHEN** CLAUDE.md is missing, longer than 60 lines (`--max-claude-lines`) or does not link to the index, the index is missing or longer than 150 lines, a relative link in CLAUDE.md or an index file is broken, a doc is linked from no index file, or an ADR is missing from the ADR index
- **THEN** an error line names it and the exit code is 1

#### Scenario: Exempt documents
- **WHEN** a doc is a plan, review or deviations file, a plan record under the plan directory, or lies under an archive directory
- **THEN** it needs no index row

#### Scenario: Warnings
- **WHEN** a link in another doc is broken, a doc exceeds 400 lines, an index row has no description, a link is listed twice, or (with `--stale-days N`) a doc has not changed in git for N days
- **THEN** a warning line is printed and the exit code is 0 unless `--strict` is given

#### Scenario: JSON and missing index setting
- **WHEN** `--json` is given
- **THEN** a JSON object with errors and warnings is printed
- **WHEN** neither the profile's docs index key nor `--index` is given
- **THEN** a message about the missing key goes to stderr and the exit code is 2

### Requirement: Docs inventory and move
The system SHALL provide `tld ops docs-index inventory`, which always exits 0 and lists every markdown doc under the docs directory with title, line count, summary, age, linkers and whether it is in the index, and `tld ops docs-index move SRC DST`, which renames one file and rewrites references to it.

#### Scenario: Inventory output
- **WHEN** `inventory` runs without `--json`
- **THEN** each doc prints two lines, marked `[NOT IN INDEX]` when neither indexed nor a plan; with `--json` a list of objects is printed

#### Scenario: Move dry run
- **WHEN** `move SRC DST` runs without `--apply`
- **THEN** it prints each reference that would be rewritten and a summary, and changes nothing

#### Scenario: Move applied
- **WHEN** `--apply` is given
- **THEN** the file is moved (with git when tracked), markdown links, root path mentions, quoted path expressions in Python files and the profile's doc paths are rewritten, emptied directories are removed, and mentions that cannot be rewritten safely are printed as `unresolved:` lines

#### Scenario: Move refused
- **WHEN** SRC is not a file or DST already exists (including a dangling symbolic link), or git refuses the move
- **THEN** a `move:` message is printed on stderr and the exit code is 1

### Requirement: Organisation audit and apply
The system SHALL provide `tld ops repo-admin` with `validate-policy POLICY`, `whoami [--org ORG]`, `audit --policy POLICY` and `apply --policy POLICY`, where sections absent from the policy are not managed and the token is read from the environment or the GitHub command-line tool and is never printed.

#### Scenario: Validate
- **WHEN** `validate-policy` runs on a valid file
- **THEN** it prints `policy: OK (<path>)` and exits 0; a missing file, invalid YAML, a schema error, an over-broad forbidden directory pattern, colliding label names or an unsafe workflow entry prints `policy:` messages on stderr and exits 1

#### Scenario: Audit exit codes
- **WHEN** `audit` runs
- **THEN** it prints a markdown report (or JSON with `--format json`, or writes it to `--out`) and exits 0 with nothing out of policy, 3 when some finding needs a fix or a person, and 1 when a check itself failed

#### Scenario: Filters
- **WHEN** `--repo` or `--check` is repeated, or `--repo` names a repository of another organisation
- **THEN** only those repositories and checks run, and a foreign or malformed repository name stops the command before any request

#### Scenario: Dry run
- **WHEN** `apply` runs without `--yes`
- **THEN** it prints the calls it would make, changes nothing and ends with a dry-run notice

#### Scenario: Irreversible changes
- **WHEN** `apply --yes` runs without `--allow-delete`
- **THEN** deleting a label, secret, variable, webhook, deploy key or branch, and revoking a token, are listed as held back and not made

#### Scenario: File changes
- **WHEN** `apply --yes` makes changes to repository files (removing a config directory, installing or updating a workflow)
- **THEN** one commit on a new branch and one pull request per repository are created, never pushed to an existing branch and never merged

#### Scenario: Selecting and failing
- **WHEN** `apply --only ID` names an id that the audit does not produce
- **THEN** it exits 1 with an unknown-id message; a failed change is printed as FAILED and makes the exit code 1

#### Scenario: Who am I
- **WHEN** `whoami` runs
- **THEN** it prints JSON with authenticated, login, org, role and can_administer, and exits 0 when authenticated (and, with `--org`, an organisation admin), else 3

### Requirement: Research prompt gate
The system SHALL, for `tld research check-prompt FILE [--forbid TEXT]...`, print `research prompt: OK (<n> characters)` and exit 0 only when the prompt has no problem, and otherwise print one line per problem and exit 1.

#### Scenario: Problems found
- **WHEN** the prompt is over 1800 characters, its first line is not `Research <id>` with an id of the form r-, eight digits, dash, one or two digits, the six required section lines are missing or out of order, it holds a control, invisible or bidirectional character, it looks like a credential or carries the scan's allow mark, it contains a `--forbid` text or the board address or token from the environment, or the report start and end lines for its id are missing
- **THEN** a line starting with too long, first line, sections, character, secret, forbidden or report format is printed and the exit code is 1

#### Scenario: Disguised values
- **WHEN** a forbidden value or secret is split by whitespace, combining marks or invisible characters
- **THEN** it is still found, and no problem line ever repeats the secret or the forbidden text

#### Scenario: Unusable input
- **WHEN** the file cannot be read or decoded, or `--forbid` is empty, or the arguments are wrong
- **THEN** a fixed message that never echoes the arguments is printed on stderr and the exit code is 2

### Requirement: Research report extraction
The system SHALL, for `tld research report --id ID --reply FILE|- [--rest FILE]`, print the body of the marked report block of ID from the owner's reply, starting at `RESEARCH-REPORT <id>` and ending at the last `END RESEARCH-REPORT <id>` after it.

#### Scenario: Valid report
- **WHEN** the block is complete, at most 3500 characters after control and invisible characters are removed, and has a line starting with `Answer:`
- **THEN** the body is printed with one final newline and the exit code is 0

#### Scenario: Report not usable
- **WHEN** the block is for another id, longer than 3500 characters, or without an `Answer:` line
- **THEN** a message goes to stderr and the exit code is 1
- **WHEN** no complete block for the id exists, or the end line is missing
- **THEN** the exit code is 3

#### Scenario: Rest of the reply
- **WHEN** `--rest FILE` is given
- **THEN** only the lines before the first report start line are written there (on exit 0, 1 and 3), so text after the block, which may be web text, never reaches the file

#### Scenario: Bad arguments
- **WHEN** the id is malformed, the reply cannot be read or decoded, or the rest file cannot be written
- **THEN** the exit code is 2

### Requirement: Judge whether a commit is green for a release
The system SHALL, for `tld ops release-check [--checks FILE|-] [--status FILE] [--self NAME]... [--sha SHA]`, judge the check runs of a commit and, when `--status` is given, its combined commit status, and print `release-check: green`, `release-check: waiting` or `release-check: red` followed by one `red: <check>: <status> <conclusion>` or `waiting: <check>: <status> <conclusion>` line for each check that stops a release.

#### Scenario: Green commit
- **WHEN** every check run is completed with the conclusion success, skipped or neutral, and the status is absent, success, or pending with a total of 0
- **THEN** `release-check: green` is printed with the number of checks and the exit code is 0, and the line says the commit status was not checked when no status was given

#### Scenario: Check still running
- **WHEN** no check is red and a check run is not completed, or the status is pending while at least one status exists
- **THEN** `release-check: waiting` and a `waiting:` line per such check are printed and the exit code is 3

#### Scenario: Red check
- **WHEN** a check run is completed with any other conclusion, or the status is failure or error
- **THEN** `release-check: red` and a `red:` line naming each such check are printed and the exit code is 1, even when other checks are still running

#### Scenario: Own run left out
- **WHEN** `--self NAME` is given, once or several times
- **THEN** a check run with that name is not judged

#### Scenario: Unreadable input
- **WHEN** the check runs or the status cannot be read or are not JSON of the documented shapes
- **THEN** `release-check: <message>` is printed on stderr and the exit code is 2

### Requirement: The release workflow template judges green by the same rule
The system SHALL ship a `tld-release` workflow template whose step "Check that the commit is green" stops the run for exactly the commits that `tld ops release-check` calls waiting or red.

#### Scenario: Same verdict
- **WHEN** the template's step and `tld ops release-check` read the same check runs and the same combined status
- **THEN** the step succeeds exactly when the command exits 0

#### Scenario: Skipping the check
- **WHEN** the workflow is started with `skip_checks` true
- **THEN** the step does not run

### Requirement: Combine dependency update groups without merging lockfiles
The system SHALL provide `tld ops deps-prepare --base REF --branch NAME --group REF... [--bot-ref REF...]`, which creates branch NAME from REF, applies in order each group ref's changes since its merge base with REF except lockfiles, and prints JSON naming each group's outcome and the lock commands of the trusted profile that must run. It never pushes and never runs a profile command.

#### Scenario: Groups applied, lockfiles left for the lock command
- **WHEN** two group refs each change a manifest and its lockfile, and the profile has a lock entry whose `when` matches the manifests and whose `lockfiles` match the lockfiles
- **THEN** the branch holds both manifest changes in one commit per group, every lockfile is byte-equal to the one at REF, the output lists both groups as `applied` and that lock entry once under `lock_commands`, and the exit code is 0

#### Scenario: What counts as a lockfile
- **WHEN** a changed path matches a `lockfiles` glob of a `deps.lock_freshness` entry of the resolved trusted profile, or a built-in lockfile name
- **THEN** it is treated as a lockfile and is never taken from the group ref

#### Scenario: Main changed the same lockfile
- **WHEN** the remote default branch and a group ref both changed the same lockfile and non-conflicting manifest lines
- **THEN** the group is applied and the lockfile on the branch equals the one at REF

#### Scenario: Lock entries from defaults and explicit values alike
- **WHEN** the lock entries come from the resolved profile, whether written in the profile or filled in by the profile's defaults
- **THEN** the same groups are applied and the same lock commands are listed

#### Scenario: The profile comes from the remote default branch
- **WHEN** REF resolves to neither the commit the guards trust nor the current commit of the remote default branch, or no trusted copy of the profile can be read
- **THEN** `deps: <message>` is printed on stderr, no branch is created and the exit code is 1

#### Scenario: The base is the current remote default branch
- **WHEN** the remote default branch moved after the trusted copy was read, REF resolves to its current commit and the profile is unchanged
- **THEN** that commit is the base of the branch and the exit code is 0

#### Scenario: The local profile decides nothing
- **WHEN** the working tree or a local branch carries another profile than the remote default branch
- **THEN** the lock commands and the protected paths follow the remote default branch's profile

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

#### Scenario: A workflow change from a work branch
- **WHEN** a group ref is a local work branch and a workflow file on it differs from the same file at the tip of every `--bot-ref`
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

#### Scenario: A merge that changes more than the group
- **WHEN** merging a group ref changes another set of paths than the group's own non-lockfile paths (for example because git followed a rename between the merge base and the branch)
- **THEN** nothing of that group is applied and it is listed as `left_out` with reason `does-not-apply`

#### Scenario: Protected paths compared without case or Unicode form
- **WHEN** a group ref changes a path that differs from a protected path only in letter case or Unicode normalization form
- **THEN** it is treated as that protected path

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
