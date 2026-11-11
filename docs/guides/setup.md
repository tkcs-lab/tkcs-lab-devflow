# `/setup`

`/setup` surveys a repository and creates or updates `.tld/toolkit.yaml`, including the `roles` block, following [playbooks/setup.md](../../playbooks/setup.md)
([roles.md](../architecture/roles.md)). It delivers the result as one pull request that it never merges. Reference for the file:
[profile-reference.md](../reference/profile-reference.md).

## Modes

- **create**: there is no `.tld/toolkit.yaml`. The command copies the starter profile and fills in the blocks that
  have a value. It loads no profile and never invents a key.
- **update**: the file exists. It is validated first (an invalid file stops the command). New and changed values are
  patched in at text level, so every other byte, comments included, stays as it was.

`/setup create` or `/setup update` forces a mode and stops with a one-line error when the file does not match.
`--accept-proposals` is for runs where nobody can answer questions (see [What is asked](#what-is-asked)).

## The flow

1. **Survey.** `tld profile survey` prints JSON: stacks, CI workflows, verify evidence, git facts, docs and the
   signals below, plus a proposal.
2. **Decide.** The playbook turns the evidence into a table `key | proposed value | evidence`.
   `verify.fast` is the command that runs the unit tests; `verify.dod` is the de-duplicated commands the CI workflows
   run on `pull_request` or `push`, without deploy or publish steps.
3. **Ask.** One ask on the status board, at most four questions; the answers go into an answers file.
4. **Write.** Create: copy the starter and edit it. Update: `tld profile patch diff` shows new, changed and stale keys,
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
| Git | the main branch (never the session branch), branch prefixes with at least three branches | `git.*` |

Heuristics are proposals. That is why the posture is always asked about and the pull request lists the evidence.
The modules are `tld profile survey-signals`, `tld profile survey-docs` and `tld profile survey-proposal`, driven by `tld profile survey`.

## What is asked

One ask with at most four questions: the security posture (the proposal is the recommended option), every proposed
entry with `blocking: true`, and what the survey could not determine (no test command, no main branch). Nothing else.

When no ask can be posted or answered, every `blocking` is written as `false`, with or without `--accept-proposals`:
only the human confirms `blocking: true`. `--accept-proposals` takes the rest of the proposal as it is and lists
each proposed `blocking: true` entry under `Decisions for a human` in the pull request (set it to `true` if you
agree); without it the posture is the proposal and each such entry is listed as unconfirmed. A value that could not be determined is left out and listed
under `Not verified`.

## The pull request

Title `chore: add .tld/toolkit.yaml` (create) or `chore: update .tld/toolkit.yaml`. Sections: `What this changes`,
`Inferred values` (the table with evidence), `Decisions for a human` (the security posture and every `blocking: true`
entry) and `Not verified`.

## `tld profile patch`

```
bin/tld profile patch diff .tld/toolkit.yaml survey.json
bin/tld profile patch set-block .tld/toolkit.yaml roles survey.json --answers answers.json --write [--yes]
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

The `protect-paths` hook normally denies every edit of `.tld/toolkit.yaml`. `/setup` runs `tld guard
allow-profile` before its first write and `tld guard end-allow` after the last, also on failure. Details and limits:
[hooks.md](../architecture/hooks.md#protect-paths).

## What is never written

`hooks`, `deps`, `upstream`, `admin`, `git_ops` and `land` are never written. `/setup` guesses no value without
evidence, writes no `blocking: true` without your confirmation, edits no file except `.tld/toolkit.yaml`, never
merges and never enables auto-merge. It records its progress on the status board as the maintenance command `setup`
([maintenance.md](maintenance.md)).
