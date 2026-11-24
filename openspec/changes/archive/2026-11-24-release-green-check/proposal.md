## Why

The release skill asked the owner for the go while the tests of the merged release commit were still running, so the dispatch of the release workflow failed its green-commit check. The skill needs the same verdict the workflow reaches, before the question.

## What Changes

- A new command `tld ops release-check` judges the check runs and the combined status of a commit and says green, waiting or red.
- The `tld-release` workflow template judges the commit by the same rule.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-and-repo-ops`: two added requirements.

## Impact

`src/tld/ops/release_check.py`, `src/tld/cli.py`, `src/tld/templates/tld-release.yml`, `playbooks/release.md`. Repositories with an installed `tld-release.yml` get the new step through the repo-admin `workflows` entry (one pull request per repository, never merged by tld).
