# Plan: a self-hosted status board (HTTP server + MCP), off claude.ai

Tracking issue: https://github.com/tkcs-lab/claude-toolkit/issues/16

## 1. Goal

The devflow status board today is a private claude.ai Artifact page whose data lives in the Artifact
database: sessions write records with the `ArtifactData` tool, the page reads them with
`claude.use("db")`. Everything about it depends on claude.ai. This plan replaces it with a board you
host yourself:

* a small stdlib-only Python HTTP server (`board_server.py`) that stores the status records in
  SQLite, serves the board page, offers a JSON API with optimistic `if_version` concurrency, and
  exposes the same four operations as an MCP endpoint (`POST /mcp`);
* a stdlib-only stdio MCP bridge (`board_mcp_stdio.py`) that the devflow plugin declares in its
  `.mcp.json`, so every session that has the plugin gets the tools `board_get`, `board_list`,
  `board_set`, `board_delete`;
* a small CLI client (`board_client.py`) as the fallback write path for sessions where the plugin's MCP
  server is not loaded (a scheduled task, for example);
* the board page polls the API instead of the Artifact database.

What changes for the owner: run `/board` once to check the connection (it no longer publishes a page);
set two environment variables (`DEVFLOW_BOARD_URL`, `DEVFLOW_BOARD_TOKEN`) in the cloud environment;
host the server (a Dockerfile and a deployment document are included). The profile key
`status.board_url` is removed. Alerts (session rename, push notification) are unchanged. The two other
Artifact uses, `/review`'s decisions page and `/make-plan`'s manual-steps page, are out of scope and
stay as they are.

## 2. Current state

* The page: `plugins/devflow/board/board.html` (359 lines) gets its data in `start()`
  (`board.html:340-353`, called on line 355) through `claude.use("db")` and `db.collection("projects").onSnapshot(...)`.
  `render(entries)` (`board.html:280-319`) takes a list of `{id, data}`, empties `#main` and rebuilds
  it. Rows are `details` elements carrying `data-project` (`board.html:210-211`); the hidden section is
  a `details[data-section="hidden"]`. The shared rules are `plugins/devflow/board/rules.js`.
