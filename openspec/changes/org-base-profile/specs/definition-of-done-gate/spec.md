## REMOVED Requirements

### Requirement: Opt-in gate
**Reason**: The gate is now on by default; "opt-in" no longer describes it.
**Migration**: Replaced by "Default-on gate" below; a repository that does not want the gate writes `hooks.dod_gate.enabled: false`, which a base may forbid.

## ADDED Requirements

### Requirement: Default-on gate
The system SHALL run the dod-gate Stop hook unless the resolved profile sets `hooks.dod_gate.enabled` to false or `dod-gate` is disabled through the profile's `disable` list, and SHALL let a session stop without any check when the repository has no profile.

#### Scenario: On by default
- **WHEN** the profile has no `hooks.dod_gate` and a Stop event arrives with failing `verify.dod` commands in a session that changed files
- **THEN** the hook blocks the stop

#### Scenario: Switched off
- **WHEN** `hooks.dod_gate.enabled` is false and a Stop event arrives with failing `verify.dod` commands
- **THEN** the hook exits 0 and runs nothing

#### Scenario: Disabled by name
- **WHEN** `dod-gate` is in the disable list read from the main branch
- **THEN** a failing session is allowed to stop with exit 0
