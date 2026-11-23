## Purpose
Mechanical helpers of the `tld plan` command group that track a plan run: accept a plan source, name branches, report phase progress, detect a concurrent run, log deviations, check the Summary section and monitor scope drift.

## ADDED Requirements

### Requirement: Plan URL check
The system SHALL accept a plan URL in `tld plan check-url` only when it is a GitHub blob URL of this repository (`--repo`, default the origin remote) whose ref is the main branch (`--main`, default `main`) or a `<type>/<kebab>` feature branch and whose path ends in `<plan-dir>/<n>/plan.md` (`--plan-dir`, default `docs/plans`), and SHALL print owner, repo, ref, path and legacy as JSON.

#### Scenario: Plan on the main branch
- **WHEN** `tld plan check-url` is given a blob URL of this repository for `docs/plans/<n>/plan.md` on the main branch
- **THEN** it prints the JSON with `legacy` false and exits 0

#### Scenario: Old layouts still accepted
- **WHEN** the URL uses the old `main/<path>` or `plan/<slug>/<path>` layout
- **THEN** the JSON has `legacy` true and a deprecation warning is printed on stderr

#### Scenario: Foreign or malformed source refused
- **WHEN** the URL belongs to another repository, is not a blob URL, names a path with `..`, or sits on a ref that is neither main nor a `<type>/<kebab>` branch
- **THEN** `plan: <message>` is printed on stderr and the exit code is 1

### Requirement: Trusted verify-after-merge commands
The system SHALL, in `tld plan check-commands PLAN --profile PROFILE`, print JSON with `trusted` and `unknown` lists of the manifest's `verify_after_merge` commands in manifest order, treating a command as trusted only under the rules of the scenarios below.

#### Scenario: Dispatchable workflow
- **WHEN** a command is `dispatch <workflow>` for a workflow in `ci.dispatchable`
- **THEN** it is listed under `trusted`

#### Scenario: Allowed prefix
- **WHEN** a command starts word by word with a `verify.after_merge_allow` prefix, has no shell metacharacter and carries only options the program is known to take safely
- **THEN** it is listed under `trusted`

#### Scenario: Exact profile entry
- **WHEN** a command equals a `verify.fast` or `verify.dod` string entry without a `cwd`
- **THEN** it is listed under `trusted`

#### Scenario: Shell metacharacter
- **WHEN** a command starts with an allowed prefix but contains a shell metacharacter, expansion or an option not known as safe
- **THEN** it is listed under `unknown`

#### Scenario: Bad allow list
- **WHEN** `verify.after_merge_allow` is not a list of strings, or the profile file cannot be read
- **THEN** an error is printed on stderr and the exit code is 1

### Requirement: Branch names
The system SHALL print one branch name from `tld plan branch-name`: `plan/<slug>` or `review/<slug>` for a kebab-case slug, otherwise from `--manifest` the feature branch, the phase branch `<feature>--<phase>`, the revision branch `<feature>--<phase>-rev<n>` or the fix branch `<feature>--fix-<n>`.

#### Scenario: Phase revision
- **WHEN** it is run with `--manifest PLAN --phase <id> --rev 2`
- **THEN** it prints `<feature>--<id>-rev2` and exits 0

#### Scenario: Invalid combination
- **WHEN** `--rev` is given without `--phase`, `--fix` is combined with `--phase`, the phase is not in the manifest, a number is below 1, or a slug is not kebab-case
- **THEN** `plan: <message>` is printed on stderr and the exit code is 1

### Requirement: Phase status from commit trailers
The system SHALL, in `tld plan phase-status PLAN`, read the first-parent history of `--ref` (default `HEAD`) and print JSON with `done`, `approved`, `gated`, `running`, `ready`, `waiting`, `start`, `all_done`, `started` and `plan_blob`.

#### Scenario: Done through trailer
- **WHEN** a commit carries a `Plan-Phase: <slug>/<id>` trailer
- **THEN** that phase is done

#### Scenario: Reverted commit
- **WHEN** a commit with a phase trailer is reverted
- **THEN** it does not count, a revert of the revert counts again, and a revert commit's own trailer never counts

#### Scenario: Gate approval
- **WHEN** a done `human_gate` phase has a newer `Plan-Gate-Approved` trailer or is named by `--approved`
- **THEN** it is approved and no longer gated

#### Scenario: Fresh run
- **WHEN** no phase trailer exists
- **THEN** phases whose `depends_on` are all done are `ready`, the others `waiting`, and `start` holds the first ready phases that fit in `max_parallel` next to the `--running` phases

#### Scenario: Gated dependency
- **WHEN** a phase with `human_gate: true` is done and not approved
- **THEN** it is listed in `gated` and its dependants stay `waiting`

#### Scenario: Unknown phase or bad manifest
- **WHEN** `--running` or `--approved` names a phase not in the manifest, or the manifest is invalid
- **THEN** `plan: <message>` is printed on stderr and the exit code is 1

### Requirement: Run record items
The system SHALL print from `tld plan record-items PLAN` one JSON list of pending run-record items, one per manifest phase in order, then `final-review`, then one per `--add ID[=TITLE]`, and with `--check RECORD` (a file or `-` for stdin) SHALL print `items: missing <id>` per expected id absent from the record's `phases`, or `items: ok (<n> expected)`.

#### Scenario: Record lists everything
- **WHEN** `--check` is given a record that has every expected id
- **THEN** `items: ok (<n> expected)` is printed and the exit code is 0

#### Scenario: Missing items
- **WHEN** the record lacks an expected id
- **THEN** `items: missing <id>` is printed for it and the exit code is 1

