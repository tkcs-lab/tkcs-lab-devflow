## MODIFIED Requirements

### Requirement: Protected path edits
The system SHALL deny edits, by the Write tools and by visible Bash writes, to paths listed in the resolved profile's `hooks.protect_paths` and always to the git configuration, hooks and ref files, the plugin's installed files, the agent runtime's own settings and the workflows that start a release, a land run or a branch deletion (the land and release workflow files, the profile's `release.workflow` and `tld-git-ops.yml`), while always allowing `.env.example`, `.env.sample`, `.env.template` and `.env.dist`.

#### Scenario: Default protected paths
- **WHEN** the profile does not set `hooks.protect_paths`
- **THEN** the default list applies: `.env` and `.env.*`, lockfiles (`*.lock`, `package-lock.json`, `go.sum`); the profile file and ordinary workflow files are not on it

#### Scenario: Visible Bash writes
- **WHEN** a Bash command writes to a protected path by a redirect, `tee`, `sed -i`, `cp`, `mv`, `rm`, `git apply`, a directory-wide checkout or extraction, or a similar visible write
- **THEN** it is denied

#### Scenario: Environment file
- **WHEN** a command is `echo x > .env`
- **THEN** it is denied; `echo x > .env.example` is allowed, as are `.env.sample`, `.env.template` and `.env.dist`

#### Scenario: Git config write
- **WHEN** a command sets an `alias.*`, `remote.*`, `push.*`, `branch.*` or `core.hooksPath` key with `git config`
- **THEN** it is denied

#### Scenario: Tld workflow files
- **WHEN** a session writes the land workflow, the release workflow (the default name or the profile's `release.workflow`) or the git-ops workflow and no workflow-install marker names that file
- **THEN** the write is denied whatever the profile lists

#### Scenario: Profile and ordinary workflows
- **WHEN** the profile does not list them and a session edits `.tld/toolkit.yaml` or an ordinary workflow file
- **THEN** the edit is allowed

#### Scenario: Changelog
- **WHEN** the profile names a changelog and an edit adds a new version heading together with other changes
- **THEN** the edit is denied; a changelog-only change is allowed

### Requirement: Plan gate
The system SHALL, unless `hooks.plan_gate.enabled` is false in the resolved profile, deny writes into the repository (write tools, writing Bash commands and the GitHub content-write tools) in a session that no plan-starting command opened, while never blocking a prompt, and SHALL add one sentence of context to a plain prompt in a closed session telling the agent to answer or research only and to propose a plan.

#### Scenario: On by default
- **WHEN** the repository has a profile that does not set the gate and a plain session writes a file
- **THEN** the write is denied

#### Scenario: Off by default
- **WHEN** the resolved profile sets `hooks.plan_gate.enabled` to false
- **THEN** all writes are allowed

#### Scenario: No profile
- **WHEN** the repository has no profile
- **THEN** all writes are allowed

#### Scenario: Closed session
- **WHEN** the gate is enabled and no command opened the session, and a Write targets a file in the repository
- **THEN** the write is denied; a write outside the repository or inside the git directory, and a read-only command, are allowed

#### Scenario: Opening
- **WHEN** a prompt starts with a plan-starting command such as `/tld:make-plan`, or the plan marker exists, or a prompt has a line starting `tld-worker: ` with a session id
- **THEN** the session is open and writes are allowed

#### Scenario: Fail open
- **WHEN** the event has no session id and no marker exists, or the `hooks.plan_gate` section is malformed
- **THEN** the write is allowed (the malformed section shows a notice)

### Requirement: Board gate
The system SHALL, unless `hooks.board_gate.enabled` is false in the resolved profile, block the end of a turn (Stop) at most once per event when a session started by a record-writing command has not written its status record, has changed things since the last record, or posted an ask and armed no timer, and SHALL never deny any other event.

#### Scenario: On by default
- **WHEN** the repository has a profile that does not set the gate and a session started by a record-writing command stops before any record write
- **THEN** the stop is blocked once

#### Scenario: No record written
- **WHEN** a board is configured and a session started by a record-writing command stops before any record write
- **THEN** the stop is blocked once with a message that says how to write the record

#### Scenario: Record written
- **WHEN** a successful record write was seen and nothing changed since
- **THEN** the stop is allowed

#### Scenario: Ask without a timer
- **WHEN** an ask was posted and no timer was armed after it
- **THEN** the stop is blocked once, even with no board configured

#### Scenario: Fail open
- **WHEN** no board is configured, the section is malformed or the state file is unreadable
- **THEN** the stop is allowed

### Requirement: Trusted profile source
The system SHALL read `hooks.disable`, the protect lists and the gate settings from the resolved profile on the remote's default branch (its own keys, its cached base and the defaults), not from the working tree, SHALL apply the stricter of the two for every guarded key so a branch may strengthen but never weaken a guard, and SHALL read a base only from the cache and never fetch it inside a hook.

#### Scenario: Disable edited locally
- **WHEN** a session edits the working-tree profile to disable a hook
- **THEN** the hook stays active until the default branch's profile changes

#### Scenario: Gate switched off on a branch
- **WHEN** a branch's profile sets a gate to false and the default branch's resolved profile has it on
- **THEN** the gate stays on and a notice says the branch value is weaker

#### Scenario: Base not cached in a hook
- **WHEN** the profile's base is not in the cache
- **THEN** nothing from the base is applied, no hook is switched off by it, and a notice says to run the profile validation to fetch it
