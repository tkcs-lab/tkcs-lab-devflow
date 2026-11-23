# board-server Specification

## Purpose
The board server is the self-hosted owner inbox started with `tld board server`. It stores status records, asks and usage readings in SQLite, serves a JSON API to sessions and a web page to the owner, and gives each of the two principals only its own routes.

## Requirements

### Requirement: Startup configuration and refusals
The system SHALL start `tld board server` only with a session token of at least 24 characters from the environment, and SHALL exit with code 2 and a line starting `board_server: ` on stderr when the token is missing or short, when an owner passphrase is set but shorter than 16 characters or equal to the token, when a secret, session-hours, API-port, public-origin or session-link setting is invalid, or when the usage plan setting is invalid.

#### Scenario: Short token
- **WHEN** the server starts with no token or a token under 24 characters
- **THEN** it exits with code 2 and prints that the token must be set to at least 24 characters

#### Scenario: Passphrase rules
- **WHEN** the passphrase is under 16 characters or identical to the token
- **THEN** the server exits with code 2

#### Scenario: No passphrase
- **WHEN** no passphrase is set
- **THEN** the server runs API only, the page, login, logout and session routes answer 404 `owner_ui_disabled`, and a notice says the owner UI is off

#### Scenario: Signing secret
- **WHEN** no signing secret is given in the environment
- **THEN** one is generated once into a file next to the database with mode 0600 and reused on later starts; a given secret shorter than 32 characters stops the server

### Requirement: Two principals and route policy
The system SHALL accept a bearer token as the session principal and a signed login cookie as the owner principal, and SHALL answer 401 `unauthorized` for a missing or wrong credential, 403 `forbidden` for a valid principal calling the other principal's route, and 401 for a wrong token even when a valid cookie is also sent.

#### Scenario: Session writes, owner reads
- **WHEN** the session token calls `PUT /api/records/<id>`, `POST /api/asks` or `POST /api/usage`
- **THEN** the call is accepted; the owner cookie on the same routes gets 403

#### Scenario: Owner answers
- **WHEN** the session token calls `POST /api/asks/<id>/answer`, `POST /api/records/<id>/dismiss` or `GET /api/usage`
- **THEN** the answer is 403 `forbidden`; the owner cookie is accepted

#### Scenario: Shared routes
- **WHEN** either principal calls `GET /api/records`, `GET /api/records/<id>`, `GET /api/asks`, `GET /api/asks/<id>` or `POST /api/asks/<id>/cancel`
- **THEN** the call is accepted

#### Scenario: Open routes and unknown paths
- **WHEN** `GET /healthz` or the page is requested without credentials
- **THEN** they answer 200; an unknown path answers 404 `not_found` and a known path with an unsupported method answers 405 `method_not_allowed` with an `Allow` header

#### Scenario: Other credential schemes
- **WHEN** a request uses basic authentication
- **THEN** it is refused with 401

### Requirement: Owner login, cookie and CSRF
The system SHALL let the owner log in with `POST /login` and the passphrase, answer 401 `wrong_passphrase` with no cookie for a wrong one, set a signed HttpOnly, SameSite=Strict cookie (Secure and host-prefixed unless the insecure-cookie flag is given) that expires after the session-hours setting (default 12 hours), end the session on `POST /logout` in a way that survives a restart, and require on every owner POST the board's own Origin and the `X-CSRF-Token` returned by login.

#### Scenario: Wrong passphrase limits
- **WHEN** a client sends five wrong passphrases
- **THEN** further attempts from it answer 429 `too_many_attempts` with a `Retry-After` header that grows with later failures up to 15 minutes, and a correct login clears the count; failures from many clients only slow all logins down, never lock the owner out

#### Scenario: Missing origin or token
- **WHEN** an owner POST lacks the board's Origin, or lacks a matching CSRF token
- **THEN** the answer is 403 `origin_not_allowed` or 403 `csrf`

#### Scenario: Session state
- **WHEN** `GET /api/session` is called
- **THEN** it answers `{"owner": true, "csrf": ...}` with a valid cookie and `{"owner": false, "csrf": null}` otherwise

#### Scenario: Tampered or logged-out cookie
- **WHEN** a cookie is altered, expired or already logged out
- **THEN** it is not accepted as the owner

