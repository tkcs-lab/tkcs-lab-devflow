## Why

After an approving final review, non-blocking findings are only reported. A fix round makes the pull request list each one as fixed or declined with a reason, and `tld plan summary-check` must be able to check that list (issue #88).

## What Changes

- `tld plan summary-check` checks a `## Non-blocking findings` section of a pull-request body: the row grammar, the declined reason, and with `--findings N` exactly N rows.
- `--findings N` is a new option, valid with `--kind pr` only.

## Capabilities

### Modified Capabilities

- `plan-run-tracking`: the requirement "Summary section check" gains the findings section rules.

## Impact

`src/tld/plan/summary.py`, the new `src/tld/plan/findings.py`, the playbooks that call `summary-check` for a pull request body. No architecture model change: the new module sits inside the existing plan part.
