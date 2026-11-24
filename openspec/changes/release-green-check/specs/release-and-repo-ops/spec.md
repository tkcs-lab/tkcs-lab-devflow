## ADDED Requirements

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
