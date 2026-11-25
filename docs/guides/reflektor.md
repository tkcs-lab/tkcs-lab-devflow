# Reflektor change report

The `reflektor` role runs the pinned Reflektor release (v0.9.1) on a branch at `dod` and gives the pull request a last
section `## Change report` plus a standalone HTML page. The design and its decisions are in plan 72
(`docs/plans/72/plan.md`, prose only: plans are not indexed).

## What you get

- A last section `## Change report` in the pull request body (what changed, risks, test gaps), written by
  `tld roles section`, never by the role's raw text. It appears when `/tld:implement` finishes and the dod report holds a
  `reflektor` answer; exit 3 of `section` leaves it out.
- An HTML page of the same report. Where it goes: with a status record for the run and a configured board
  (`tld board client health` exits 0), it is stored with `tld board client put-report <id> <file>` and the run's card gets a
  "Change report" link that opens it in a locked-down tab (needs the board upgrade, schema version 6, and the proxy body
  limit of [board-server.md](board-server.md)). Otherwise, or when that fails, it is sent to you as a file.
- The page embeds the full contents of the changed files; on the board it stays as long as the record exists, in the
  database and its backups. Copies also remain in the role's scratch directory and the dod scratch directory (the page
  and `diff.json`, with full file contents; delete them when done). A session can remove a stored page early with
  `DELETE /api/records/<id>/report` (session token only; it does not reach existing backups).
- A page that is refused or cannot be stored is never silent. These are rules of the dod and implement playbooks, not a code check: the dod row reads `needs attention (... ; HTML page not stored)` (a row that is already `FAIL` stays `FAIL`) and the `## Change report` section starts with the line `HTML page not stored: <reason>`. The reason is one of: the reflektor role built no checked page, the page check refused it, the page is too large to upload, the board answered an error or could not be reached, the file could not be sent. A page the check refused is not edited or rebuilt to get past it (also a playbook rule).
- A branch that quotes the secret-scan allow mark still gets its page: the mark is shown as `[secret-scan mark removed]` in the page (the count is printed by `reflektor-html`).

## Turn it on

1. Install the release that carries the role first: an older `tld` rejects the profile line.
2. Add `- role: reflektor` with `at: [dod]` to `roles.required` in `.tld/toolkit.yaml` (a protected path: edit it
   yourself). No other point is valid.
3. The environment must reach `github.com` and `release-assets.githubusercontent.com`; Node 18 or later must be on
   `PATH`. Warning: allowing `github.com` opens git and HTTPS traffic to all of GitHub for every session of that
   environment; use a dedicated environment ([cloud-environments.md](cloud-environments.md)).
4. A required role that cannot run makes the `dod` row FAIL (`required role did not run`): the answer ends
   `verdict=n/a` with the reason, for example a blocked download, a missing Node or git, a PATH with an empty or relative
   entry, a pin mismatch, a `baseRef` mismatch, a timeout or three failed build rounds (the first plus two retries). Add
   the role only where it can run.
5. A `.reflektor.json` in the clone with a key other than `base`, `targets` or `generated` (so `hooks` and `coverage`
   too), or one the branch under review changed, makes the role `n/a`.
6. The role is not run inside implement's phase workers or final reviewer: their row is `n/a (worker)`; the
   orchestrator's Finishing step and a person's `/tld:dod` run it.

## What is lost against local Reflektor

Live comments, rounds, `--since last`, checks, screenshots, coverage, the agent banner, links to the host and
publishing: the daemon and `review.mjs` are never run. `tld` makes the one download; at this pin, with `--no-fetch` and a local-path origin, `collect.mjs` and `build.mjs` make
no network call (read at the pin, not enforced). The HTML
page (full contents of the changed files) is stored on your board or sent to you as a file, and the cleaned section goes
into the pull request.

## Safety rules

- The code is pinned: `tld roles reflektor-prepare` downloads one tarball from `github.com` (redirects are followed, so
  only the size and sha256 make the download safe), checks it against `PIN`, unpacks it into a new directory and checks
  every member name. PATH is checked first (no empty or relative entry) and git is resolved once.
- Card rules, not enforced controls: the role works in a hardened scratch clone (no hooks, no symlinks, no LFS filters;
  its only remote is the local checkout path, since a remote on a host would make `collect` call `gh`); only `collect.mjs`
  and `build.mjs` run, one command at a time under `env -i` with a minimal `PATH`, a scratch `HOME`, a timeout and no
  session token; the agent never opens `SKILL.md` (`prepare` reads it only to cut out `report-guide.md`); it never uses
  `--open`, publishing, the daemon or test runners.
- Enforced by code: the `reflektor-prepare` checks (pin, `.reflektor.json`, PATH), `reflektor-check`, `reflektor-html`
  and `section`, described below.