### Requirement: Separate page and API endpoints
The system SHALL, when started with `--api-port` (which needs a passphrase and a port different from `--port`), serve the owner's page, login and owner routes on `--port` and only the sessions' routes on the API port, refusing any request that carries an Authorization header on the page port with 403 `wrong_endpoint`, ignoring cookies on the API port, and answering 404 on an endpoint for a route or method it does not serve.

#### Scenario: Token on the page port
- **WHEN** a request with an Authorization header reaches the page port
- **THEN** it is answered 403 `wrong_endpoint`

#### Scenario: Owner route on the API port
- **WHEN** the owner's dismiss route is requested on the API port
- **THEN** it answers 404 `not_found`

#### Scenario: Health on both
- **WHEN** `GET /healthz` is requested on either port
- **THEN** it answers 200 `{"ok": true}`

### Requirement: Status records and versioning
The system SHALL store each status record under a valid id with an integer version, accept `PUT /api/records/<id>` with `{"data": ..., "if_version": n}`, and apply optimistic concurrency so that a write succeeds only when it matches the stored state.

#### Scenario: Record id format
- **WHEN** a record id is used
- **THEN** it consists of lower-case letters, digits and hyphens, is at most 100 characters and starts with a letter or digit

#### Scenario: Write without if_version
- **WHEN** a write carries no `if_version` and the record already exists
- **THEN** the answer is 409 `version_conflict` with the stored record as `current`; when the record does not exist it is created

#### Scenario: Write with if_version
- **WHEN** a write carries an `if_version` equal to the stored version
- **THEN** it succeeds and stores version n+1

#### Scenario: Create and update
- **WHEN** a valid record is written without `if_version`, then written again with `if_version` 1
- **THEN** the answers are 200 `{"id", "version": 1}` and 200 with version 2

#### Scenario: Stale version
- **WHEN** a write carries an `if_version` that differs from the stored version
- **THEN** the answer is 409 `version_conflict` and the stored record is unchanged

#### Scenario: Invalid body
- **WHEN** the body is not an object with a `data` key, or `if_version` is not an integer of at least 1 (a boolean is refused)
- **THEN** the answer is 400 `bad_request`; a record that breaks the status record rules, whose id does not match its project and command, or that exceeds 262144 bytes answers 422 `invalid` with an `errors` list

#### Scenario: Read and delete
- **WHEN** a record is read or deleted by the session token
- **THEN** `GET` returns id, version, `dismissed_at`, data and report metadata; `DELETE` answers 200 `{"deleted": true}`, also removing its dismissal and report, and 404 `not_found` for an unknown id

#### Scenario: Body limits
- **WHEN** a request body is over 1048576 bytes (4096 for login), has no valid Content-Length, or trickles in slower than the deadline
- **THEN** the answer is 413 `payload_too_large`, 400 `bad_request` or 408 `request_timeout`

### Requirement: Dismiss, restore and hidden records
The system SHALL let only the owner dismiss a record with `POST /api/records/<id>/dismiss` and restore it with `POST /api/records/<id>/restore`, and `tld board stale` SHALL print the ids of hidden records, one per line.

#### Scenario: Dismiss request
- **WHEN** the owner dismisses a record with a body of exactly `{"version": n}`
- **THEN** the dismissal is stored beside the record without changing its data or version; the answer is 409 `version_conflict` when n is not the stored version, 400 for any other body and 404 for an unknown id

#### Scenario: Dismissal lapses on write
- **WHEN** a record is dismissed and a session then writes a new version
- **THEN** its `dismissed_at` is null again

#### Scenario: Stale listing
- **WHEN** `tld board stale` reads a JSON list of `{id, data}` documents
- **THEN** it prints the id of each record that is dismissed, or that has not been updated for more than 7 days without needing the owner, or that finished in a final done/failed state more than 7 days ago, and a record that needs the owner is never printed unless dismissed

#### Scenario: Unreadable input
- **WHEN** `tld board stale` cannot read or parse its input
- **THEN** it exits with code 1 and prints a line starting `board_stale: `

### Requirement: Resolving a record
The system SHALL provide `tld board resolve FILE|- --now <time> --reason <text>`, which prints the record with needs_you cleared (needs_you false, empty reason, no since time, status done, finished_at and updated_at set to the given time, no next check, last event set to the reason) and exits 0.

#### Scenario: Cleared record
- **WHEN** a record that needs the owner is resolved with a reason of at most 200 characters
- **THEN** the cleared record is printed as JSON and passes the record validator

