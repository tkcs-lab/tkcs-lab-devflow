## ADDED Requirements

### Requirement: Hand-over from a plan or an issue body
The system SHALL, in `tld plan handover FILE --kind plan|issue --repo OWNER/NAME --plan-slug SLUG`, print one JSON hand-over object for a status record, or print `handover: <problem>` per problem and exit 1.

#### Scenario: Hand-over printed
- **WHEN** the file passes the Summary section check of its kind, its Summary holds nothing the secret scan finds, and every given value (`--issue-url`, `--plan-url`, `--spec-url`, `--command-prefix`) passes the hand-over rules of a status record of that repository
- **THEN** the object with the fields `summary`, `plan_slug`, `issue_url`, `plan_url`, `spec_url` and `next_command` is printed and the exit code is 0

#### Scenario: Summary word for word and command built
- **WHEN** a hand-over is printed
- **THEN** the summary is the Summary section text between its heading and the next heading without leading or trailing blank lines, the command is the prefix, one space and the plan link, and each link not given and the command without a prefix are null

#### Scenario: Summary fails its check
- **WHEN** the file's Summary fails the Summary section check of its kind
- **THEN** each problem is printed as `handover: summary: <problem>` and the exit code is 1

#### Scenario: Secret in the Summary
- **WHEN** the secret scan finds a secret-like value in the Summary
- **THEN** `handover: the Summary holds a secret-like value on line <n>` is printed, without the value, and the exit code is 1

#### Scenario: Value fails the record rules
- **WHEN** a link, the slug or the prefix breaks the hand-over rules of a status record, or a prefix is given without a plan link
- **THEN** each error is printed as `handover: <error>` and the exit code is 1

#### Scenario: Unreadable file
- **WHEN** the file is missing, larger than 1000000 bytes or not UTF-8
- **THEN** one `handover:` line is printed and the exit code is 1
