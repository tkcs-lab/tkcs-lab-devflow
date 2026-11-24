## MODIFIED Requirements

### Requirement: Reflektor page hardening and send
The system SHALL, in `tld roles reflektor-html`, either add the Content-Security-Policy to a built page with `--file` or, with `--send --answer FILE --dest DIR`, copy the page named by the last `REPORT-HTML` line of the saved answer to `DIR/report.html` and print its path. Before either writes, it SHALL scan every line of the original page and of every decoded data string for credentials without honouring the secret-scan allow mark, and SHALL write the page with every literal allow mark replaced by the placeholder `[secret-scan mark removed]`.

#### Scenario: Page hardened once
- **WHEN** `--file` names a page with exactly one `<head>` that is not yet hardened and passes the viewer and secret checks
- **THEN** the policy is inserted after `<head>` and the exit code is 0; a second run, a page with another head count, or a failing page exits 1 and leaves the file unchanged

#### Scenario: Quoted allow mark
- **WHEN** the page text or its data quotes the secret-scan allow mark and holds no credential-like string
- **THEN** the page is written with each mark replaced by `[secret-scan mark removed]`, the written page holds no allow mark, `tld roles: reflektor: removed <n> secret-scan allow marks from the page` is printed on stderr and the exit code is 0

#### Scenario: Credential on a marked line
- **WHEN** a line of the page or of a decoded data string holds a credential-like string and ends in the secret-scan allow mark
- **THEN** the credential is found, nothing is written and the exit code is 1

#### Scenario: Escaped allow mark
- **WHEN** a decoded data string or key still holds the allow mark after the literal marks are replaced (a JSON-escaped form)
- **THEN** `tld roles: reflektor: the data carries an escaped secret-scan allow mark` is printed, nothing is written and the exit code is 1

#### Scenario: Unsafe send
- **WHEN** the answer has no `REPORT-HTML` line, the path is not an `out/report.html` path, a file is a symlink, too large or not UTF-8, or the page holds a credential-like string
- **THEN** nothing is written and the exit code is 1

#### Scenario: Send misuse
- **WHEN** `--send` lacks `--answer` or `--dest`, or those are given without `--send`
- **THEN** a usage error is printed and the exit code is 2

## ADDED Requirements

### Requirement: Change report page note
The system SHALL, in `tld roles page-note --stage role|check|board|send [--stderr FILE] [--sent]`, print exactly one line that starts with `HTML page not stored: ` and says why, built only from fixed text, a reason of the page check that is on the list of known reasons, and a three-digit HTTP status.

#### Scenario: No page from the role
- **WHEN** the stage is `role`
- **THEN** `HTML page not stored: the reflektor role built no checked page.` is printed and the exit code is 0

#### Scenario: Page check refused
- **WHEN** the stage is `check` and the first `tld roles: reflektor: <reason>` line of FILE holds a known reason of the page check
- **THEN** `HTML page not stored: the page check refused it (<reason>).` is printed; with any other FILE content, or none, `HTML page not stored: the page check refused it.` is printed; the exit code is 0

#### Scenario: Board refused or unreachable
- **WHEN** the stage is `board`
- **THEN** `HTML page not stored: the board answered HTTP <n>.` is printed when FILE holds `the server answered HTTP <n>` with a three-digit status, `HTML page not stored: the page is too large to upload.` when it holds `cannot read the report (larger than`, `HTML page not stored: the board cannot be reached.` when it holds `cannot reach the board` and `HTML page not stored: the board did not accept it.` otherwise; with `--sent` the line ends with ` It was sent to the owner as a file instead.`; the exit code is 0

#### Scenario: File not sent
- **WHEN** the stage is `send`
- **THEN** `HTML page not stored: the page could not be sent as a file.` is printed and the exit code is 0

#### Scenario: Page note misuse
- **WHEN** the stage is missing or unknown, or `--sent` is given with a stage other than `board`
- **THEN** a usage error is printed and the exit code is 2

### Requirement: Change report with a page note
The system SHALL, in `tld roles change-report --report FILE [--note FILE]`, print the page note line given in the note file, when it is a valid page note, then a blank line and the cleaned change-report block of the report, exactly as `tld roles section --report FILE` prints it.

#### Scenario: Note and block
- **WHEN** the note file holds one valid page note line and the report has a usable block
- **THEN** the note, a blank line and the cleaned block are printed and the exit code is 0

#### Scenario: Note without a usable block
- **WHEN** the note file holds a valid page note line and the report has no usable block, or its block looks like a credential or carries the allow mark
- **THEN** only the note is printed and the exit code is 0

#### Scenario: No note
- **WHEN** the note file is missing, empty or not given
- **THEN** the output and exit codes are those of `tld roles section --report FILE`

#### Scenario: Invalid note
- **WHEN** the note file holds anything but one line of the shape `tld roles page-note` prints
- **THEN** `tld roles: the page note is not a page-note line` is printed on stderr and the exit code is 1
