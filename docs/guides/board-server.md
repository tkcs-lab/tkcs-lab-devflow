# The board server

## What it is

The tld board is a small Python server you host yourself. It is the owner's inbox (decisions D7, D8): every
session writes a short **status record** of its run to it, and every question a playbook has for you (review
decisions, the manual steps before an implementation, confirmations) arrives as an **ask**. You log in on its
page, see what needs you first, answer the asks in the browser, and watch the runs. It replaces the earlier
board and the decision pages that lived on claude.ai.

* `tld board server` stores records and asks in SQLite, serves the page, offers a JSON API and the same
  operations as an MCP endpoint (`POST /mcp`).
* `tld board mcp-stdio` is the stdio bridge the tld plugin declares in its `.mcp.json`; it gives every session
  the tools `board_list`, `board_get`, `board_set`, `board_ask`, `board_answers` and `board_cancel`.
* `tld board client` (records) and `tld board ask`, `tld board answers`, `tld board cancel` (asks) are the
  command-line clients sessions use when the MCP tools are not loaded.

Two principals, never mixed. A **session** sends the token `TLD_BOARD_TOKEN`: it writes records and posts,
reads and cancels asks, but can never answer one. **You** log in with `TLD_BOARD_OWNER_PASSPHRASE`: you read
everything, answer and cancel asks, and can never write a record. The server uses only the Python standard
library (3.11 or newer) and speaks plain HTTP; TLS is the job of a reverse proxy.

## Run it locally

From a checkout of the tkcs-lab-devflow repository:

```bash
export TLD_BOARD_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
read -rs TLD_BOARD_OWNER_PASSPHRASE && export TLD_BOARD_OWNER_PASSPHRASE   # type 16+ characters
cli/tld board server --port 8787 --insecure-cookie
```

`--insecure-cookie` drops the cookie's `Secure` flag so the login works over plain `http://127.0.0.1`; never use
it behind a public address. The server prints `board_server: listening on http://127.0.0.1:8787`. In a second
terminal, with `TLD_BOARD_URL=http://127.0.0.1:8787` and the same token, post an ask:

```bash
export TLD_BOARD_URL=http://127.0.0.1:8787
cat > ask.json <<'JSON'
{"schema": 1, "kind": "ask", "project": "example-project", "repo": "example/example-project",
 "title": "Try the inbox", "created_by": "local-test",
 "questions": [{"id": "go", "text": "Does the inbox work?", "kind": "confirm"}]}
JSON
cli/tld board ask ask.json            # prints the ask id
```

Open `http://127.0.0.1:8787/`, log in, open the ask under "Needs you" and answer it; then
`cli/tld board answers <id>` prints `{"go":true}`. A status record is written with `tld board client set`;
this one is valid (save it as `record.json`):

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
  "attended": true,
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

```bash
cli/tld board client set example-project record.json
```

The answer is `{"id":"example-project","version":1}`, and the run shows on the page.

## Configuration

Environment variables:

| Variable | Used by | Meaning |
|---|---|---|
| `TLD_BOARD_TOKEN` | server, client, bridge | The session token, at least 24 characters. Clients send it as `Authorization: Bearer <token>`. |
| `TLD_BOARD_OWNER_PASSPHRASE` | server | Your login, at least 16 characters, different from the token. Unset: the page and the login are off (API only). Shorter: the server does not start. |
| `TLD_BOARD_SECRET` | server | Optional key (32+ characters) that signs the session cookie. Unset: the server generates one once into `<db>.secret` (mode 0600) next to the database. |
| `TLD_BOARD_PUBLIC_ORIGIN` | server | Default for `--public-origin`. |
| `TLD_BOARD_SESSION_URL` | server | Optional https base, ending in `/`, that a session id is appended to for the page's session links. Without it the page shows no session links. For Claude Code on the web: `https://claude.ai/code/`. |
| `TLD_BOARD_DB` | server | Default for `--db`. |
| `TLD_BOARD_URL` | client, bridge | Base URL of the server, for example `https://board.example.org`. Not a secret. |
| `TLD_BOARD_PLAN` | server | `standard` or `max`: the plan the account is on. Unset: the usage readings are off (`POST /api/usage` answers 409 `usage_off`). Anything else: the server does not start. |
| `TLD_BOARD_MAX_FACTOR` | server | How many times the Standard limit Max gives: a number above 1 and at most 20, default 5. Anything else: the server does not start. It is an assumption, not a measured value. |
| `TLD_BOARD_ALLOW_HTTP` | client, bridge | `1` allows a plain `http://` URL for a non-loopback host. |

