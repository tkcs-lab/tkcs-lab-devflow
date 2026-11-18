# Plan: integrate OpenSpec (spec from code, spec change with the plan, archived in the PR)

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** A repository opts in by adding `spec: {version: "<openspec version>"}` to its profile. `/tld:spec init` then reads the existing code, proposes one OpenSpec capability per observable behaviour area, asks you to confirm the list, writes and validates the specs and opens one pull request that you merge; `/tld:spec check` only validates and reports. From then on `/tld:make-plan` writes an OpenSpec change (proposal and spec deltas) next to the plan on the feature branch, and the last phase of `/tld:implement` archives it, so the one feature pull request merges code, plan and updated specs together.

**Scope:** Node.js 22.20 or newer and access to the npm registry (first run of a version) are needed wherever the spec commands run. New: profile key `spec.version`, command `tld ops spec` (five fixed subcommands around a pinned OpenSpec CLI), playbook and command `spec`, manifest key `spec_change` (with new `validate-manifest` errors), status-record command `spec`, changes to the make-plan and implement playbooks, one guide. Not changed: repositories without a `spec` block behave exactly as today; no OpenSpec skills or commands are installed into sessions; this repository does not turn the feature on for itself.

**Security:** The wrapper runs an npm package. The version is exact and lives in the protected profile; it is installed once outside the repository with scripts off and the public registry, then run with a reduced environment, no stdin, a timeout and telemetry off, and only five fixed subcommands exist. Transitive dependencies are not pinned: the package ships no shrinkwrap.

**Review focus:** the wrapper's install and run rules, allowlist and environment (3.2); archive in the last phase and the fence that lets only that phase touch `openspec/` (3.5, 3.6); `init` building specs by writing a change and archiving it (3.4); the phase order that keeps the suite and the eval baseline green after every merge (manifest).

## 1. Goal

