## Why

The weekly dependency run opens one pull request per update group, so the owner reviews and merges several
pull requests for one week's updates. One combined pull request per run needs two deterministic steps the
playbook cannot do safely by hand: applying several groups onto one branch without merging lockfiles as text,
and rendering a pull request body from data that comes from untrusted pull request titles.

## What Changes

- New command `tld ops deps-prepare`: builds a branch from a base ref and applies the changes of each group ref
  except lockfiles, reports per group whether it was applied or left out and why, and lists the lock commands
  of the profile that must regenerate the skipped lockfiles. It never pushes and never runs a profile command.
- New command `tld ops deps-body`: renders the combined pull request body from a strictly validated JSON file,
  security groups first, with a Summary that passes the pull request Summary check.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-and-repo-ops`: two added requirements for the dependency commands.

## Impact

`src/tld/ops/deps_prepare.py` and `src/tld/ops/deps_body.py` (new), `src/tld/cli.py`, the deps playbook, the maintenance guide, the CLI reference and
the evals. No profile key changes.