If `TLD_BOARD_URL` or `TLD_BOARD_TOKEN` is unset, sessions skip every record step and put their asks on GitHub
instead (see "The issue fallback").

Server flags (secrets come from the environment only):

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Address to bind. |
| `--port` | `8787` | Port to bind; `0` picks a free port. |
| `--db` | `$TLD_BOARD_DB`, else `board.sqlite3` | SQLite file. An older board's database is upgraded in place on start. |
| `--title` | `tld Board` | Title of the page. |
| `--public-origin` | `$TLD_BOARD_PUBLIC_ORIGIN`, else the request's `Host` | The origin (`https://board.example.org`) every login and owner `POST` must come from. Set it in production. |
| `--insecure-cookie` | off | Local development only: the cookie without `Secure`, and an `http://` origin is accepted. |
| `--session-hours` | `12` | How long a login lasts (1 to 720). |
| `--trust-proxy` | off (on in the image) | Rate-limit logins by the last `X-Forwarded-For` entry; only behind a proxy that sets it. |
| `--allow-origin` | none | An `Origin` that may call `POST /mcp`; repeatable. Clients that are not browsers send no `Origin`. |

## Docker

This is the development route; to run a release use the installer (next section). Build from the repository root (the image holds only the server, its modules and the page):

```bash
docker build -f deploy/board/Dockerfile -t tld-board .
```

Run it with a volume for the database and the cookie secret:

```bash
docker run -d --name tld-board --restart unless-stopped \
  -p 127.0.0.1:8787:8787 -v tld-board-data:/data \
  -e TLD_BOARD_TOKEN -e TLD_BOARD_OWNER_PASSPHRASE \
  -e TLD_BOARD_PUBLIC_ORIGIN=https://board.example.org -e TLD_BOARD_SESSION_URL=https://claude.ai/code/ \
  tld-board
```

`-e NAME` without a value passes the variable from your shell, so no secret appears in the command line. The
container runs as an unprivileged user (uid 10001), keeps `/data/board.sqlite3` and `/data/board.sqlite3.secret`
in the volume, rate-limits logins per client behind the proxy (`--trust-proxy`), and has a health check on
`/healthz`. Publish the port on `127.0.0.1` only: the proxy is the one way in.

## Docker Compose (the installer)

The release carries the image `ghcr.io/tkcs-lab/tld-board` (linux/amd64 and linux/arm64) and a compose file that
pins it by digest. The installer sets it up (needs Docker with the compose plugin):

```
curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board
```

It creates `~/tld-board` (`TLD_BOARD_DIR`) with:

- `compose.yaml`: overwritten on every upgrade. Put local changes in `compose.override.yaml`, which compose merges
  and the installer never touches.
- `.env`: created once (mode 0600) with a fresh `TLD_BOARD_TOKEN`, empty `TLD_BOARD_OWNER_PASSPHRASE` and
  `TLD_BOARD_PUBLIC_ORIGIN`, and `TLD_BOARD_SESSION_URL`. The installer never prints the token and never rewrites the file.

Fill in `TLD_BOARD_OWNER_PASSPHRASE` and `TLD_BOARD_PUBLIC_ORIGIN` (avoid `$` in `.env` values: Compose may expand it), then start the board: `docker compose up -d` in
the directory. The installer starts it itself only when both are set. Upgrade: run the line again (it pulls the new
image and restarts). Stop: `docker compose down` (the volume stays). The compose file uses the volume
`tld-board-data`, so the data of an earlier `docker run` setup is reused. If a container named `tld-board` made by
`docker run` still exists, the installer stops with a message: run `docker rm -f tld-board` once and run the line
again. If the pull is denied, the package must be made public once by the repository owner
([CONTRIBUTING.md](../../CONTRIBUTING.md)).

