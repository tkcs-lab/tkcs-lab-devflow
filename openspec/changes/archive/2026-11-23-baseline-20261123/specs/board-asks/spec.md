## Purpose
Board asks let a session put questions to the owner and read the answers back. This covers ask validation, the commands `tld board ask`, `answers`, `cancel` and `ask-text`, the GitHub issue fallback with its rules for trusting replies, and `tld board ask-digest`.

## ADDED Requirements

### Requirement: Ask validation
The system SHALL accept an ask only when it is a JSON object with the fields schema (1), kind ("ask"), project, repo, title, created_by and 1 to 30 questions, with no unknown field, and SHALL report each violation as a line starting `ask: ` (`tld board validate-ask FILE|-` exits 0 with `ask: OK` or exit 1 with the lines).

#### Scenario: Valid ask
- **WHEN** an ask has a one-line title of at most 120 characters, a project equal to the slug of the repository name, an `owner/name` repo and valid questions
- **THEN** validation prints `ask: OK` and exits 0

#### Scenario: Project mismatch
- **WHEN** the project is not the slug of the repo name, or contains a double hyphen
- **THEN** validation exits 1 with a line naming the field

#### Scenario: Question rules
- **WHEN** a question id repeats, a choice has fewer than 2 or more than 10 options, option values repeat ignoring case, an option list is given for a non-choice, a text is over 2000 characters, or text contains control characters or bidirectional controls
- **THEN** validation exits 1

#### Scenario: Server-assigned fields
- **WHEN** a posted ask sets an id, creation time or answer time, a state other than open, or non-empty answers
- **THEN** validation exits 1 saying the field is set by the board

#### Scenario: Optional links
- **WHEN** `context_url` is not null and not an https URL of at most 500 characters without whitespace, or `fallback_issue` is not `owner/repo` or `owner/repo#n`
- **THEN** validation exits 1

#### Scenario: Size and unreadable input
- **WHEN** the ask is over 65536 bytes, or the file cannot be read as JSON
- **THEN** validation exits 1

### Requirement: Posting an ask to the board
The system SHALL, on `tld board ask FILE|-`, validate the ask, post it to the configured board and print the new ask id on stdout with exit code 0, and SHALL exit 1 (invalid ask, unreadable file, or the board refused it with an answer other than a created ask) or 3 (no board configured and no fallback issue given).

#### Scenario: Posted
- **WHEN** the board accepts the ask
- **THEN** stdout is the ask id starting `a-` followed by 16 hex digits and the exit code is 0; the board stores it as open with empty answers

#### Scenario: Refused by validation
- **WHEN** the ask is invalid
- **THEN** each error is printed to stderr starting `ask: ` and the exit code is 1

#### Scenario: No board and no fallback
- **WHEN** no board is configured and `--fallback-issue` is not given
- **THEN** the exit code is 3

#### Scenario: Open ask cap
- **WHEN** the board already holds 200 open asks
- **THEN** the board refuses the new ask and the command exits 1

### Requirement: Reading answers
The system SHALL, on `tld board answers ID`, print the answers as one JSON object (question id to answer) and exit 0 when the owner has answered, exit 3 when the ask is still open (after polling up to `--wait` seconds every `--interval` seconds, at least 1), exit 4 when it was cancelled, and exit 1 when the ask is unknown, no board is configured or the board cannot be reached.

#### Scenario: Answered
- **WHEN** the owner has answered the ask
- **THEN** stdout is the answers object and the exit code is 0

#### Scenario: Still open
- **WHEN** the ask is open and the wait ends
- **THEN** stderr says the ask is still open and the exit code is 3

#### Scenario: Cancelled
- **WHEN** the ask was cancelled
- **THEN** the exit code is 4

#### Scenario: Unreachable board while waiting
- **WHEN** `--wait` is given and the board does not connect, or answers 429 or a 5xx status
- **THEN** the command retries until the wait ends and then exits 1

#### Scenario: No ask id
- **WHEN** no id and no `--from-issue` or `--from-reply` is given
- **THEN** the exit code is 2

### Requirement: Owner answers on the board
The system SHALL accept the owner's answers only for an open ask, require an answer for every required question (questions are required unless marked otherwise), normalise a choice answer to the option's value ignoring case, accept a boolean for a confirm, accept a text of at most 4000 characters without control characters (trimmed), ignore null or blank answers for optional questions, and reject answers for unknown question ids.

#### Scenario: Answer stored
- **WHEN** the owner posts complete valid answers to an open ask
- **THEN** the ask becomes answered with the cleaned answers and an answer time

#### Scenario: Missing or wrong answers
- **WHEN** a required question has no answer, or an answer does not fit its kind or options
- **THEN** the board answers 422 and the ask stays open

#### Scenario: Not open
- **WHEN** the owner answers an ask that is answered or cancelled
- **THEN** the board answers 409 `not_open`

### Requirement: Cancelling an ask
The system SHALL, on `tld board cancel ID`, cancel an open ask and print `{"id", "state"}` with exit code 0, treat cancelling an already cancelled ask as success, and exit 1 when the ask is unknown, already answered, or no board is configured or reachable.

#### Scenario: Cancel open
- **WHEN** an open ask is cancelled
- **THEN** its state is cancelled and the exit code is 0

