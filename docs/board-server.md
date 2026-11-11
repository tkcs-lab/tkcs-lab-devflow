# The status board server

## What it is

The devflow status board is a small Python server you host yourself. Sessions that run `/implement`, `/deps`, `/upstream` and `/land` write short status records to it; you open the board in a browser to see which runs are going, which wait for you, and which are stale. It replaces the earlier board that lived on claude.ai.

* `board_server.py` stores the records in SQLite, serves the board page, offers a JSON API with optimistic `if_version` concurrency, and exposes the same operations as an MCP endpoint (`POST /mcp`).
* `board_mcp_stdio.py` is a stdio bridge that the devflow plugin declares in its `.mcp.json`; it gives every session the tools `board_get`, `board_list`, `board_set` and `board_delete`.
* `board_client.py` is a command-line client, the fallback write path for sessions where the plugin's MCP server is not loaded.

The server uses only the Python standard library (3.11 or newer). It speaks plain HTTP; TLS is the job of a reverse proxy (see below).

## Run it locally

From a checkout of the claude-toolkit repository:

```bash
export DEVFLOW_BOARD_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 plugins/devflow/scripts/board_server.py --port 8787
```

The server prints `board_server: listening on http://127.0.0.1:8787` and keeps running. In a second terminal, with the same variable set, write a sample record. First save this record as `record.json`:

```json
{
  "schema": 1,
  "kind": "run",
  "command": null,
  "project": "example-project",
  "repo": "example/example-project",
  "plan_slug": "plan-example-project",
  "plan_url": "https://example.com/example/example-project/blob/plan/docs/plan.md",
  "feature_branch": "feature/plan-example-project",
  "orchestrator_session": "session_example-project",
  "status": "running",
  "needs_you": false,
  "needs_you_reason": "",
  "needs_you_since": null,
  "phases": [
    {
      "id": "p0",
      "title": "Phase zero",
      "depends_on": [],
      "complexity": "S",
      "state": "merged",
      "session": null,
      "branch": null,
      "started_at": null,
      "finished_at": null,
      "scope": {
        "check": "ok",
        "in_scope": 4,
        "out_of_scope_count": 3,
        "collision_count": 1,
        "paths": [
          "src/shared.py",
          "docs/a.md",
          "docs/b.md"
        ],
        "disposition": "accepted"
      }
    },
    {
      "id": "p1",
      "title": "Phase one",
      "depends_on": [
        "p0"
      ],
      "complexity": "S",
      "state": "running",
      "session": null,
      "branch": null,
      "started_at": null,
      "finished_at": null
    }
  ],
  "pr": {
    "number": null,
    "url": null,
    "state": null,
    "ci": null,
    "awaiting": null
  },
  "last_event": "running",
  "next_check_at": "2026-11-09T12:15:00Z",
  "finished_at": null,
  "updated_at": "2026-11-09T11:58:00Z"
}
```

Then send it (the body wraps the record in `data`; leave out `if_version` for the first write):

```bash
(printf '{"data": '; cat record.json; printf '}') | curl -sS -X PUT \
  -H "Authorization: Bearer $DEVFLOW_BOARD_TOKEN" -H "Content-Type: application/json" \
  --data-binary @- http://127.0.0.1:8787/api/records/example-project
```

The answer is `{"id": "example-project", "version": 1}`. Open `http://127.0.0.1:8787/` in a browser; when it asks for a password, type the token (the user name is ignored).

## Configuration

Environment variables:

| Variable | Used by | Meaning |
|---|---|---|
| `DEVFLOW_BOARD_TOKEN` | server, client, bridge | The write token. Server: required, at least 24 characters. Client and bridge: sent as `Authorization: Bearer <token>`. |
| `DEVFLOW_BOARD_READ_TOKEN` | server | Optional second token that may only read (for browsers). Must differ from the write token. |
| `DEVFLOW_BOARD_URL` | client, bridge | Base URL of the server, for example `https://board.example.org`. Not a secret. |
| `DEVFLOW_BOARD_DB` | server | Default for `--db`. |
| `DEVFLOW_BOARD_ALLOW_HTTP` | client, bridge | `1` allows a plain `http://` URL for a non-loopback host. |

If `DEVFLOW_BOARD_URL` or `DEVFLOW_BOARD_TOKEN` is unset, sessions skip every board step silently.

Server flags (tokens come from the environment only):

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Address to bind. |
| `--port` | `8787` | Port to bind; `0` picks a free port. |
| `--db` | `$DEVFLOW_BOARD_DB`, else `board.sqlite3` | SQLite file. |
| `--title` | `Devflow Board` | Title of the page. |
| `--allow-origin` | none | An `Origin` that may call `POST /mcp`; repeatable. Clients that are not browsers send no `Origin`. |

## Docker

Build from the repository root (the image holds only the server, its modules and the page):

```bash
docker build -f plugins/devflow/board/Dockerfile -t devflow-board plugins/devflow
```

Run it with a volume for the database:

```bash
docker run -d --name devflow-board --restart unless-stopped \
  -p 127.0.0.1:8787:8787 -v devflow-board-data:/data \
  -e DEVFLOW_BOARD_TOKEN -e DEVFLOW_BOARD_READ_TOKEN devflow-board
```

`-e NAME` without a value passes the variable from your shell, so the token never appears in the command line. The container runs as an unprivileged user, keeps the database in `/data/board.sqlite3`, and has a health check on `/healthz`.

## TLS and a reverse proxy

Put the container behind a reverse proxy that terminates TLS. With Caddy:

```
board.example.org {
    reverse_proxy 127.0.0.1:8787
}
```