## TLS and a reverse proxy

Put the container behind a reverse proxy that terminates TLS. With Caddy (it gets the certificate itself, keeps
the `Host` header and appends the client to `X-Forwarded-For`):

```
board.example.org {
    request_body {
        max_size 1MB
    }
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy 127.0.0.1:8787
}
```

nginx needs the same: TLS on the server block, `proxy_pass http://127.0.0.1:8787;`, `proxy_set_header Host $host;`,
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` and `client_max_body_size 1m;`. Do not publish
port 8787 itself.

## Deploy it

The steps you follow once, about 30 minutes:

1. On a host with Docker and a DNS name (`board.example.org` below), run the installer
   (`curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board`, section Docker Compose).
2. The installer made the token in `~/tld-board/.env`; keep a copy in your password manager. Put a passphrase of
   four or more random words in `TLD_BOARD_OWNER_PASSPHRASE` there.
3. Put your host name in `TLD_BOARD_PUBLIC_ORIGIN` (`https://board.example.org`) and start the board:
   `docker compose up -d` in `~/tld-board`.
4. Install Caddy, put the Caddyfile above in `/etc/caddy/Caddyfile` with your host name, and reload it
   (`systemctl reload caddy`). `curl -sS https://board.example.org/healthz` answers `{"ok": true}`.
5. Open `https://board.example.org/` and log in with the passphrase. The page is empty until a session writes.
6. Connect the Claude cloud environment (next section), start a session and run `/tld:board`: it reports the
   connection and the write path.

## Connect Claude Code sessions

In claude.ai, open the cloud environment the sessions run in (the environment menu in a session's title bar,
then Edit):

1. **Network access:** keep the Limited level and add `board.example.org` under Allowed domains (leave Allow
   package managers ticked). Without it every board call fails with a network error and the run falls back to
   GitHub.
2. **Network secrets** (where the section is offered): add one for host `board.example.org`, header
   `Authorization`, prefix `Bearer`, value the token. The proxy then adds the token to every request to the
   board, and saving it also allows the host. Set the environment variable `TLD_BOARD_TOKEN` to a placeholder
   such as `injected-by-the-proxy` (the clients need a value; the proxy replaces the header). Where Network
   secrets are not offered, put the real token into `TLD_BOARD_TOKEN` instead.
3. **Environment variables:** `TLD_BOARD_URL=https://board.example.org` (not a secret) and `TLD_BOARD_TOKEN` as
   in step 2.
4. Start a new session (running ones do not pick the change up) and run `/tld:board`.

You type the token into the settings form yourself, never into a chat. Anyone who holds it can write records
and post asks, but cannot answer them.

The whole environment, including the research environment, is in [cloud-environments.md](cloud-environments.md).

## Rotating the token and the passphrase

* **Token:** make a new one, restart the container with it (`docker rm -f tld-board`, then the `docker run`
  again with the new `TLD_BOARD_TOKEN`), and replace it in the environment's network secret (or variable).
  Sessions with the old one get 401 until they restart.
* **Passphrase:** restart the container with the new `TLD_BOARD_OWNER_PASSPHRASE`. The cookie key depends on
  the passphrase, so every open login ends.
* **Cookie secret:** to end every login without a new passphrase, stop the container, delete
  `/data/board.sqlite3.secret` (or change `TLD_BOARD_SECRET`) and start it again.

## HTTP API

`/healthz` and the page need nothing. The rest takes either the session token (`Authorization: Bearer
<token>`) or your login cookie; a wrong token is 401 even with a cookie. Every `POST` with the cookie needs the
board's own `Origin` and the `X-CSRF-Token` header the login returned; the login itself needs the `Origin`.

