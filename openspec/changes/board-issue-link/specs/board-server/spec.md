## ADDED Requirements

### Requirement: Tracking issue on a status record
The system SHALL accept an optional `tracking_issue` field on a status record of either kind, holding null or a positive integer of at most ten digits, and SHALL refuse a record whose tracking issue breaks the rules below with 422 `invalid` and an error that names `tracking_issue`.

#### Scenario: Valid tracking issue
- **WHEN** a run or command record carries a tracking issue that is a positive integer of at most ten digits, or null
- **THEN** the record is stored and read back with the tracking issue unchanged

#### Scenario: Malformed tracking issue
- **WHEN** the tracking issue is zero, negative, longer than ten digits, a boolean, a fraction or a string
- **THEN** the write is refused with an error naming `tracking_issue`

#### Scenario: Tracking issue disagrees with the hand-over
- **WHEN** a record carries both a tracking issue and a hand-over whose issue link names another issue number
- **THEN** the write is refused with an error naming `tracking_issue`

#### Scenario: Tracking issue disagrees with an issue plan slug
- **WHEN** a record's plan slug is `issue-<n>` and its tracking issue is set to a number other than n
- **THEN** the write is refused with an error naming `tracking_issue`

#### Scenario: Record without tracking issue
- **WHEN** a record carries no `tracking_issue` field
- **THEN** it is validated exactly as before

### Requirement: Issue link on the owner page
The owner page SHALL show, in the links of a card whose record carries a valid tracking issue and a valid repository, a link named `issue #<n>` to the issue page of that repository on github.com, before every other link of the card, and SHALL show no issue link otherwise.

#### Scenario: Issue link on a card
- **WHEN** a run or command record with repository `<owner>/<name>` and tracking issue n is on the board
- **THEN** its card's links start with `issue #<n>` pointing to `https://github.com/<owner>/<name>/issues/<n>`

#### Scenario: No issue link
- **WHEN** a record has no tracking issue, a null one, or a value or repository the page does not accept
- **THEN** its card shows no issue link and its other links are unchanged