#### Scenario: Bad input
- **WHEN** the plan file is missing, the manifest is malformed, an added id is invalid or duplicate, or the record is not a JSON object with a `phases` list
- **THEN** a `tld plan record-items:` message is printed on stderr and the exit code is 2

### Requirement: Active run detection
The system SHALL, in `tld plan active-run --kind make-plan|implement --comments FILE --bot LOGIN`, decide from the issue comments written by the bot (login compared case-insensitively) whether a run is open between a start marker and the next final marker on a comment's first line, and print one JSON line with `state` `none`, `own`, `active` or `stale`; for `implement` it SHALL also consider a usable board record given with `--record` and `--plan-slug`.

#### Scenario: Live run by another session
- **WHEN** a start marker has no later final marker and its last sign of life is within `--max-age-minutes` (default 120)
- **THEN** the state is `active` and the exit code is 4

#### Scenario: Own or silent run
- **WHEN** the start comment names the session given by `--self`, or the last sign of life is older than the limit
- **THEN** the state is `own` or `stale` and the exit code is 0

#### Scenario: Other authors ignored
- **WHEN** the markers are written by someone other than the bot
- **THEN** the state is `none` and the exit code is 0

#### Scenario: Bad input
- **WHEN** a comment lacks a string field, a timestamp is not `YYYY-MM-DDTHH:MM:SSZ`, `--max-age-minutes` is below 1, or `--record` is given without `--plan-slug`
- **THEN** `plan: <message>` is printed on stderr and the exit code is 1

### Requirement: Deviations log
The system SHALL provide `tld plan deviations init`, `add` and `check` to create, fill and verify the deviations log of a plan run, and `check` SHALL print `deviations: <problem>` per problem and exit 1, or print `deviations: OK`.

#### Scenario: Init
- **WHEN** `init` is run
- **THEN** it writes a `## <phase id>` section per manifest phase plus `## Final review` and `## Finishing`, each holding `- pending`

#### Scenario: Add a bullet
- **WHEN** `add` is given a section and a text with one of the tags worker, review, scope, retry, conflict, gate, level or final, or `--none`
- **THEN** it replaces the pending line or appends a bullet (`- None.` with `--none`), cuts the text at 500 characters and replaces control characters

#### Scenario: Pending section
- **WHEN** `check` is run with `--done <id>` and that phase's section still holds `- pending`
- **THEN** it prints `deviations: section '<id>' is still pending` and exits 1

#### Scenario: Out-of-scope path not recorded
- **WHEN** `check --scope-results FILE` finds an out-of-scope path of an entry that its section (a fix label maps to Final review, a revision label to its phase) does not list
- **THEN** it reports that path as not listed and exits 1

#### Scenario: Unknown tag or section
- **WHEN** `add` is given an unknown tag or a section the file lacks
- **THEN** `deviations: <message>` is printed and the exit code is 1

### Requirement: Summary section check
The system SHALL, in `tld plan summary-check FILE --kind plan|issue|pr`, require exactly one `## Summary` section placed first (an issue: right after `## Request`) that follows the rules of the scenarios below, and SHALL print `summary: <problem>` per problem and exit 1, or `summary: OK (<n> words)`.

#### Scenario: Labels
- **WHEN** the Summary is checked
- **THEN** the labels must be in the kind's order, the required labels present (plan and issue: Use it, Scope, Review focus; pr: Deviations, Review focus), and none unknown or duplicate

#### Scenario: Values
- **WHEN** the Summary values are checked
- **THEN** there is no placeholder value, each value has at least three words, `None.` appears only for Deviations, Security and Performance, and there is no HTML comment or details block

#### Scenario: Length
- **WHEN** the Summary is checked for length
- **THEN** it has at most 350 words (plan, issue) or 175 words (pr)

#### Scenario: Valid summary
- **WHEN** the file satisfies the rules
- **THEN** `summary: OK (<n> words)` is printed and the exit code is 0

#### Scenario: Deviations claimed as None
- **WHEN** `--deviations FILE` is given with `--kind pr` and the Summary says `None.` while the file records deviations other than `None.` or `pending`
- **THEN** a problem is printed and the exit code is 1

#### Scenario: Unreadable file or misuse
- **WHEN** the file is missing, larger than 1000000 bytes or not UTF-8, or `--deviations` is used with a kind other than pr
- **THEN** a missing, oversized or non-UTF-8 file prints one `summary:` line and exits 1, and the misuse prints a usage message and exits 2

### Requirement: Scope drift monitoring
The system SHALL provide `tld plan scope-check check | disposition | record | section` that compares the files a phase branch changed against the phase's `touches`, classifying each path as in scope, ignored (profile `scope.ignore` and the changelog file) or out of scope with the other phases that name it as collisions, SHALL keep one entry per label in the `--results` file, and SHALL never block: every subcommand exits 0 even when a check is `unavailable`.

#### Scenario: Out-of-scope file
- **WHEN** `check` finds a changed path outside the phase's `touches` and not ignored
- **THEN** the entry lists it under `out_of_scope` with its `collides_with` phases and disposition `accepted`

#### Scenario: Check cannot be made
- **WHEN** the manifest or profile is unreadable, the phase is unknown, the phase declares no `touches`, or git fails
- **THEN** the entry has `check` `unavailable` with a short reason and the exit code is 0

#### Scenario: Resumed phase
- **WHEN** `--plan-slug` and `--feature` are given and the feature branch already holds the phase's `Plan-Phase` trailer for an unlabelled run
- **THEN** the entry has `check` `skipped`

#### Scenario: Disposition and report
- **WHEN** `disposition` compares the feature branch with the main branch, and `section` prints the pull request Scope section
- **THEN** each entry becomes accepted, partly_reverted or reverted by whether its paths remain in the final diff, and `section` lists at most `--cap` (default 20) paths per phase, collisions first