| Request | Session token | Owner cookie | Success | Errors |
|---|---|---|---|---|
| `GET /healthz` | - | - | 200 `{"ok": true}` | |
| `GET /` and `GET /index.html` | - | - | 200, the page | 404 `owner_ui_disabled` without a passphrase |
| `POST /login` | - | - | 200 `{"owner": true, "csrf"}` and the cookie; body `{"passphrase"}` | 401 `wrong_passphrase`, 429 `too_many_attempts` (`Retry-After`), 403 `origin_not_allowed` |
| `GET /api/session` | - | - | 200 `{"owner": bool, "csrf"}` | |
| `POST /logout` | 403 | yes | 200, the cookie cleared and its session ended | |
| `GET /api/records` | yes | yes | 200 `{"records": [{"id", "version", "dismissed_at", "data"}, ...]}` | |
| `GET /api/records/<id>` | yes | yes | 200 `{"id", "version", "dismissed_at", "data"}` | 404 `not_found` |
| `PUT /api/records/<id>` | yes | 403 | 200 `{"id", "version"}`; body `{"data": {...}, "if_version": 3}` | 400 `bad_request`, 409 `version_conflict` (`current`), 422 `invalid` (`errors`) |
| `DELETE /api/records/<id>` | yes | 403 | 200 `{"deleted": true}` | 404 `not_found` |
| `POST /api/records/<id>/dismiss` | 403 | yes | 200 `{"id", "version", "dismissed_at"}`; body `{"version": n}` | 400 `bad_request`, 404 `not_found`, 409 `version_conflict` (`current`), 403 `csrf` |
| `POST /api/records/<id>/restore` | 403 | yes | 200 `{"id", "dismissed_at": null}`; empty body | 404 `not_found` |
| `GET /api/asks[?state=open]` | yes | yes | 200 `{"asks": [...]}`, open ones first | 400 for an unknown state |
| `POST /api/asks` | yes | 403 | 201, the stored ask with its `id`; body the ask | 422 `invalid` (`errors`) |
| `GET /api/asks/<id>` | yes | yes | 200, the ask | 404 `not_found` |
| `POST /api/asks/<id>/answer` | 403 | yes | 200, the answered ask; body `{"answers": {"<question id>": value}}` | 409 `not_open`, 422 `invalid`, 403 `csrf` |
| `POST /api/asks/<id>/cancel` | yes | yes | 200, the ask (cancelling a cancelled ask is a no-op) | 409 `not_open` (answered), 404 |
| `GET /api/usage` | 403 | yes | 200 `{"now", "plan", "factor", "windows": {"five_hour": [...], "seven_day": [...]}}`; `plan` is null when `TLD_BOARD_PLAN` is unset | |
| `POST /api/usage` | yes | 403 | 200 `{"stored": n}`; body `{"five_hour": {"utilization", "resets_at"}, "seven_day": {...}, "source": "final"}` (at least one window; `source` is `final` or `scheduled`) | 409 `usage_off` (no plan set), 422 `invalid` (`errors`), 413 `payload_too_large` (over 4096 bytes) |
| `POST /mcp` | yes | 403 | JSON-RPC answer, see the next section | |

