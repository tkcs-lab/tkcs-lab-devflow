## Purpose
The tld command line routes `tld <group> <command> [args...]` and the one-word command `tld migrate` to the module that implements each command, prints help and the running version, and reports usage problems with a stable exit code.

## ADDED Requirements

### Requirement: Route a group and command to its module
The system SHALL hand every argument after `tld <group> <command>` unchanged to the module registered for that pair, and SHALL return that module's integer exit code as its own (0 when the module returns no integer).

#### Scenario: Registered command runs
- **WHEN** `tld profile validate <file>` is run
- **THEN** the profile validator runs with `<file>` as its argument and `tld` exits with the validator's exit code

#### Scenario: Fixed leading arguments
- **WHEN** a command registered with fixed leading arguments (for example `tld guard end-allow`) is run
- **THEN** those fixed arguments are placed in front of the user's arguments

### Requirement: Route the one-word migrate command
The system SHALL treat `tld migrate [ROOT] [--write]` as a one-word command and pass everything after `migrate` to the migrate module.

#### Scenario: Migrate is listed and reachable
- **WHEN** `tld migrate --help` is run
- **THEN** the help text of the migrate module is printed and the exit code is 0

### Requirement: Print the version
The system SHALL print `tld <version>` and exit 0 for `tld --version` and for `tld version show`.

#### Scenario: Version flag
- **WHEN** `tld --version` is run
- **THEN** stdout is exactly `tld ` followed by the package version and a newline, exit code 0

#### Scenario: Version subcommand
- **WHEN** `tld version show` is run
- **THEN** the same line is printed and the exit code is 0

### Requirement: List commands in the top-level help
The system SHALL print a usage line and the list of every registered command with a one-line description for `tld --help`, `tld -h` and `tld help`, exiting 0, and SHALL print the same list and exit 2 when `tld` is run with no arguments.

#### Scenario: Help requested
- **WHEN** `tld --help` is run
- **THEN** stdout lists every `<group> <command>` pair and `migrate`, and the exit code is 0

#### Scenario: No arguments
- **WHEN** `tld` is run with no arguments
- **THEN** the usage list is printed and the exit code is 2

### Requirement: Reject unknown commands
The system SHALL print `tld: unknown command '<words>'` followed by the usage list to stderr and exit 2 when the first two words are not a registered pair (including when only one word is given).

#### Scenario: Unknown pair
- **WHEN** `tld profile nosuch` is run
- **THEN** stderr contains the unknown-command message and the usage list, and the exit code is 2

### Requirement: Command help never runs the command
The system SHALL, for `tld <group> <command> --help` or `-h`, exit 0 without running the command; for commands without a parser of their own (the survey commands, `dod exempt`, the `guard allow-*` and `guard end-allow` commands, `board mcp-stdio`, `version show`) it SHALL print a usage line with the one-line description and the module's documentation instead.

#### Scenario: Help for a command without its own parser
- **WHEN** `tld guard allow-profile --help` is run in a git repository
- **THEN** stdout starts with `usage: tld guard allow-profile`, the exit code is 0 and no marker file is written under `.git/tld`

### Requirement: Keep the CLI reference complete
The system SHALL have every registered command appear as `tld <group> <command>` in `docs/reference/cli.md`, and every `tld` call in the playbooks and adapter files SHALL name a registered command whose `--help` lists the flags used.

#### Scenario: Reference lists all commands
- **WHEN** the reference document is compared with the command registry
- **THEN** no registered command is missing from the document
