# The board behind Cloudflare

Run the board on two ports so Cloudflare Access can guard the owner's page and an IP rule can guard the sessions' API.
The ranges for Claude are not confirmed to cover cloud sessions: verify before you rely on them (see "Verify").
Placeholders: `board.example.org` (page host) and `board-api.example.org` (API host); use your own.

## Why the split

One port serves the owner's page and the sessions' API, and `/api/records`, `/api/asks` and `/api/usage` are shared,
so Cloudflare cannot ask for a login on the page and an IP limit on the API on the same host. With `--api-port` the
board has two listeners over one store:

- **Page endpoint** (`--port`, 8787): the page, login, and the owner's reads and answers. Any request with an
  `Authorization` header to a route it serves gets 403 `wrong_endpoint`.
- **API endpoint** (`--api-port`, 8788): the sessions' routes and the bearer token only. It never reads the cookie:
  a request without a token is 401 `unauthorized`, even with a valid owner cookie.
- Every other route or method on a listener is 404 (also for a token on the page port, for example `PUT /api/records/x`). `/healthz` answers on both. The server has no IP check: the proxy does it.

## The picture

```
owner    -> board.example.org      -> Access login -> tunnel -> http://localhost:8787 (page endpoint)
sessions -> board-api.example.org  -> WAF rule (Anthropic ranges only) -> tunnel -> http://localhost:8788 (API endpoint)
```

Two hostnames, one tunnel. Access protects the page host only; the API host has no Access application and no
Bypass policy.

## 1. The board host

In `~/tld-board/.env` (see [board-server.md](board-server.md#docker-compose-the-installer)) add
`TLD_BOARD_API_PORT=8788` and set `TLD_BOARD_PUBLIC_ORIGIN=https://board.example.org` (the page host). Next to
`compose.yaml` create `compose.override.yaml`:

```yaml
services:
  board:
    ports: ["127.0.0.1:8788:8788"]
```

Then `docker compose up -d` and check both listeners (the log prints `listening on ... (page)` and `... (api)`):

```bash
curl -sS http://127.0.0.1:8787/healthz
curl -sS http://127.0.0.1:8788/healthz
curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8788/
```

The first two print `{"ok": true}`, the last prints `404`. `--api-port` needs `TLD_BOARD_OWNER_PASSPHRASE`: the page
endpoint serves only the owner.

## 2. Cloudflare

Do these in order, so the page host is never open.

1. **Access app on the page host.** Zero Trust, Access controls, Applications, Create new application, Self-hosted
   and private, Add public hostname (`board.example.org`), add an Allow policy for yourself, Create. Apps are deny
   by default. Do not use a Bypass policy: it is not logged and Cloudflare advises against it for permanent access.
2. **Tunnel public hostnames.** In the tunnel that runs on the board host add `board.example.org` to
   `http://localhost:8787` and `board-api.example.org` to `http://localhost:8788`. Each hostname gets its own
   CNAME to `<UUID>.cfargotunnel.com` and its own zone WAF rules. Create no Access application for the API host.
3. **WAF rule on the API host.** Security, WAF, Custom rules, name `board-api claude only`, action Block, expression:

   ```
   http.host eq "board-api.example.org" and not ip.src in {160.79.104.0/21 153.61.208.0/20}
   ```

   An IP list (Configurations, Lists) can replace the inline set; whether the Free plan offers lists was not
   confirmed.

## Caddy instead of a tunnel

Where Caddy terminates TLS directly, the same limit on the API host is:

```
board-api.example.org {
    @claude remote_ip 160.79.104.0/21 153.61.208.0/20
    handle @claude {
        reverse_proxy 127.0.0.1:8788
    }
    handle {
        respond 403
    }
}
```

Behind cloudflared the peer address is the local tunnel client, and behind a proxied (orange cloud) DNS record it is
a Cloudflare edge address, so this works only when the API host's DNS record is DNS-only and Caddy is reached
directly. Access on the page host still needs that host proxied or tunnelled.

## 3. The session environment

In the Claude environment ([cloud-environments.md](cloud-environments.md)) the board host becomes the API host in
three places: Allowed domains, the network secret's host (the token stays in the secret form), and
`TLD_BOARD_URL=https://board-api.example.org`. From the moment Access exists until this is done, running sessions
cannot reach the board and fall back to GitHub asks: do steps 2 and 3 in one sitting.

## Verify

1. Open `https://board.example.org`: Cloudflare's login comes first, then the board's own.
2. From your machine, `curl -sS -o /dev/null -w '%{http_code}' https://board-api.example.org/healthz` prints `403`.
3. Start a new session and run `/tld:board`: it reports the connection.

If `/tld:board` fails with 403, the ranges do not cover that session. In the Cloudflare dashboard open Security,
Events, find the blocked request's source address, check that it is Anthropic's, and only then add it to the rule.

## What was confirmed (read on 2026-11-14)

- Anthropic's outbound IPv4 ranges are `160.79.104.0/21` and `153.61.208.0/20`, "stable IP addresses... for
  outbound requests (for example, MCP tool calls)", not changing without notice
  (https://platform.claude.com/docs/en/api/ip-addresses). That page does not say they cover Claude Code on the
  web; the cloud environments page says session traffic goes through a security proxy and gives no source IPs
  (https://code.claude.com/docs/en/cloud-environments.md). A status incident of 2026-05-06 about changed outbound
  IPs for GitHub connections suggests but does not prove it. Coverage is unconfirmed.
- Access app steps and deny by default:
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Policy actions (Allow, Block, Bypass, Service Auth):
  https://developers.cloudflare.com/cloudflare-one/access-controls/policies/
- One tunnel, many hostnames:
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/.
  Publishing through a tunnel needs no paid plan; Access policies need a Zero Trust plan with a seat per user
  (check the plan page).
- WAF custom rules (Free allows 5): https://developers.cloudflare.com/waf/custom-rules/ ; IP lists:
  https://developers.cloudflare.com/waf/tools/lists/create-dashboard/
