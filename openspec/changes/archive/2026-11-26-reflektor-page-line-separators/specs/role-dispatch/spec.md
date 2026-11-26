## ADDED Requirements

### Requirement: Line separators in the page data
The system SHALL accept a Reflektor page whose decoded data strings hold at most 1000 line or paragraph separators, next-line characters, or vertical tab, form feed or information-separator control characters, and SHALL scan a window around each of them, in the raw data and in every decoded data string, a second time with each such character read as a space and deleted, so a credential that the viewer shows on one line is found. A page with more of them SHALL be refused.

#### Scenario: Changed file with a line separator
- **WHEN** the old and new content of a changed file hold U+2028 and U+2029 on a line and the page holds no credential-like string
- **THEN** the page is written unchanged apart from the policy, no line about the characters is printed and the exit code is 0

#### Scenario: Credential next to a line separator
- **WHEN** a decoded data string holds a credential-like string right after such a character, a secret-like name before such a character and its value after it, or a name and a value in two strings that meet at it
- **THEN** `tld roles: reflektor: the page holds something that looks like a credential (<names>)` is printed, nothing is written and the exit code is 1

#### Scenario: Too many separators
- **WHEN** the decoded data strings hold more than 1000 such characters
- **THEN** `tld roles: reflektor: the data holds a line-splitting character` is printed, nothing is written and the exit code is 1