nginx needs the same: a `proxy_pass` to `http://127.0.0.1:8787`, TLS on the server block, and `client_max_body_size 1m;` (the server refuses bodies over 1 MiB anyway). Do not publish port 8787 itself.

## Connect Claude Code sessions

1. Set `DEVFLOW_BOARD_URL` (the https address of the proxy) and `DEVFLOW_BOARD_TOKEN` in the cloud environment's settings. The token is a secret value: you type it into the settings form yourself, never into a chat.
2. Add the host of the board under the environment's allowed network domains; without it every board call fails with a network error and the run continues without a board.
3. The write token must reach only the environments that write. Anyone who holds it can change every record.
4. Run `/board` once in a session. It checks the connection and reports which write path the session has.
5. Open the page in a browser at the board URL and use the read token (or the write token) as the password.

## HTTP API

`/healthz` needs no token. Everything else needs `Authorization: Bearer <token>` or a Basic password that is the token; a read token may only read.

| Request | Role | Success | Errors |
|---|---|---|---|
| `GET /healthz` | none | 200 `{"ok": true}` | |
| `GET /` and `GET /index.html` | read | 200 `text/html; charset=utf-8`, the page | |
| `GET /api/records` | read | 200 `{"records": [{"id", "version", "data"}, ...]}` | |
| `GET /api/records/<id>` | read | 200 `{"id", "version", "data"}` | 404 `not_found` |
| `PUT /api/records/<id>` | write | 200 `{"id", "version"}`; body `{"data": {...}, "if_version": 3}` (`if_version` optional, integer >= 1 or null) | 400 `bad_request`, 409 `version_conflict` (`current` holds the stored record or null), 422 `invalid` (`errors` holds the list) |
| `DELETE /api/records/<id>` | write | 200 `{"deleted": true}` | 404 `not_found` |
| `POST /mcp` | write | JSON-RPC answer, see the next section | |

A write without `if_version` creates the record and conflicts when it exists; with `if_version` it succeeds only when the stored version equals it. A known path with the wrong method is 405 with `Allow`. Other errors are `{"error": "<code>"}`: 401 `unauthorized`, 403 `forbidden` (a read token on a write route), 404 `not_found`, 405 `method_not_allowed`, 413 `payload_too_large` (body over 1048576 bytes).

## MCP tools

`POST /mcp` is a stateless streamable-HTTP MCP endpoint: one JSON-RPC object per request, answered as `application/json`. It supports `initialize`, `ping`, `tools/list` and `tools/call`. A notification gets 202 with an empty body; a batch gets 400. The plugin reaches it through the stdio bridge, because credential variables in a remote server's headers are not expanded in a plugin's `.mcp.json`; any other client that can send the `Authorization` header may call it directly.

| Tool | Arguments | Result text (JSON) |
|---|---|---|
| `board_list` | none | `{"records": [{"id", "version", "data"}, ...]}` |
| `board_get` | `id` (string) | the record `{"id", "version", "data"}`; error `{"error": "not_found"}` |
| `board_set` | `id` (string), `data` (object), `if_version` (integer >= 1, optional) | `{"id", "version"}`; errors `{"error": "version_conflict", "current": <record or null>}` and `{"error": "invalid", "errors": [...]}` |
| `board_delete` | `ids` (array of 1 to 50 strings) | `{"deleted": [ids that existed], "missing": [ids that did not]}` |

Errors come back as a tool result with `isError` true. The tools appear in a session under the `devflow-board` server; use whichever prefix the tool list shows.

## Security notes

* One write token and an optional read token; both need 24 or more characters. Generate them with `secrets.token_urlsafe(32)`.
* There is no rate limiting. Put the server behind a proxy that limits requests.
* The client and the bridge refuse a plain `http://` URL unless the host is loopback (or `DEVFLOW_BOARD_ALLOW_HTTP=1`).
* The page is served with a Content-Security-Policy that allows only its own inline script and style and requests to its own origin, and with `X-Frame-Options: DENY`.
* Records must not contain secrets; anyone with the read token can read all of them.
* The SQLite file is not encrypted. Protect the volume.

## Backup and restore

While the server runs, make a consistent copy with SQLite's online backup:

```bash
sqlite3 board.sqlite3 ".backup 'copy.sqlite3'"
```

To restore, stop the server, put the copy at the path given by `--db` (inside the container, `/data/board.sqlite3`), and start it again. Records are short-lived and rewritten by the next run, so a stale backup costs little.

## Troubleshooting

* **401 in the browser, again and again**: the password is wrong; type the token, not the user name.
* **`/board` says no board is configured**: `DEVFLOW_BOARD_URL` or `DEVFLOW_BOARD_TOKEN` is unset in that environment.
* **Network error from a cloud session**: the host is missing from the environment's allowed network domains.
* **`DEVFLOW_BOARD_URL must be https`**: the URL is plain `http://` for a remote host; use TLS.
* **409 `version_conflict`**: another session wrote first; read the record again, merge your fields, retry once.
* **422 `invalid`**: the record does not match the status-record format; the `errors` list names the fields.
* **The board shows "Cannot reach the board server"**: the page keeps what it has and retries every 15 seconds; check the proxy and the container (`docker logs devflow-board`).
* **The server will not start**: it prints which token is missing, too short, or equal to the other.

## Replacing the artifact board

There is no migration: records are short-lived and rewritten by the next run, and copying the old ones would need claude.ai. The old board page can be deleted from claude.ai. The profile key `status.board_url` is no longer read, and a profile that still has it fails validation with `unknown key 'status'`; remove the `status:` block from `.claude/toolkit.yaml`.
