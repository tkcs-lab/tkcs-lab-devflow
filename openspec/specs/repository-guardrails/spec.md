# repository-guardrails Specification

## Purpose
The guard hooks stop an agent session from doing what only a human may do (merge or approve, force-push, delete branches, create tags, write credentials, edit protected files) and nudge it on plans, status records, model level and environment. They run as Claude Code hooks over a runtime-neutral policy core.

## Requirements

### Requirement: Denial protocol and failure mode
The system SHALL signal a denial from a PreToolUse hook with exit code 2 and a message on stderr that starts with "tld <hook-name>: " and says what to do instead, and SHALL deny (fail closed) when the merge, force-push or tag hook hits an internal error, an unreadable event or its time budget, while the other hooks report such a problem as a non-blocking error.

#### Scenario: Denied command
- **WHEN** a Bash event runs `gh pr merge 12`
- **THEN** the no-merge hook exits with code 2 and its stderr starts with "tld no-merge: "

#### Scenario: Unreadable event
- **WHEN** a destructive hook (no-merge, no-force-push, no-git-tag) receives input that is not a JSON object
- **THEN** it exits with code 2; the secret-scan hook given the same input exits with code 1 instead

#### Scenario: Prompt events never block
- **WHEN** a guard decides to deny during a UserPromptSubmit or SessionStart event
- **THEN** the hook exits with code 0 and reports the reason as a systemMessage

### Requirement: Merge and approval denial
The system SHALL deny, in Bash commands and in the GitHub tools that merge, approve or write to a branch, any pull request merge (including auto-merge), any approval, and any push or content write whose target is the profile's main branch or cannot be shown not to be.

#### Scenario: Merge and approve forms
- **WHEN** a command is `gh pr merge`, `gh pr review --approve`, or a `gh api` call to a merge or APPROVE review endpoint
- **THEN** the command is denied

#### Scenario: Push to the main branch
- **WHEN** a command is `git push origin HEAD:main`, or a push whose destination is only known at run time
- **THEN** the command is denied

#### Scenario: Feature branch work
- **WHEN** a command is `git push -u origin feature/x` or a local `git merge origin/main`
- **THEN** the command is allowed

#### Scenario: Missing main branch setting
- **WHEN** the repository has no profile value for the main branch and a `git push` is attempted
- **THEN** the push is denied with a message about the missing required key for the main branch

### Requirement: Force-push and branch deletion denial
The system SHALL deny `git push` with `--force`, `-f`, `--force-with-lease`, `--force-if-includes` (or unambiguous abbreviations), a refspec starting with `+`, any push that deletes a remote branch (`--delete`, `-d`, `--prune`, `--mirror`, a refspec starting with `:`), and the API and pull-request forms of branch deletion, while allowing normal pushes and local branch deletion.

#### Scenario: Force push
- **WHEN** a command is `git push -f origin x`
- **THEN** the command is denied with a message that says to push normally and merge the remote branch instead of rewriting history

#### Scenario: Remote branch deletion
- **WHEN** a command is `git push origin :old` or `gh pr close --delete-branch`
- **THEN** the command is denied

#### Scenario: Allowed forms
- **WHEN** a command is `git push -u origin x`, `git branch -d old` or `git fetch --prune`
- **THEN** the command is allowed

### Requirement: Git tag and release denial
The system SHALL deny creating, moving, deleting or pushing git tags and creating or editing releases (through git, `gh`, or API calls), and SHALL deny dispatching the release workflow unless `dry_run` is exactly true or a release allow marker written in the last 10 minutes exists, while allowing read-only tag commands.

#### Scenario: Tag creation
- **WHEN** a command is `git tag v2` or `git push --tags`
- **THEN** the command is denied and no tag is created

#### Scenario: Reading tags
- **WHEN** a command is `git tag -l`, `git describe` or `git ls-remote --tags`
- **THEN** the command is allowed

#### Scenario: Release dispatch
- **WHEN** the release workflow is dispatched with dry_run false and no release marker exists
- **THEN** the dispatch is denied; with dry_run true, or with a marker younger than 10 minutes, it is allowed

#### Scenario: Git-ops dispatch
- **WHEN** the git-ops workflow is dispatched with dry_run false and no git-ops marker younger than 10 minutes exists
- **THEN** the dispatch is denied

### Requirement: Secret write denial
The system SHALL deny a Write, Edit, MultiEdit or NotebookEdit call, and a Bash command that writes to a file, whose new content matches a credential pattern (private key blocks, known provider token formats, generic key/token/secret/password assignments of a high-entropy literal, credentials in URLs, bearer tokens, web tokens), and the message SHALL name the pattern and line but never the value.

#### Scenario: Token in a file
- **WHEN** a Write call's content contains a string shaped like a GitHub token
- **THEN** the call is denied and the message names the pattern and the line number without printing the value

#### Scenario: Environment lookup
- **WHEN** the content is `API_KEY = os.environ["API_KEY"]` or a removal of a secret
- **THEN** the call is allowed

#### Scenario: Allow mark
- **WHEN** a line ends with `secret-scan:allow` as its last text
- **THEN** that line is not scanned; the mark in the middle of a line does not exempt it

### Requirement: Protected path edits
The system SHALL deny edits, by the Write tools and by visible Bash writes, to paths listed in the resolved profile's `hooks.protect_paths` and always to the git configuration, hooks and ref files, the plugin's installed files, the agent runtime's own settings and the workflows that start a release, a land run or a branch deletion, while always allowing `.env.example`, `.env.sample`, `.env.template` and `.env.dist`.

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

### Requirement: Allow markers
The system SHALL provide `tld guard allow-profile` (2 hours), `allow-workflow-install <file>` (15 minutes), `allow-git-ops` (10 minutes), `allow-release <workflow-file>` (10 minutes) and `allow-plan` (8 hours), each writing a short-lived marker file inside the checkout's git directory, and `tld guard end-allow` SHALL remove every marker except the plan marker; unknown arguments SHALL exit 2 with a usage line.

#### Scenario: Profile marker
- **WHEN** `tld guard allow-profile` ran less than 2 hours ago
- **THEN** a write to the profile file is allowed and writes to `.env` or lockfiles stay denied

#### Scenario: Marker ends
- **WHEN** `tld guard end-allow` runs, or a marker is older than its lifetime
- **THEN** the guarded step is denied again

#### Scenario: Release marker without a name
- **WHEN** `tld guard allow-release` runs with no workflow file
- **THEN** it exits with code 2 and writes no marker

#### Scenario: Markers are per checkout
- **WHEN** a marker is written in one checkout
- **THEN** it does not unlock another checkout

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

### Requirement: Advisory model and environment checks
The system SHALL, at session start and when a prompt starts a tld command, show a warning (and never deny) when the session runs at the strongest model level while the command is meant for a lower one (model-check), and when a cloud session's environment name is unset or not among the profile's `runtime.environments` (env-check); either can be turned off with `hooks.disable`.

#### Scenario: Strong session
- **WHEN** the session level is strong and the command's level is not
- **THEN** the hook exits 0 with a systemMessage warning and no context; with a strong command or an unknown session level it is silent

#### Scenario: Wrong environment
- **WHEN** the session is remote, the profile lists environment names and the environment variable is unset or names another environment
- **THEN** a systemMessage warns; a listed name (compared ignoring case) or a local session is silent

#### Scenario: Switched off
- **WHEN** the trusted profile lists the hook in `hooks.disable`
- **THEN** no warning is shown, and a malformed disable list never causes a denial

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
