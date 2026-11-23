# spec-and-architecture-models Specification

## Purpose
`tld ops spec` runs a pinned OpenSpec release through five fixed subcommands, and `tld ops sysml` keeps an architecture model written in a small subset of the SysML v2 textual notation, with changes, checks, rendering and archiving. Together they let playbooks build and validate specs and models without free-form tool arguments.

## Requirements

### Requirement: Fixed OpenSpec subcommands
The system SHALL accept only the subcommands init, new-change ID, list [--json], validate [--change ID] [--json] and archive ID for `tld ops spec`, each with optional `--profile` and `--root`, and SHALL pass no other argument through to OpenSpec.

#### Scenario: Each form runs a fixed command
- **WHEN** a subcommand is run
- **THEN** OpenSpec runs in the `--root` directory with a fixed argument list: init without tool files and without animation, new change ID, list of specs, validate of everything (or one change) in strict non-interactive mode, and archive ID with automatic confirmation

#### Scenario: Unknown or extra arguments
- **WHEN** an unknown subcommand or an extra argument is given
- **THEN** nothing runs and the exit code is 2

#### Scenario: Invalid id
- **WHEN** an ID or `--change` value is not lower-case words joined by hyphens
- **THEN** an "invalid id" message is printed on stderr, nothing runs and the exit code is 2

### Requirement: Pinned OpenSpec version from the profile
The system SHALL read the OpenSpec release from `spec.version` of the profile (default `.tld/toolkit.yaml` under `--root`) and SHALL require it to be an exact release of the form X.Y.Z.

#### Scenario: Profile problems
- **WHEN** the profile file is missing, has no `spec` block or no `spec.version`
- **THEN** a message on stderr names the problem (the missing key message points to the spec guide), nothing runs and the exit code is 2

#### Scenario: Inexact version
- **WHEN** `spec.version` is not an exact X.Y.Z string (a range, a tag or a number)
- **THEN** the exit code is 2 and the message says an exact release is needed

### Requirement: Node requirement and isolated install
The system SHALL require node and npm on the path and Node.js 22.20.0 or newer, and SHALL install the pinned OpenSpec once per version into the cache directory (TLD_CACHE_DIR, default a `.cache/tld` folder in the home directory) outside the repository, without running install scripts.

#### Scenario: Node missing or too old
- **WHEN** node or npm is absent, the node version cannot be read, or it is older than 22.20.0
- **THEN** a message naming the requirement is printed on stderr and the exit code is 2

#### Scenario: First and later runs
- **WHEN** the pinned version is not yet in the cache
- **THEN** it is installed before the first run; a second call finds it and skips the install

#### Scenario: Install problems
- **WHEN** the install fails, or the installed package version differs from the pinned one
- **THEN** a message is printed on stderr and the exit code is 2

### Requirement: Contained OpenSpec run
The system SHALL run npm and node with an allowlisted environment (path, home, locale, proxy and certificate variables only, no tokens, with telemetry off and CI mode on), with standard input closed, and SHALL end a run that lasts more than 600 seconds.

#### Scenario: Exit code passthrough
- **WHEN** OpenSpec finishes
- **THEN** `tld ops spec` exits with OpenSpec's own exit code, unchanged

#### Scenario: Timeout
- **WHEN** a run exceeds 600 seconds
- **THEN** a "did not finish within 600 seconds" message is printed on stderr and the exit code is 2

#### Scenario: Secrets stay out
- **WHEN** the caller's environment holds tokens
- **THEN** they are not visible to npm or node

### Requirement: Architecture model commands and gating
The system SHALL provide `tld ops sysml` with exactly the subcommands new-change ID, check, render and archive ID, each with optional `--profile` and `--root`, requiring `sysml.subset` equal to the integer 1 in the profile, and SHALL exit 0 when ok, 1 on findings or drift and 2 when it cannot run.

#### Scenario: Cannot run
- **WHEN** a usage error occurs, an id or file path is invalid, the profile is missing, has no sysml block or a subset other than 1, there are no files under `sysml/model`, a path is a symbolic link, or a file system error occurs
- **THEN** a one-line message prefixed `tld ops sysml:` (escaped, bounded in length) goes to stderr and the exit code is 2

#### Scenario: Missing block message
- **WHEN** the profile has no `sysml.subset`
- **THEN** the message points to the sysml guide and has no prefix

#### Scenario: Reserved and malformed ids
- **WHEN** the change id is `archive`, longer than 100 characters or not lower-case words joined by hyphens
- **THEN** the exit code is 2

