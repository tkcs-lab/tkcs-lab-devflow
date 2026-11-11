---
description: "Survey this repository and create or update .tld/toolkit.yaml, delivered as one pull request that is never merged"
argument-hint: "[optional: create | update] [--accept-proposals]"
model: sonnet
---

Create or update the project profile `.tld/toolkit.yaml` from what the repository shows, and deliver it as one pull request.

## Profile

Load the `project-profile` skill and follow the first step of its "Loading the profile" section ("Find the toolkit"). If the toolkit is not installed, show its message and stop; never substitute a value of your own for a missing key.
Skill names carry a plugin prefix (`tld:project-profile`, `tld:profile-setup`, `tld:status-board`, `tld:pr-steward`); use whichever form the skill list shows.

- With `.tld/toolkit.yaml` present the mode is *update*. Validate it first with `"${CLAUDE_PLUGIN_ROOT}/bin/tld" profile validate .tld/toolkit.yaml`; if it is invalid, show the messages and stop.
- Without it the mode is *create*. The create path loads no profile; say so, and never invent a key.
- The argument `create` or `update` forces a mode. When the file does not match it, stop with a one-line error.

## Guardrail hooks

- Run `"${CLAUDE_PLUGIN_ROOT}/bin/tld" dod exempt` once.
- Run `"${CLAUDE_PLUGIN_ROOT}/bin/tld" guard allow-profile` before the first write of the profile.
- Run `"${CLAUDE_PLUGIN_ROOT}/bin/tld" guard end-allow` after the last write, also when a step failed.

## 1. Survey

Run `"${CLAUDE_PLUGIN_ROOT}/bin/tld" profile survey .` and save the output as `survey.json` in the scratchpad directory.

## 2. Decide

Load the `profile-setup` skill. Build one table `key | proposed value | evidence`. `verify.fast` and `verify.dod` are chosen from `evidence.verify_evidence` by the skill's rules.

## 3. Ask

Make one `AskUserQuestion` call with at most four questions: the security posture (always asked, the proposal is the recommended option), every entry the proposal marks `blocking: true`, and whatever the survey could not determine (no test command, no main branch). Nothing else is asked.

When `AskUserQuestion` is unavailable or refused: with the argument `--accept-proposals` the proposals count as confirmed and are listed under `Decisions for a human` in the pull request. Without it every `blocking` is written as `false`, the posture is the proposal, and each such entry is listed under `Decisions for a human` as unconfirmed. A value the survey could not determine is left out of the profile and listed under `Not verified`.

## 4. Write

- *create*: copy `${CLAUDE_PLUGIN_ROOT}/src/tld/templates/toolkit.yaml` to `.tld/toolkit.yaml` and fill it in from the table of step 2 with the Edit tool, uncommenting only the blocks that have a value. Replace nothing else.
- *update*: run `tld profile patch diff` first (`"${CLAUDE_PLUGIN_ROOT}/bin/tld" profile patch diff .tld/toolkit.yaml survey.json`) and show the new, changed and stale keys. Then run `tld profile patch set-block` (`"${CLAUDE_PLUGIN_ROOT}/bin/tld" profile patch set-block .tld/toolkit.yaml agents survey.json --write`) and the same for `docs.website` (both take `survey.json` itself as the value file); use the Edit tool for single other keys.

## 5. Check

Run `"${CLAUDE_PLUGIN_ROOT}/bin/tld" profile validate .tld/toolkit.yaml` with its file checks, then each `verify.fast` command once (never a retry). List what was not verified and why.

## 6. Deliver

1. Create the branch with `git checkout -b chore/toolkit-profile origin/<main>`. A session that cannot push that name uses its assigned branch and puts `chore` in the pull request title, as `pr-steward` says.
2. Stage with `git add .tld/toolkit.yaml` and commit only `.tld/toolkit.yaml`.
3. Push with `git push -u origin chore/toolkit-profile`.
4. Open one pull request with `create_pull_request`, using the body of the `profile-setup` skill. Never merge it. Subscribe to it and follow `pr-steward`.
5. When no pull request can be opened (no GitHub access), stop after the commit and say what remains.

This command never merges and never enables auto-merge.

## Status board

Follow the `status-board` skill's `## /setup records` section: `kind: maintenance`, `command: setup`, document id `<project>--setup`, `orchestrator_session` the real session id, items `survey`, `confirm`, `write`, `verify`, `pr`. Alerts are push only, never a rename.
