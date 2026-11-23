# board-session-access Specification

## Purpose
A session reaches the tld status board through a command-line client (`tld board client`), a usage sender (`tld board usage`) and an MCP endpoint with a stdio bridge (`tld board mcp-stdio`). This capability covers configuration, exit codes, the report page check and the behaviour when no board is configured.

## Requirements

### Requirement: Board configuration from the environment
The system SHALL read the board address from TLD_BOARD_URL and the bearer token from TLD_BOARD_TOKEN, and SHALL treat the board as not configured when the address is unset or empty or (for every command except `health`) the token is empty.

#### Scenario: Trailing slash and loopback http
- **WHEN** TLD_BOARD_URL ends in a slash, or is a plain http URL for a loopback host
- **THEN** the slash is dropped and the URL is accepted without TLD_BOARD_ALLOW_HTTP

#### Scenario: Refused addresses
- **WHEN** TLD_BOARD_URL is not http(s), holds user info, a query or a fragment, or is plain http for a non-loopback host while TLD_BOARD_ALLOW_HTTP is not 1
- **THEN** the command prints a configuration error on stderr and exits 1

#### Scenario: Not configured
- **WHEN** `tld board client list` runs with no board variables set
- **THEN** it prints "no board configured" on stderr and exits 3

### Requirement: Client record commands
The system SHALL provide `tld board client list`, `get ID`, `set ID FILE|- [--if-version N]` and `delete ID [ID ...]`, each printing one line of compact JSON on stdout and exiting 0 on an HTTP 200 answer.

#### Scenario: Set, get, list
- **WHEN** `set ID FILE` is run with a JSON document, then `get ID` and `list`
- **THEN** the document is stored as the record and both reads print it as JSON with exit 0

#### Scenario: Version conflict or invalid record
- **WHEN** `set` is refused by the server (a version conflict or an invalid record)
- **THEN** the server's JSON body is printed on stdout, "the server answered HTTP <status>" goes to stderr, and the exit code is 1

#### Scenario: Unreadable document
- **WHEN** the FILE (or stdin) of `set` is unreadable or not JSON
- **THEN** "cannot read the document" is printed on stderr and the exit code is 1

#### Scenario: Delete several records
- **WHEN** `delete` is given one existing and one unknown id
- **THEN** stdout is a JSON object listing the ids under "deleted" and "missing" and the exit code is 0; any other error status stops the command with exit 1

#### Scenario: Wrong token
- **WHEN** the token is not accepted by the board
- **THEN** the command exits 1

### Requirement: Client health check
The system SHALL provide `tld board client health`, which needs only the board URL, sends no Authorization header and prints `ok` on a 200 answer.

#### Scenario: Healthy board
- **WHEN** `health` runs against a running board with only TLD_BOARD_URL set
- **THEN** stdout is `ok` and the exit code is 0

#### Scenario: Network failure
- **WHEN** the board cannot be reached
- **THEN** "cannot reach the board" is printed on stderr and the exit code is 1

### Requirement: Report upload
The system SHALL provide `tld board client put-report ID FILE`, which sends a regular file of at most 20 MiB as an HTML page for the record, and SHALL print the server's JSON answer and exit 0 only when the board stores it.

#### Scenario: File refused locally
- **WHEN** FILE is missing, is a directory, or is larger than 20 MiB
- **THEN** no request is sent, "cannot read the report" is printed on stderr and the exit code is 1

#### Scenario: Page refused by the board
- **WHEN** the board answers 422 because the page fails its check
- **THEN** the JSON error with its reasons is printed on stdout, "HTTP 422" on stderr, nothing is stored and the exit code is 1

#### Scenario: Unknown record
- **WHEN** the record id does not exist on the board
- **THEN** the exit code is 1 and stderr names HTTP 404

#### Scenario: Valid page
- **WHEN** the page passes the check
- **THEN** stdout is JSON with the record id, the size in bytes and the page's sha256, and the exit code is 0

#### Scenario: Not a record write
- **WHEN** the board-write gate inspects a `put-report` command
- **THEN** it does not count it as a record `set`

### Requirement: Report page check
The system SHALL accept a report page only if it equals the pinned viewer page with exactly three variable places: the Content-Security-Policy meta tag, a plain one-line title of at most 200 characters (no "<", no "&", no control, format or line-separator characters), and a one-line JSON payload.

#### Scenario: Altered viewer or policy
- **WHEN** any fixed part of the viewer, or the policy meta tag, differs from the pinned one
- **THEN** the check returns a reason naming that part

#### Scenario: Unacceptable payload
- **WHEN** the payload spans several lines, contains "<", is not JSON, contains NaN or Infinity, repeats an object key or nests deeper than 200 levels
- **THEN** the check returns a reason starting "invalid payload"

