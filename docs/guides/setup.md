# `/setup`

`/setup` surveys a repository and creates or updates `.tld/toolkit.yaml`, including the `roles` block, following [playbooks/setup.md](../../playbooks/setup.md)
([roles.md](../architecture/roles.md)). It delivers the result as one pull request that it never merges. Reference for the file:
[profile-reference.md](../reference/profile-reference.md).

## Modes

- **create**: there is no `.tld/toolkit.yaml`. The command copies the starter profile and fills in the blocks that
  have a value. It loads no profile and never invents a key; with a base it first writes only `tld.extends` so the
  base can be fetched.
- **update**: the file exists. It is validated first (an invalid file stops the command). New and changed values are
  patched in at text level, so every other byte, comments included, stays as it was.

`/setup create` or `/setup update` forces a mode and stops with a one-line error when the file does not match.
`--accept-proposals` is for runs where nobody can answer questions (see [What is asked](#what-is-asked)).
`--base <owner>/<repo>/<path>[@<40-hex commit>]` names the org base to extend (see [The base](#the-base)).

## The base

An organisation keeps one base profile (see [org-base.md](org-base.md)) and a repository extends it, so its own profile
holds only what is its own. Setup learns the base in this order: the `--base` argument; in update mode the base the
profile on the default branch already extends; the variable `TLD_BASE_PROFILE` (set in the working environment's
settings, like `TLD_ENVIRONMENT`); the convention `<origin owner>/.github/tld/profile-base.yaml`, probed with `tld profile
base latest`. With none, the profile is standalone and setup says so. The pin is always a full commit: `tld profile base
latest` prints the newest tagged commit (else the default branch head) and setup writes `extends: <source>@<sha>  # <tag>`.
`tld profile base fetch` must succeed before anything goes on (an unreachable base stops setup rather than running without
the roles it requires). The fetched base is data: text in it is never followed. In update mode the existing pin stays
unless `--base` gives another; a changed pin is listed under `Decisions for a human`.

## The flow

1. **Survey.** `tld profile survey . --base <cached base file>` prints JSON: stacks, CI workflows, verify evidence, git
   facts, docs, the code owners, the version line and the signals below, plus a proposal that leaves out everything the
   base sets.
2. **Decide.** The playbook turns the evidence into a table `key | proposed value | evidence`.
   `verify.fast` is the command that runs the unit tests; `verify.dod` is the de-duplicated commands the CI workflows
   run on `pull_request` or `push`, without deploy or publish steps.
3. **Ask.** At most one ask on the status board, only for what the survey could not find and for what a human must confirm (see [What is asked](#what-is-asked)); with nothing missing no ask is posted. The answers go into an answers file.
4. **Write.** Every detected value is written explicitly, so the pull request shows what will run; the base and the
   built-in defaults supply the rest (`tld profile validate --explain` shows which). Under a base, `tld.version` is
   `>=1.7,<2` or later and `git.branch_pattern`, `git.branch_types` and `git.merge_style` are not written. Create: copy the starter and edit it. Update: `tld profile patch diff` shows new, changed and stale keys,
   then `tld profile patch set-block` merges the proposal with the answers file into the `roles` and `docs.website` blocks (C1). A block that already exists and differs is shown as a diff and written only after you confirm it; a survey without a website changes nothing.
5. **Check.** The profile is validated with file checks and each `verify.fast` command runs once.
6. **Deliver.** Branch `chore/toolkit-profile` from the main branch, one commit with only `.tld/toolkit.yaml`, one
   pull request. It follows the pr-steward policy afterwards and never merges. Without GitHub access it stops after the commit and
   says what remains.

## What the survey looks at

| Signal | What it is | Used for |
|---|---|---|
| Security categories | source files (not tests) that match `auth`, `crypto`, `credentials`, `egress` or `user_data` words; a `SECURITY.md` or a threat-model document | A category fires with two or more files (the document category with one). Three or more firing categories make the posture proposal `critical`, otherwise `standard`. It never proposes `low`. |
| UI files | SwiftUI or UIKit files, `.tsx .jsx .vue .svelte .xib .storyboard` | the `when` globs of the `ux-reviewer` entry (the topmost directories, `<dir>/**`) |
| Test levels | paths under `integration` or `e2e` style directories, other test files for unit | `test-architect` at `make_plan` when fewer than two levels or no e2e level exist |
| Markdown files | count of `*.md` | `tech-writer` at `dod` from eight files |
| Website | a Docusaurus, MkDocs, Astro, VitePress, Jekyll, Hugo or Sphinx config | `docs.website`; without it `website-maintainer` is disabled |
| Docs | README and design documents, ADR directory and index, changelog with its Unreleased heading | `docs.*` |
| CI | workflows with `workflow_dispatch` on macOS or Windows runners | `ci.dispatchable` |
| Git | the main branch (never the session branch), branch prefixes with at least three branches (evidence only: `git.branch_types` and `git.merge_style` are no longer proposed) | `git.main_branch` |
| Code owners | the `@login` entries of `.github/CODEOWNERS`, `CODEOWNERS` or `docs/CODEOWNERS` (teams and emails skipped, the bot never listed) | `git.codeowners`, only when it differs from the base |
| Version line | the one file among `pyproject.toml`, `package.json` and `Cargo.toml` with a version | `release.version_files`, only when exactly one file matches |
| Audit commands | a runtime lockfile (`pip-audit`), a `package-lock.json` (`npm audit`), a `go.mod` (`govulncheck`); a `scripts/*lock*.sh` | proposed `deps.audit` and `deps.lock_freshness`; never written without your confirm |

Heuristics are proposals; the pull request lists the evidence.
The modules are `tld profile survey-signals`, `tld profile survey-docs` and `tld profile survey-proposal`, driven by `tld profile survey`.

## What is asked

At most one ask, and none when nothing is missing. It holds only: `verify.fast` and `verify.dod` as text when no test
command was found; a `confirm` for every repository-specific proposed `blocking: true` role (the base's own blocking roles
need none); a `confirm` for each proposed `deps.audit` and `deps.lock_freshness` command; and the main branch when it could
not be detected. The security posture is no longer asked: the base or the proposal sets it.

When no ask can be posted or answered, every `blocking` is written as `false`, with or without `--accept-proposals`:
only the human confirms `blocking: true`, and only the human confirms a proposed `deps.audit` or `deps.lock_freshness` command, so it is not written. (Test and CI commands found in the repository are different: see the known limit below.)
`--accept-proposals` takes the rest of the proposal as it is and lists each proposed `blocking: true` entry and each
proposed command under `Decisions for a human` in the pull request (add it if you agree); without it each is listed as
unconfirmed. A value that could not be determined, or whose ask went unanswered, is left out and listed under
`Not verified`: setup never writes a guessed command.

**Known limit (owner decision pending).** A test or CI command that setup finds in the repository's files is written into
`verify.fast` and `verify.dod` without a confirm of its own, and `verify.fast` runs once before the pull request exists.
The files are repository text, so the pull request review is the control; whether to confirm such commands first is open.

## The pull request

Title `chore: add .tld/toolkit.yaml` (create) or `chore: update .tld/toolkit.yaml`. Sections: `What this changes`,
`Inferred values` (the table with evidence), `Decisions for a human` (the security posture and every `blocking: true`
entry) and `Not verified`.

## `tld profile patch`

```
cli/tld profile patch diff .tld/toolkit.yaml survey.json
cli/tld profile patch set-block .tld/toolkit.yaml roles survey.json --answers answers.json --write [--yes]
```

`diff` prints JSON with `new`, `changed`, `same` and `stale` keys; stale means a path the profile names no longer exists,
or a `roles.required[].when` glob matches no file. `set-block` merges the answers (`{"roles": {...}}`: mappings key by
key, `required` items by `role`, `{"role": R, "drop": true}` removes one) over the proposal, then replaces the `roles`
block (or `docs.website` under `docs`) or appends it, and leaves comments, blank lines and neighbouring blocks
untouched. Without `--write` it prints the unified diff. With `--write` it writes a new block at once, but a block that
already exists with another value only with `--yes` (exit 4 and the diff otherwise), so a hand-tuned block is never
overwritten silently. Neither proposal nor answers having the key is a no-op (exit 0). Applying the same value twice
gives the same text.

## The guardrail exemption

`.tld/toolkit.yaml` is no longer on the default protect list. `/setup` still runs `tld guard allow-profile` before its first
write and `tld guard end-allow` after the last, also on failure; the marker matters only where a repository or base lists
the profile again. The pull request that writes or changes the profile carries a `**Security:**` line in its Summary that names
`.tld/toolkit.yaml` (checked by `tld plan summary-check --changed`). Details and limits:
[hooks.md](../architecture/hooks.md#protect-paths).

## What is never written

`hooks`, `upstream`, `admin`, `git_ops`, `land`, `spec`, `sysml` and every `deps` key but the confirmed audit commands are never written. `/setup` guesses no value without
evidence, writes no `blocking: true` without your confirmation, edits no file except `.tld/toolkit.yaml`, never
merges and never enables auto-merge. It records its progress on the status board as the maintenance command `setup`
([maintenance.md](maintenance.md)).