### Requirement: Model check
The system SHALL, for `tld ops sysml check [--change ID] [--json]`, parse every `.sysml` file under `sysml/model` and report problems as `<file>:<line>: <message>`.

#### Scenario: Clean model
- **WHEN** the model has no finding
- **THEN** `sysml: ok (<n> elements)` is printed and the exit code is 0

#### Scenario: Findings
- **WHEN** the model has a syntax problem (an unexpected, control or bidirectional character, a reserved word or over-long name, nesting deeper than 6 levels, an unsupported element, a doc that is too long, repeated or holds a link or a credential-like text), a duplicate name, a part def without a doc, an unknown or wrong-kind type or reference, or a connect to a part or port that does not exist
- **THEN** each finding is printed on one line and the exit code is 1

#### Scenario: Size limits
- **WHEN** the model has more than 300 elements or 600 relations
- **THEN** a single finding names the limit and the exit code is 1; a model over 50 files, 100000 bytes per file or 1000000 bytes in total exits 2

#### Scenario: JSON output
- **WHEN** `--json` is given
- **THEN** one JSON object with `ok`, `findings` (file, line, message) and `changes` (op, kind, qname) is printed, with exit 1 if there are findings

#### Scenario: Check a change
- **WHEN** `--change ID` is given
- **THEN** the change is applied in memory, its proposal and base records are checked, and the added, changed and removed elements against the current model are listed after any findings

### Requirement: Create and extend a change
The system SHALL, for `tld ops sysml new-change ID [--file R]... [--remove R]...`, create `sysml/changes/<ID>/` with a proposal skeleton, copies of the model files to replace and a base record of their content hashes, and print `created` or `updated` with the change folder.

#### Scenario: Skeleton
- **WHEN** a change is created
- **THEN** its proposal has the headings Why, What Changes and Impact, each containing TODO, which `check --change` reports as findings until they are filled in

#### Scenario: Repeat call
- **WHEN** the command runs again for the same ID with more files
- **THEN** it only adds, keeps existing edited copies and prints `updated`

#### Scenario: Refusals
- **WHEN** a named model file does not exist, a file is both replaced and removed, an existing copy has no recorded base, or the base record is invalid
- **THEN** nothing is written and the exit code is 2

#### Scenario: Stale or empty change
- **WHEN** a model file changed after the change was written, a copy is listed but missing, a change changes nothing, or the base record is missing
- **THEN** `check --change` reports a finding and exits 1

### Requirement: Render the model
The system SHALL, for `tld ops sysml render`, write `docs/architecture.svg` and `docs/architecture.md` from a model without findings, printing `wrote <path>` for each, and SHALL produce byte-identical output for the same model regardless of the clock or hash seed.

#### Scenario: Findings or limits
- **WHEN** the model has findings
- **THEN** they are printed, nothing is written and the exit code is 1

#### Scenario: Foreign output file
- **WHEN** an existing output file carries no tld stamp
- **THEN** the message says it was not generated by tld and must be moved, nothing is written and the exit code is 2

#### Scenario: Unsafe output paths
- **WHEN** the docs directory or an output file is a symbolic link or a hard-linked file
- **THEN** nothing is written and the exit code is 2

### Requirement: Render drift check
The system SHALL, for `tld ops sysml render --check`, write nothing and compare both outputs to what would be rendered.

#### Scenario: Up to date
- **WHEN** both files match
- **THEN** `sysml: docs up to date` is printed and the exit code is 0

#### Scenario: Drift
- **WHEN** a file is missing, differs, or was drawn by another layout version
- **THEN** one line per file says to run `tld ops sysml render` and the exit code is 1; an unstamped file counts as out of date rather than refused

### Requirement: Archive a change
The system SHALL, for `tld ops sysml archive ID`, apply a clean change to `sysml/model`, move the change folder to `sysml/changes/archive/<UTC date>-<ID>`, redraw both outputs and print `archived <source> to <destination>`.

#### Scenario: Successful archive
- **WHEN** the change checks clean
- **THEN** replaced files are written, removed files are deleted, the change folder is moved, the outputs are redrawn and the exit code is 0

#### Scenario: Findings or stale base
- **WHEN** the change has findings or a model file changed since the change was written
- **THEN** the findings are printed, nothing is written and the exit code is 1

#### Scenario: Unsafe or blocked
- **WHEN** the change does not exist, the destination exists, a path is a symbolic link or hard link, or an output is not tld-generated
- **THEN** nothing is written and the exit code is 2

#### Scenario: Failure while applying
- **WHEN** a write or move fails midway
- **THEN** every applied step is undone and the message says the model was restored; if an undo also fails the message names the files left changed (up to three) and says to restore them from git, and the exit code is 2