#### Scenario: Link targets
- **WHEN** a non-null value appears at any depth under the keys url, ownerUrl, href, notesUrl, web, screenshots, projectChecks, coverage or agent, or under branch.pr or avatar.image
- **THEN** the check returns one reason per such key; a page with none of them returns no reasons

### Requirement: Usage reading sender
The system SHALL provide `tld board usage FILE|- [--source final|scheduled]` (default final), which reads a rate-limit reading in one of three shapes (the whole rate_limit_info, its unifiedWindows, or an object with five_hour and seven_day directly), with the reset time spelled resetsAt or resets_at, and posts the windows still in the future to the board's usage endpoint.

#### Scenario: Sent
- **WHEN** a reading with a current window is sent and the board answers 200
- **THEN** stdout is the board's answer (a JSON object with the stored count) and the exit code is 0

#### Scenario: Expired windows
- **WHEN** every window's reset time is not in the future
- **THEN** nothing is sent, "no current window" is printed on stderr and the exit code is 0; an expired window next to a current one is left out of the body

#### Scenario: Reading not understood
- **WHEN** the input is not JSON, has neither window, or a window lacks a numeric utilization or reset time
- **THEN** "cannot read the reading" is printed on stderr and the exit code is 1

#### Scenario: Board has usage off
- **WHEN** the board answers 409
- **THEN** stderr says usage is off on the board and the exit code is 1; any other non-200 answer prints its body, the HTTP status on stderr and exits 1

#### Scenario: No board or bad source
- **WHEN** no board is configured, or --source is neither final nor scheduled
- **THEN** the exit code is 3 for no board and 2 for the bad option

### Requirement: Board MCP tools
The system SHALL answer JSON-RPC over the board's MCP endpoint with initialize, ping, tools/list and tools/call, and SHALL offer exactly the tools board_list, board_get, board_set, board_ask, board_answers and board_cancel, with no delete tool and no tool that answers an ask.

#### Scenario: Protocol negotiation
- **WHEN** initialize asks for a supported protocol version
- **THEN** that version is echoed; for an unsupported or missing one the newest supported version is answered

#### Scenario: Record tools
- **WHEN** board_set is called with an id and a data object, then board_get and board_list
- **THEN** the record is stored and returned with its id, version, dismissed_at and data; board_get of an unknown id returns an error result "not_found"

#### Scenario: Conflict and invalid record
- **WHEN** board_set passes a stale if_version, omits it for an existing record, or sends an invalid record
- **THEN** the tool result has isError true with "version_conflict" (carrying the current record) or "invalid" (carrying the errors)

#### Scenario: Ask tools
- **WHEN** board_ask posts an ask, then board_answers and board_cancel are called with its id
- **THEN** the stored ask with its id is returned, then its state and answers, then the cancelled state; cancelling an already answered ask returns "not_open"

#### Scenario: Bad arguments and protocol errors
- **WHEN** a tool gets missing, extra or wrongly typed arguments
- **THEN** the result has isError true with "bad_arguments"; an unknown tool or non-object arguments give error -32602, an unknown method -32601, and a non-object message -32600

#### Scenario: Notification
- **WHEN** a message has no id or no method
- **THEN** no reply is produced

### Requirement: Stdio bridge to the board
The system SHALL, for `tld board mcp-stdio`, read newline-delimited JSON-RPC from stdin, forward each message to the board's MCP endpoint with the bearer token, and write each reply as one JSON line on stdout, exiting 0.

#### Scenario: Forwarded request
- **WHEN** a request line is read and the board answers 200 with a JSON object
- **THEN** that object is written to stdout as one line

#### Scenario: Notification
- **WHEN** the board answers 202 to a notification
- **THEN** nothing is written to stdout

#### Scenario: Server or network failure
- **WHEN** a request gets an error status or a network error
- **THEN** a JSON-RPC error -32000 naming the HTTP status or the error type is written for that request id; a failing notification writes nothing

#### Scenario: Bad input lines
- **WHEN** a line is blank, not JSON, or not a JSON object
- **THEN** it is skipped (non-JSON and non-object lines with a note on stderr) and stdout carries only JSON lines

### Requirement: Behaviour without a board
The system SHALL, when TLD_BOARD_URL or TLD_BOARD_TOKEN is missing or the URL is refused, keep `tld board mcp-stdio` running and answer locally.

#### Scenario: Local answers
- **WHEN** initialize, tools/list or ping arrives with no board configured
- **THEN** initialize reports server name tld-board with instructions saying no board is configured, tools/list returns an empty list and ping returns an empty result

#### Scenario: Other methods
- **WHEN** any other request arrives
- **THEN** error -32601 "method not found" is written; notifications get no reply

#### Scenario: Refused configuration
- **WHEN** the URL is refused as a configuration error
- **THEN** the error is printed on stderr and the bridge behaves as if no board were configured