A write without `if_version` creates the record and conflicts when it exists; with `if_version` it succeeds
only when the stored version equals it. Other errors are `{"error": "<code>"}`: 401 `unauthorized`, 403
`forbidden` (the other principal's route), 404 `not_found`, 405 `method_not_allowed` (with `Allow`), 413
`payload_too_large` (over 1048576 bytes; 4096 for the login). The ask format is
`src/tld/schema/ask.schema.json`: at most 30 questions of kind `choice` (2 to 10 options), `confirm` or `text`,
each text at most 2000 characters, the whole ask at most 64 KiB, and at most 200 open asks.

## Usage readings

With `TLD_BOARD_PLAN` set, the board keeps the subscription use sessions report (the `usage_samples` table, schema
version 5). A reading is one sample per window kind (`five_hour`, `seven_day`): the raw `utilization` (a fraction of
the limit, 0.26 is 26%), the time the window ends (`resets_at`, to the minute), the server's own time of arrival,
the plan and the factor in force then, and the source (`final`, `scheduled`). The plan and the factor are applied
only when the page reads the samples, so a wrong setting can be corrected later. Limits: 50 samples per window, a
window is deleted 120 days after it ended, and at most 20,000 rows are kept (the oldest go first). Upgrading moves
the database to schema 5: an older board image cannot open it again, so keep the backup from before the upgrade
(Backup and restore) if you may roll back. The factor (`TLD_BOARD_MAX_FACTOR`, default 5) is an assumption about
how much more Max allows than Standard; the Max figures are Standard figures divided by it. Whoever holds the session token can post readings and so push older history out of the 20,000-row limit; the readings can be collected again.

## MCP tools

`POST /mcp` is a stateless streamable-HTTP MCP endpoint: one JSON-RPC object per request, answered as
`application/json`. It supports `initialize`, `ping`, `tools/list` and `tools/call`. A notification gets 202
with an empty body; a batch gets 400. The plugin reaches it through the stdio bridge, because credential
variables in a remote server's headers are not expanded in a plugin's `.mcp.json`.

| Tool | Arguments | Result text (JSON) |
|---|---|---|
| `board_list` | none | `{"records": [{"id", "version", "dismissed_at", "data"}, ...]}` |
| `board_get` | `id` (string) | the record `{"id", "version", "dismissed_at", "data"}`; error `{"error": "not_found"}` |
| `board_set` | `id` (string), `data` (object), `if_version` (integer >= 1, optional) | `{"id", "version"}`; errors `{"error": "version_conflict", "current"}` and `{"error": "invalid", "errors"}` |
| `board_ask` | `ask` (object) | the stored ask with its `id`; error `{"error": "invalid", "errors"}` |
| `board_answers` | `id` (string) | `{"id", "state", "answers", "answered_at"}` |
| `board_cancel` | `id` (string) | `{"id", "state"}`; error `{"error": "not_open"}` for an answered ask |

Errors come back as a tool result with `isError` true. There is no delete tool: `/tld:board prune` deletes and
clears records after you confirmed ([Cards that wait](maintenance.md#cards-that-wait)).

## The issue fallback

When the board is not configured or cannot be reached, `tld board ask <file> --fallback-issue <owner>/<repo>[#<n>]`
exits 5 and prints the comment body; the session posts it on the tracking issue (or a new issue) with its
GitHub tool. The body mentions `git.owner_login` from the profile (else the repository owner) and lists the
questions, with an example reply as plain lines between `-- example reply --` and `-- end of example --` (no
code fence). Reply on the issue with one plain line per question, outside any code block, quote or HTML
comment (text there never counts), for example:

```
SEC-1: plan
go: yes
notes: one line of text
```

Only replies by the owner (every `--owner`, else `git.owner_login`, else the repository owner) or by an admin
count; replies by collaborators with write or maintain access never do (the agent account has write), and neither
do the session's own login (`--self LOGIN`, required) and the fallback comment itself. The session reads them with
`tld board answers --from-issue COMMENTS.json --ask FILE --self LOGIN` (see `playbooks/runtime.md`, `ask_human`).

## Answering in the session

In an attended session (you started the command and watch the chat) the ask is also shown in the conversation
(`tld board ask-text`). Answer there with one `<question id>: <answer>` line per question, or just the answer when
there is one choice or confirm question. The session reads the lines with `tld board answers --from-reply` and
cancels the board copy. It also checks the board on its own, every 10 minutes for the first hour after the ask,
then hourly, and stops after 24 hours, so an answer on the board needs no chat message. Unattended sessions are
unchanged.

## Security notes

* The passphrase is compared in constant time (on SHA-256 digests). Wrong passphrases lock that client out
  after 5 failures for 2 s, doubling up to 15 minutes; a successful login clears it. A client is its IPv4 address
  or its IPv6 /64 network. When all clients together exceed 30 failures a minute, every login attempt is slowed
  down (by at most 2 s) but nobody is locked out, so a flood from many addresses cannot keep the owner from
  logging in. The counters live in memory: a restart clears them.
* `--trust-proxy` keys the limiter on the **rightmost** `X-Forwarded-For` entry, the one the proxy appended.
  Only a single trusted proxy in front of the board is supported; behind a chain of proxies every client would
  share the key of the inner proxy, and without `--trust-proxy` behind a proxy every client shares the proxy's.
* A connection that sends nothing for 15 s is closed, a request body must arrive within 30 s (else `408`), and
  at most 64 connections are served at once; one more gets `503` and is closed.
* The cookie is `HttpOnly`, `Secure` (unless `--insecure-cookie`), `SameSite=Strict`, `Path=/`, named
  `__Host-tld_owner`, signed with HMAC-SHA256 and valid for `--session-hours`. Logout ends the session on the
  server too, and the logged-out session is kept in the database (`revoked_sessions`, schema version 4), so a
  restart does not bring it back.
* Every owner `POST` checks the `Origin` (and `Sec-Fetch-Site` when sent) and a CSRF token bound to the
  session. The session token cannot answer asks; the cookie cannot write records.
* Dismissals are kept in the database (`dismissals`, schema version 4), next to a record and never inside it.
  The owner still writes no record; a dismissal counts only until a session writes the record again.
* The page is served with a Content-Security-Policy that allows only its own inline script and style and
  requests to its own origin, and with `X-Frame-Options: DENY`. It builds every element with `textContent`:
  no text of a record or an ask is ever read as HTML.
* The client and the bridge refuse a plain `http://` URL unless the host is loopback (or `TLD_BOARD_ALLOW_HTTP=1`),
  and drop the token on a redirect to another scheme, host or port.
* Records and asks must not contain secrets. The SQLite file and the secret file are not encrypted: protect the
  volume.

## Backup and restore

While the server runs, make a consistent copy with SQLite's online backup. On the host, with the sqlite3 tool:

```bash
sqlite3 board.sqlite3 ".backup 'copy.sqlite3'"
```

In the container (the image has no sqlite3 tool):

```bash
docker exec tld-board python -c "import sqlite3; sqlite3.connect('/data/board.sqlite3').backup(sqlite3.connect('/data/copy.sqlite3'))"
docker cp tld-board:/data/copy.sqlite3 ./board-backup.sqlite3
```

A database at schema 5 is refused by an older image, so keep the backup from before the upgrade to roll back.

To restore, stop the server, put the copy at the path given by `--db` (in the container `/data/board.sqlite3`),
and start it again. Records are short-lived and rewritten by the next run; open asks are the part worth
keeping. The secret file needs no backup: without it you only log in again.

## Troubleshooting

* **The page says "Wrong passphrase" or "Too many attempts"**: wait the seconds it shows; a restart of the
  container clears the lockout.
* **Login fails with 403 `origin_not_allowed`**: `TLD_BOARD_PUBLIC_ORIGIN` does not match the address in the
  browser, or the proxy changes the `Host` header.
* **The page answers 404 `owner_ui_disabled`**: `TLD_BOARD_OWNER_PASSPHRASE` is not set in the container.
* **`/tld:board` says no board is configured**: `TLD_BOARD_URL` or `TLD_BOARD_TOKEN` is unset in that environment.
* **Network error from a cloud session**: the host is missing from the environment's allowed domains.
* **401 from a session**: the token in the environment differs from the server's.
* **`TLD_BOARD_URL must be https`**: the URL is plain `http://` for a remote host; use TLS.
* **409 `version_conflict`**: another session wrote first; read the record again, merge your fields, retry once.
* **422 `invalid`**: the record or the ask does not match its format; the `errors` list names the fields.
* **The page shows "Cannot reach the board server"**: it keeps what it has and retries every 15 seconds; check the
  proxy and the container (`docker logs tld-board`).
* **The server will not start**: it prints which variable is missing, too short or equal to another.

## Replacing the artifact board

There is no migration: records are short-lived and rewritten by the next run, and copying the old ones would
need claude.ai. The old board page and decision pages can be deleted from claude.ai. The profile key
`status.board_url` is no longer read, and a profile that still has it fails validation with
`unknown key 'status'`; remove the `status:` block from `.tld/toolkit.yaml`. A database of the first self-hosted board is
upgraded in place when the new server starts; records of kind `maintenance` fail validation on their next
write (the kind is `command` now) and are replaced by the next run.
