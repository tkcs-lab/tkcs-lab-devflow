## ADDED Requirements

### Requirement: Hand-over on a status record
The system SHALL accept an optional `handover` field on a status record of kind `command`, command `make-plan` and status `done`, holding exactly `summary`, `plan_slug`, `issue_url`, `plan_url`, `spec_url` and `next_command`, and SHALL refuse a record whose hand-over breaks the rules below with 422 `invalid` and an error that names the `handover` field.

#### Scenario: Valid hand-over
- **WHEN** a done make-plan record carries a hand-over whose summary is plain text of at most 350 words and 4000 characters, whose plan slug is lower-case letters, digits and hyphens, whose links point to this record's repository on github.com (an issue, a Markdown file of a branch, the spec change folder named by the plan slug), and whose command is an allowed runtime prefix, one space and the plan link
- **THEN** the record is stored and read back with the hand-over unchanged

#### Scenario: Hand-over in the wrong record
- **WHEN** a hand-over is written on a run record, on a record of another command, or on a record whose status is not `done`
- **THEN** the write is refused with an error naming `handover`

#### Scenario: Unsafe hand-over text
- **WHEN** the summary holds a control character other than a line break, a bidirectional or other invisible format character, a surrogate, a private-use character, a line or paragraph separator, more than 350 words or more than 4000 characters
- **THEN** the write is refused with an error naming the field

#### Scenario: Foreign or malformed link
- **WHEN** a link is not https, points to another repository or another host, contains a `..` segment, a `?`, a `#` or a character outside letters, digits, `.`, `_`, `/` and `-` in its branch or path, or is longer than 300 characters
- **THEN** the write is refused with an error naming the field

#### Scenario: Command not built from the plan link
- **WHEN** the command is set while the plan link is not, or is anything other than an allowed prefix (`/tld:implement` or `implement`), one space and the plan link
- **THEN** the write is refused with an error naming `handover.next_command`

#### Scenario: Record without hand-over
- **WHEN** a record carries no `handover` field
- **THEN** it is validated exactly as before

### Requirement: Plan ready cards on the owner page
The system SHALL show every done record with a hand-over that finished in the last seven days, is not dismissed and needs nothing from the owner in a "Plan ready" section above "Running", with the summary, the links and the command ready to copy, and SHALL move it to "Done" once a run record of the same project and plan slug is on the board.

#### Scenario: Plan ready card
- **WHEN** the page shows a record with a hand-over
- **THEN** its card under "Plan ready" shows each summary label in bold followed by its text, links named issue, plan and spec for the links that are set, and the command in a read-only field with a Copy button

#### Scenario: Copy the command
- **WHEN** the owner presses Copy
- **THEN** on a secure page the command is put on the clipboard and the button says `Copied`; elsewhere the field's text is selected and the button says `Selected: copy it`; in both cases the card does not open or close

#### Scenario: Implementation started
- **WHEN** a run record of the same project whose plan slug equals the hand-over's plan slug is on the board
- **THEN** the card is shown under "Done" instead of "Plan ready"

#### Scenario: Old or dismissed card
- **WHEN** the record finished more than seven days ago or the owner dismissed it
- **THEN** it is shown under "Hidden", as any other finished record, and `tld board stale` lists it as it lists any other finished record
