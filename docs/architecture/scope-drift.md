# Scope-drift monitoring in `/implement`

Every phase of a plan declares `touches`: each file or glob it may change. Phases that can run at the
same time have disjoint `touches`, which is what lets them be merged without conflicts. A worker that
changes a file outside its `touches` weakens that promise. `/implement` therefore checks each phase
when it merges it and **records and reports** what it finds. It never blocks.

## What happens at each merge

Before `git merge --no-ff`, `/implement` runs
[`scripts/scope_check.py`](../../plugins/devflow/scripts/scope_check.py) `check`. The script:

1. Lists the files the phase branch changed since its merge base with the feature branch
   (`git diff --name-only --no-renames`). A rename counts as the old path deleted and the new path
   added, so both are checked.
2. Matches each path against the phase's `touches` with `path_matches` from `validate_manifest.py`,
   the same function the manifest validator's overlap check uses. A `touches` entry is a literal
   path, a directory ending in `/`, or an fnmatch glob. `*` and `**` both match across `/`; note that
   `src/**/x.py` needs at least one directory between `src/` and `x.py`, so it does not match
   `src/x.py`. List both forms if you mean both.
3. Sorts every changed path into one of three groups:
   - **in scope**: named by this phase's `touches`;
   - **ignored**: not in scope, but named by `scope.ignore` or the changelog file;
   - **out of scope**: everything else. It is a **collision** when another phase's `touches` names
     it too, which means the disjointness promise was broken (or, for a phase that depends on the
     other, that work moved earlier than planned).

It is mechanical: no model judges whether a change "really" belongs to the phase. The script reads
paths only; it never opens a file, a diff or a commit message. If it fails for any reason (a missing
ref, an unreadable plan), it prints an `unavailable` result with a short reason, exits 0, and the merge
goes ahead.

A phase whose `Plan-Phase` trailer is already in the feature branch's history (a resumed run) is not
checked again; the pull request section says "not checked". Fix sessions (`fix-<n>`) and rework
sessions (`<phase id>-rev<n>`) are always checked, even though the original phase's trailer is already
in the feature branch: they run under their own name against the original phase's `touches`, are never
reported as merged before the run resumed, and are listed under their own name in the pull request section.

## Why it never blocks

A real change sometimes has to touch one more file than the plan foresaw: a shared test fixture, a
renamed import. Stopping the run for that costs more than the drift does, and the orchestrator's
review of each phase's diff already sends back what is wrong. The point here is to measure how often
and where plans and workers disagree, with records precise enough to study later. The hard-stop list
(workflow files, secrets, protected paths) belongs to the guardrail hooks; this feature does not repeat it.

## Tuning `scope.ignore`

```yaml
scope:
  ignore:                 # globs; default: none
    - "package-lock.json"
    - "**/generated/**"
```

Use it for files that every phase may legitimately change and that a plan would not list. Two things
are decided by what the commands themselves demand:

- **The changelog** is always ignored when the profile has `docs.changelog`: the worker brief tells
  every phase to add its line there, so it would otherwise show up as drift in every phase. Without
  `docs.changelog` nothing is ignored for it.
- **Lockfiles** are not ignored by default. No command asks a phase to regenerate one, so a lockfile
  changed outside a phase's `touches` is a real signal, and plans should list it. If your tooling
  regenerates lockfiles as a side effect, add them here.

Anything in a phase's own `touches` stays in scope even when an ignore glob also names it.

## What is recorded, and where

| Where | What | How long |
|---|---|---|
| Status record, phase item field `scope` | `check` (`ok` or `unavailable`), `in_scope`, `out_of_scope_count`, `collision_count`, at most 20 paths (collisions first), `disposition` | Until the record is overwritten or pruned |
| Pull request description, `## Scope` | Per phase: out-of-scope paths (at most 20, then "and n more"), the phase each collides with, the disposition; or `none` | As long as the pull request |
| Board page | A count only (`drift 3`, or `scope ?` when the check was unavailable) on the phase chip | While the record exists |

Never recorded: file contents, diffs, commit messages, or anything but repository-relative paths.
The status record validator rejects a path with control characters, a leading `/`, a `..` segment or
more than 300 characters, and a list of more than 20 paths. It does not scan for secrets (it never has
and the field holds no content to scan); the path rules are what keep the field to paths.

**Durable history is the pull request description.** The board record is overwritten at every write
and pruned after a week, so it is a status display, not a history. A separate board collection was
considered and rejected: the board page reads only the `projects` collection, `/board prune` and
`board_stale.py` only know that collection, and a second document type would need its own schema,
validator, key scheme and retention rule, which is new infrastructure. The pull request section is
written once per run, sits next to the review, and is versioned by GitHub. If a later eval set needs
the cases, it can read them from merged pull requests.

### The `disposition`

`accepted` means the drift was merged as it is. After the last phase merges, before the pull request is
opened, `scope_check.py disposition` compares the recorded out-of-scope paths with the final diff of
the feature branch against the main branch (`git diff --name-only origin/<main>...HEAD`): a phase's
disposition becomes `reverted` when none of its out-of-scope paths is in that diff any more,
`partly_reverted` when some are, and stays `accepted` when all are. A path that is in the final diff
because a different phase changed it later also counts as still there. A phase without drift has
`disposition: null`.

### Schema version

The field is an **optional property in schema version 1**, not a version 2. Records written before it
exist stay valid, the board treats a missing field as "not checked", and the validator and the board ship
in the same plugin as the writer. Migration: none. A validator from before this change rejects a record
that carries `scope` (the schema forbids unknown properties), so update the plugin before pointing an
older environment at a board that already holds such records.

## Reading the pull request section

```
## Scope

- **p1-core**: none
- **p2-api**: 3 out of scope, 1 collision, accepted (merged as is)
  - `src/shared.py` (collides with `p3-ui`)
  - `scripts/tool.sh`
  - `docs/extra.md`
- **p3-ui**: scope check unavailable (git diff failed)
```

Read a collision first: two phases that were meant to be independent both wanted the same file, so the
plan's `touches` were wrong or a worker strayed. A path without a collision is something nobody
planned for; look at whether it belongs in a later plan's `touches`. `unavailable` means the numbers
are missing, not that there was no drift. Paths the profile's `scope.ignore` names are not listed.

## Not part of this feature

Replaying runs as evals, blocking on drift, model-based classification of the drift, and per-repository
configuration beyond `scope.ignore`.
