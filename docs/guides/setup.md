# `/setup`

`/setup` surveys a repository and creates or updates `.claude/toolkit.yaml`, including the `agents` block
([agents.md](../architecture/agents.md)). It delivers the result as one pull request that it never merges. Reference for the file:
[profile-reference.md](../reference/profile-reference.md).

## Modes

- **create**: there is no `.claude/toolkit.yaml`. The command copies the starter profile and fills in the blocks that
  have a value. It loads no profile and never invents a key.
- **update**: the file exists. It is validated first (an invalid file stops the command). New and changed values are
  patched in at text level, so every other byte, comments included, stays as it was.

`/setup create` or `/setup update` forces a mode and stops with a one-line error when the file does not match.
`--accept-proposals` is for runs where nobody can answer questions (see [What is asked](#what-is-asked)).

## The flow

1. **Survey.** `scripts/profile_survey.py` prints JSON: stacks, CI workflows, verify evidence, git facts, docs and the
   signals below, plus a proposal.
2. **Decide.** The `profile-setup` skill turns the evidence into a table `key | proposed value | evidence`.
   `verify.fast` is the command that runs the unit tests; `verify.dod` is the de-duplicated commands the CI workflows
   run on `pull_request` or `push`, without deploy or publish steps.
3. **Ask.** One question call, at most four questions.
4. **Write.** Create: copy the starter and edit it. Update: `profile_patch.py diff` shows new, changed and stale keys,
   then `profile_patch.py set-block` replaces the `agents` and `docs.website` blocks.
5. **Check.** The profile is validated with file checks and each `verify.fast` command runs once.
6. **Deliver.** Branch `chore/toolkit-profile` from the main branch, one commit with only `.claude/toolkit.yaml`, one
   pull request. It follows `pr-steward` afterwards and never merges. Without GitHub access it stops after the commit and
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
The modules are `survey_signals.py`, `survey_docs.py` and `survey_proposal.py`, driven by `profile_survey.py`.

## What is asked

One call with at most four questions: the security posture (the proposal is the recommended option), every proposed
entry with `blocking: true`, and what the survey could not determine (no test command, no main branch). Nothing else.

When questions cannot be asked: with `--accept-proposals` the proposals count as confirmed and are listed under
`Decisions for a human` in the pull request; without it every `blocking` is written as `false`, the posture is the
proposal, and each such entry is listed as unconfirmed. A value that could not be determined is left out and listed
under `Not verified`.

## The pull request

Title `chore: add .claude/toolkit.yaml` (create) or `chore: update .claude/toolkit.yaml`. Sections: `What this changes`,
`Inferred values` (the table with evidence), `Decisions for a human` (the security posture and every `blocking: true`
entry) and `Not verified`.

## `profile_patch.py`

```
python3 plugins/devflow/scripts/profile_patch.py diff .claude/toolkit.yaml survey.json
python3 plugins/devflow/scripts/profile_patch.py set-block .claude/toolkit.yaml agents survey.json --write
```

`diff` prints JSON with `new`, `changed`, `same` and `stale` keys; stale means a path the profile names no longer exists,
or an `agents.required[].when` glob matches no file. `set-block` replaces the `agents` block (or `docs.website` under
`docs`) or appends it, and leaves comments, blank lines and neighbouring blocks untouched. It writes to stdout unless
`--write` is given, and applying the same value twice gives the same text.

## The guardrail exemption

The `protect-paths` hook normally denies every edit of `.claude/toolkit.yaml`. `/setup` runs `protect_paths.py
--allow-profile` before its first write and `--end-allow` after the last, also on failure. Details and limits:
[hooks.md](../architecture/hooks.md#protect-paths).

## What is never written

`hooks`, `deps`, `upstream`, `admin`, `git_ops` and `land` are never written. `/setup` guesses no value without
evidence, writes no `blocking: true` without your confirmation, edits no file except `.claude/toolkit.yaml`, never
merges and never enables auto-merge. It records its progress on the status board as the maintenance command `setup`
([maintenance.md](maintenance.md)).
