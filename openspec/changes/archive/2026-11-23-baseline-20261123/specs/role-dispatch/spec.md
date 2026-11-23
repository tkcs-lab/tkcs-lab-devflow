## Purpose
Decide which review and edit roles a profile makes mandatory at each workflow point, verify that their reports exist, print a role report's change section safely, and prepare and check the pinned Reflektor tool.

## ADDED Requirements

### Requirement: Required roles at a point
The system SHALL, in `tld roles required --profile FILE --at POINT`, validate the profile, apply the `roles` defaults (security posture `standard`, no disabled roles, no extra context, non-blocking) and print JSON with `point`, `posture`, `extra_context`, `disabled`, `required` (each item with `role`, `blocking`, `matched` and `mode`) and `not_applicable`, where POINT is one of `make_plan`, `implement_phase`, `implement_final`, `review` or `dod`.

#### Scenario: Role listed at its point
- **WHEN** the profile's `roles.required` has an entry whose `at` includes the point and that has no `when`
- **THEN** the role is in `required` with `matched` equal to `always` and the exit code is 0

#### Scenario: Several entries for one role
- **WHEN** two entries name the same role at the same point
- **THEN** the role appears once, `blocking` is true if any entry is blocking, and `matched` is the union

#### Scenario: Mode of an edit role
- **WHEN** a role of tech-writer, website-maintainer, debugger or refactorer is required at `implement_phase`
- **THEN** its `mode` is `edit`, and at every other point (or for any other role) it is `review`

#### Scenario: Unknown point or invalid profile
- **WHEN** the point is not one of the five, or the profile is not valid YAML or fails validation
- **THEN** `tld roles: <message>` is printed on stderr and the exit code is 1

### Requirement: Conditional roles by changed files
The system SHALL treat an entry with `when` globs as required only if a path in the `--changed` file (one repo-relative path per line, `-` for stdin) matches a glob, listing the matching globs, and SHALL list it in `not_applicable` with a reason otherwise.

#### Scenario: No match
- **WHEN** no changed path matches the `when` globs at `implement_final` or `dod`
- **THEN** the role is in `not_applicable` with the reason "no changed file matches 'when'"

#### Scenario: Point without a diff
- **WHEN** an entry has `when` at `make_plan` or `review`
- **THEN** it is in `not_applicable` with the reason "no diff at this point", and `--changed` is not needed

#### Scenario: Changed list missing
- **WHEN** an entry with `when` applies at a point that has a diff and `--changed` is not given
- **THEN** the command prints that `--changed` is needed on stderr and exits 1

### Requirement: Verify role reports
The system SHALL, in `tld roles verify --required FILE --report FILE`, use the last `AGENT-REPORT <role> at=<point> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>` line per role and point (a leading `>`, spaces or backticks are tolerated), print `OK`, `MISSING` or `BLOCKED` per required role and a summary line, and exit 0 only when nothing is missing or blocked.

#### Scenario: All reported
- **WHEN** every required role has a report line at the required point
- **THEN** each is printed `OK ... blocking=<n>`, the summary is `roles: ok (<n> required)` and the exit code is 0

#### Scenario: Missing report
- **WHEN** a required role has no line at that point, only a line for another point, or a verdict of `n/a`
- **THEN** `MISSING <role> at=<point>` is printed, the summary is `roles: FAILED (<k> of <n> required)` and the exit code is 1

#### Scenario: Blocking findings
- **WHEN** a role required as blocking reports `blocking` above 0
- **THEN** `BLOCKED <role> at=<point> blocking=<n>` is printed and the exit code is 1; a non-blocking entry with findings is `OK`

#### Scenario: Unreadable input
- **WHEN** the required file is not valid JSON or a file cannot be read
- **THEN** `tld roles: <message>` is printed on stderr and the exit code is 1

### Requirement: Change-report section
The system SHALL, in `tld roles section --report FILE`, print the last complete `BEGIN change-report` / `END change-report` block after cleaning it so that it is safe to use as a pull request body.

#### Scenario: Characters and markup removed
- **WHEN** the block holds control or format characters, forged report lines or markers, backticks, backslashes, HTML, fences, images, links or URLs
- **THEN** they are removed or neutralised in the printed text

#### Scenario: Headings, mentions and keywords
- **WHEN** the block holds headings, mentions, issue references or closing keywords
- **THEN** headings are demoted to `###` or lower, mentions and issue references are wrapped in code spans, and closing keywords are replaced

