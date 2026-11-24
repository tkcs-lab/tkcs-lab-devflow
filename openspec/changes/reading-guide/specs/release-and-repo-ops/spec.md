## ADDED Requirements

### Requirement: Docs reading guide
The system SHALL, for `tld ops docs-index guide [--profile PATH] [--root DIR] [--index PATH] [--write]`, build a reading guide from the profile alone, enclosed by the line `<!-- tld:reading-guide v1 -->` and the line `<!-- /tld:reading-guide -->`, print it without `--write`, and with `--write` put it into the entry file, which is `AGENTS.md` when the root `CLAUDE.md` links to a root `AGENTS.md` file and `CLAUDE.md` otherwise.

#### Scenario: Only declared sources
- **WHEN** the guide is built
- **THEN** it always names the docs index from the profile and the code search, and names the specs only with a `spec` profile block, the architecture doc only with a `sysml` block, the ADR index only with `docs.adr_dir`, and the changelog only with `docs.changelog`

#### Scenario: Same profile, same guide
- **WHEN** the guide is built twice from the same profile
- **THEN** both outputs are byte for byte equal, and a second `--write` prints `unchanged <entry file>` and leaves the file as it was

#### Scenario: Write keeps existing text
- **WHEN** `--write` runs on an entry file with the two markers, with a `## Docs` heading and no markers, or with neither
- **THEN** it replaces only the lines from the start marker to the end marker, or inserts the guide directly under the `## Docs` heading, or appends a `## Docs` section with the guide, keeps every other line, prints `wrote <entry file>` and exits 0

#### Scenario: Refused write
- **WHEN** the entry file is missing, is a symbolic link or lies outside the root, its markers are duplicated, unbalanced or of another version, a profile path is absolute, climbs out of the root or holds a character that would break a link, or the file would exceed 60 lines
- **THEN** `docs index guide: <reason>` goes to stderr, nothing is written and the exit code is 1

## MODIFIED Requirements

### Requirement: Docs index check
The system SHALL, for `tld ops docs-index check`, report errors and warnings one per line as `error: ...` or `warning: ...`, end with `docs index: <e> error(s), <w> warning(s)`, and exit 1 on an error (or on a warning with `--strict`), else 0.

#### Scenario: Errors
- **WHEN** CLAUDE.md is missing, longer than 60 lines (`--max-claude-lines`) or does not link to the index, the index is missing or longer than 150 lines, a relative link in CLAUDE.md or an index file is broken, a doc is linked from no index file, an ADR is missing from the ADR index, the entry file's reading guide markers are duplicated, unbalanced or of another version, or both CLAUDE.md and AGENTS.md hold a reading guide
- **THEN** an error line names it and the exit code is 1

#### Scenario: Exempt documents
- **WHEN** a doc is a plan, review or deviations file, a plan record under the plan directory, or lies under an archive directory
- **THEN** it needs no index row

#### Scenario: Warnings
- **WHEN** a link in another doc is broken, a doc exceeds 400 lines, an index row has no description, a link is listed twice, (with `--stale-days N`) a doc has not changed in git for N days, or the entry file's reading guide differs from the one the profile gives
- **THEN** a warning line is printed and the exit code is 0 unless `--strict` is given

#### Scenario: No reading guide
- **WHEN** the entry file holds no reading guide markers
- **THEN** no line is printed about the reading guide

#### Scenario: JSON and missing index setting
- **WHEN** `--json` is given
- **THEN** a JSON object with errors and warnings is printed
- **WHEN** neither the profile's docs index key nor `--index` is given
- **THEN** a message about the missing key goes to stderr and the exit code is 2
