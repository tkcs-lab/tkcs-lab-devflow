## Why

A repository that uses tld has many sources an agent can read: the entry file, the docs index and its leaf docs, the ADRs, the OpenSpec specs, the SysML model and its drawn architecture doc, the changelog and the kept plans. Nothing tells a session which source answers which kind of question, so sessions read too much or guess, which costs tokens and gives weaker answers.

## What Changes

- A new subcommand `tld ops docs-index guide` prints a short reading guide built from the profile (only the sources the repository declares), and with `--write` puts it into the entry file between two markers without dropping any existing text.
- `tld ops docs-index check` warns when the written guide no longer matches the profile and reports broken markers as errors.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-and-repo-ops`: one added requirement and one modified requirement.

## Impact

`src/tld/ops/reading_guide.py` (new), `src/tld/ops/docs_index.py`, `playbooks/policies/docs.md`, `playbooks/docs.md`, `playbooks/ask.md`, `playbooks/make-plan.md`, `docs/guides/docs-index.md`, `docs/reference/cli.md`, `AGENTS.md`. Other repositories get the guide when docs init runs, when a plan's last phase runs, or when the owner runs the command once; a repository without the markers sees no new message.