- `env -i` is defence in depth, not a sandbox: the Reflektor code runs as the same user, so it can read every file the session can read and reach every host the
  environment allows. The real control is the
  pinned, hash-checked code and reading the shipped code at each pin refresh.
- The role's answer is untrusted text. It reaches the pull request only through `tld roles section`: that command
  refuses a block carrying the secret-scan allow mark, scans the raw block and the cleaned text for secrets, strips markup and
  links, wraps mentions and issue references in code spans, removes closing keywords before them, drops forged report lines after the last step, and cuts the length; its
  `--report-line` splits at newlines only. Only that output and one extracted line (`--report-line`) reach the report or
  the gate file. The dod playbook runs `section --report` on the saved answer (written with a file-writing tool, never
  through a shell command) and implement runs it on that same saved answer file of dod step 5, not on the subsection.
- The page is sent only by `tld roles reflektor-html --send`, which reads the saved answer, opens the one named path with
  `O_NOFOLLOW`, and runs the page check; the board runs the same check (`src/tld/board/report_check.py`) and answers 422
  otherwise. The page must be the pinned viewer, byte for byte in its four fixed parts, plus the exact
  Content-Security-Policy meta, a plain title (no `<`, no `&`, no control, format or line-separator character, at most 200
  characters) and a one-line JSON payload. `verify_html` only checks: it scans every line of the original page and of every decoded string with the allow mark's skip turned off (a credential on a line that ends in the mark is found and refuses the page). Then `prepare_page` replaces each literal mark in the title and the data by `[secret-scan mark removed]` and runs the whole check again on the swapped page (the swap can create a word boundary next to a credential); a mark that survives as an escaped form is refused, and a page with a line-splitting character is refused. The secret scan runs only in `reflektor-html` (the board image has no `tld.guard`), so the
  board's check is the page rule only.
- The page note (`tld roles page-note`) is built only from fixed text, a known reason and an HTTP status, and `tld roles change-report` prints it as the first line of the section, so text inside the role's own block cannot forge or move it. The command also replaces any block line that looks like a page note by the fixed line `(a line that looked like a page note was removed)`; paraphrases of the note are not caught.
- The Content-Security-Policy stops requests and subresources, not navigation. What keeps the page safe is the check
  against the pinned viewer and the rule that its data holds no link target (`url`, `web`, `branch.pr`, `avatar.image`,
  `coverage`, `agent` and the like must be null). The board serves it only to the logged-in owner under `sandbox`
  with `connect-src 'none'` (checked in Chromium only); the stored-page rule is the control that does not depend on that
  header.
- What the pin proves: the bytes are the bytes seen on 2026-11-18. The signing key lives in the pinned repository, so it
  does not prove the release is benign.

## Refresh the pin

Never inside another phase; a worker that sees the tarball no longer match the pin stops with `status=blocked`.

1. Download the three assets of the new release (`manifest.json`, `manifest.json.sig`, the tarball).
2. Take the signing key from the new release's `install.sh` (never run it). Its sha256 must equal `release_key_sha256` in
   `PIN`, or the refresh stops and goes to the owner.
3. Check the manifest signature with node's `crypto.verify` and that key; only then `sha256sum` the tarball against the
   manifest. Record `manifest_sha256` and `signature_sha256`.
4. List the tarball members first (no absolute, `..`, link or device member), then unpack into a scratch directory and write
   your own throwaway node script outside the unpacked directory for the checks; never run a script that ships in the
   release (read it only). Read the shipped `.mjs` of the whole import closure of `collect.mjs` and
   `build.mjs`: every command they run, every network call and the `.reflektor.json` keys they read. Read `SKILL.md`
   section 5, `schema/types.ts` and `style-guide.md` (the agent follows them, so they are an instruction surface) and the
   viewer's network sinks; `report-guide.md` is generated by `prepare`. Never add a `.reflektor.json` key that names a
   command, a hook or a path outside the clone.
5. Check that every import specifier in those shipped `.mjs` files is relative or `node:` (a bare import would resolve
   upward from the scratch directory).
6. From the new viewer list every data key it turns into a link, an embed, CSS text or HTML (including strings it
   renders as HTML: a JSON `\u003c` escape passes the raw `<` ban). Update `NULL_KEYS` and `NULL_UNDER` in
   `src/tld/board/report_check.py` and their tests; confirm `CSP_META` and the board's `REPORT_HEADERS` still cover the
   viewer. A sink that cannot be nulled stops the refresh and goes to the owner.
7. Recompute `VIEWER_PARTS` in `src/tld/board/report_check.py`: the four parts around `<head>`, the title and the
   placeholder of `assets/viewer.html`.
8. Update `PIN` in `src/tld/roles/reflektor.py`, the test fixtures and this guide; refresh the evals baseline
   (`python3 evals/run.py baseline --refresh-hashes`).
9. Publish a new board image too: a board with the old parts answers the new page with 422, and `dod` then sends the file
   instead.
