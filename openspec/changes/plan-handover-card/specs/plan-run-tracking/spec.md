## ADDED Requirements

### Requirement: Hand-over from a plan or an issue body
The system SHALL, in `tld plan handover FILE --kind plan|issue --repo OWNER/NAME --plan-slug SLUG [--issue-url URL] [--plan-url URL] [--spec-url URL] [--command-prefix PREFIX]`, print one JSON object with the fields `summary`, `plan_slug`, `issue_url`, `plan_url`, `spec_url` and `next_command`, whose summary is the text of the file's `## Summary` section word for word and whose command is the prefix, one space and the plan link, and SHALL exit 0, or print `handover: <problem>` per problem and exit 1.

#### Scenario: Hand-over printed
- **WHEN** the file passes the Summary section check of its kind, its Summary holds nothing the secret scan finds, and every value passes the hand-over rules of a status record of that repository
- **THEN** the object is printed with the Summary text between its heading and the next heading, without leading or trailing blank lines, and null for each link not given and for the command when no prefix is given

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
