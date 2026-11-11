# Docs index: a thin CLAUDE.md and docs read on demand

A thin `CLAUDE.md` (at most 60 lines) points to one docs index (`docs/README.md`, at most 150 lines), and the
index routes to leaf docs that a session opens only when a row matches its task.
`/docs [check | init | tidy]` and `tld ops docs-index` keep that structure true.

## Why

Every session pays for `CLAUDE.md` and for every doc it reads. A flat pile of docs makes each session
read too much or guess. One short index with a row per doc (what it answers and when to read it) keeps
the fixed cost small and the choice of what to read deterministic.

## The structure

```
CLAUDE.md                  thin: loaded in every session, at most 60 lines
docs/README.md             the index (profile key docs.index), at most 150 lines
docs/architecture/         how it is built and why
docs/guides/               how to do things
docs/reference/            lookups: config keys, schema, API
docs/adr/                  README.md (ADR index) + NNNN-<kebab>.md   (only when the project uses ADRs)
docs/plans/                active plans only (<slug>-plan.md), deleted at retirement, never indexed
docs/archive/              superseded docs, kept for history, never read by default
```

An index row is `- [<title>](<relative path>) - <what it answers>; read when <condition>.`
A doc starts with `# Title` and a summary of at most 3 lines; each fact lives in one doc and others link to it.

## How a session reads

`CLAUDE.md` is already loaded. Open the index and nothing else, then only the rows that match the task.
For decisions read the ADR index and only the ADRs whose one-line decision touches the area. Never read
`archive/` or another change's plan, and never read every doc.

## Keeping it current

- `/make-plan` reads the index and writes a `Read first:` line in each phase brief.
- `/implement` workers read only their `Read first:` list; the retirement phase updates the index
  (one row per doc added, moved or deleted) and the `CLAUDE.md` lines a change made untrue.
- `/dod` reports a `docs index` row; an index error fails it (C3).
- The `tech-writer` role reports index errors through `checklists/docs.md` when the profile requires it; it never fixes the index (only the retirement phase, `/docs init` and `/docs tidy` edit it).
- `/docs tidy` repairs drift: missing rows, repointable links, rows for deleted docs.

## /docs

- `check` (default): runs `tld ops docs-index check` with `--stale-days 180`, reports every error and warning in
  a table and changes nothing.
- `init`: attended; moves docs into `architecture/`, `guides/` and `reference/`, thins `CLAUDE.md`, writes
  the index, edits the profile's `docs` block and opens one pull request (never merged).
- `tidy`: unattended weekly cleanup; applies mechanical fixes in one pull request or lists the decisions
  in an issue; writes a status record with `command: docs`; never merges.

## The profile key

`docs.index` in `.tld/toolkit.yaml` names the index file. Without it there is no docs index and the
commands read `docs.must_read` as before. With it, keep `docs.must_read` to what every task needs.
Reference: [profile-reference.md](../reference/profile-reference.md).

## Moving a doc

`bin/tld ops docs-index move SRC DST` is a dry run: it lists every reference it
would rewrite and every mention it cannot resolve. Add `--apply` to do the git move and the rewrites.
It rewrites markdown links, root path mentions and quoted path expressions in `.py` files, and skips
fixtures, the profile and plan files. Fix each `unresolved:` line by hand.

## Scheduling /docs tidy

Create the scheduled task in the claude.ai interface with the repository attached, as described in
[maintenance.md](maintenance.md). Update the status board server first: an older one rejects
`command: docs` records.

## Limits

`CLAUDE.md` 60 lines and the index 150 lines (errors); a doc 400 lines (warning).