#### Scenario: Long block
- **WHEN** the cleaned text is longer than 60 lines or about 6000 characters
- **THEN** it is cut to that size with a `(truncated)` mark

#### Scenario: Block present
- **WHEN** the report has a complete block
- **THEN** the cleaned text is printed and the exit code is 0

#### Scenario: Nothing usable or a secret
- **WHEN** there is no complete block, it is empty after cleaning, or the block (raw or cleaned) looks like a credential or carries the secret-scan allow mark
- **THEN** a `tld roles:` message is printed on stderr and the exit code is 3

#### Scenario: Unreadable file
- **WHEN** the file cannot be read or is not UTF-8
- **THEN** `tld roles: cannot read '<file>'` is printed and the exit code is 1

### Requirement: Reflektor report line
The system SHALL, with `tld roles section --report FILE --report-line`, print the last non-blank line of the file only when it is a complete `AGENT-REPORT reflektor at=dod ...` line without control characters.

#### Scenario: Valid last line
- **WHEN** the last non-blank line is a Reflektor report line at `dod`
- **THEN** it is printed and the exit code is 0

#### Scenario: Other last line
- **WHEN** the last line belongs to another role or point, is not a report line, or the file is empty
- **THEN** `tld roles: no reflektor report line` is printed on stderr and the exit code is 3

### Requirement: Reflektor preparation
The system SHALL, in `tld roles reflektor-prepare --dest DIR --repo CLONE --base BASE`, refuse a clone whose `.reflektor.json` is unsafe, refuse an unfit PATH or Node, then download the pinned release, verify it and write the files and a report guide under `DIR/reflektor`, printing that path and the path of Node.

#### Scenario: Unsafe repository config
- **WHEN** `.reflektor.json` is a symlink, not a regular file, over 100000 bytes, not a JSON object, holds keys other than `base`, `targets` and `generated`, holds disallowed globs or more than 50 globs, or was changed by the branch against BASE
- **THEN** the preparation is refused

#### Scenario: Unfit PATH or Node
- **WHEN** PATH has an empty or relative entry, or Node is missing or older than 18
- **THEN** the preparation is refused

#### Scenario: Pinned release checked
- **WHEN** the release is downloaded
- **THEN** its size, its sha256 and every archive member are checked before the files are written

#### Scenario: Success
- **WHEN** the clone, branch, Node and download are all fit
- **THEN** the absolute path of `DIR/reflektor` and of `node` are printed and the exit code is 0

#### Scenario: Environment not fit
- **WHEN** the repository config, branch, Node, PATH or network is not fit
- **THEN** `tld roles: reflektor: <reason>` is printed on stderr and the exit code is 3

#### Scenario: Release not as pinned
- **WHEN** the download has the wrong size or sha256, the archive has an unsafe, duplicate, special or missing required member, or `DIR/reflektor` already exists
- **THEN** the reason is printed on stderr, nothing is written for a bad member, and the exit code is 1

### Requirement: Reflektor report and page checks
The system SHALL, in `tld roles reflektor-check --report FILE --root CLONE`, accept a one-line JSON object report whose every `path` value is a plain relative path that stays inside the clone (also through symlinks), and exit 1 with reasons on stderr otherwise.

#### Scenario: Path leaves the clone
- **WHEN** a report `path` is absolute, starts with `~`, contains `..` or an empty segment, or resolves outside the clone
- **THEN** `tld roles: reflektor: <reason>` is printed on stderr and the exit code is 1

### Requirement: Reflektor page hardening and send
The system SHALL, in `tld roles reflektor-html`, either add the Content-Security-Policy to a built page with `--file` or, with `--send --answer FILE --dest DIR`, copy the page named by the last `REPORT-HTML` line of the saved answer to `DIR/report.html` and print its path.

#### Scenario: Page hardened once
- **WHEN** `--file` names a page with exactly one `<head>` that is not yet hardened and passes the viewer and secret checks
- **THEN** the policy is inserted after `<head>` and the exit code is 0; a second run, a page with another head count, or a failing page exits 1 and leaves the file unchanged

#### Scenario: Unsafe send
- **WHEN** the answer has no `REPORT-HTML` line, the path is not an `out/report.html` path, a file is a symlink, too large or not UTF-8, or the page holds a credential-like string or the allow mark
- **THEN** nothing is written and the exit code is 1

#### Scenario: Send misuse
- **WHEN** `--send` lacks `--answer` or `--dest`, or those are given without `--send`
- **THEN** a usage error is printed and the exit code is 2
