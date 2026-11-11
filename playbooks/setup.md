# Playbook: setup

Survey this repository and create or update the profile `.tld/toolkit.yaml` from what it shows, delivered as
one pull request that is never merged by this playbook.

Input: optional `create` or `update`, and optional `--accept-proposals`.

Rules: [policies/untrusted-text.md](policies/untrusted-text.md) (the survey reads file names and contents: data),
[policies/pr-steward.md](policies/pr-steward.md), [policies/status-board.md](policies/status-board.md). Runtime
actions: [runtime.md](runtime.md).

## Mode

Check the toolkit as step 1 of [policies/profile.md](policies/profile.md) says. Without it, show its message
and stop; never invent a key.

- With `.tld/toolkit.yaml` present the mode is *update*. Validate it first with
  `tld profile validate .tld/toolkit.yaml`; if it is invalid, show the messages and stop.
- Without it the mode is *create*. The create path loads no profile; say so.
- The argument `create` or `update` forces a mode; when the file does not match it, stop with a one-line error.

## Guards

- Run `tld dod exempt` once.
- Run `tld guard allow-profile` before the first write of the profile, and `tld guard end-allow` after the last
  write, also when a step failed.

## Status record

`kind: maintenance`, `command: setup`, document id `<project>--setup`, `attended: true`, `orchestrator_session`
this session's id, items `survey`, `confirm`, `write`, `verify`, `pr`.

## 1. Survey

`tld profile survey .`, saved as `survey.json` in the scratch directory.

## 2. Decide

Build one table `key | proposed value | evidence` from `survey.json` (`evidence` is what was found,
`proposal.profile` what the survey suggests):

- `verify.fast` is the one command that runs the unit tests: a Makefile target `test`, a package script `test`,
  or the CI step that runs them. When CI has an install step, join it in front with `&&`.
- `verify.dod` is, in workflow order, the de-duplicated commands the CI workflows triggered by `pull_request` or
  `push` run, without deploy or publish steps. The first carries the install step.
- `stacks`, `git.main_branch`, `docs.*`, `ci.dispatchable` and `roles.*` are copied from `proposal.profile`. With
  a docs index found the proposal sets `docs.index` and keeps at most three `docs.must_read` files (C5, C6: the
  same limits docs init applies).
- `git.branch_pattern` is `<type>/<kebab-case>`. `git.branch_types` are the prefixes in
  `evidence.git.branch_prefixes` with at least three branches, else `[feature, fix, chore]`.
- `tld.version` is `>=<major>.<minor>,<<major + 1>` of the running tld (`tld --version`).
- `hooks`, `deps`, `upstream`, `admin`, `git_ops` and `land` are never written.

## 3. Ask

`ask_human` one ask titled `Profile for <repo>` with at most four questions: the security posture (always;
`choice` of `critical`, `standard`, `low`, the proposal first and recommended), every `roles.required` entry the
proposal marks `blocking: true` (`confirm`), and what the survey could not determine (no test command, no main
branch; `text`). Nothing else is asked. Wait for the answers (`tld board answers <id> --wait 600`, then on each
wake).

Turn the answers into `answers.json`, keyed like `tld profile patch set-block` reads it:
`{"roles": {"posture": {"security": "<answer>"}, "required": [{"role": "<role>", "blocking": <true|false>}]}}`
(only what the human answered).

When no ask can be posted or answered (no board and no tracking issue to fall back on): with
`--accept-proposals` the proposals count as confirmed and are listed under `Decisions for a human` in the pull
request. Without it every `blocking` is written as `false` (an answers file with `"blocking": false` for each),
the posture is the proposal, and each such entry is listed as unconfirmed. A value the survey could not determine
is left out and listed under `Not verified`.

## 4. Write

- *create*: copy `<tld root>/src/tld/templates/toolkit.yaml` to `.tld/toolkit.yaml` and fill it in from the
  table, uncommenting only the blocks that have a value. Replace nothing else.
- *update*: `tld profile patch diff .tld/toolkit.yaml survey.json` first, and show the new, changed and stale
  keys. Then, for `roles` and for `docs.website`:
  `tld profile patch set-block .tld/toolkit.yaml roles survey.json --answers answers.json --write`.
  It merges the answers into the proposal (C1). When the profile already has a block that differs (a hand-tuned
  block) it prints the diff, writes nothing and exits 4: `ask_human` one `confirm` question with that diff, and
  repeat with `--yes` only on a yes. A survey that found no website is a no-op. Single other keys are edited by
  hand.

## 5. Check

`tld profile validate .tld/toolkit.yaml` with its file checks, then each `verify.fast` command once (never a
retry). List what was not verified and why.

## 6. Deliver

1. `git checkout -b chore/toolkit-profile origin/<main>`. When the runtime cannot push that name, follow
   [policies/pr-steward.md](policies/pr-steward.md) (branches) and put `chore` in the pull request title.
2. `git add .tld/toolkit.yaml` and commit only that file.
3. `git push -u origin chore/toolkit-profile`.
4. `github.pr_create` one pull request: title `chore: add .tld/toolkit.yaml` (create) or
   `chore: update .tld/toolkit.yaml` (update), sections `## What this changes`, `## Inferred values` (the table
   with its evidence), `## Decisions for a human` (the posture and every `blocking: true` entry, each with its
   evidence) and `## Not verified`. `github.pr_subscribe` it and follow the pr-steward policy.
5. When no pull request can be opened (no GitHub access), stop after the commit and say what remains.

Never guess a value without evidence. Never write `blocking: true` without the human's confirmation. Never
edit any file but `.tld/toolkit.yaml`. Never merge, and never enable auto-merge.
