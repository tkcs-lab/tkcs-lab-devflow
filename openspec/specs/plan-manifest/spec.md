# plan-manifest Specification

## Purpose
The implementation manifest validator checks the manifest of a plan document before /make-plan pushes it and before /implement starts, so that phases are well formed, ordered and free of write conflicts.

## Requirements

### Requirement: Locate the manifest
The system SHALL, for `tld plan validate-manifest PLAN`, read the first fenced yaml block under the `## Implementation manifest` heading when the file name ends in `.md`, and SHALL read any other file as the manifest yaml itself.

#### Scenario: Plan without manifest
- **WHEN** a Markdown plan has no `## Implementation manifest` heading
- **THEN** stderr says the command only runs plans that have a manifest and the exit code is 1

#### Scenario: Missing file or invalid YAML
- **WHEN** the file does not exist, or the manifest is not valid YAML
- **THEN** a `manifest:` message goes to stderr and the exit code is 1

### Requirement: Require and type-check top-level keys
The system SHALL require `plan_slug`, `feature_branch` and a non-empty `phases` list, SHALL reject unknown top-level keys with a message listing the known keys (legacy keys such as `worker_model` with a hint to the replacement), and SHALL require `max_parallel`, `tracking_issue` to be positive integers and `closes` to be a list of positive integers.

#### Scenario: Missing required key
- **WHEN** the manifest has no `feature_branch`
- **THEN** stderr contains `missing required key 'feature_branch'` and the exit code is 1

#### Scenario: Bad tracking issue
- **WHEN** `tracking_issue` is 0 or a non-integer
- **THEN** an error `tracking_issue must be a positive integer` is reported

#### Scenario: Closes repeats the tracking issue
- **WHEN** `closes` contains the `tracking_issue` number
- **THEN** a warning `closes contains tracking_issue` is printed and validation still passes

### Requirement: Check each phase
The system SHALL require each phase to have an `id`, `title`, `brief` and a non-empty `acceptance` list, SHALL reject duplicate ids and unknown phase keys, SHALL accept `complexity` only as S or M, and SHALL accept `worker_level` only as strong, standard or fast.

#### Scenario: Strong level needs a reason
- **WHEN** a phase has `worker_level: strong` and no `worker_level_reason`
- **THEN** an error says strong needs a worker_level_reason

#### Scenario: Fast level needs a small phase
- **WHEN** a phase has `worker_level: fast` and complexity other than S
- **THEN** an error says fast needs complexity S

#### Scenario: Complexity L
- **WHEN** a phase has `complexity: L`
- **THEN** an error says complexity must be S or M and the phase must be split

### Requirement: Check phase dependencies
The system SHALL report a `depends_on` entry that names an unknown phase, a phase that depends on itself, and a dependency cycle, and SHALL stop further checks after reporting a cycle.

#### Scenario: Cycle
- **WHEN** phase a depends on b and b depends on a
- **THEN** an error `dependency cycle:` followed by the path is printed and the exit code is 1

### Requirement: Detect write overlap between parallel phases
The system SHALL report an error when two phases that are not ordered by `depends_on` (directly or transitively) have `touches` entries that could name the same file, and SHALL warn about a phase with no `touches`.

#### Scenario: Overlap
- **WHEN** two independent phases both touch the same file
- **THEN** an error names both phases and both entries and asks for a depends_on edge or a split

#### Scenario: Overlap resolved by dependency
- **WHEN** one phase depends on the other, directly or through a third phase
- **THEN** no overlap error is reported

### Requirement: Protect plan records and protected paths
The system SHALL report an error for a `touches` entry that grants write scope over a plan's `plan.md` or `deviations.md` under the plan directory, and SHALL warn (not fail) for an entry that is, or could name, a protected path of the profile's protect list or the built-in default.

#### Scenario: Plan record touched
- **WHEN** a phase touches the plan file of its own plan
- **THEN** an error says a phase never edits a plan or its deviations file

#### Scenario: Protected path
- **WHEN** a phase touches a protected path
- **THEN** a warning says the phase never edits it, and the exit code is still 0

### Requirement: Fence spec and architecture changes to the last phase
The system SHALL, when `spec_change` or `sysml_change` is set, require its value to be lower-case words joined by hyphens, require the matching profile block when a profile is given, allow only the last phase to touch the fenced paths (`openspec/` for spec, `sysml/` and the architecture documents for sysml), require the last phase to touch them and to depend on every other phase, and warn when the value differs from `plan_slug`.

#### Scenario: Middle phase touches openspec
- **WHEN** `spec_change` is set and a non-last phase touches `openspec/`
- **THEN** an error says only the last phase may

#### Scenario: Sysml path without sysml_change
- **WHEN** a profile has a sysml block, the manifest has no `sysml_change` and a phase touches the architecture paths
- **THEN** an error asks to narrow the touches or set `sysml_change`

### Requirement: Check the profile and the plan ref
The system SHALL, with `--profile`, check that `feature_branch` starts with one of the profile's `git.branch_types`, and SHALL, with `--ref`, accept only the main branch, the manifest's own feature branch or the deprecated `plan/<slug>` branch (which prints a deprecation warning), exiting 1 for any other ref or an empty one.

#### Scenario: Valid manifest
- **WHEN** the manifest has no errors
- **THEN** stdout prints `manifest: OK (<slug>, <n> phases)` and the exit code is 0

#### Scenario: Wrong ref
- **WHEN** `--ref` names a branch that is neither main nor the feature branch
- **THEN** stderr says the plan may only be on main or on its feature branch and the exit code is 1
