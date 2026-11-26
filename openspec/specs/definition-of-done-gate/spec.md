# definition-of-done-gate Specification

## Purpose
Keep a coding session from stopping while the profile's definition-of-done commands fail, through an opt-in Stop hook named dod-gate, without looping forever, and let an orchestrator session exempt itself with `tld dod exempt`.

## Requirements

### Requirement: Blocking a red definition of done
The system SHALL, when the gate is enabled and the tree has changes, run every `verify.dod` command (a string, or a mapping with `run` and optional `cwd` under the project) through the shell, run all of them even after a failure, and block the stop by exiting 2 with a message on stderr that names the attempt, each failing command with its exit code, timeout or start error, and the last lines of its output.

#### Scenario: Failing command
- **WHEN** a command exits non-zero
- **THEN** the hook exits 2 and stderr says the definition of done is red with "attempt 1 of 3" and the command's exit code and output tail

#### Scenario: Several failures
- **WHEN** two commands fail and a third passes
- **THEN** both failing commands are named in the message and the passing one is not

#### Scenario: Working directory and timeout
- **WHEN** a command has a `cwd`, or the total time budget (1700 seconds) is used up
- **THEN** it runs in that directory under the project, and commands that cannot run in the budget are reported as not run and count as failures

### Requirement: Pass once per tree state
The system SHALL let the session stop with exit 0 and no output when all commands pass, and SHALL NOT rerun the commands while the tree (HEAD, status, diff and untracked files) is unchanged since the last pass.

#### Scenario: Green gate
- **WHEN** all commands pass
- **THEN** the hook exits 0 and a second Stop on the same tree runs no command

#### Scenario: Tree changes
- **WHEN** a file changes after a pass
- **THEN** the commands run again

### Requirement: Only sessions with work are checked
The system SHALL check a session only when the working tree is dirty or HEAD has commits that the remote main branch (or, failing that, the local main branch) lacks, treating "cannot tell" as changed.

#### Scenario: Clean and level with main
- **WHEN** the tree is clean and HEAD has no commit ahead of main
- **THEN** the hook exits 0 without running commands

#### Scenario: Committed work
- **WHEN** the tree is clean but HEAD is ahead of the remote main branch
- **THEN** the commands run

### Requirement: Attempt limit
The system SHALL count failed attempts per session, never loop, and after `hooks.dod_gate.max_attempts` failed attempts (default 3, integer from 1 to 10) let the session stop with exit 0 and a `systemMessage` on stdout that names the failing commands, the count and the limit; it SHALL also stop blocking when the Stop event is a continuation and the counter cannot be saved.

#### Scenario: Limit reached
- **WHEN** the gate has failed as many times as the limit
- **THEN** the next Stop exits 0 with a message that the definition of done is still red, and the same tree is not blocked again

#### Scenario: Separate sessions
- **WHEN** two sessions fail in the same checkout
- **THEN** each has its own attempt count

#### Scenario: Configured limit
- **WHEN** `max_attempts` is 1
- **THEN** the first failure already lets the session stop with the message

### Requirement: Profile problems
The system SHALL treat a broken profile (missing `verify.dod`, missing `git.main_branch`, a `verify.dod` entry that is neither a string nor a mapping with `run`, a `hooks.dod_gate` that is not a mapping, a malformed `disable`, or a `max_attempts` that is not a positive integer or exceeds 10) as a failed attempt: the hook exits 2 with the problem on stderr, and after the same attempt limit exits 0 with the problem in a `systemMessage`.

#### Scenario: Missing dod key
- **WHEN** the gate is enabled and the profile has no `verify.dod`
- **THEN** the first two Stop events exit 2 naming the missing key and the third exits 0 with a message that the profile is still broken

#### Scenario: Too many attempts configured
- **WHEN** `max_attempts` is above 10
- **THEN** stderr says it must be between 1 and 10 and the exit code is 2

### Requirement: Exempt session
The system SHALL, through `tld dod exempt`, write an exempt marker in the checkout's private git state directory, print `dod-gate: this session is exempt (<marker path>)` and exit 0; while the marker is younger than 24 hours the gate SHALL let that checkout's sessions stop, and every Stop that sees the marker refreshes its age.

#### Scenario: Orchestrator stops
- **WHEN** `tld dod exempt` was run in the checkout and a Stop event arrives with failing commands
- **THEN** the hook exits 0 and runs nothing

#### Scenario: Marker lapses
- **WHEN** the marker is more than a day old and was not refreshed
- **THEN** the gate applies again

#### Scenario: Fresh clone
- **WHEN** a child session works in its own fresh clone
- **THEN** it has no marker and is gated

### Requirement: Hook script contract
The system SHALL accept the Stop event as JSON on stdin in the hook script, print nothing on stdout when blocking, and exit 2 when the script is called with an unknown flag.

#### Scenario: Blocking output
- **WHEN** the script blocks a stop
- **THEN** the exit code is 2, the failure text is on stderr and stdout is empty

#### Scenario: Unknown flag
- **WHEN** the script or `tld dod` is given an argument other than the exempt flag
- **THEN** usage text is printed on stderr and the exit code is 2

### Requirement: Default-on gate
The system SHALL run the dod-gate Stop hook unless the resolved profile sets `hooks.dod_gate.enabled` to false or `dod-gate` is disabled through the profile's `disable` list, and SHALL let a session stop without any check when the repository has no profile. The gate SHALL read `verify.dod` and `max_attempts` from the profile on the remote's default branch when that copy is available, and from the working tree only when no such copy is available.

#### Scenario: On by default
- **WHEN** the profile has no `hooks.dod_gate` and a Stop event arrives with failing `verify.dod` commands in a session that changed files
- **THEN** the hook blocks the stop

#### Scenario: Switched off
- **WHEN** `hooks.dod_gate.enabled` is false and a Stop event arrives with failing `verify.dod` commands
- **THEN** the hook exits 0 and runs nothing

#### Scenario: Commands come from the default branch
- **WHEN** a branch's profile changes `verify.dod` and the default branch's copy is available
- **THEN** the hook runs the default branch's commands

#### Scenario: Disabled by name
- **WHEN** `dod-gate` is in the disable list read from the main branch
- **THEN** a failing session is allowed to stop with exit 0
