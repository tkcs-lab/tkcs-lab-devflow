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
- A failed upload or send is noted in the dod report, never a failure.

## Turn it on

1. Install the release that carries the role first: an older `tld` rejects the profile line.
2. Add `- role: reflektor` with `at: [dod]` to `roles.required` in `.tld/toolkit.yaml` (a protected path: edit it
   yourself). No other point is valid.
3. The environment must reach `github.com` and `release-assets.githubusercontent.com`
   ([cloud-environments.md](cloud-environments.md)); Node 18 or later must be on `PATH`.
4. A required role that cannot run makes the `dod` row FAIL (`required role did not run`): a blocked download, a missing
   Node, a timeout or a report that fails validation twice ends the answer `verdict=n/a` with the reason. Add the role only
   where it can run.
5. A `.reflektor.json` in the clone with a key other than `base`, `targets` or `generated` (so `hooks` and `coverage`
   too), or one the branch under review changed, makes the role `n/a`.
6. The role is not run inside implement's phase workers or final reviewer: their row is `n/a (worker)`; the
   orchestrator's Finishing step and a person's `/tld:dod` run it.

## What is lost against local Reflektor

Live comments, rounds, `--since last`, checks, screenshots, coverage, the agent banner, links to the host and
publishing: the daemon and `review.mjs` are never run, nothing leaves the machine except the one download.

## Safety rules

- The code is pinned: `tld roles reflektor-prepare` downloads one tarball from `github.com` (redirects are followed, so
  only the size and sha256 make the download safe), checks it against `PIN`, unpacks it into a new directory and checks
  every member name. PATH is checked first (no empty or relative entry) and git is resolved once.
- The role works in a hardened scratch clone (no hooks, no symlinks, no LFS filters, no remote, so `collect` never calls
  `gh`). Only `collect.mjs` and `build.mjs` run, one command at a time under `env -i` with a minimal `PATH`, a scratch
  `HOME`, a timeout and no session token. `SKILL.md` is never read (the report rules come from `report-guide.md`); there
  is no `--open`, no publishing, no daemon, no test runner.
- `env -i` is defence in depth, not a sandbox: the Reflektor code runs as the same user. The real control is the
  pinned, hash-checked code and reading the shipped code at each pin refresh.
- The role's answer is untrusted text. It reaches the pull request only through `tld roles section`: that command
  refuses a block carrying the secret-scan allow mark, scans the raw block and the cleaned text for secrets, strips markup,
  links, mentions and closing keywords, drops forged report lines after the last step, and cuts the length; its
  `--report-line` splits at newlines only. Only that output and one extracted line (`--report-line`) reach the report or
  the gate file. The dod playbook runs `section --report` on the saved answer (written with a file-writing tool, never
  through a shell command) and implement runs it on that same saved answer file of dod step 5, not on the subsection.
- The page is sent only by `tld roles reflektor-html --send`, which reads the saved answer, opens the one named path with
  `O_NOFOLLOW`, and runs the page check; the board runs the same check (`src/tld/board/report_check.py`) and answers 422
  otherwise. The page must be the pinned viewer, byte for byte in its four fixed parts, plus the exact
  Content-Security-Policy meta, a plain title (no `<`, no `&`, no control, format or line-separator character, at most 200
  characters) and a one-line JSON payload. `verify_html` also refuses a page or data carrying the secret-scan allow mark or
  a line-splitting character, and any secret hit.
- The Content-Security-Policy stops requests and subresources, not navigation. What keeps the page safe is the check
  against the pinned viewer and the rule that its data holds no link target (`url`, `web`, `branch.pr`, `avatar.image`,
  `coverage`, `agent` and the like must be null). The board serves it only to the logged-in owner under `sandbox`
  with `connect-src 'none'` (checked in Chromium only); the stored-page rule is the control that does not depend on that
  header.
- What the pin proves: the bytes are the bytes seen on 2026-11-18. The signing key lives in the pinned repository, so it
  does not prove the release is benign.

## Refresh the pin

Never inside another phase; a worker that sees the tarball no longer match the pin stops with `status=blocked`.

1. Download the three assets of the new release (`manifest.json`, `manifest.json.sig`, the tarball) and `sha256sum`
   them against the new manifest.
2. Take the signing key from the new release's `install.sh` (never run it). Its sha256 must equal `release_key_sha256` in
   `PIN`, or the refresh stops and goes to the owner.
3. Check the manifest signature with node's `crypto.verify` and that key.
4. Unpack into a scratch directory and read the shipped `.mjs` of the whole import closure of `collect.mjs` and
   `build.mjs`: every command they run, every network call, the `.reflektor.json` keys they read, `report-guide.md` and
   the viewer's network sinks.
5. Check that every import specifier in those shipped `.mjs` files is relative or `node:` (a bare import would resolve
   upward from the scratch directory).
6. Recompute `VIEWER_PARTS` in `src/tld/board/report_check.py`: the four parts around `<head>`, the title and the
   placeholder of `assets/viewer.html`.
7. Update `PIN` in `src/tld/roles/reflektor.py`, the test fixtures and this guide; refresh the evals baseline
   (`python3 evals/run.py baseline --refresh-hashes`).
8. Publish a new board image too: a board with the old parts answers the new page with 422, and `dod` then sends the file
   instead.