#### Scenario: Refusal
- **WHEN** the record does not need the owner, the reason is empty or over 200 characters, or the cleared record is invalid
- **THEN** the command exits 1 with a line starting `board_resolve: `

### Requirement: Change reports
The system SHALL store at most one HTML report page per record through `PUT /api/records/<id>/report` (session token) and serve it to the owner through `GET /api/records/<id>/report` as a sandboxed page.

#### Scenario: Missing record
- **WHEN** a report is uploaded for a record that does not exist
- **THEN** the answer is 404 `not_found`, before the body is read

#### Scenario: Bad body
- **WHEN** the body is empty, not UTF-8 or contains a NUL
- **THEN** the answer is 400 `bad_request`; a body over 20 MiB answers 413

#### Scenario: Page rules and capacity
- **WHEN** the page rules fail, another upload is running, or the total size cap is passed
- **THEN** the answer is 422 `invalid_report` with reasons, 503 `busy` or 507 `store_full`

#### Scenario: Upload and read
- **WHEN** a valid report is uploaded for an existing record
- **THEN** the answer is 200 with id, size and sha256, and the record's listing shows the report metadata

#### Scenario: Report removed with record
- **WHEN** the record is deleted
- **THEN** its report is deleted too

### Requirement: Usage readings
The system SHALL keep subscription usage readings only when a plan (standard or max) is set in the environment, accept them through `POST /api/usage`, and show them to the owner through `GET /api/usage`.

#### Scenario: Reading shape
- **WHEN** a reading is posted
- **THEN** it has at least one of `five_hour` or `seven_day`, each with `utilization` from 0 to 1.5 and an integer `resets_at` in the future within the window length plus 10 minutes, and a `source` of final or scheduled

#### Scenario: Owner view
- **WHEN** the owner calls `GET /api/usage`
- **THEN** the answer shows windows with peak, last reading, over-limit flag, blocked hours, idle flag and completeness

#### Scenario: Plan not set
- **WHEN** a reading is posted and no plan is set
- **THEN** the answer is 409 `usage_off`

#### Scenario: Invalid reading
- **WHEN** the body has an unknown key, a bad utilization or a bad `resets_at`
- **THEN** the answer is 422 `invalid` with an `errors` list; a body over 4096 bytes is 413 and non-JSON is 400

#### Scenario: Stored reading
- **WHEN** a valid reading is posted
- **THEN** the answer is 200 `{"stored": n}`, `resets_at` is floored to the minute and the server's own clock gives the observation time

#### Scenario: Retention
- **WHEN** more than 50 samples exist for one window, a window ended more than 120 days ago, or more than 20000 rows exist
- **THEN** the oldest samples are deleted

#### Scenario: Invalid plan setting
- **WHEN** the plan is neither standard nor max, or the Max factor is not above 1 and at most 20
- **THEN** the server exits with code 2 (the factor defaults to 5)

### Requirement: Web page and security headers
The system SHALL serve the owner page at `/` and `/index.html` with a restrictive content security policy and a deny-framing header, and every response SHALL carry no-store caching, no-sniff and no-referrer headers; the server SHALL answer 503 `busy` when more than 64 connections are open and drop silent or trickling clients.

#### Scenario: Page headers
- **WHEN** the page is requested
- **THEN** the answer is 200 HTML with a Content-Security-Policy and X-Frame-Options header

#### Scenario: Connection cap
- **WHEN** a connection arrives while 64 are being served
- **THEN** it is answered 503 and closed

### Requirement: Database and deployment
The system SHALL keep its data in one SQLite file (default `board.sqlite3`, set by `--db` or the database environment variable), migrate an older database to the current schema version while keeping every record, and refuse a database with a newer schema; the repository SHALL ship a container build for the server that runs as a non-root user, exposes port 8787, keeps data on a `/data` volume and has a health check.

#### Scenario: Older database
- **WHEN** the server opens a database made by an earlier schema version
- **THEN** it adds the missing tables and keeps the records and usage rows

#### Scenario: Newer database
- **WHEN** the database has a schema version above the one the server knows
- **THEN** startup fails with exit code 2

#### Scenario: Port in use
- **WHEN** a requested port cannot be bound
- **THEN** the server prints a `board_server: ` line and exits with code 2
