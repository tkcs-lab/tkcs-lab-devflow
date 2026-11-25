## MODIFIED Requirements

### Requirement: Summary section check
The system SHALL, in `tld plan summary-check FILE --kind plan|issue|pr [--findings N]`, require exactly one `## Summary` section placed first (an issue: right after `## Request`) that follows the rules of the scenarios below, and SHALL print `summary: <problem>` per problem and exit 1, or `summary: OK (<n> words)`.

#### Scenario: Labels
- **WHEN** the Summary is checked
- **THEN** the labels must be in the kind's order, the required labels present (plan and issue: Use it, Scope, Review focus; pr: Deviations, Review focus), and none unknown or duplicate

#### Scenario: Values
- **WHEN** the Summary values are checked
- **THEN** there is no placeholder value, each value has at least three words, `None.` appears only for Deviations, Security and Performance, and there is no HTML comment or details block

#### Scenario: Length
- **WHEN** the Summary is checked for length
- **THEN** it has at most 350 words (plan, issue) or 175 words (pr)

#### Scenario: Valid summary
- **WHEN** the file satisfies the rules
- **THEN** `summary: OK (<n> words)` is printed and the exit code is 0

#### Scenario: Deviations claimed as None
- **WHEN** `--deviations FILE` is given with `--kind pr` and the Summary says `None.` while the file records deviations other than `None.` or `pending`
- **THEN** a problem is printed and the exit code is 1

#### Scenario: Findings section rows
- **WHEN** `--kind pr` is checked and the body has a `## Non-blocking findings` section (with or without `--findings`)
- **THEN** the section is either the single line `None.` or rows of the form `- F<n> · <source> · <path>[:<line>] · <finding> · fixed <sha>` or `... · declined: <reason>` with ids F1, F2, ... in order, a `declined` reason of at least three words that is not a placeholder, and no hidden markup, control character or mention; each problem is printed as `summary: findings: <problem>` and the exit code is 1

#### Scenario: Findings count
- **WHEN** `--findings N` is given with `--kind pr`
- **THEN** the section must exist and hold exactly N rows (the line `None.` when N is 0), otherwise a `summary: findings:` or `summary: no '## Non-blocking findings' section` problem is printed and the exit code is 1

#### Scenario: Unreadable file or misuse
- **WHEN** the file is missing, larger than 1000000 bytes or not UTF-8, or `--deviations` or `--findings` is used with a kind other than pr, or `--findings` is negative
- **THEN** a missing, oversized or non-UTF-8 file prints one `summary:` line and exits 1, and the misuse prints a usage message and exits 2