* `plugins/devflow/scripts/build_board.py` fills the title, the rules, and optionally a fixture and a
  clock into `board.html` (it requires each marker `<!--DEVFLOW:TITLE-->`, `/*DEVFLOW:RULES*/`,
  `/*DEVFLOW:FIXTURE*/null`, `/*DEVFLOW:NOW*/null` exactly once). `board_stale.py` prints the ids of
  records the board hides. `validate_status_record.py` exposes `validate(rec, doc_id) -> list[str]`
  (the doc id must equal the record's `project`, or `<project>--<command>` for a maintenance record).
  All three stay.
* The write path: `plugins/devflow/skills/status-board/SKILL.md:12-23` tells a session to find the board
  URL in the profile key `status.board_url` or the variable `DEVFLOW_BOARD_URL` and to write with
  `ArtifactData` `set`/`if_version`. `/implement` (`implement.md:342-367`), `/deps`, `/upstream` and
  `/land` only say "follow the `status-board` skill"; they need no change.
* `plugins/devflow/commands/board.md` publishes the page with `Artifact` (`capabilities: {db: {}}`) and
  prunes with `ArtifactData`.
* The profile key: `plugins/devflow/schema/profile.schema.json:130-134`,
  `plugins/devflow/skills/project-profile/SKILL.md:70`, `docs/profile-reference.md:46`,
  `templates/toolkit.yaml:61-62`. The root of the profile schema has `additionalProperties: false`, so
  removing the key makes a profile that still has `status:` fail validation with "unknown key 'status'".
* Tests that name the old behaviour: `tests/test_board.py:55` (the `/board` command's needles
  `capabilities: {db: {}}`, `status.board_url`), `tests/test_status_board.py:22-24`
  (`board_url` in the schema). `tests/test_status_board.py:8-14` pins the skill's `##` headings;
  `tests/test_alerts.py` pins the Alerts strings. Both must keep passing unchanged.
* The generic plugin may not contain the words `privacyfence`, `ruff`, `pytest`, `connector` in
  `.md .py .sh .json .yaml .yml .txt` files under `plugins/` and `templates/`
  (`tests/test_no_project_words.py`); `docs/` and `tests/` are exempt.
* Baseline: `python -m pytest tests -q` passes (1692 tests).

## 3. Design

All decisions are made here. A brief points to a subsection by its number.

### 3.1 Files

| New file | Phase |
|---|---|
| `plugins/devflow/scripts/board_store.py` | p1 |
| `plugins/devflow/scripts/board_server.py` | p1, p2 |
| `plugins/devflow/scripts/board_mcp.py` | p2 |
| `plugins/devflow/scripts/board_client.py` | p4 |
| `plugins/devflow/scripts/board_mcp_stdio.py` | p6 |
| `plugins/devflow/.mcp.json` | p7 |
| `plugins/devflow/board/Dockerfile` | p8 |
| `docs/board-server.md` | p8 |
| `tests/test_board_store.py`, `test_board_server.py`, `test_board_mcp.py`, `test_board_page.py`, `board_poll_check.js`, `test_board_client.py`, `test_board_mcp_stdio.py`, `test_board_wiring.py`, `test_board_deploy.py` | per phase |

Conventions for every new Python file: `#!/usr/bin/env python3`, a module docstring with the usage
line (like `board_stale.py`), `from __future__ import annotations`, stdlib only, no syntax newer than
Python 3.11, type hints on every function, `sys.exit(main())` at the bottom, every message to the
user on stderr starts with the module name and a colon (`board_server: `). Tests import the scripts
with `sys.path.insert(0, str(DEVFLOW / "scripts"))` and a plain `import` (`conftest.py` is not
changed). No file under `plugins/` contains the four forbidden words.

### 3.2 Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `DEVFLOW_BOARD_TOKEN` | server, client, bridge | The write token. Server: required, at least 24 characters. Client and bridge: sent as `Authorization: Bearer <token>`. |
| `DEVFLOW_BOARD_READ_TOKEN` | server | Optional second token that may only read (for browsers). Must differ from the write token. |
| `DEVFLOW_BOARD_URL` | client, bridge | Base URL of the server, for example `https://board.example.org`. Not a secret. |
| `DEVFLOW_BOARD_DB` | server | Default for `--db`. |
| `DEVFLOW_BOARD_ALLOW_HTTP` | client, bridge | `1` allows a plain `http://` URL for a non-loopback host. |

Unset `DEVFLOW_BOARD_URL` or `DEVFLOW_BOARD_TOKEN` means "no board": every board step is skipped
silently (as before).

### 3.3 Storage and record semantics (`Store` in `board_store.py`)

`board_store.py` imports `validate_status_record` (same `sys.path.insert` line as the other scripts) and
nothing else of ours. SQLite file, one table: `records(id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL)`,
WAL mode, one connection with `check_same_thread=False` guarded by one `threading.Lock`.

```python
MAX_RECORD = 262144          # bytes of the JSON text of one record
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")

class Conflict(Exception):   # attribute: current (dict | None)
class Invalid(Exception):    # attribute: errors (list[str])

class Store:
    def __init__(self, path: str) -> None
    def get(self, doc_id: str) -> dict | None            # {"id", "version", "data"}
    def list(self) -> list[dict]                         # sorted by id
    def set(self, doc_id: str, data: object, if_version: int | None) -> dict   # {"id", "version"}
    def delete(self, doc_id: str) -> bool
    def count(self) -> int
```

`set` rules, in this order:

1. `doc_id` not matching `ID_RE` -> `Invalid([f"document id '{doc_id}' is not valid"])`.
2. `validate_status_record.validate(data, doc_id)` returns errors -> `Invalid(errors)`.
3. The JSON text of `data` longer than `MAX_RECORD` bytes -> `Invalid(["the record is larger than 262144 bytes"])`.
4. Under the lock: `if_version is None` and the record exists -> `Conflict(current)`; `if_version is None`
   and it does not exist -> insert with version 1; `if_version` given and the record is missing or its
   version differs -> `Conflict(current or None)`; versions equal -> update, version + 1.

Rationale for "no `if_version` means create only": it is the semantics the old skill had (pin to the
version you read, omit only for the first write), and it makes two sessions that start the same run
detect each other.

### 3.4 HTTP server (`board_server.py`)

```python
class Tokens:
    def __init__(self, write: str, read: str | None = None) -> None
    def role(self, authorization: str | None) -> str | None     # "write", "read" or None

def make_server(store: Store, tokens: Tokens, title: str, host: str, port: int,
                allow_origins: tuple[str, ...] = ()) -> ThreadingHTTPServer
def main(argv: list[str] | None = None) -> int
```

`Tokens.role` accepts `Bearer <token>` or `Basic base64(user:token)` (any user name; the password is the
token, so a browser can use the built-in prompt). Comparison with `hmac.compare_digest` on the UTF-8
bytes. `make_server` returns the server with the attributes `store`, `tokens`, `page` (bytes,
`build_board.build(title, None, None).encode()` computed once), `allow_origins`.

Routes. `/healthz` is answered first, with no auth; everything else checks the role first, so an
unauthenticated request never learns whether a route exists.

| Request | Role | Success | Errors |
|---|---|---|---|
| `GET /healthz` | none | 200 `{"ok": true}` | |
| `GET /` and `GET /index.html` | read | 200 `text/html; charset=utf-8`, the page | |
| `GET /api/records` | read | 200 `{"records": [{"id", "version", "data"}, ...]}` | |
| `GET /api/records/<id>` | read | 200 `{"id", "version", "data"}` | 404 `not_found` |
| `PUT /api/records/<id>` | write | 200 `{"id", "version"}`; body `{"data": {...}, "if_version": 3}` (`if_version` optional, integer >= 1 or null) | 400 `bad_request`, 409 `version_conflict` (`current` holds the stored record or null), 422 `invalid` (`errors` holds the list) |
| `DELETE /api/records/<id>` | write | 200 `{"deleted": true}` | 404 `not_found` |
| `POST /mcp` | write | see 3.5 (p2; until then 404) | |

A known path with the wrong method is 405 with `Allow` listing the right ones: `POST` on `/`, `/index.html`,
`/api/records` or `/api/records/<id>`; `PUT` or `DELETE` on `/api/records` or `/`; anything but `POST` on
`/mcp` once p2 has added it (`Allow: POST`). Unknown paths are 404.

Other errors, all `{"error": "<code>"}` JSON: 401 `unauthorized` (with
`WWW-Authenticate: Basic realm="devflow board", charset="UTF-8"`), 403 `forbidden` (a read token on a
write route), 404 `not_found`, 405 `method_not_allowed` (known path, wrong method, with `Allow`), 413
`payload_too_large` (request body over 1048576 bytes, decided from `Content-Length`; a PUT without
`Content-Length` is 400), 400 `bad_request` (not JSON, not an object, `data` missing, `if_version`
not an integer).

The handler speaks HTTP/1.1 with keep-alive: every response, including the 202 of 3.5 (`Content-Length: 0`),
sets `Content-Length`; a 400 or 413 decided before the body was read also sets `self.close_connection = True`.
In a PUT body `if_version` must be an integer >= 1 or null; a boolean, a string or 0 is 400 `bad_request`.

Every response carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`. The HTML page also carries `X-Frame-Options: DENY` and
`Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
The access log goes to stderr as `board_server: <METHOD> <path without query> <status>`; it never
prints a header or a body.

`main`: flags `--host` (default `127.0.0.1`), `--port` (default `8787`, `0` picks a free port),
`--db` (default `$DEVFLOW_BOARD_DB`, else `board.sqlite3`), `--title` (default `Devflow Board`),
`--allow-origin` (repeatable). Tokens come from the environment only. Returns 2 with a message on
stderr when `DEVFLOW_BOARD_TOKEN` is missing or shorter than 24 characters
(`board_server: DEVFLOW_BOARD_TOKEN must be set to at least 24 characters`), when
`DEVFLOW_BOARD_READ_TOKEN` is set and shorter than 24 characters or equal to the write token
(`board_server: DEVFLOW_BOARD_READ_TOKEN must differ from DEVFLOW_BOARD_TOKEN and have at least 24 characters`).
It prints `board_server: listening on http://<host>:<actual port>` to stderr and serves until
interrupted (exit 0).

The server speaks plain HTTP. TLS is the reverse proxy's job (documented in p8).

### 3.5 MCP endpoint (`board_mcp.py` and `POST /mcp`)

```python
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
def handle(store: Store, message: object) -> dict | None   # a JSON-RPC response, or None for a notification
```

`board_mcp.py` imports `Store`, `Conflict`, `Invalid` from `board_store`; `board_server.py` imports
`board_store` and `board_mcp` at the top, and neither of the two imports `board_server`. This matters:
a script run as `python board_server.py` is the module `__main__`, and a module that imported it by name
would load it a second time with its own, different `Conflict` and `Invalid` classes, so `except` clauses
would never match.

Transport: streamable HTTP, stateless. `POST /mcp` with one JSON-RPC object, answered with
`Content-Type: application/json` (never SSE) and no session id. A message with no `id` key (a notification), or with no `method` key (a client's response), gets 202 with
an empty body. A JSON array (batch) gets 400 with a JSON-RPC error `-32600`. A body
that is not JSON gets 400 with `-32700`. `GET /mcp` and `DELETE /mcp` get 405 with `Allow: POST`. If
the request has an `Origin` header and its value is not in `allow_origins`, the answer is 403
`{"error": "origin_not_allowed"}` (clients that are not browsers send none).

Methods: `initialize` (result: `protocolVersion` = the client's if it is in `PROTOCOLS`, else
`PROTOCOLS[0]`; `capabilities` = `{"tools": {"listChanged": false}}`; `serverInfo` =
`{"name": "devflow-board", "version": "1"}`; `instructions` = `"Devflow status board. Records are status records (collection 'projects'); write with board_set and the version you read."`),
`ping` (result `{}`), `tools/list`, `tools/call`. Any other method: JSON-RPC error `-32601`.

Tools. Each `inputSchema` has `"type": "object"` and `"additionalProperties": false`.

| Tool | Arguments | Result text (JSON) |
|---|---|---|
| `board_list` | none | `{"records": [{"id", "version", "data"}, ...]}` |
| `board_get` | `id` (string) | the record `{"id", "version", "data"}`; error `{"error": "not_found"}` |
| `board_set` | `id` (string), `data` (object), `if_version` (integer >= 1, optional) | `{"id", "version"}`; errors `{"error": "version_conflict", "current": <record or null>}` and `{"error": "invalid", "errors": [...]}` |
| `board_delete` | `ids` (array of 1 to 50 strings) | `{"deleted": [ids that existed], "missing": [ids that did not]}` |

A tool result is `{"content": [{"type": "text", "text": "<json.dumps(payload, ensure_ascii=False)>"}], "isError": <bool>}`;
the error cases above and bad arguments (`{"error": "bad_arguments", "detail": "<short text>"}`) have
`isError: true`. An unknown tool name or non-object `arguments` is the JSON-RPC error `-32602`.

### 3.6 The page (`board.html`)

`start()` keeps the fixture branch (`FIXTURE !== null` renders once and stops) and otherwise polls:

* `GET api/records` (relative URL, `cache: "no-store"`, `credentials: "same-origin"`) every
  `POLL_MS` milliseconds, once immediately. `POLL_MS` is 15000, or the integer from the query
  parameter `poll` when it is at least 500 (for tests).
* On success it calls `render(validEntries(body.records))`, but only when the JSON text of the
  records differs from the previous response or at least 60 seconds have passed since the last render
  (so relative times such as "3 min ago" stay fresh without collapsing what the reader opened).
* `render` rebuilds the DOM, so before it runs the page collects the `data-project` values of the
  `details[open]` rows and whether `details[data-section="hidden"]` is open, and reopens them after.
* On failure (network error, non-2xx) it keeps what is shown and calls `fail("Cannot reach the board
  server (<reason>). What is shown may be out of date.")` where `<reason>` is `HTTP <status>` or the
  error message. The next success removes the notice (`#status`) by re-rendering.
* No `claude.use`, no write call, no `<button>` (the existing `test_page_has_no_write_calls` keeps
  guarding that); the four markers `build_board.py` needs stay exactly once.

### 3.7 Client (`board_client.py`)

```python
class ConfigError(Exception): ...
class Config(NamedTuple): url: str; token: str
def load_config(env: Mapping[str, str] = os.environ) -> Config | None   # None when URL or token is unset/empty
def call(config: Config, method: str, path: str, body: object | None = None, timeout: float = 20.0) -> tuple[int, object | None]
```

`load_config` strips one trailing `/` from the URL and raises `ConfigError` when the URL has user
info, a query or a fragment, or is `http://` for a host other than `localhost`, `127.0.0.1`, `::1`
while `DEVFLOW_BOARD_ALLOW_HTTP` is not `1` (message: `DEVFLOW_BOARD_URL must be https (set DEVFLOW_BOARD_ALLOW_HTTP=1 to allow plain http)`).
`call` sends JSON with the bearer header and returns `(status, parsed JSON or None)`; HTTP error
statuses are returned, not raised; network errors raise `OSError`.

CLI: `board_client.py health | list | get ID | set ID FILE|- [--if-version N] | delete ID [ID ...]`.
Output is one line of compact JSON on stdout (`health` prints `ok`). Exit codes: 0 success; 1 the
server answered with an error status (its JSON body is printed on stdout and a one-line message on
stderr), a network error, or a `ConfigError`; 2 usage error; 3 no board configured (URL or token
unset; nothing on stdout, `board_client: no board configured` on stderr). `health` needs only the URL
(`GET /healthz`, no token); it exits 3 when the URL is unset.

### 3.8 Stdio bridge (`board_mcp_stdio.py`)

An MCP stdio server (newline-delimited JSON-RPC on stdin/stdout) that forwards to `POST /mcp`:

```python
def serve(stdin: TextIO, stdout: TextIO, config: Config | None, call: Callable = board_client.call) -> None
```

For each input line: parse JSON (an unparsable line is dropped with a note on stderr). With a `config`,
forward the message with `call(config, "POST", "/mcp", message)`: status 200 and a JSON object ->
write it as one line; status 202 -> write nothing; anything else, or `OSError`, for a request (has
`id`) -> write `{"jsonrpc": "2.0", "id": <id>, "error": {"code": -32000, "message": "board server: HTTP <status>"}}`
(or `... board server: <error class name>` for `OSError`). Without a `config`: answer locally,
`initialize` as in 3.5 (instructions: `"No devflow board is configured (DEVFLOW_BOARD_URL and DEVFLOW_BOARD_TOKEN are unset)."`),
`tools/list` -> `{"tools": []}`, `ping` -> `{}`, other requests -> `-32601`, notifications ignored.
`main` builds the config with `load_config()`; a `ConfigError` is printed to stderr and treated as no
config. Nothing but JSON lines goes to stdout. Exit 0 at end of input.

### 3.9 Plugin wiring (`plugins/devflow/.mcp.json`)

```json
{
  "mcpServers": {
    "devflow-board": {
      "command": "python3",
      "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/board_mcp_stdio.py"],
      "env": {
        "DEVFLOW_BOARD_URL": "${DEVFLOW_BOARD_URL:-}",
        "DEVFLOW_BOARD_TOKEN": "${DEVFLOW_BOARD_TOKEN:-}"
      }
    }
  }
}
```

The tools then appear as `mcp__plugin_devflow_devflow-board__board_get` (and `_list`, `_set`,
`_delete`); the skill says "whichever prefix the tool list shows".

### 3.10 Skill and command text

* `status-board/SKILL.md` keeps its six `##` headings in the same order (`Where the board is`,
  `Writing a record`, `When to write`, `Best effort`, `No secrets`, `Alerts`) and the whole Alerts
  section byte for byte; the other sections change as follows. Where the board is: the board is
  reached through the tools `board_get`, `board_list`, `board_set`, `board_delete` of the `devflow-board`
  MCP server when the tool list has them; when it has none and both `DEVFLOW_BOARD_URL` and
  `DEVFLOW_BOARD_TOKEN` are set, through `board_client.py` (same operations, found next to the
  `project-profile` skill's scripts); when neither works there is no board: skip every board step
  silently. Writing a record: `board_set` (or `board_client.py set ID - [--if-version N]` with the
  JSON on stdin) with the whole document and `if_version` set to the version last read; document id
  as before; the server validates, so on `invalid` fix the listed errors and retry once, on
  `version_conflict` re-read with `board_get`, merge the fields this session owns and retry once; a
  `version_conflict` on the very first write (no `if_version`) means a record of an earlier run
  exists: `board_get` it and write over it with its version. Best effort and No secrets: wording
  adapted ("the board is readable by everyone who has the read token or the write token" instead of
  "everyone who can open it").
* `commands/board.md`: front matter `description: Check the devflow status board connection, or prune the stale records from it`, `model: sonnet`, `argument-hint` kept. `/board` (no argument): locate the toolkit scripts with the
  `project-profile` skill's "Find the toolkit scripts" step (the profile is not loaded for anything else; the p7 brief gives the exact `## Profile` sentence the structure test needs);
  run `board_client.py health`; exit 3 -> print the setup text (the two variables and where the
  deployment document is: `docs/board-server.md` in the claude-toolkit repository) and stop; exit 1
  -> show stderr and stop; else report which write path this session has (the `board_*` tools, or
  `board_client.py` only), the number of records and how many need the owner (from `board_list`
  or `board_client.py list`), and the board URL (`DEVFLOW_BOARD_URL`, never the token). `/board prune`:
  needs a working board; list the records into a JSON file in the scratchpad directory (or `/tmp`);
  `board_stale.py FILE`; nothing printed -> "Nothing to prune"; else show each id with its
  `updated_at` and ask exactly one question (delete these n records? yes or no); on yes delete with
  `board_delete` (at most 50 ids per call) or `board_client.py delete ID...`; nothing else is ever
  deleted.

### 3.11 Docker and deployment document (p8)

`plugins/devflow/board/Dockerfile`, built with
`docker build -f plugins/devflow/board/Dockerfile -t devflow-board plugins/devflow`:

```dockerfile
FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home board && mkdir /data && chown board /data
WORKDIR /app
COPY scripts/board_server.py scripts/board_store.py scripts/board_mcp.py scripts/build_board.py scripts/validate_status_record.py /app/scripts/
COPY board/board.html board/rules.js /app/board/
ENV DEVFLOW_BOARD_DB=/data/board.sqlite3 PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8787
USER board
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=4).status == 200 else 1)"]
CMD ["python", "/app/scripts/board_server.py", "--host", "0.0.0.0", "--port", "8787"]
```

`docs/board-server.md` has these `##` sections in this order: `What it is`, `Run it locally`,
`Configuration`, `Docker`, `TLS and a reverse proxy`, `Connect Claude Code sessions`, `HTTP API`,
`MCP tools`, `Security notes`, `Backup and restore`, `Troubleshooting`, `Replacing the artifact board`.
Required content: the local run uses `DEVFLOW_BOARD_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"`
and a `curl` PUT of a sample record (a fenced `json` block of one valid run record, with doc id
`example-project`); the Configuration section has the table of 3.2 plus the flags of 3.4; the TLS
section gives a Caddy `reverse_proxy` example and says nginx needs the same (`proxy_pass`, a
`client_max_body_size 1m`); Connect: set `DEVFLOW_BOARD_URL` and `DEVFLOW_BOARD_TOKEN` in the cloud
environment's settings (the token as a secret value the owner types, never in chat), add the host
under the environment's allowed network domains, and note that the token must reach only the
environments that write; the page is opened in a browser with the read token as the password; HTTP
API and MCP tools are the tables of 3.4 and 3.5; Security notes: one write token, optional read
token, tokens of 24+ characters, no rate limiting (use a proxy), plain HTTP refused by the client
unless loopback, CSP, the database is not encrypted; Backup: `sqlite3 board.sqlite3 ".backup 'copy.sqlite3'"`
while running; Replacing: no migration (records are short-lived and rewritten on the next run), the
old page can be deleted from claude.ai, `status.board_url` is no longer read and a profile that
still has it fails validation with `unknown key 'status'`.

### 3.12 What was rejected

* **Keeping the artifact board** (or both): the point is to not depend on claude.ai.
* **A remote `type: http` entry in the plugin `.mcp.json` with `Authorization: Bearer ${DEVFLOW_BOARD_TOKEN}`**:
  the Claude Code documentation says credential variables in a remote server's `url` and `headers`
  are read as empty instead of expanded. A stdio bridge keeps the token inside a process we control
  and reads it with `os.environ`. The `/mcp` endpoint stays, so any client that can send the header
  can use the server directly (documented, not wired).
* **The `mcp` SDK, FastAPI, Flask**: the repository is stdlib-only; the MCP subset needed here
  (initialize, ping, tools/list, tools/call over JSON) is about 150 lines.
* **Server-sent events or WebSockets for the page**: records change a few times an hour; 15 s polling
  is enough and keeps the server stateless.
* **Per-project tokens, OAuth**: one write token and an optional read token; a status board for one
  owner does not need more.
* **Automatic expiry of old records on the server**: pruning stays a command that asks the owner once
  (`/board prune`), as before.
* **Migrating old records**: they are rewritten by the next run; copying them would need claude.ai.

## 4. ADRs

None (the profile has no `docs.adr_dir`). The decision is recorded in `docs/design.md` section 12 by
the last phase.

## 5. Manual steps

There is nothing the owner must do before the phases run: every phase builds and tests against a
local server. After the last merge there are three things only the owner can do: host the server,
put the two variables into the cloud environment and allow the host, and look at a real board with a
real session. Step by step page: see `manual_steps_artifact` in the manifest.

## 6. Risks and open questions

* **The plugin's stdio MCP server might not load in a scheduled (unattended) session.** The Claude Code
  docs do not say. That is why `board_client.py` exists and why the skill falls back to it. A worker
  never tests this; `ma3-first-board` does, in a real scheduled task.
* **`env` expansion in `.mcp.json`** (`${VAR:-}` for a stdio server) is documented for plugins' stdio
  servers; if a session shows the server connected but with no tools while the variables are set, the
  variables did not reach the bridge. Recognise it by `ma3`; the fix would be a documented change to
  the `.mcp.json`, not a workaround in the bridge.
* **The cloud container's network policy** blocks hosts that are not allowed, so `board_client.py`
  fails with a network error until `ma2-environment` is done. It is best effort by design: the run
  continues.
* **Breaking change**: a profile that still has `status:` fails validation. Phase p9 records it in
  `docs/design.md` and the plugin version goes to 0.7.0.
* **Brief stop conditions** are in the briefs: a worker that meets a different signature of
  `validate_status_record.validate`, a missing marker in `board.html`, or a different heading list in
  the skill stops with `status=blocked`.
* **Sockets in tests**: the server tests bind `127.0.0.1` port 0 in a thread. If the container
  forbids that, stop and report instead of mocking the server away.

## Implementation manifest

```yaml
plan_slug: board-server
feature_branch: feature/board-server
tracking_issue: 16
max_parallel: 2
manual_steps_artifact: https://claude.ai/artifact/Dn6Fn9kkxj5gu8wjg9zGJH
manual_steps_source: docs/board-server-plan-manual-steps.html
manual_after:
  - id: ma1-host-the-server
    title: Host the board server behind HTTPS
    why: Nothing in the pull request runs a server for you; the board is empty and unreachable until it is hosted
  - id: ma2-environment
    title: Give the cloud environment the board URL, the token and network access
    why: Sessions write to the board only when DEVFLOW_BOARD_URL and DEVFLOW_BOARD_TOKEN are set and the host is allowed
  - id: ma3-first-board
    title: Check the board with a real session and a real scheduled task
    why: CI cannot show that the plugin's MCP bridge loads in a cloud or unattended session, which is the one thing the plan could not verify
verify_after_merge:
  - .venv/bin/python -m pytest tests -q -k "board or status or alerts or profile"
final_checks:
  - docs/board-server-plan.md and docs/board-server-plan-manual-steps.html are deleted and nothing links to them
  - 'grep -rn "board_url\|capabilities: {db" plugins templates prints nothing except plugins/devflow/scripts/review_decisions.html and plugins/devflow/commands/review.md'
  - docs/board-server.md exists and README.md, docs/maintenance.md and docs/design.md link to it
phases:
  - id: p1-server-core
    title: Board server core (store, HTTP API, auth, page)
    depends_on: []
    complexity: M
    touches:
      - plugins/devflow/scripts/board_store.py
      - plugins/devflow/scripts/board_server.py
      - tests/test_board_store.py
      - tests/test_board_server.py
    brief: |
      Build the storage and HTTP half of the board server exactly as specified in Design 3.1 to 3.4.
      Read first: plugins/devflow/scripts/board_stale.py (script style), plugins/devflow/scripts/build_board.py
      (`build(title, fixture, now)`), plugins/devflow/scripts/validate_status_record.py (`validate(rec, doc_id)`).
      1. Create plugins/devflow/scripts/board_store.py following the conventions of Design 3.1 (it has no `main`;
         it is imported). After the standard imports: `sys.path.insert(0,
         str(Path(__file__).resolve().parent))`, then `import validate_status_record`. Define MAX_RECORD = 262144,
         ID_RE, `Conflict`, `Invalid` and `Store` with the exact rules of Design 3.3 (create the table in
         `__init__`, `PRAGMA journal_mode=WAL`, `json.dumps(data, ensure_ascii=False, separators=(",", ":"))`
         for storage).
      2. Create plugins/devflow/scripts/board_server.py following the conventions of Design 3.1. After the
         standard imports: the same `sys.path.insert` line, then `import build_board` and
         `from board_store import Conflict, Invalid, Store`. Define MAX_BODY = 1048576 and MIN_TOKEN = 24.
      3. Define `Tokens` (Design 3.4): `role()` parses `Bearer <t>` and `Basic <b64>` (decode, split on the first
         colon, the password is the token); compare with `hmac.compare_digest` over UTF-8 bytes; the write
         token is checked before the read token.
      4. Define the request handler class (subclass of `BaseHTTPRequestHandler`, `protocol_version = "HTTP/1.1"`;
         the HTTP/1.1 rules of Design 3.4 apply)
         with `do_GET`, `do_PUT`, `do_DELETE`, `do_POST`, and a helper that sends JSON or HTML with the standard
         headers of Design 3.4. Order inside every method: `/healthz` (GET only) first; then the role (401 when
         None); then route; then method check (405 with `Allow`); then the role required by the route (403).
         `do_POST` answers 405 on `/`, `/index.html`, `/api/records` and `/api/records/<id>` and 404 `not_found`
         everywhere else in this phase (the `/mcp` route is added in p2).
         Override `log_message` to print `board_server: <METHOD> <path without query> <status>` to stderr only.
         Read the request body only from `Content-Length` (reject > MAX_BODY with 413 before reading).
      5. Define `make_server(...)` and `main(...)` per Design 3.4, including the two token error messages and
         exit code 2. Build the page once with `build_board.build(title, None, None)`.
      6. Write tests/test_board_store.py with the Store tests below and tests/test_board_server.py with the HTTP
         tests. Seed with entries from tests/fixtures/board-records.json (all 13 are
         valid; use `f-running-ok`). Start the server with `make_server(Store(str(tmp_path / "b.sqlite3")),
         Tokens("w" * 24, "r" * 24), "T", "127.0.0.1", 0)` in a daemon thread and talk to it with
         `urllib.request`; shut it down in a fixture. Tests, with these exact names. In tests/test_board_store.py:
         test_store_set_creates_version_1, test_store_set_needs_matching_if_version,
         test_store_set_without_if_version_conflicts_when_the_record_exists, test_store_rejects_an_invalid_record,
         test_store_rejects_a_bad_id, test_store_rejects_an_oversized_record, test_store_delete,
         test_store_persists_across_reopen, test_store_two_threads_cannot_both_create. In tests/test_board_server.py:
         test_healthz_needs_no_token, test_api_requires_a_token,
         test_bearer_and_basic_both_work, test_read_token_reads_but_cannot_write, test_put_get_list_delete_roundtrip,
         test_put_conflict_returns_409_with_the_current_record, test_put_invalid_returns_422_with_errors,
         test_page_is_served_with_security_headers, test_unknown_route_is_401_without_a_token_and_404_with_one,
         test_wrong_method_is_405 (POST /api/records), test_if_version_true_is_400, test_responses_have_content_length,
         test_oversized_body_is_413, test_main_refuses_a_missing_or_short_token,
         test_main_refuses_a_read_token_equal_to_the_write_token.
      Stop with status=blocked if `validate_status_record.validate` does not take `(rec, doc_id)` and return a
      list of strings, or if `build_board.build` does not take `(title, fixture, now)`.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_store.py tests/test_board_server.py -q passes
      - .venv/bin/python plugins/devflow/scripts/board_server.py --port 0 exits 2 and prints a message starting `board_server: DEVFLOW_BOARD_TOKEN` when the variable is unset
      - grep -n "claude" plugins/devflow/scripts/board_server.py prints nothing
      - .venv/bin/python -m pytest tests/test_no_project_words.py -q passes
  - id: p2-mcp-endpoint
    title: MCP endpoint (POST /mcp) with the four board tools
    depends_on: [p1-server-core]
    complexity: M
    touches:
      - plugins/devflow/scripts/board_mcp.py
      - plugins/devflow/scripts/board_server.py
      - tests/test_board_mcp.py
    brief: |
      Add the MCP half exactly as specified in Design 3.5.
      1. Create plugins/devflow/scripts/board_mcp.py (conventions of Design 3.1) with `PROTOCOLS`, a module-level
         `TOOLS` list (name, description in one sentence, inputSchema, exactly as the table in 3.5) and
         `handle(store, message)`. `from board_store import Conflict, Invalid, Store` after the same
         `sys.path.insert` line as board_server.py (board_mcp never imports board_server). Implement `initialize`, `ping`, `tools/list`, `tools/call`,
         notifications (return None), the JSON-RPC errors -32601 and -32602, and the tool result envelope. Map
         `Conflict` and `Invalid` from `Store.set` to the `isError` payloads of 3.5; `board_delete` calls
         `Store.delete` per id and fills `deleted` and `missing`; validate arguments by hand (types, 1 to 50
         ids) and answer `bad_arguments` with a short `detail`.
      2. In plugins/devflow/scripts/board_server.py replace the `do_POST` 404 with the `/mcp` route: write role
         required (401/403 as before), `Origin` check against `server.allow_origins`, `Content-Length` limit,
         JSON parse (-32700 on failure, HTTP 400), a JSON array is -32600 with HTTP 400, then
         `board_mcp.handle(self.server.store, message)` (add `import board_mcp` at the top of board_server.py); `None` ->
         202 with `Content-Length: 0`; otherwise 200 JSON. `GET`, `PUT` and `DELETE` on `/mcp` answer 405 with
         `Allow: POST`.
      3. Write tests/test_board_mcp.py: unit tests of `handle` against a `Store` in tmp_path, and HTTP tests with
         the server fixture pattern of tests/test_board_server.py (copy the fixture; do not edit that file).
         Test names: test_initialize_echoes_a_supported_protocol, test_initialize_falls_back_to_the_newest,
         test_tools_list_has_the_four_tools, test_board_set_then_get_then_list, test_board_set_conflict_is_an_error_result,
         test_board_set_invalid_is_an_error_result, test_board_set_first_write_conflicts_when_the_record_exists,
         test_board_delete_reports_deleted_and_missing, test_board_delete_rejects_more_than_50_ids,
         test_unknown_tool_is_32602, test_unknown_method_is_32601, test_notification_gets_202_and_no_body,
         test_batch_is_rejected_with_400, test_non_json_is_32700, test_mcp_requires_the_write_token,
         test_mcp_get_is_405, test_origin_header_is_refused_unless_allowed, and test_script_run_reports_a_conflict:
         start `python plugins/devflow/scripts/board_server.py --port 0` with `subprocess.Popen` (env has a 24+
         character `DEVFLOW_BOARD_TOKEN`), read the port from the stderr line `board_server: listening on http://127.0.0.1:<port>`,
         POST two `tools/call` `board_set` requests for the same valid record without `if_version`, and assert the second result
         has `isError` true and `version_conflict` in its text (this guards the script-run path, not the module path); terminate the process in a finally block.
      Stop with status=blocked if p1's `do_POST` or `make_server` differ from Design 3.4 in a way that makes
      this impossible to add without redesign, or if board_store.py is missing.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_mcp.py tests/test_board_server.py -q passes
      - .venv/bin/python -m pytest tests/test_no_project_words.py -q passes
  - id: p3-page-polling
    title: Board page polls the API instead of the artifact database
    depends_on: [p1-server-core]
    complexity: S
    touches:
      - plugins/devflow/board/board.html
      - tests/test_board_page.py
      - tests/board_poll_check.js
    brief: |
      Change only how board.html gets its data, exactly as specified in Design 3.6.
      1. In plugins/devflow/board/board.html replace the body of `start()` (currently `board.html:340-353`, the
         `claude.use("db")` block with its 10-second timer) with the polling described in 3.6. Add the helper
         functions `load()` and `restoreOpen(openKeys)` next to `fail()` and keep `render()`, `validEntries()`,
         `fail()` and the fixture branch as they are; the `FIXTURE !== null` branch must still render once and
         return before any polling or `location` code runs (tests/board_render_check.js opens the page as a
         file). Keep the open keys in a plain array: the text `.set(`, `.update(` or `.delete(` must not occur
         anywhere in board.html (tests/test_board.py `test_page_has_no_write_calls` greps for it), so no
         `Map`/`Set` mutation methods and no `URLSearchParams.set`. The four markers (`<!--DEVFLOW:TITLE-->`,
         `/*DEVFLOW:RULES*/`, `/*DEVFLOW:FIXTURE*/null`, `/*DEVFLOW:NOW*/null`) stay exactly once.
      2. Write tests/test_board_page.py (plain-text tests of the built page): test_page_has_no_claude_runtime
         (`claude.use` and `onSnapshot` are absent), test_page_polls_the_records_api (contains `api/records`),
         test_page_keeps_the_markers_the_builder_needs (build via `build_board.build("T", None, None)` does not
         raise), test_page_poll_interval_has_a_floor (contains `500` and `15000`), and test_poll_in_a_browser:
         skip when `node` or `require('playwright')` is missing (copy the skip logic of tests/test_board.py), start
         the server from tests/test_board_server.py's pattern (import `board_server`, `make_server` on port 0
         in a thread, seed `f-running-ok` from tests/fixtures/board-records.json with `updated_at` set to the
         current UTC time in `YYYY-MM-DDTHH:MM:SSZ` form, because the fixture's dates are old and the page
         hides a record not updated for 7 days, and `next_check_at` set to null), run
         `node tests/board_poll_check.js <base url> <write token>` and assert stdout is `OK`.
      3. Write tests/board_poll_check.js (pattern of tests/board_render_check.js): launch Chromium with
         `httpCredentials: {username: "x", password: <token>}`, open `<base>/?poll=500`, wait for
         `[data-project="f-running-ok"]`; then `fetch` a `PUT <base>/api/records/f-waiting` with the bearer token
         and body `{"data": <that fixture record with updated_at set to now and needs_you_since set to now>}` from
         inside the Node process (global `fetch`), and wait (max 5 s) for `[data-project="f-waiting"]` to appear
         without a reload; then open the `f-running-ok` row, PUT `f-waiting` again with `last_event` changed to
         `changed`, wait for that text to show (so a render has really happened), and assert the `f-running-ok`
         row is still open; fail on any console error; print `OK`.
      Stop with status=blocked if a marker is missing from board.html, if row elements no longer carry
      `data-project`, or if `render()` no longer takes a list of `{id, data}`.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_page.py tests/test_board.py -q passes
      - grep -c "claude.use" plugins/devflow/board/board.html prints 0
      - .venv/bin/python -m pytest tests/test_board.py -q passes (it runs tests/board_render_check.js when Playwright is available)
  - id: p4-client
    title: board_client.py, the command-line client
    depends_on: [p1-server-core]
    complexity: S
    touches:
      - plugins/devflow/scripts/board_client.py
      - tests/test_board_client.py
    brief: |
      Build the client exactly as specified in Design 3.7.
      1. Create plugins/devflow/scripts/board_client.py (conventions of Design 3.1) with `ConfigError`, `Config`,
         `load_config`, `call` and `main` (argparse sub-commands `health`, `list`, `get`, `set`, `delete`). Use
         `urllib.request` with an explicit `Request`, `Authorization: Bearer`, `Content-Type: application/json`,
         and catch `urllib.error.HTTPError` to return `(e.code, parsed body or None)`.
         Add `load_url(env) -> str | None` (the URL checks of Design 3.7 without the token) and make
         `load_config` use it. `health` uses `load_url` and sends no `Authorization` header (give `call` an
         optional parameter `auth: bool = True`; `Config` may then hold an empty token).
         Paths: list = `GET /api/records`, get = `GET /api/records/<id>`, set = `PUT /api/records/<id>` with
         `{"data": <doc>, "if_version": N}` (omit the key without `--if-version`), delete = one
         `DELETE /api/records/<id>` per id, printing one line `{"deleted": [...], "missing": [...]}` (a 404 puts the id
         in `missing`) and exiting 0 when every answer was 200 or 404, else 1; health = `GET /healthz`.
      2. Exit codes and output as in 3.7; `set` reads the JSON document from FILE or from stdin for `-`.
      3. Write tests/test_board_client.py with the server fixture pattern of tests/test_board_server.py (copy
         it; do not edit that file), run the CLI through `subprocess.run([sys.executable, SCRIPT, ...], env=...)`.
         Tests: test_load_config_none_when_unset, test_load_config_strips_trailing_slash,
         test_load_config_refuses_plain_http_for_a_remote_host, test_load_config_allows_loopback_http,
         test_load_config_allows_http_with_the_override, test_load_config_refuses_userinfo,
         test_cli_exit_3_without_configuration, test_cli_health, test_cli_set_get_list_delete, test_cli_set_conflict_exits_1_and_prints_the_body,
         test_cli_set_invalid_exits_1, test_cli_wrong_token_exits_1, test_cli_delete_reports_missing, test_cli_health_sends_no_token.
      Stop with status=blocked if the server's routes differ from Design 3.4.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_client.py -q passes
      - .venv/bin/python plugins/devflow/scripts/board_client.py list exits 3 with DEVFLOW_BOARD_URL unset
      - .venv/bin/python -m pytest tests/test_no_project_words.py -q passes
  - id: p5-profile-key-removal
    title: Remove the status.board_url profile key
    depends_on: []
    complexity: S
    touches:
      - plugins/devflow/schema/profile.schema.json
      - plugins/devflow/skills/project-profile/SKILL.md
      - docs/profile-reference.md
      - templates/toolkit.yaml
      - tests/test_status_board.py
    brief: |
      1. In plugins/devflow/schema/profile.schema.json delete the whole `"status"` property (currently lines
         130-134) and keep the JSON valid (mind the comma after the previous property).
      2. In plugins/devflow/skills/project-profile/SKILL.md delete the table row that starts with
         `| \`status.board_url\``. In docs/profile-reference.md delete the row that starts with
         `| \`status.board_url\``. In templates/toolkit.yaml delete the two commented lines that start with
         `# status:` and `#   board_url:` and the blank line that follows them, keeping one blank line
         between the neighbouring blocks.
      3. In tests/test_status_board.py replace `test_profile_schema_has_status_board_url` with
         `test_profile_schema_has_no_status_key` (asserts `"status"` is not in `schema["properties"]`) and add
         `test_profile_with_the_old_status_key_is_rejected`: write a copy of `.claude/toolkit.yaml` plus
         `status:\n  board_url: https://example.org/x\n` to tmp_path and run
         `plugins/devflow/scripts/validate_profile.py <file>` with `subprocess.run`; assert exit code 1 and
         `unknown key 'status'` in stderr. Leave the other two tests in that file unchanged.
      Stop with status=blocked if `test_every_profile_key_in_the_schema_is_documented` in tests/test_structure.py
      still fails after step 2 (both the schema property and the documentation row must be gone together).
    acceptance:
      - .venv/bin/python -m pytest tests/test_status_board.py tests/test_validate_profile.py tests/test_structure.py -q passes
      - grep -n "board_url" plugins/devflow/schema/profile.schema.json plugins/devflow/skills/project-profile/SKILL.md docs/profile-reference.md templates/toolkit.yaml prints nothing
      - .venv/bin/python plugins/devflow/scripts/validate_profile.py templates/toolkit.yaml --no-file-checks prints a line starting `toolkit.yaml: OK`
  - id: p6-stdio-bridge
    title: Stdio MCP bridge for the plugin
    depends_on: [p2-mcp-endpoint, p4-client]
    complexity: S
    touches:
      - plugins/devflow/scripts/board_mcp_stdio.py
      - tests/test_board_mcp_stdio.py
    brief: |
      Build the bridge exactly as specified in Design 3.8.
      1. Create plugins/devflow/scripts/board_mcp_stdio.py (conventions of Design 3.1) with `serve` and `main`.
         Import `board_client` after the same `sys.path.insert` line as the other scripts. The local answers for
         the no-configuration case reuse `board_mcp.PROTOCOLS` for the protocol negotiation (import `board_mcp`).
         Flush stdout after every line written.
      2. Write tests/test_board_mcp_stdio.py. Unit tests call `serve(io.StringIO(...), out, config, call=fake)`
         with a fake `call`; one process test starts the real server (pattern of tests/test_board_server.py,
         copied) and runs `python board_mcp_stdio.py` with `subprocess.Popen`, `DEVFLOW_BOARD_URL` and
         `DEVFLOW_BOARD_TOKEN` in `env`, writes initialize, notifications/initialized, tools/list and a
         tools/call board_set line, and reads the replies. Tests: test_forwards_a_request_and_writes_the_reply,
         test_notification_writes_nothing, test_http_error_becomes_a_jsonrpc_error, test_oserror_becomes_a_jsonrpc_error,
         test_without_config_initialize_and_empty_tool_list, test_without_config_other_methods_are_32601,
         test_unparsable_line_is_dropped, test_stdout_has_only_json_lines, test_end_to_end_with_the_real_server,
         test_config_error_is_treated_as_no_config.
      Stop with status=blocked if `POST /mcp` of the server does not behave as Design 3.5.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_mcp_stdio.py -q passes
      - .venv/bin/python -m pytest tests/test_no_project_words.py -q passes
  - id: p7-plugin-wiring
    title: Plugin .mcp.json, status-board skill and /board command
    depends_on: [p4-client, p6-stdio-bridge]
    complexity: M
    touches:
      - plugins/devflow/.mcp.json
      - plugins/devflow/skills/status-board/SKILL.md
      - plugins/devflow/commands/board.md
      - plugins/devflow/commands/deps.md
      - tests/test_board.py
      - tests/test_board_wiring.py
    brief: |
      Wire the board into the plugin as specified in Design 3.9 and 3.10.
      1. Create plugins/devflow/.mcp.json with exactly the JSON of Design 3.9.
      2. Rewrite plugins/devflow/skills/status-board/SKILL.md per Design 3.10. Keep the front matter `name:` and
         `user-invocable: false`, update the `description:` to say "where the board is (the board_* tools or
         board_client.py)". Keep the six `##` headings in the same order and keep the `## Alerts` section
         byte for byte (copy it from git: `git show HEAD:plugins/devflow/skills/status-board/SKILL.md`). Remove every
         mention of `ArtifactData`, `status.board_url` and `validate_status_record.py -` from the other sections.
      3. Rewrite plugins/devflow/commands/board.md per Design 3.10 (front matter changes as written there; the
         body keeps the "Skill names carry a plugin prefix" sentence and the "Find the toolkit scripts" reference).
         It must contain the strings `board_client.py health`, `board_stale.py`, `board_delete`, `board_list`,
         `DEVFLOW_BOARD_URL`, `DEVFLOW_BOARD_TOKEN`, `docs/board-server.md`. Set `argument-hint: "[empty to check the board | prune]"`.
         tests/test_structure.py requires every command to contain `project-profile` and the words `never substitute`,
         so keep a `## Profile` paragraph with this sentence: "Use the `project-profile` skill only for its
         'Find the toolkit scripts' step; if it reports an error, show the message verbatim and stop; never substitute
         a path of your own." For prune, the file handed to `board_stale.py` holds the value of `records` (the
         array), not the whole answer, because the script reads a list of `{id, data}`; the command text says so.
         If `health` succeeds but `board_client.py list` exits 3 (URL set, token unset), `/board` prints "DEVFLOW_BOARD_URL
         is set but DEVFLOW_BOARD_TOKEN is not" and stops.
      4. In plugins/devflow/commands/deps.md line 92 change "validate before each write" to "write with the version
         last read" (the skill no longer validates locally). In tests/test_board.py replace the needles of
         `test_board_command_names_its_keys` with the seven strings of step 3; leave the other tests of that file unchanged.
      5. Create tests/test_board_wiring.py: test_mcp_json_declares_the_bridge (parse the JSON, check command,
         args, the two env keys and that the args point at a file that exists under plugins/devflow/scripts),
         test_mcp_json_has_no_remote_url_or_literal_token, test_skill_names_the_tools_and_the_client,
         test_skill_has_no_artifact_words (no `ArtifactData`, `status.board_url`, `claude.ai/artifact`),
         test_skill_alerts_table_has_five_rows (count the lines of the Alerts table that start with `| ` after the
         header and separator rows: 5),
         test_board_command_has_no_artifact_publishing (the text has no `capabilities`, no `icon` and no `Artifact`).
      Stop with status=blocked if tests/test_status_board.py or tests/test_alerts.py need an edit to pass.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_wiring.py tests/test_board.py tests/test_status_board.py tests/test_alerts.py tests/test_structure.py tests/test_deps.py -q passes
      - grep -rn "ArtifactData" plugins/devflow/skills plugins/devflow/commands/board.md prints nothing
      - .venv/bin/python -c "import json; json.load(open('plugins/devflow/.mcp.json'))" exits 0
      - claude plugin validate plugins/devflow exits 0
  - id: p8-deploy
    title: Dockerfile and deployment document
    depends_on: [p3-page-polling, p6-stdio-bridge]
    complexity: M
    touches:
      - plugins/devflow/board/Dockerfile
      - docs/board-server.md
      - tests/test_board_deploy.py
    brief: |
      Write the Dockerfile exactly as in Design 3.11 and the document with the sections and required
      content listed there (headings exactly as listed, in that order).
      1. Create plugins/devflow/board/Dockerfile with the text in Design 3.11.
      2. Create docs/board-server.md. Take the HTTP and MCP tables from Design 3.4 and 3.5, the variables
         from 3.2, the sample record from the `f-running-ok` entry of tests/fixtures/board-records.json with
         `project` and `repo` changed to `example-project` and `example/example-project` (it must still pass
         `validate_status_record.py - --doc-id example-project`). Explain secrets as in the Design: the owner
         types the token into the environment settings; never write a real token anywhere.
      3. Create tests/test_board_deploy.py: test_dockerfile_basics (FROM python, non-root USER, EXPOSE 8787,
         VOLUME /data, HEALTHCHECK, CMD names board_server.py), test_dockerfile_copies_every_sibling_module
         (start from board_server.py and follow imports recursively with `ast`; every imported module that exists as
         plugins/devflow/scripts/<name>.py, including those imported inside functions, is on the COPY line),
         test_dockerfile_copies_the_page_files, test_doc_has_the_sections_in_order, test_doc_names_every_variable_and_route_and_tool,
         test_doc_sample_record_is_valid (extract the first fenced json block, run validate_status_record
         `validate(rec, "example-project")`), test_doc_has_no_token_looking_value (no run of 32+ chars of
         [A-Za-z0-9_-] in the whole doc; so the doc names only the bare tool names `board_get` and so on, never the
         `mcp__plugin_..` prefixed form).
      No phase runs `docker build` (the container has no Docker); `ma1-host-the-server` builds the image for real.
      Stop with status=blocked if the server imports a module that Design 3.11 does not copy.
    acceptance:
      - .venv/bin/python -m pytest tests/test_board_deploy.py -q passes
      - grep -c "^## " docs/board-server.md prints 12
  - id: p9-retire
    title: Documentation, version bump and plan retirement
    depends_on: [p5-profile-key-removal, p7-plugin-wiring, p8-deploy]
    complexity: S
    touches:
      - README.md
      - docs/design.md
      - docs/maintenance.md
      - plugins/devflow/.claude-plugin/plugin.json
      - plugins/stack-go/.claude-plugin/plugin.json
      - plugins/stack-ipados/.claude-plugin/plugin.json
      - plugins/stack-python/.claude-plugin/plugin.json
      - plugins/stack-swift/.claude-plugin/plugin.json
      - docs/board-server-plan.md
      - docs/board-server-plan-manual-steps.html
    brief: |
      1. README.md: replace the `/board [prune]` bullet (lines 21-23) with: `/board` checks the connection to your
         self-hosted status board (a small Python server you run, see docs/board-server.md), and `/board prune`
         deletes the stale records after you confirm. In the `plugins/devflow` table row add `board_server.py`,
         `board_mcp.py`, `board_client.py`, `board_mcp_stdio.py` to the script list and `.mcp.json`.
      2. docs/maintenance.md: rewrite the `## The board` section (from its heading to the line before
         `## What /land needs from GitHub`): the board is the server of docs/board-server.md; the two
         variables; `/board` checks, `/board prune` prunes; keep the paragraph about the `drift <n>` chip and the
         scope-drift link. Update line 83's mention of `DEVFLOW_BOARD_URL` to "the variables DEVFLOW_BOARD_URL and
         DEVFLOW_BOARD_TOKEN (see the next section)".
      3. docs/design.md: in the layout block add the four scripts, `.mcp.json` and `board/Dockerfile`, and change
         the `board/` comment to "the status board page (board.html, rules.js) and its Dockerfile"; change the
         line `* **board**: publishes the status board page once; ...` to "checks the connection to the board;
         `/board prune` deletes stale records after one confirmation"; in section 10 replace the two lines "`/board` publishes a status board, one private" and "page that reads
         the status records every session writes through the `status-board` skill (format:" with "`/board` checks the
         connection to the status board, a server that holds the status records every session writes through the
         `status-board` skill (format:" and leave the following line as it is; append
         `## 12. A self-hosted status board` with: why (the Artifact board needed claude.ai), what was built
         (Design 3.1 to 3.10 in 10 lines), what was rejected (Design 3.12, one bullet each), and the breaking
         change (`status.board_url` removed; a profile that still has `status:` fails validation).
      4. Set `"version": "0.7.0"` in all five plugin.json files (devflow, stack-go, stack-ipados, stack-python,
         stack-swift); tests/test_structure.py `test_plugin_versions_agree` requires one common version.
      5. Delete docs/board-server-plan.md and docs/board-server-plan-manual-steps.html with `git rm`.
    acceptance:
      - grep -rn "board-server-plan" . --exclude-dir=.git --exclude-dir=.venv prints nothing
      - grep -c "0.7.0" plugins/devflow/.claude-plugin/plugin.json plugins/stack-go/.claude-plugin/plugin.json plugins/stack-ipados/.claude-plugin/plugin.json plugins/stack-python/.claude-plugin/plugin.json plugins/stack-swift/.claude-plugin/plugin.json prints 1 for each file
      - grep -n "board-server.md" README.md docs/maintenance.md docs/design.md matches in all three files
      - .venv/bin/python -m pytest tests -q passes
```
