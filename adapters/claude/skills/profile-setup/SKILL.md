---
name: profile-setup
description: Rules the /setup command follows to turn a repository survey into .claude/toolkit.yaml values - how to choose the verify commands, which keys come from evidence, what to ask the user, and what the pull request says. Load it in step 2 of /setup.
user-invocable: false
---

# Turning a survey into a profile

Input is `survey.json` from `profile_survey.py`: `evidence` (what was found) and `proposal.profile` (what the survey suggests).

## Choosing verify commands

- `verify.fast` is the one command that runs the unit tests: a Makefile target `test`, a package script `test`, or the CI step that runs them. When CI has an install step, join it in front with `&&`.
- `verify.dod` is, in workflow order, the de-duplicated commands that the CI workflows triggered by `pull_request` or `push` run, without deploy or publish steps. The first one carries the install step.
- When the survey finds no test command, ask (see Questions).

## Mapping evidence to keys

- `stacks`, `git.main_branch`, `docs.*`, `ci.dispatchable` and `agents.*` are copied from `proposal.profile`.
- `git.branch_pattern` is `<type>/<kebab-case>`. `git.branch_types` are the prefixes in `evidence.git.branch_prefixes` with at least three branches, else the default `[feature, fix, chore]`.
- `docs.must_read` comes from the proposal.
- `hooks`, `deps`, `upstream`, `admin`, `git_ops` and `land` are never written.

## Questions

The posture question offers `critical`, `standard` and `low`, with the proposal first and "(Recommended)" on it. When `AskUserQuestion` is unavailable or refused: with `--accept-proposals` the proposals count as confirmed; otherwise every `blocking` is written as `false` and each entry is noted as unconfirmed (command section 3).

## Pull request body

Title `chore: add .claude/toolkit.yaml` (create) or `chore: update .claude/toolkit.yaml` (update). Sections:

- `## What this changes`
- `## Inferred values`: the table with its evidence
- `## Decisions for a human`: the security posture and every `blocking: true` entry, each with the evidence that led to it
- `## Not verified`

## Never

Never guess a value without evidence. Never write `blocking: true` without the user's confirmation. Never edit any file except `.claude/toolkit.yaml`. Never merge, and never enable auto-merge.