Add [OpenSpec](https://github.com/Fission-AI/OpenSpec) as the spec layer of tld ([#71](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/71)): a command that builds specs for existing code, make-plan that creates the spec change together with the plan, and a feature pull request that merges the spec change as well.

## 2. Current state

- Plans live at `docs/plans/<n>/plan.md` with a manifest that `tld plan validate-manifest` checks (`src/tld/plan/manifest.py:26-29` list the allowed top-level and phase keys). make-plan writes it (`playbooks/make-plan.md`), implement runs it (`playbooks/implement.md`); the last phase is the retirement phase.
- There is no spec layer: the only record of intended behaviour is the plan, kept as history, and the docs.
- A command needs a playbook, a thin wrapper in `adapters/claude/commands/` and rows in the contract tests (`AGENTS.md`, `tests/core/test_contracts.py:25`, `tests/adapters/claude/test_structure.py:64`). A command that writes a status record is also registered in `src/tld/board/record.py:42`, `src/tld/schema/status-record.schema.json:201`, `src/tld/guard/board_gate.py:28-29` and `src/tld/guard/plan_gate.py:20`; each command needs an eval task (`tests/core/test_evals_stubs.py:22`) and the eval baseline hashes every command with its playbook and linked policies (`evals/harness/baseline.py`, `tests/core/test_evals_baseline.py`).
- Optional profile blocks (`land`, `release`) are declared in `src/tld/schema/profile.schema.json`, documented in `docs/reference/profile-reference.md` and sketched, commented, in `src/tld/templates/toolkit.yaml:58-141`; `tests/adapters/claude/test_structure.py:173` requires every schema key to be documented.
- CLI commands are registered in `src/tld/cli.py` (`COMMANDS`, line 15) and listed in `docs/reference/cli.md`; module convention: `src/tld/ops/docs_index.py`.

## 3. Design

### 3.1 Facts about OpenSpec (research, 2026-11-18)

Read from the npm tarball of `@fission-ai/openspec` 2.1.0 (published 2026-11-17, MIT, `engines.node >=22.20.0`, https://www.npmjs.com/package/@fission-ai/openspec, source https://github.com/Fission-AI/OpenSpec). The package was read, not run: running it in the planning session was refused. The first worker that runs it confirms the open points below (p2's smoke step).

- Layout: `openspec/specs/<capability>/spec.md` holds the current behaviour; `openspec/changes/<id>/` holds one change: `proposal.md`, `specs/<capability>/spec.md` deltas, optional `design.md` and `tasks.md`, and `.openspec.yaml` (`schema`, `created`, optional `skip_specs`). `openspec/config.yaml` is written by `init`.
- A delta uses `## ADDED Requirements`, `## MODIFIED Requirements` (the whole updated requirement block), `## REMOVED Requirements` (with `**Reason**` and `**Migration**`) and `## RENAMED Requirements`; a new capability's delta starts with `## Purpose` (50+ characters). A requirement is `### Requirement: <name>` with SHALL/MUST text of at most 500 characters and at least one `#### Scenario: <name>` with `**WHEN**` and `**THEN**` lines.
- `openspec archive <id> --yes` merges the deltas into `openspec/specs/` and moves the change to `openspec/changes/archive/<date>-<id>/`. A new capability's delta `## Purpose` is carried into the new main spec (a placeholder is written only when the delta's Purpose would leave the spec unreadable; archive then warns). `openspec validate --all --strict --no-interactive` checks changes and specs; strict fails on warnings; a change with no deltas fails unless its `.openspec.yaml` sets `skip_specs: true`.
- The package declares no install lifecycle scripts, ships no `npm-shrinkwrap.json` (its 13 runtime dependencies are given as ranges, so transitive versions float), and `init` writes only `openspec/config.yaml` and directories when `--tools none` is given.
- Telemetry (command names and version only) is off when `OPENSPEC_TELEMETRY=0` or `DO_NOT_TRACK=1` or `CI` is set.
- Not settled: whether `openspec new change <id>` and `openspec validate <id> --type change --strict` accept a change with no `tasks.md` (the validator reads `tasks.md` as the tracked task file and only warns about missing checkboxes; strict turns warnings into failures). p2's smoke step settles it; see Risks.

### 3.2 The wrapper `tld ops spec`

New module `src/tld/ops/spec.py`, registered as `("ops", "spec"): ("tld.ops.spec", (), "init | new-change | list | validate | archive: the pinned OpenSpec CLI")`. It never takes free-form OpenSpec arguments: five fixed subcommands, each mapped to a fixed OpenSpec argument list. `--profile FILE` (default `<root>/.tld/toolkit.yaml`) and `--root DIR` (default `.`) are accepted by **every subcommand** (a shared parent parser, `parents=[common]`, as `src/tld/ops/docs_index.py:555-561` does), so `tld ops spec validate --profile P --change X` parses.

| `tld ops spec ...` | runs `openspec ...` |
|---|---|
| `init` | `init --tools none --no-animation` |
| `new-change ID` | `new change ID` |
| `list [--json]` | `list --specs` plus `--json` |
| `validate [--change ID] [--json]` | `validate --all --strict --no-interactive`, or `validate ID --type change --strict --no-interactive`, plus `--json` |
| `archive ID` | `archive ID --yes` |

Checks before anything runs (each exits 2 with the exact stderr line, and nothing is installed or run):

- `ID` must `re.fullmatch` `[a-z0-9]+(-[a-z0-9]+)*`: `tld ops spec: invalid id '<id>': use lower-case words joined by hyphens`.
- The profile file must exist: `tld ops spec: profile not found: <path>`. `spec.version` missing, or `spec` not a mapping: `toolkit.yaml: missing required key 'spec.version' (add a spec block; see docs/guides/spec.md)`.
- `spec.version` must be a string that `re.fullmatch`es `\d+\.\d+\.\d+`: `tld ops spec: spec.version must be an exact release such as 2.1.0 (got <repr>)`.
- `node` and `npm` on `PATH`, and `node --version` (a leading `v` removed) at least 22.20.0 compared as integer tuples: `tld ops spec: node and npm are required (OpenSpec <version> needs Node.js 22.20.0 or newer)` when either is missing or the version cannot be read; `tld ops spec: Node.js <found> is too old; OpenSpec <version> needs 22.20.0 or newer` when older.

Install (once per version, outside the repository): the cache root is `$TLD_CACHE_DIR`, else `~/.cache/tld`; the install directory is `<cache>/openspec/<version>`. When `<dir>/node_modules/@fission-ai/openspec/package.json` is missing, create `<dir>`, write `{"private": true}` to `<dir>/package.json` and run in `<dir>`: `npm install --ignore-scripts --no-save --no-audit --no-fund --registry https://registry.npmjs.org/ @fission-ai/openspec@<version>`. A non-zero exit gives `tld ops spec: installing @fission-ai/openspec@<version> failed (exit <n>)`; an installed `package.json` whose `version` differs gives `tld ops spec: installed version <x> is not <version>`.

Run: `node <dir>/node_modules/@fission-ai/openspec/bin/openspec.js <args>` with the working directory `--root`, stdin `/dev/null` and a timeout of 600 seconds (on timeout: `tld ops spec: OpenSpec did not finish within 600 seconds`, exit 2). stdout and stderr pass through; otherwise the exit code is OpenSpec's. The environment for both npm and node is an allowlist: `PATH`, `HOME`, `USER`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` (and their lower-case forms), `SSL_CERT_FILE`, `SSL_CERT_DIR`, `NODE_EXTRA_CA_CERTS`, plus `npm_config_ignore_scripts=true`, `npm_config_registry=https://registry.npmjs.org/`, `OPENSPEC_TELEMETRY=0`, `DO_NOT_TRACK=1` and `CI=1`. No other variable (tokens included) is passed.

Test seams: module-level `_run(argv, cwd, env, timeout) -> int` (wraps `subprocess.run`, stdin devnull), `_which(name)` and `_node_version() -> str | None`; unit tests replace them with `monkeypatch`; one integration test runs the real functions against fake `node` and `npm` scripts on `PATH`.

Rejected: a Python reimplementation of validate and archive (owner's decision: format drift against a project that shipped 2.0 a week ago); `npx --package` from the repository root (the repository's `.npmrc` or `node_modules` would decide what runs, and install scripts would run); passing arbitrary OpenSpec arguments through (a prompt-injected text could run `openspec feedback` or `openspec install`); a `show` subcommand (make-plan reads the spec files directly, 3.5).

### 3.3 Profile key

`spec` is an optional top-level block, `additionalProperties: false`, one key: `version`, a string matching `^\d+\.\d+\.\d+$`, required inside the block, no default. Description: "Exact OpenSpec release the spec commands run (npm @fission-ai/openspec). Present means the repository uses specs: /spec works and /make-plan writes a spec change." A bump is a profile change, so the owner decides it through the protected-change flow.

### 3.4 `/tld:spec init` and `/tld:spec check` (playbook `spec`)

Input `init` or `check` (default `check`); anything else prints `Usage: spec [check | init]`. Profile load as `policies/profile.md` says; without `spec.version` stop with the wrapper's missing-key line.

`check` (no record, changes nothing): `tld ops spec validate --profile .tld/toolkit.yaml`; with `openspec/specs` present also `tld ops spec list --profile .tld/toolkit.yaml --json`; report the capability count and the validator's findings; the check passes when validate exits 0.

`init` (attended, writes a record): `kind: command`, `command: spec`, `attended: true`, items `survey`, `confirm`, `draft`, `validate`, `pr`. It runs `tld dod exempt`. Branch `chore/spec-init-<yyyymmdd>` from `origin/<main>`; the command is the permission to push it and open one pull request, never to merge. The first record is written before step 1.

1. **Survey** (read-only): stop with `Specs already exist (openspec/specs holds capabilities); plans update them. Nothing was changed.` when `openspec/specs/` already holds a capability. Otherwise `run_helper` sweeps (level `standard`) list the repository's observable behaviour areas: user-facing commands, public APIs, configuration, data formats, error behaviour. Propose a flat list of at most 12 capabilities (kebab-case, each a durable behaviour area, no near-duplicates), each with one evidence path.
2. **Confirm**: `ask_human` once: one `text` question holding the proposed list, one line per capability `<capability>: <at most 8 words> (<one evidence path>)`, at most 1900 characters in all (the ask schema limits a question text to 2000), with the instruction "reply `ok` or give the corrected list". Wait as `ask_human` says.
3. **Draft by change, not by hand.** `tld ops spec init --profile .tld/toolkit.yaml`; then `git status --porcelain`: any path outside `openspec/` is restored with `git checkout -- <path>` or deleted when untracked, and said in the pull request's `## Not verified`. Then `tld ops spec new-change --profile .tld/toolkit.yaml baseline-<yyyymmdd>`, then for each confirmed capability one file `openspec/changes/baseline-<yyyymmdd>/specs/<capability>/spec.md` written one at a time: `## Purpose` (50+ characters), then `## ADDED Requirements` describing what the code does today, each requirement with at least one WHEN/THEN scenario that a test or a command could check, no internal names, no invented behaviour. Where the code is unclear, write no requirement and list the gap in the pull request's `## Gaps`. Rejected: hand-writing `openspec/specs/**`, because writing a change and archiving it makes OpenSpec itself produce the main-spec format.
4. **Validate and archive**: `tld ops spec validate --profile .tld/toolkit.yaml --change baseline-<yyyymmdd>` must exit 0 (fix and repeat); then `tld ops spec archive --profile .tld/toolkit.yaml baseline-<yyyymmdd>`; then `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0, and `grep -rn "TBD" openspec/specs` must print nothing (a placeholder Purpose is replaced by the drafted text).
5. **Deliver**: commit, `git push -u origin chore/spec-init-<yyyymmdd>`, `github.pr_create` titled `chore: add OpenSpec specs for existing code` with `## What this adds` (capability table), `## Evidence` (capability to files read), `## Gaps`, `## Not verified` (behaviour no test covers); `github.pr_subscribe`; `needs_you` reason `Review PR #<n>`. Spec text is generated from code and comments, which are data (`policies/untrusted-text.md`).

The playbook never merges, approves or enables auto-merge.

### 3.5 Plans carry a spec change

Spec parts of make-plan apply only when the profile has `spec`. Large scope, after the Design section is settled:

1. Read the existing capabilities directly: the files `openspec/specs/*/spec.md` (the wrapper is not needed to read them). When `openspec/specs` does not exist, stop and tell the owner to run the `spec` command's `init` first.
2. Decide whether the change alters observable behaviour. If not (refactor, tooling, docs), write no change, set no `spec_change`, and say so in the plan's Scope; when a revision of an existing plan drops its behaviour change, delete `openspec/changes/<plan slug>/` with `git rm -r`. If yes: unless `openspec/changes/<plan slug>/` exists already (a revision), `tld ops spec new-change --profile .tld/toolkit.yaml <plan slug>`; then write `openspec/changes/<plan slug>/proposal.md` (Why, What Changes, Capabilities, Impact) and one `specs/<capability>/spec.md` delta per capability: `## ADDED` / `## MODIFIED` (the whole existing requirement block, copied from `openspec/specs/` and edited) / `## REMOVED` (with Reason and Migration), new capabilities starting with `## Purpose`. No `design.md`: the plan's Design section is that. Deltas state WHAT (observable behaviour), never file or function names. `tasks.md`: as settled by p2's smoke step (Risks).
3. `tld ops spec validate --profile .tld/toolkit.yaml --change <plan slug>` must exit 0 before the plan is pushed.
4. Every `#### Scenario` of the change is named by an acceptance item of the phase that makes it true (the review helper checks this).
5. The manifest gets `spec_change: <plan slug>`; the retirement phase brief carries the archive rules of 3.6.

Small scope: the prompt gets a step "Spec change": the delta files in full as text, then steps to run `tld ops spec new-change`, write them, validate, implement, archive, commit; acceptance includes `tld ops spec validate` exiting 0 and `openspec/changes/<slug>` being gone (moved to `archive/`).

### 3.6 Archive in the retirement phase; fence

- Manifest: optional top-level `spec_change: <id>`, `re.fullmatch` `[a-z0-9]+(-[a-z0-9]+)*` (else `spec_change must be lower-case words joined by hyphens`; a non-string gives the same error). When a profile is given and has no `spec` block: `spec_change needs the profile's spec block`. With `spec_change` set (profile or not): every phase except the last whose `touches` has an entry for which `paths_overlap(entry, "openspec/**")` is true (`src/tld/plan/manifest.py:89`; this catches literal paths, directories, `openspec/**` and broad globs such as `**/*.md`) is an error `phase '<id>': touches openspec/ but only the last phase may when spec_change is set`; a last phase with no such entry is an error `last phase '<id>' must touch openspec/ when spec_change is set`; with `spec_change` set the last phase must depend, directly or through other phases, on every other phase (error `last phase '<id>' must depend on every other phase when spec_change is set (missing: <ids>)`), so the archive runs after all code has merged; a `spec_change` different from `plan_slug` is a warning.
- The retirement phase lists `openspec/**` in `touches` and its brief, in this order: reconcile `openspec/changes/<id>/` with the deviations file so the deltas describe what was built; `git diff --quiet $(git merge-base HEAD origin/<main>) origin/<main> -- openspec/specs` must exit 0 (else stop with `status=blocked`: main changed the specs, the MODIFIED blocks may be stale); `tld ops spec archive --profile .tld/toolkit.yaml <id>`; `tld ops spec validate --profile .tld/toolkit.yaml` exits 0; `grep -rn "TBD" openspec/specs` prints nothing; commit the moved change and updated specs. `final_checks` gets: `tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/<id> does not exist`.
- implement: a merge whose diff touches `openspec/` in a phase other than the last is sent back, except that a revision or fix worker whose findings belong to the last phase may touch it; the final reviewer is told that the files under `openspec/changes/<id>/` are authored by the plan (not deviations), and runs the final check and checks that every scenario of the archived change under `openspec/changes/archive/` is covered by a test or an acceptance item.
- Archive in the retirement phase, inside the PR, was chosen by the owner over archiving after merge: one merge lands code, plan and specs. The control is `final_checks` and the final review; a consumer's own CI is not assumed to have Node.

### 3.7 Status record command `spec`

`spec` joins `tld.board.record.COMMANDS` and the `command` enum of the status-record schema (p4), then `board_gate.RECORD_COMMANDS` with `RECORD_MODES["spec"] = ("init",)` (only `init` writes a record, like `docs`) and `plan_gate.OPENING` (p5, together with the playbook and wrapper: tests require a record command to have its playbook and command file, and every command an eval task).

## 4. ADRs

None (the profile has no `docs.adr_dir`).

## 5. Manual steps

### After implementation

**ma1-real-openspec-run** (about 15 minutes). The tests fake the OpenSpec CLI and the planning session could not run it, so one real run is the check CI cannot do.

1. After this feature is merged and the `tld` plugin is updated in your Claude Project (the install steps are in the repository's README), take a scratch repository that has a `.tld/toolkit.yaml` and a board host upgraded to this release. Install Node.js 22.20 or newer from https://nodejs.org/en/download if `node --version` is older. Open the profile, add the two lines `spec:` and `  version: "2.1.0"`, then commit and push that change to the repository's default branch (the command branches from `origin/<main>`).
2. Start a Claude Code session on that repository and run `/tld:spec init`. Expect a question listing proposed capabilities; reply `ok`.
3. Expect a pull request titled `chore: add OpenSpec specs for existing code`; open it and check that `openspec/specs/` holds one folder per capability, `openspec/changes/archive/` holds the baseline change, and the pull request's file list shows no path outside `openspec/`.
4. Run `/tld:spec check` and expect it to report no findings.
5. Report back: pass or fail, and the first error line if it failed.

## 6. Risks and open questions

- OpenSpec was read, not run (3.1). If a flag or the layout differs from 3.1, p2 stops with `status=blocked`; the owner decides between adjusting the wrapper's fixed table and pinning another version.
- `tasks.md`: if `openspec validate --strict` rejects a change without it, p2 stops (`status=blocked`) and the owner decides how plans satisfy it (for example a one-line `tasks.md`). Until then make-plan writes none.
- The registry must be reachable on the first run of a version. Environments that block it fail with exit 2 and npm's message; the answer is a research request or an allowed host, never a fallback.
- Transitive dependencies of OpenSpec float (no shrinkwrap). The version pin protects against a changed top-level release only; the guide says so.
- A large init may exceed one session's context: the survey caps the list at 12 capabilities and says so in `## Gaps`.
- A board host older than this release refuses `command: spec` records (it validates against its own command list); `init` still runs (a board error never stops a run) but its record is lost until the board is upgraded. The guide says so.
- Archive runs before the final merge of `<main>`: the retirement brief's spec comparison against `origin/<main>` catches a changed spec; the final review runs validate again.

## Implementation manifest

```yaml
plan_slug: openspec-integration
feature_branch: feature/openspec-integration
tracking_issue: 71
max_parallel: 2
manual_after:
  - id: ma1-real-openspec-run
    title: Run /tld:spec init against the real OpenSpec 2.1.0 in a scratch repository
    why: the tests fake the OpenSpec CLI, so only a real run proves the pinned flags and the layout
verify_after_merge:
  - .venv/bin/python cli/tld profile validate .tld/toolkit.yaml
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - tld plan deviations check --file docs/plans/71/deviations.md --plan docs/plans/71/plan.md --all exits 0
  - the changelog has entries under docs.changelog.section and no version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
phases:
  - id: p1-profile-spec-key
    title: Add the optional spec profile block
    depends_on: []
    complexity: S
    touches:
      - src/tld/schema/profile.schema.json
      - src/tld/templates/toolkit.yaml
      - docs/reference/profile-reference.md
      - tests/core/test_validate_profile.py
    brief: |
      Read first: docs/reference/profile-reference.md, plan section 3.3.
      1. In src/tld/schema/profile.schema.json add a top-level property `spec` next to `land` (copy its shape): {"type":"object","additionalProperties":false,"required":["version"],"properties":{"version":{"type":"string","pattern":"^\\d+\\.\\d+\\.\\d+$","description":"Exact OpenSpec release the spec commands run (npm @fission-ai/openspec). Present means the repository uses specs: /spec works and /make-plan writes a spec change."}},"description":"Optional. Repository uses OpenSpec specs."}. Do not add it to the top-level `required` list and give it no default.
      2. In src/tld/templates/toolkit.yaml add, after the commented `# land:` block, a commented block `# spec:` and `#   version: "2.1.0"      # exact OpenSpec release; present = the repository uses specs`, in the style of its neighbours.
      3. In docs/reference/profile-reference.md add table rows after the `land.max_prs` row: `spec` (no) "Section for the spec commands and the spec change /make-plan writes. Absent means the repository does not use specs" and `spec.version` (**yes** in `spec`) "Exact OpenSpec release as MAJOR.MINOR.PATCH; the wrapper installs @fission-ai/openspec@<version> and re-checks the format with a full match (the schema pattern alone would let a trailing newline through). Guide: docs/guides/spec.md (plain text, no Markdown link: the guide is added in p8)". The keys must appear as `` `spec `` and `` `spec.version ``.
      4. Tests in tests/core/test_validate_profile.py, in the style of test_maintenance_keys_are_checked: `spec: {version: "2.1.0"}` validates; `spec: {}` fails with `missing required key 'spec.version'`; `version: 2.1` (a float) fails with `'spec.version': must be a string`; `"latest"` and `"v2.1.0"` fail on the pattern; the unknown key `spec.dir` fails; a profile without `spec` validates and `--resolved` output has no `spec` key; `test_resolved_profile_keeps_spec_version`; `test_starter_template_spec_block_validates_when_uncommented` (slice the `# spec:` block of the template, strip `# `, merge it into the loaded template, assert no errors and that `# spec:` is in the text).
      Stop condition: if the validator does not enforce `pattern`, stop with status=blocked (src/tld/profile/validate.py check()).
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_profile.py -q passes, including the new spec tests
      - .venv/bin/python -m pytest tests -q passes
      - grep -n "spec.version" docs/reference/profile-reference.md matches
  - id: p2-ops-spec-cli
    title: Add tld ops spec, the pinned OpenSpec wrapper
    depends_on: []
    complexity: M
    touches:
      - src/tld/ops/spec.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_ops_spec.py
      - tests/core/test_mutants_file.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/reference/cli.md, tests/core/test_mutants_file.py, tests/mutation/mutants.yaml, src/tld/ops/docs_index.py (argparse and profile loading, lines 480-570), plan sections 3.1 and 3.2.
      1. Create src/tld/ops/spec.py in the convention of src/tld/ops/docs_index.py: module docstring with the usage lines, `main(argv=None) -> int`, a shared parent parser with `--profile` and `--root` passed as `parents=[common]` to each of the five subparsers (init, new-change, list, validate, archive), `if __name__ == "__main__": sys.exit(main())`. argparse usage errors exit 2. No other subcommand and no pass-through arguments exist.
      2. Implement exactly plan section 3.2: `build_args(sub, ns) -> list[str]` (the table); the checks in the order listed there with their exact stderr lines and exit 2 (id with `re.fullmatch`, profile file, `spec` mapping and `spec.version`, version `re.fullmatch`, node and npm, node version as integer tuples against (22, 20, 0)); the install into `<cache>/openspec/<version>` with the exact npm argv and the installed-version check; the run with `node <dir>/node_modules/@fission-ai/openspec/bin/openspec.js`; the allowlist environment (build it from `os.environ` names listed in 3.2, then set the fixed variables); stdin devnull; timeout 600 with `subprocess.TimeoutExpired` mapped to the timeout line.
      3. Seams: `_which(name)` (shutil.which), `_node_version()` (run `node --version`, strip `v` and whitespace, None on any failure), `_run(argv, cwd, env, timeout) -> int` (subprocess.run, no shell, `stdin=subprocess.DEVNULL`, returns the return code).
      4. Register in src/tld/cli.py COMMANDS: `("ops", "spec"): ("tld.ops.spec", (), "init | new-change | list | validate | archive: the pinned OpenSpec CLI")`. The module has argparse `--help`, so no DOC_HELP entry.
      5. Add the row to docs/reference/cli.md in the ops block, the format of the `docs-index` row: `tld ops spec init\|new-change\|list\|validate\|archive [--profile FILE] [--root DIR]`, module `tld.ops.spec`.
      6. Tests in tests/core/test_ops_spec.py. Expected argv lists are literal lists in the tests, never built by `build_args`. Unit (monkeypatched seams): every form (init; new-change; list and list --json; validate, validate --json, validate --change X, validate --change X --json; archive); `--profile` and `--root` accepted after the subcommand (cwd equals the root); the usage line lists exactly the five subcommands in braces; `test_unknown_or_extra_arguments_are_rejected_and_nothing_runs` for `["feedback"]`, `["install"]`, `["show","x"]`, `["archive","x","--no-validate"]`, `["new-change","x","extra"]` (exit 2, none of `_run`, `_which`, `_node_version` called); invalid ids `"abc\n"`, `"-x"`, `"../x"`, `"A"`, `"a--b"`, `""`, `"a_b"`; invalid versions `"latest"`, `"^2.1.0"`, `"2.1"`, `2.1`, `"2.1.0\n"`, `"2.1.0 --registry=x"`, None (exit 2, the exact line, nothing runs); missing profile file; `spec: "2.1.0"` not a mapping; node missing, npm missing, `_node_version()` None, 22.19.9 rejected, 22.20.0 and 23.0.0 accepted; a fresh cache runs the literal npm install argv in the cache directory and then the node argv, a second call skips the install, a mismatching installed version exits 2; the environment passed satisfies `set(env) <= ALLOWED | FIXED` with both sets written out literally in the test (the names of plan section 3.2) while the test sets `GITHUB_TOKEN`, `TLD_BOARD_TOKEN`, `NPM_TOKEN`, `NODE_OPTIONS`, `npm_config_userconfig` and a lower-case `http_proxy`: `http_proxy` is passed, the others are dropped, and `OPENSPEC_TELEMETRY` is `0` although the test set it to `1`; an autouse fixture sets `TLD_CACHE_DIR` and `HOME` to `tmp_path`, and `test_cache_defaults_to_home_cache_tld` unsets `TLD_CACHE_DIR` and asserts the npm install cwd is `tmp_path/.cache/tld/openspec/2.1.0`; `TimeoutExpired` gives the timeout line; the exit code of `_run` is returned unchanged; `_node_version` returns `"22.20.0"` for `"v22.20.0\n"` and None for a failing command. Integration (no Node needed): `test_cli_runs_node_with_fixed_argv_env_and_cwd` puts fake `node` and `npm` shell scripts in a temp `bin` on `PATH`. The fake npm creates `node_modules/@fission-ai/openspec/package.json` with the pinned version and `bin/openspec.js`, writes its `env` output and its stdin (`cat`) to files, and exits 0. The fake node prints `v22.20.0` and exits 0 when `$1` is `--version`; otherwise it records its arguments, working directory and `env` output and its stdin to files and exits 7. The test sets `TLD_CACHE_DIR` to a temp directory and, in the subprocess environment, `GITHUB_TOKEN=x`, `TLD_BOARD_TOKEN=x`, `NPM_TOKEN=x`, `NODE_OPTIONS=--require=/nonexistent.js`, `npm_config_registry=https://evil.invalid/` and `OPENSPEC_TELEMETRY=1`; it runs `cli/tld ops spec validate --root R --profile P` as a subprocess with `input="secret\n"` and asserts return code 7, the recorded node argv and cwd R, that neither recorded environment contains `GITHUB_TOKEN`, `TLD_BOARD_TOKEN`, `NPM_TOKEN`, `NODE_OPTIONS` or `evil.invalid`, that npm saw `npm_config_registry=https://registry.npmjs.org/` and `npm_config_ignore_scripts=true`, that both saw `OPENSPEC_TELEMETRY=0`, and that both read empty stdin.
      7. Mutation: add `src/tld/ops/spec.py` to `MODULES` in tests/core/test_mutants_file.py (line 11) and three mutants to tests/mutation/mutants.yaml in the file's existing format, each pointed at tests/core/test_ops_spec.py: drop `--ignore-scripts` from the npm argv; turn the `re.fullmatch` on the id into `re.match`; pass the whole `os.environ` instead of the allowlist. Stop with status=blocked if `MODULES` is not defined in that test file.
      8. Smoke step (stop condition): if `node --version` here is 22.20.0 or newer and the registry is reachable, run in an empty `git init` temp directory outside the repository with a temp profile `spec: {version: "2.1.0"}` and `TLD_CACHE_DIR` set to another temp directory: `tld ops spec init`, `new-change smoke-test`, `validate --change smoke-test`, and report what each printed, whether any file outside `openspec/` appeared, and whether validate accepted the change without `tasks.md`. If OpenSpec rejects a flag of the plan's table, or a file outside `openspec/` appears, stop with status=blocked and quote the output. If `tasks.md` is required, stop with status=blocked (Risks). If node or the registry is unavailable, say so and finish.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_ops_spec.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - .venv/bin/python cli/tld ops spec --help exits 0 and lists init, new-change, list, validate and archive
  - id: p3-manifest-spec-change
    title: Add the spec_change manifest key and its fence
    depends_on: [p1-profile-spec-key, p2-ops-spec-cli]
    complexity: S
    touches:
      - src/tld/plan/manifest.py
      - tests/core/test_validate_manifest.py
      - tests/mutation/mutants.yaml
      - docs/reference/profile-reference.md
    brief: |
      Read first: src/tld/plan/manifest.py (lines 20-100 and the validate function from line 231), tests/mutation/mutants.yaml, plan section 3.6.
      1. Add "spec_change" to TOP_KEYS (src/tld/plan/manifest.py:26) after "tracking_issue".
      2. In validate(): when "spec_change" is in the manifest, it must be a string and `re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value)` must match, else the error `spec_change must be lower-case words joined by hyphens` (a non-string gives the same error; `"abc\n"` is invalid). When it is valid and a profile was given without a `spec` block, the error `spec_change needs the profile's spec block`; with no profile that check is skipped. When it is valid (profile or not): for every phase except the last entry of `phases`, if any `touches` entry satisfies `paths_overlap(entry, "openspec/**")`, add `phase '<id>': touches openspec/ but only the last phase may when spec_change is set`; if the last phase has no such entry, add the error `last phase '<id>' must touch openspec/ when spec_change is set`; if the last phase does not depend, directly or through other phases, on every other phase, add the error `last phase '<id>' must depend on every other phase when spec_change is set (missing: <ids>)` (ids in phase order, joined by `, `); if the value differs from `plan_slug`, add a warning `spec_change differs from plan_slug`.
      3. docs/reference/profile-reference.md, section "The manifest": add one sentence: `spec_change` (optional) names the OpenSpec change the plan carries; the profile needs a `spec` block and only the last phase may touch `openspec/`.
      4. Tests in tests/core/test_validate_manifest.py (next to the unknown-key tests, line 396 area): valid with a spec profile; ids `"abc\n"`, `"-x"`, `"../x"`, `"A"`, `"a--b"`, `""`, `"a_b"`, `7`, `["x"]` give the id error; no spec block; the fence for a middle phase whose touches entry is each of `openspec/specs/auth/spec.md`, `openspec/changes/x/specs/auth/spec.md`, `openspec/project.md`, `openspec/changes/other/`, `openspec/`, `openspec/**`, `**/*.md` (exact error each), and not flagged for `docs/**` and `src/**`; the last phase touching `openspec/**` passes; the last phase without it gives the last-phase error; the fence applies with `profile=None`; with no `spec_change` a middle phase touching `openspec/` passes; the warning for a differing slug; `spec_change` added to the key-known test at line 410 (with a profile that has `spec`; in that test make `plan_slug` equal `spec_change`, add `openspec/**` to the last phase's `touches`, and make sure the last phase depends on every other phase, so that `errors(m, vm) == []` still holds); `test_spec_change_last_phase_must_depend_on_all_phases`; one CLI test through `--profile` with a spec profile file.
      5. tests/mutation/mutants.yaml: add two mutants in the file's existing format (copy the last entry's shape), one that drops the last-phase exclusion in the fence and one that skips the spec-block check, each pointed at tests/core/test_validate_manifest.py.
      Stop condition: if tests/mutation/mutants.yaml does not exist or has a format you cannot copy, skip step 5 and say so in the report; if `paths_overlap` does not behave as the plan says for a probe entry, stop with status=blocked and quote the result.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_manifest.py tests/core/test_mutants_file.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - grep -n "spec_change" src/tld/plan/manifest.py matches in TOP_KEYS and validate
  - id: p4-spec-record
    title: Register spec as a status-record command
    depends_on: []
    complexity: S
    touches:
      - src/tld/board/record.py
      - src/tld/schema/status-record.schema.json
      - tests/core/test_status_record.py
      - tests/core/test_contracts.py
    brief: |
      Read first: src/tld/board/record.py (line 42 area), tests/core/test_status_record.py (lines 85-95 and 435-460), plan section 3.7.
      1. src/tld/board/record.py: add "spec" to COMMANDS (line 42) after "questions".
      2. src/tld/schema/status-record.schema.json: add "spec" to the `command` enum (line 201 area) and to the sentence listing commands in the description (line 198 area), in COMMANDS order (test_command_enum_matches_commands checks it).
      3. tests/core/test_contracts.py: add "spec" to the `expected` set of test_record_commands_cover_the_playbooks (line 279). Do not touch COMMANDS at line 25 (phase p5).
      4. tests/core/test_status_record.py: add "spec" to the parametrize list at line 89 (`["review", "make-plan"]`); add `test_record_id_for_spec`: `tld board record-id --repo o/r --command spec --session session_01abc` prints `r--spec--ion01abc` and `parse_doc_id` accepts it (copy the make-plan case at line 490).
      Stop condition: if a test outside these files fails because `spec` is not yet a command file or a playbook, stop with status=blocked and name the test.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_contracts.py -q passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p5-spec-command
    title: Write the spec playbook, its command wrapper and register them
    depends_on: [p2-ops-spec-cli, p4-spec-record]
    complexity: M
    touches:
      - playbooks/spec.md
      - adapters/claude/commands/spec.md
      - src/tld/guard/board_gate.py
      - src/tld/guard/plan_gate.py
      - evals/fixtures/commands.py
      - evals/tasks/spec-needs-version/task.yaml
      - evals/stubs/spec-needs-version.json
      - evals/baselines/default.json
      - tests/core/test_contracts.py
      - tests/core/test_spec_playbook.py
      - tests/core/test_evals_fixtures.py
      - tests/core/test_board_record_wording.py
      - tests/core/test_hook_board_gate.py
      - tests/core/test_hook_plan_gate.py
      - tests/adapters/claude/test_structure.py
      - tests/adapters/claude/test_hooks_compat.py
      - tests/adapters/claude/test_hooks_config.py
      - tests/adapters/claude/test_hook_board_gate_adapter.py
    brief: |
      Read first: playbooks/docs.md (the init flow, the model for this playbook), adapters/claude/commands/review.md, plan section 3.4 and 3.7, the eval task `land-needs-bot-login` (evals/tasks, evals/stubs, evals/fixtures/commands.py).
      1. Create playbooks/spec.md from plan section 3.4, in the shape of playbooks/docs.md: title, one-paragraph purpose, `Input: check (default) or init`, the rules line linking policies/untrusted-text.md, policies/status-board.md, policies/research.md and runtime.md, Setup (profile as policies/profile.md says; stop with the missing-key line; `tld dod exempt` for init), `## check`, `## init` with the five steps under the headings `1. Survey`, `2. Confirm`, `3. Draft`, `4. Validate and archive`, `5. Deliver`, and the status record (kind command, command spec, `attended: true`, document id from `tld board record-id --repo <owner>/<repo> --command spec --session <this session's id>`, items survey, confirm, draft, validate, pr), `## Never` (merge, approve, enable auto-merge, hand-write openspec/specs, free-form OpenSpec arguments). Every `tld ops spec` call uses `--profile .tld/toolkit.yaml` and only flags the subcommand's --help lists.
      2. The playbook must not contain `/tld:`, runtime tool or model names, or the words ruff, pytest, connector, mypy (tests/core/test_contracts.py RUNTIME_WORDS, tests/conftest.py FORBIDDEN). Refer to the command as `spec`.
      3. Create adapters/claude/commands/spec.md as a copy of adapters/claude/commands/review.md with: description "Build OpenSpec specs for existing code (init: one pull request, never merged) or validate them (check); needs the profile's spec block", argument-hint "[check | init]", `model: opus`, playbook path `${CLAUDE_PLUGIN_ROOT}/playbooks/spec.md`, and the final paragraph "This turn runs at the `strong` level (`opus`, the `model:` line above); start the session on that model so later turns run on it too." Under 1500 bytes.
      4. src/tld/guard/board_gate.py: add "spec" to RECORD_COMMANDS and `"spec": ("init",)` to RECORD_MODES, like `docs`. src/tld/guard/plan_gate.py: add "spec" to OPENING.
      5. tests/core/test_contracts.py: add "spec" to COMMANDS (line 25) and RESEARCH_PLAYBOOKS (line 313). tests/adapters/claude/test_structure.py: add "spec" to the tuple at line 64. tests/core/test_board_record_wording.py: add "spec" to WRITERS (line 8). tests/adapters/claude/test_hooks_compat.py: add `COMPAT["spec"]` with the two rows `("git checkout -b chore/spec-init-20260101 origin/main", "git checkout -b chore/spec-init-<yyyymmdd> origin/<main>")` and `("git push -u origin chore/spec-init-20260101", "git push -u origin chore/spec-init-<yyyymmdd>")`, and add `openspec/changes/baseline-20260101/specs/x/spec.md` and `openspec/specs/x/spec.md` to test_files_the_commands_write_are_allowed (line 214). tests/adapters/claude/test_hooks_config.py: add `("spec", True)` to the dod-exempt parametrize (line 210).
      6. Guard tests: tests/core/test_hook_board_gate.py: copy the docs tests (lines 60-80) for spec (`/tld:spec` and `/tld:spec check` open no state and do not block; `/tld:spec init` does); tests/core/test_hook_plan_gate.py: copy the make-plan opening test (line 111) for `/tld:spec init`; tests/adapters/claude/test_hook_board_gate_adapter.py: copy the `/tld:docs init` real-script case for `/tld:spec init`.
      7. Eval task: copy `land-needs-bot-login` as `spec-needs-version`: a profile without a `spec` block, command `/tld:spec init`, expected stop message the missing-key line of plan section 3.2; add the `spec` branch to `build` in evals/fixtures/commands.py and "spec" to the parametrize at tests/core/test_evals_fixtures.py:81.
      8. tests/core/test_spec_playbook.py: the playbook contains the line `Usage: spec [check | init]`, contains `attended: true`, contains the five step headings of item 1, and the command file names the playbook path; `test_spec_playbook_names_the_stop_message_of_its_eval` (model: tests/core/test_contracts.py:393) reads the `stop_message` of the `command == "spec"` branch of evals/fixtures/commands.py, asserts it occurs in playbooks/spec.md and equals the stderr of `tld.ops.spec.main` for a profile without a `spec` block.
      9. Refresh the eval baseline last: `python3 evals/run.py baseline --refresh-hashes` and commit evals/baselines/default.json.
      Stop condition: if a test in tests/core/test_contracts.py fails for a reason this brief does not cover, read the assertion and fix the playbook text, not the test; stop with status=blocked only if the test itself contradicts this brief.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_spec_playbook.py tests/core/test_board_record_wording.py tests/core/test_evals_stubs.py tests/core/test_evals_baseline.py tests/adapters/claude -q passes
      - .venv/bin/python -m pytest tests -q passes
      - python3 evals/run.py check-baseline exits 0
  - id: p6-plan-playbooks
    title: Make make-plan write the spec change and implement archive it
    depends_on: [p3-manifest-spec-change, p5-spec-command]
    complexity: M
    touches:
      - playbooks/make-plan.md
      - playbooks/implement.md
      - evals/baselines/default.json
      - tests/core/test_spec_calls.py
      - tests/adapters/claude/test_hooks_compat.py
    brief: |
      Read first: playbooks/make-plan.md, playbooks/implement.md (sections 4, 5 and 6), plan sections 3.5 and 3.6.
      1. playbooks/make-plan.md, Setup step 1: add a bullet: `"Spec parts" (the spec change, `spec_change`, the spec steps of the review) apply only with the profile's `spec` block; without it leave them out and never mention specs.`
      2. Section 0 step 2: with the spec block add: read the existing capabilities from the files `openspec/specs/*/spec.md`; when `openspec/specs` does not exist, stop and tell the owner to run the spec command's init first.
      3. After section 2's Design description add a subsection `### The spec change (spec parts)` with plan section 3.5 items 2 to 4 in imperative form (decide whether behaviour changes and what a revision does; `tld ops spec new-change --profile .tld/toolkit.yaml <plan slug>` unless the folder exists; proposal.md and one delta per capability; MODIFIED is the whole existing block; no design.md; validate with `tld ops spec validate --profile .tld/toolkit.yaml --change <plan slug>` before the push; every `#### Scenario` is named by an acceptance item). The files are committed to the feature branch with the plan.
      4. The manifest block in section 2: add the line `spec_change: <plan slug>   # optional; spec parts only; the OpenSpec change this plan carries` after `closes`, and to the retirement-phase text add the ordered rules of plan section 3.6 (reconcile with the deviations file; the `git diff --quiet ... -- openspec/specs` check with `status=blocked` on failure; `tld ops spec archive --profile .tld/toolkit.yaml <id>`; `tld ops spec validate --profile .tld/toolkit.yaml`; no `TBD` in `openspec/specs`; `openspec/**` in `touches`; no other phase touches `openspec/`) and the extra `final_checks` line.
      5. Small scope section: at the end of item 4 (Design) of the prompt list add a paragraph headed `Spec change (spec parts):` holding the delta files in full as text, the steps new-change, write, validate, implement, archive, commit, and the two acceptance items of plan section 3.5 (renumber nothing).
      6. Section 4: add to the helper's list (spec parts) that every Scenario has an acceptance item, MODIFIED blocks are whole, deltas name no file or function.
      7. playbooks/implement.md Merge step 2: add one sentence: with `spec_change` in the manifest, a diff that touches `openspec/` in any phase but the last is sent back, except a revision or fix worker whose findings belong to the last phase. Section 5 final reviewer brief: add: with `spec_change`, the files under `openspec/changes/<spec_change>/` were authored by the plan and are not deviations; run `tld ops spec validate --profile .tld/toolkit.yaml`; `openspec/changes/<spec_change>` must be gone; every scenario of the archived change under `openspec/changes/archive/` must be covered by a test or an acceptance item; failing any is a blocking finding.
      8. Both files stay free of `/tld:`, runtime tool names and the forbidden words (p5's brief item 2). Do not renumber sections.
      9. tests/core/test_spec_calls.py: `test_every_tld_ops_spec_span_runs_through_the_wrapper`: extract each `tld ops spec ...` span from playbooks/spec.md, playbooks/make-plan.md and playbooks/implement.md, fill placeholders with valid ids, call `tld.ops.spec.main` with the seams faked and a temp profile, assert it returns 0 and that the OpenSpec arguments are one of the forms of plan section 3.2 (literal list in the test); assert the set of subcommands found per file, so an empty extraction fails: playbooks/spec.md has `{init, new-change, list, validate, archive}`, playbooks/make-plan.md has `{new-change, validate, archive}`, playbooks/implement.md has `{validate}`.
      10. tests/adapters/claude/test_hooks_compat.py: every git code span in the playbooks has its `<...>` placeholders filled from `PLACEHOLDERS` (line 161); add `"<plan slug>": "foo"`, `"<id>": "foo"` and `"<spec_change>": "foo"` to it, and add the case that `git rm -r openspec/changes/foo/` is allowed by the hooks if the file's tests list allowed commands.
      11. Refresh the eval baseline last: `python3 evals/run.py baseline --refresh-hashes`; commit evals/baselines/default.json.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_spec_calls.py tests/core/test_contracts.py tests/core/test_no_project_words.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - python3 evals/run.py check-baseline exits 0
  - id: p7-docs-lists
    title: Update the command lists in the architecture docs, setup, status-board policy and plugin manifests
    depends_on: [p6-plan-playbooks]
    complexity: S
    touches:
      - docs/architecture/design.md
      - docs/architecture/hooks.md
      - playbooks/setup.md
      - playbooks/policies/status-board.md
      - .claude-plugin/plugin.json
      - .claude-plugin/marketplace.json
      - evals/baselines/default.json
    brief: |
      Read first: docs/architecture/design.md (lines 30-45), docs/architecture/hooks.md (lines 260-300), plan section 3.
      1. docs/architecture/design.md lines 38-40 (the Playbooks paragraph): add `spec` to the list of playbooks and one sentence: OpenSpec is wrapped, pinned and opt-in, and the plan's spec change is archived by the retirement phase. Do not link the guide (it is added in p8).
      2. docs/architecture/hooks.md: add `spec` to the plan-gate list of commands that open a session (lines 265-266) and to the board-gate list of commands that write a record, naming only `spec init` (lines 295-297).
      3. playbooks/setup.md line 52: add `spec` to the list of blocks that setup never writes.
      4. playbooks/policies/status-board.md: add `spec` to every list of commands: line 5 (the playbooks that write a record), the `kind` row (line 39) and the `command` row (line 40); nothing else.
      5. .claude-plugin/plugin.json line 4 and .claude-plugin/marketplace.json lines 7 and 13: add `/spec` to the command list of each description string (nothing else; versions stay equal).
      6. Refresh the eval baseline last: `python3 evals/run.py baseline --refresh-hashes`; commit evals/baselines/default.json.
    acceptance:
      - .venv/bin/python -m pytest tests -q passes
      - grep -c "/spec" .claude-plugin/plugin.json and grep -c "/spec" .claude-plugin/marketplace.json each print at least 1
      - python3 evals/run.py check-baseline exits 0
  - id: p8-retire
    title: Retire the plan - the spec guide, its index row, the README row and the changelog line
    depends_on: [p7-docs-lists]
    complexity: S
    touches:
      - docs/guides/spec.md
      - docs/README.md
      - README.md
      - CHANGELOG.md
    brief: |
      Read first: README.md (the Commands table, lines 56-71), docs/guides/questions.md (the shape of a guide), docs/README.md, CHANGELOG.md (the `## [Unreleased]` section), plan sections 3 and 5.
      1. Create docs/guides/spec.md: `# Specs with OpenSpec`, a summary of at most 3 lines, then: what it is and the opt-in (`spec.version` with a profile snippet), Node.js 22.20+ and registry access on the first run of a version, `/tld:spec init` and `check`, how make-plan writes the change and implement archives it in the last phase, the fence on `openspec/`, the supply-chain notes (exact top-level pin, install outside the repository with scripts off, five fixed subcommands, reduced environment, telemetry off, transitive dependencies float), that a board host older than this release refuses `spec` records and must be upgraded, how to bump the version (protected profile change), and the manual check ma1 of plan section 5. Under 120 lines.
      2. docs/README.md: in `## Guides` add after the `guides/questions.md` row: `- [guides/spec.md](guides/spec.md) - specs with OpenSpec: the profile's spec block, /spec init and check, the spec change a plan carries and its archive; read when setting up specs or changing the spec commands.`
      3. README.md: add a row to the Commands table after `/tld:migrate`: `/tld:spec [check \| init]` | builds OpenSpec specs for existing code (one pull request, never merged) or validates them; with a `spec` profile block make-plan also writes the spec change and implement archives it ([guide](docs/guides/spec.md)).
      4. CHANGELOG.md: under `## [Unreleased]`, in its `### Added` subsection, add one line in the file's existing style: `/tld:spec builds OpenSpec specs for existing code; with a spec profile block /tld:make-plan writes the spec change and /tld:implement archives it in the last phase (#71).` No version heading.
      5. This repository's profile has no `spec` block and this plan has no `spec_change`, so nothing under `openspec/` changes; do not create it.
      6. Run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, then `python3 evals/run.py check-baseline`.
    acceptance:
      - sed -n '/^## \[Unreleased\]/,/^## \[/p' CHANGELOG.md | grep -n "#71" matches
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - python3 evals/run.py check-baseline exits 0
      - .venv/bin/python -m pytest tests -q passes
```