#### Scenario: Cancel answered
- **WHEN** the ask is already answered
- **THEN** stderr says it is already answered and the exit code is 1

### Requirement: Ask as chat text
The system SHALL, on `tld board ask-text FILE|- [--id ID]`, validate the ask and print it as one Markdown chat message with the title, where to answer (the chat plus the board ask id, or the issue when the id is an https link), the context link when present, each question numbered with its id, kind, required or optional, text and options, and an example reply with one `<question id>: <answer>` line per question; the command SHALL exit 1 for an invalid or unreadable ask.

#### Scenario: Single choice or confirm
- **WHEN** the ask has exactly one question that is a choice or confirm
- **THEN** the message adds that the answer alone is enough

#### Scenario: Reading the owner's reply
- **WHEN** `tld board answers --from-reply REPLY|- --ask FILE` is given the messages the owner typed
- **THEN** each plain line `<question id>: <answer>` that fits is an answer with later lines overriding earlier ones, and for one choice or confirm question a final line alone also counts; a text question never takes a bare answer

#### Scenario: Reply result codes
- **WHEN** every required question has an answer, or one is missing
- **THEN** the exit code is 0 with the answers JSON, or 3 with stderr naming the missing questions; the exit code is 2 when `--ask` is missing, an ask id or `--from-issue` is also given, or both inputs read stdin

### Requirement: Issue fallback
The system SHALL, when `tld board ask` is given `--fallback-issue OWNER/REPO[#N]` and the board is not configured, cannot be reached or answers with a 5xx status, print the exact comment body for that issue on stdout (a new-issue body when no number is given), name the reason on stderr and exit 5, without writing to GitHub itself.

#### Scenario: Comment body
- **WHEN** the fallback body is printed
- **THEN** it starts with a hidden ask marker, mentions the owner (the `--mention` login, else the profile's owner login, else the repository owner) with every other at-sign neutralised, lists the questions and shows an example reply

#### Scenario: Board unreachable
- **WHEN** the board cannot be reached and a fallback issue is given
- **THEN** the exit code is 5 and stdout is the comment body

#### Scenario: Invalid fallback value
- **WHEN** `--fallback-issue` is not `owner/repo` or `owner/repo#n`, or `--mention` is not a GitHub login
- **THEN** the exit code is 2

### Requirement: Trust of replies on the issue
The system SHALL, on `tld board answers --from-issue COMMENTS.json --ask FILE --self LOGIN`, take answers only from counted comments, reading each plain `<question id>: <answer>` line that fits the question, with later answers overriding earlier ones.

#### Scenario: Counted comments
- **WHEN** a comment is by an owner login (every `--owner`, else the profile's owner login, else the owner of `--repo` or of the ask's fallback issue) or by an author with admin permission
- **THEN** its answer lines are read

#### Scenario: Uncounted comments
- **WHEN** a comment is by the `--self` login or is the fallback comment itself
- **THEN** it is never counted

#### Scenario: Line forms
- **WHEN** a plain line answers a choice, a confirm or a text question
- **THEN** it fits as a choice value, yes or no, or the rest of the line respectively

#### Scenario: Write permission does not count
- **WHEN** a reply comes from an author with write or maintain permission who is not an owner login
- **THEN** its answers are ignored

#### Scenario: Hidden text
- **WHEN** an answer line sits in a fenced block, indented code, a quote, an HTML comment, or a blockquote or details block
- **THEN** it is ignored

#### Scenario: Complete or missing
- **WHEN** every required question is answered, or not
- **THEN** the exit code is 0 with the answers JSON, or 3 with stderr naming the missing questions

#### Scenario: Missing input
- **WHEN** `--ask` or `--self` is missing, an owner login is malformed, or no owner can be determined
- **THEN** the exit code is 2

#### Scenario: Bad input files
- **WHEN** the comments file is not a JSON list or the ask is invalid
- **THEN** the exit code is 1

### Requirement: Ask digest
The system SHALL, on `tld board ask-digest --repo OWNER/NAME [--since T] [--file FILE|-] [--vocab FILE] [--now T]`, read the asks from the board (or from the file) and print one line of JSON with the project, a list of clusters of similar masked questions, counts and a cursor, never any answer text or text of another project's ask.

#### Scenario: Analysis scope
- **WHEN** the asks are read
- **THEN** only asks of that repository are analysed, asks of the questions command and open asks are left out of analysis, and questions of other projects are only counted

#### Scenario: Masking and clusters
- **WHEN** questions are analysed
- **THEN** each question text is masked (URLs, code, e-mail addresses, logins, paths, hosts, hashes, hyphenated names, numbers) and similar questions of the same source and kind are grouped into clusters ordered by count and capped at 60

#### Scenario: Digest printed
- **WHEN** the command runs on a readable list of asks
- **THEN** it prints one JSON line and exits 0

#### Scenario: Candidate clusters
- **WHEN** a cluster has at least 3 questions across at least 2 records, or at least 3 questions with at least 80 percent empty text answers, or 2 reposted or 3 cancelled asks
- **THEN** it is flagged as a candidate

#### Scenario: Word list
- **WHEN** `--vocab` is given
- **THEN** every word not in the list is replaced in the emitted template

#### Scenario: Exit codes
- **WHEN** no board is configured, the board or a file cannot be read, or the arguments are wrong
- **THEN** the exit code is 3, 1 or 2 respectively
