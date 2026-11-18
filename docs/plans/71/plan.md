# Plan: integrate OpenSpec (spec from code, spec change with the plan, archived in the PR)

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** A repository opts in by adding `spec: {version: "<openspec version>"}` to its profile. `/tld:spec init` then reads the existing code, drafts one OpenSpec capability per observable behaviour area, asks you to confirm the capability list, validates the result and opens one pull request that you merge; `/tld:spec check` only validates the specs and reports. From then on `/tld:make-plan` writes an OpenSpec change (proposal and spec deltas) next to the plan on the feature branch, and `/tld:implement`'s last phase archives it, so the one feature pull request merges code, plan and updated specs together.

**Scope:** New: profile key `spec.version`, command `tld ops spec` (a thin wrapper around the pinned OpenSpec CLI), playbook and command `spec`, manifest key `spec_change`, status-record command `spec`, changes to the make-plan and implement playbooks, one guide. Not changed: repositories without a `spec` block behave exactly as today; no OpenSpec skills or commands are installed into sessions; this repository does not turn the feature on for itself.

**Security:** The wrapper runs an npm package, so the supply chain is the risk: the version is exact and lives in the protected profile, the wrapper allows only six fixed OpenSpec subcommands, and telemetry is switched off in its environment.

**Review focus:** the wrapper's command allowlist and environment (3.2); archive inside the retirement phase and the rule that only that phase may touch `openspec/` (3.5, 3.6); that `init` builds specs by writing a change and archiving it, not by hand-writing main specs (3.4).

## 1. Goal

Add [OpenSpec](https://github.com/Fission-AI/OpenSpec) as the spec layer of tld ([#71](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/71)): a command that builds specs for existing code, make-plan that creates the spec change together with the plan, and a feature pull request that merges the spec change as well.

## 2. Current state

- Plans live at `docs/plans/<n>/plan.md` with a manifest that `tld plan validate-manifest` checks (`src/tld/plan/manifest.py:26-29` list the allowed top-level and phase keys). make-plan writes it (`playbooks/make-plan.md`), implement runs it (`playbooks/implement.md`); the last phase is the retirement phase.
- There is no spec layer: the only record of intended behaviour is the plan, kept as history, and the docs.
- Commands need a playbook, a thin wrapper in `adapters/claude/commands/` and rows in the contract tests (`AGENTS.md`, `tests/core/test_contracts.py:25`, `tests/adapters/claude/test_structure.py:64`). A command that writes a status record is registered in `src/tld/board/record.py:42`, `src/tld/schema/status-record.schema.json:201`, `src/tld/guard/board_gate.py:28-29` and `src/tld/guard/plan_gate.py:20`.
- Optional profile blocks (`land`, `release`) are declared in `src/tld/schema/profile.schema.json`, documented in `docs/reference/profile-reference.md` and sketched, commented, in `src/tld/templates/toolkit.yaml:58-141`; `tests/adapters/claude/test_structure.py:173` requires every schema key to be documented.
- CLI commands are registered in `src/tld/cli.py` (`COMMANDS`, line 15) and listed in `docs/reference/cli.md`.

## 3. Design

### 3.1 Facts about OpenSpec (research, 2026-11-18)

Read from the npm package `@fission-ai/openspec` 2.1.0 (published 2026-11-17, MIT, `engines.node >=22.20.0`, https://www.npmjs.com/package/@fission-ai/openspec, source https://github.com/Fission-AI/OpenSpec). The package was read, not run: running it in the planning session was refused. The first worker that runs it confirms these facts (stop condition in p2).

- Layout: `openspec/specs/<capability>/spec.md` holds the current behaviour; `openspec/changes/<id>/` holds one change: `proposal.md`, `specs/<capability>/spec.md` deltas, optional `design.md` and `tasks.md`, and `.openspec.yaml` (`schema`, `created`, optional `skip_specs`).
- A delta uses the headings `## ADDED Requirements`, `## MODIFIED Requirements` (the whole updated requirement block), `## REMOVED Requirements` (with `**Reason**` and `**Migration**`) and `## RENAMED Requirements`; a new capability's delta starts with `## Purpose` (50+ characters). A requirement is `### Requirement: <name>` with SHALL/MUST text of at most 500 characters and at least one `#### Scenario: <name>` with `**WHEN**` and `**THEN**` lines.
- `openspec archive <id> --yes` merges the deltas into `openspec/specs/` and moves the change to `openspec/changes/archive/<date>-<id>/`. `openspec validate --all --strict --no-interactive` checks changes and specs; a change with no deltas fails unless its `.openspec.yaml` sets `skip_specs: true`.
- Commands used: `init --tools none --no-animation`, `new change <id>`, `list --specs [--json]`, `show <id> --type spec|change [--json]`, `validate`, `archive`.
- Telemetry (command names and version only) is off when `OPENSPEC_TELEMETRY=0` or `DO_NOT_TRACK=1` or a CI variable is set.

### 3.2 The wrapper `tld ops spec`

New module `src/tld/ops/spec.py`, registered as `("ops", "spec"): ("tld.ops.spec", (), "init | new-change | list | show | validate | archive: the pinned OpenSpec CLI")`. It never takes free-form OpenSpec arguments: six fixed subcommands, each mapped to a fixed OpenSpec argument list (`<root>` is `--root`, default `.`):

| `tld ops spec ...` | runs `openspec ...` |
|---|---|
| `init` | `init --tools none --no-animation` |
| `new-change ID` | `new change ID` |
| `list [--json]` | `list --specs` plus `--json` |
| `show ID [--type spec\|change] [--json]` | `show ID --type <type>` (default `spec`) plus `--json` |
| `validate [--change ID] [--json]` | `validate --all --strict --no-interactive`, or `validate ID --type change --strict --no-interactive`, plus `--json` |
| `archive ID` | `archive ID --yes` |

Common option before the subcommand: `--profile FILE` (default `<root>/.tld/toolkit.yaml`) and `--root DIR`. `ID` must match `^[a-z0-9]+(-[a-z0-9]+)*$` (checked before anything runs; error `tld ops spec: invalid id '<id>': use lower-case words joined by hyphens`).

The runner is `npx --yes --package @fission-ai/openspec@<spec.version> -- openspec <args>`, run in `<root>` with the environment plus `OPENSPEC_TELEMETRY=0` and `DO_NOT_TRACK=1`. stdout and stderr pass through; the exit code is OpenSpec's. Errors that stop before running exit 2 with these exact lines on stderr:

- no `spec.version`: `toolkit.yaml: missing required key 'spec.version' (add a spec block; see docs/guides/spec.md)`
- `npx` or `node` not on `PATH`: `tld ops spec: node and npx are required (OpenSpec <version> needs Node.js 22.20.0 or newer)`
- Node older than 22.20.0 (from `node --version`): `tld ops spec: Node.js <found> is too old; OpenSpec <version> needs 22.20.0 or newer`

Test seams: module-level `_run(argv, cwd, env) -> int` (wraps `subprocess.run`), `_which(name)` and `_node_version() -> str | None`; tests replace them with `monkeypatch`. Rejected: reimplementing validate and archive in Python (owner's decision: format drift against a project that shipped 2.0 a week ago); passing arbitrary OpenSpec arguments through (would let a prompt-injected text run `openspec feedback` or `openspec install`).

### 3.3 Profile key

`spec` is an optional top-level block, `additionalProperties: false`, one key: `version`, a string matching `^\d+\.\d+\.\d+$`, required inside the block, no default. Description: "Exact OpenSpec release the spec commands run (npm @fission-ai/openspec). Present means the repository uses specs: /spec works and /make-plan writes a spec change." A bump is a profile change, so the owner decides it through the protected-change flow.

### 3.4 `/tld:spec init` and `/tld:spec check` (playbook `spec`)

Input `init` or `check` (default `check`); anything else prints `Usage: spec [check | init]`. Profile load as `policies/profile.md` says; without `spec.version` stop with the wrapper's missing-key line.

`check` (no record, changes nothing): `tld ops spec validate --profile .tld/toolkit.yaml`; with `openspec/specs` present also `tld ops spec list --profile .tld/toolkit.yaml --json`; report the capability count and the validator's findings; the check passes when validate exits 0.

`init` (attended, writes a record): `kind: command`, `command: spec`, `attended: true`, items `survey`, `confirm`, `draft`, `validate`, `pr`. It runs `tld dod exempt`. Branch `chore/spec-init-<yyyymmdd>` from `origin/<main>`; the command is the permission to push it and open one pull request, never to merge.

1. **Survey** (read-only): `run_helper` sweeps (level `standard`) list the repository's observable behaviour areas: user-facing commands, public APIs, configuration, data formats, error behaviour. Propose a flat list of capabilities (kebab-case, each a durable behaviour area, no near-duplicates), each with the source paths that evidence it.
2. **Confirm**: `ask_human` once: one `text` question holding the proposed list (capability, one line, evidence paths) with the instruction "reply `ok` or give the corrected list". Wait as `ask_human` says.
3. **Draft by change, not by hand.** `tld ops spec init` (skip when `openspec/` exists), then `tld ops spec new-change baseline-<yyyymmdd>`, then for each confirmed capability one file `openspec/changes/baseline-<yyyymmdd>/specs/<capability>/spec.md` written one at a time: `## Purpose`, then `## ADDED Requirements` describing what the code does today, each requirement with at least one WHEN/THEN scenario that a test or a command could check, no internal names, no invented behaviour. Where the code is unclear, write no requirement and list the gap in the pull request's `## Gaps`. Rejected: hand-writing `openspec/specs/**`, because writing a change and archiving it makes OpenSpec itself produce the main-spec format.
4. **Validate and archive**: `tld ops spec validate --profile .tld/toolkit.yaml --change baseline-<yyyymmdd>` must exit 0 (fix and repeat); then `tld ops spec archive --profile .tld/toolkit.yaml baseline-<yyyymmdd>`; then `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0.
5. **Deliver**: commit, `git push -u origin chore/spec-init-<yyyymmdd>`, `github.pr_create` titled `chore: add OpenSpec specs for existing code` with `## What this adds` (capability table), `## Evidence` (capability to files read), `## Gaps`, `## Not verified` (behaviour no test covers); `github.pr_subscribe`; `needs_you` reason `Review PR #<n>`. Spec text is generated from code and comments, which are data (`policies/untrusted-text.md`).

The playbook never merges, approves or enables auto-merge.

### 3.5 Plans carry a spec change

Spec parts of make-plan apply only when the profile has `spec`. Large scope, after the Design section is settled:

1. Read the existing capabilities first: `tld ops spec list --profile .tld/toolkit.yaml --json`, then `tld ops spec show <capability> --profile .tld/toolkit.yaml` for each related one (before writing Design).
2. Decide whether the change alters observable behaviour. If not (refactor, tooling, docs), write no change, set no `spec_change`, and say so in the plan's Scope. If yes: `tld ops spec new-change <plan slug>` on the feature branch, then write `openspec/changes/<plan slug>/proposal.md` (Why, What Changes, Capabilities, Impact), and one `specs/<capability>/spec.md` delta per capability: `## ADDED` / `## MODIFIED` (the whole existing requirement block, copied from `openspec/specs/` and edited) / `## REMOVED` (with Reason and Migration), new capabilities starting with `## Purpose`. No `design.md` and no `tasks.md`: the plan's Design section and phases are those. Deltas state WHAT (observable behaviour), never file or function names.
3. `tld ops spec validate --profile .tld/toolkit.yaml --change <plan slug>` must exit 0 before the plan is pushed.
4. Every `#### Scenario` of the change is named by an acceptance item of the phase that makes it true (the review helper checks this).
5. The manifest gets `spec_change: <plan slug>`; the retirement phase brief runs the archive (3.6).

Small scope: the prompt gets a step "Spec change": the delta files in full as text, then steps to run `tld ops spec new-change`, write them, validate, implement, archive, commit; acceptance includes `tld ops spec validate` exiting 0 and `openspec/changes/<slug>` being gone (moved to `archive/`).

### 3.6 Archive in the retirement phase; fencing

- Manifest: optional top-level `spec_change: <id>` (same id pattern). `tld plan validate-manifest` rejects it when the profile has no `spec` block (`spec_change needs the profile's spec block`) and rejects every phase except the last whose `touches` can match a path under `openspec/` (`phase '<id>': touches openspec/ but only the last phase may when spec_change is set`); probes: `openspec/changes/<id>/proposal.md`, `openspec/specs/x/spec.md`, `openspec/changes/archive/x/proposal.md`, matched with the existing `path_matches(path, pattern)` helper.
- The retirement phase lists `openspec/**` in `touches`, runs `tld ops spec archive --profile .tld/toolkit.yaml <id>`, then `tld ops spec validate --profile .tld/toolkit.yaml`, and commits the moved change and updated specs. `final_checks` gets: `tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/<id> does not exist`.
- implement: a merge whose diff touches `openspec/` in a phase other than the last is sent back; the final review checks the same final check and that every scenario of the archived change is covered by a test or acceptance item.
- Archive in the retirement phase, inside the PR, was chosen by the owner over archiving after merge: one merge lands code, plan and specs, and a failed archive is caught by CI on the same PR.

### 3.7 Status record command `spec`

`spec` joins `tld.board.record.COMMANDS`, the `command` enum of the status-record schema, `board_gate.RECORD_COMMANDS` with `RECORD_MODES["spec"] = ("init",)` (only `init` writes a record, like `docs`), and `plan_gate.OPENING`.

## 4. ADRs

None (the profile has no `docs.adr_dir`).

## 5. Manual steps

### After implementation

**ma1-real-openspec-run** (about 15 minutes). The tests fake the OpenSpec CLI, and the planning session could not run it, so one real run is the check CI cannot do.

1. In a scratch clone of any small repository that has a `.tld/toolkit.yaml` and Node.js 22.20 or newer installed (`node --version`), open the profile and add the two lines `spec:` and `  version: "2.1.0"`.
2. Start a Claude Code session on that clone and run `/tld:spec init`. Expect a question listing proposed capabilities; reply `ok`.
3. Expect a pull request titled `chore: add OpenSpec specs for existing code`; open it and check that `openspec/specs/` holds one folder per capability and `openspec/changes/archive/` holds the baseline change.
4. Run `/tld:spec check` and expect it to report no findings.
5. Report back: pass or fail, and the first error line if it failed.

## 6. Risks and open questions

- OpenSpec was read, not run (3.1). If a flag or the layout differs from 3.1, p2 stops with `status=blocked`; the owner decides between adjusting the wrapper's fixed table and pinning another version.
- `npx` downloads the package at run time: the registry must be reachable. Environments that block the registry fail with the wrapper's exit code 2 or npx's own error; the answer is a research request or an allowed host, not a fallback.
- Without `tasks.md` the archive may warn; if `openspec validate` rejects a change without `tasks.md`, p2 stops (`status=blocked`) and the owner decides whether plans write a one-line `tasks.md`.
- A large init may exceed one session's context; the survey caps the list at 15 capabilities and the playbook says so in the PR's `## Gaps` when it cut the list.
- `openspec init --tools none` might still write files outside `openspec/`; p2 checks with `git status` in its fake-free smoke step and stops if so.

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
      Read first: docs/reference/profile-reference.md, playbooks/policies/profile.md, plan section 3.3.
      1. In src/tld/schema/profile.schema.json add a top-level property `spec` next to `land` (copy its shape):
         {"type":"object","additionalProperties":false,"required":["version"],"properties":{"version":
         {"type":"string","pattern":"^\\d+\\.\\d+\\.\\d+$","description":"Exact OpenSpec release the spec commands run (npm @fission-ai/openspec). Present means the repository uses specs: /spec works and /make-plan writes a spec change."}},
         "description":"Optional. Repository uses OpenSpec specs."}. Do not add it to the top-level `required` list and give it no default.
      2. In src/tld/templates/toolkit.yaml add, after the commented `# land:` block (line 109 area), a commented block:
         `# spec:` / `#   version: "2.1.0"      # exact OpenSpec release; present = the repository uses specs`
         in the same comment style as its neighbours. The template must stay valid when uncommented.
      3. In docs/reference/profile-reference.md add table rows after the `land.max_prs` row: `spec` (no) "Section for the spec commands: /spec and the spec change /make-plan writes. Absent means the repository does not use specs" and `spec.version` (**yes** in `spec`) "Exact OpenSpec release as MAJOR.MINOR.PATCH, run through npx as @fission-ai/openspec@<version>. Docs: docs/guides/spec.md". The keys must appear as `` `spec `` and `` `spec.version ``.
      4. Tests in tests/core/test_validate_profile.py, copying test_maintenance_keys_are_checked's style: a profile with `spec: {version: "2.1.0"}` validates; `spec: {}` fails with `missing required key 'spec.version'`; `version: "2.1"`, `version: 2.1.0` (YAML string vs number: use the string "latest") and an unknown key `spec.dir` each fail; a profile without `spec` still validates and `--resolved` output has no `spec` key.
      Stop condition: if the validator does not enforce `pattern`, stop with status=blocked and say so (src/tld/profile/validate.py check()).
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_profile.py -q passes, including the new spec tests
      - .venv/bin/python -m pytest tests/adapters/claude/test_structure.py -q passes (every schema key documented)
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
    brief: |
      Read first: docs/reference/cli.md, src/tld/ops/docs_index.py (argparse and profile loading pattern, lines 480-570), plan sections 3.1 and 3.2.
      1. Create src/tld/ops/spec.py following the module convention of src/tld/ops/docs_index.py: module docstring with the usage lines, `main(argv=None) -> int`, argparse with subparsers `init`, `new-change`, `list`, `show`, `validate`, `archive`, common options `--profile` and `--root` on the parent parser, `if __name__ == "__main__": sys.exit(main())`.
      2. Implement exactly the table of plan section 3.2: a pure function `build_args(sub, ns) -> list[str]` returning the OpenSpec arguments; ID check with regex `^[a-z0-9]+(-[a-z0-9]+)*$` and the error text of 3.2; `--type` choices `spec`, `change`; `--json` on list, show, validate.
      3. Profile: read `<profile>` with yaml.safe_load; take `spec.version`; when absent print the exact missing-key line of 3.2 to stderr and return 2.
      4. Runner: module-level `_which(name)` (shutil.which), `_node_version()` (run `node --version`, strip a leading `v`, None when it fails), `_run(argv, cwd, env) -> int` (subprocess.run, no shell, returns the return code). Check node and npx with the two error lines of 3.2 (compare versions as integer tuples against (22, 20, 0)). argv is `["npx","--yes","--package",f"@fission-ai/openspec@{version}","--","openspec",*args]`; env is os.environ plus OPENSPEC_TELEMETRY=0 and DO_NOT_TRACK=1; cwd is `--root`.
      5. Register in src/tld/cli.py COMMANDS: `("ops", "spec"): ("tld.ops.spec", (), "init | new-change | list | show | validate | archive: the pinned OpenSpec CLI")`. The module has argparse `--help`, so no DOC_HELP entry.
      6. Add the row to docs/reference/cli.md in the ops block, the same format as the `docs-index` row: `tld ops spec init\|new-change\|list\|show\|validate\|archive [--profile FILE] [--root DIR]`, module `tld.ops.spec`. The literal `tld ops spec` must appear.
      7. Tests in tests/core/test_ops_spec.py with monkeypatched `_run`, `_which`, `_node_version` (no network, no node needed): one test per table row asserting the exact argv passed to `_run` and the env flags; invalid id exits 2 with the 3.2 text and `_run` not called; missing `spec.version` exits 2 with the exact line; missing npx, old node and exactly 22.20.0 (accepted); the exit code of `_run` is returned unchanged; `tld ops spec --help` exits 0 through the real CLI (`tests` call `cli.main`).
      8. Smoke step (stop condition): if `node --version` here is 22.20.0 or newer and the npm registry is reachable, run `tld ops spec init` in an empty `git init` temp directory outside the repository with a temp profile `spec: {version: "2.1.0"}`, then `new-change smoke-test`, `validate`, and record in your report what each printed and whether any file outside `openspec/` appeared. If a flag in the plan's table is rejected by OpenSpec, `validate` rejects a change that has no tasks.md, or a file appears outside `openspec/`, stop with status=blocked and quote the output. If node or the registry is unavailable, say so and continue.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_ops_spec.py -q passes
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_cli_reference.py -q passes
      - .venv/bin/python cli/tld ops spec --help exits 0 and lists init, new-change, list, show, validate and archive
  - id: p3-manifest-spec-change
    title: Add the spec_change manifest key and its fence
    depends_on: [p1-profile-spec-key]
    complexity: S
    touches:
      - src/tld/plan/manifest.py
      - tests/core/test_validate_manifest.py
      - docs/reference/profile-reference.md
    brief: |
      Read first: src/tld/plan/manifest.py (lines 20-50, the validate function from line 231), plan section 3.6.
      1. Add "spec_change" to TOP_KEYS (src/tld/plan/manifest.py:26) after "tracking_issue".
      2. In validate(): when "spec_change" is in the manifest it must be a string matching `^[a-z0-9]+(-[a-z0-9]+)*$`, else the error `spec_change must be lower-case words joined by hyphens`. When it is set and a profile was given without a `spec` block the error is `spec_change needs the profile's spec block`.
      3. When set and valid, for every phase except the last entry of `phases`, if any `touches` entry matches one of the probe paths `openspec/changes/<id>/proposal.md`, `openspec/specs/x/spec.md`, `openspec/changes/archive/x/proposal.md` using the existing `path_matches(path, pattern)` helper (see how it is called near line 224), add `phase '<id>': touches openspec/ but only the last phase may when spec_change is set`. The last phase is never flagged.
      4. docs/reference/profile-reference.md, section "The manifest": add one sentence: `spec_change` (optional) names the OpenSpec change the plan carries; the profile needs a `spec` block and only the last phase may touch `openspec/`.
      5. Tests in tests/core/test_validate_manifest.py next to the unknown-key tests (line 396 area): valid spec_change passes with a spec profile; bad id; no spec block; a middle phase touching `openspec/**` and `**/*.md`-style broad globs that match the probes (broad `**` matches count); the last phase touching `openspec/**` passes; without spec_change a middle phase touching openspec/ passes.
      Stop condition: if path_matches has another signature, read its definition and use it as defined; if no helper does glob matching of one path against one pattern, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_manifest.py -q passes, including the new spec_change tests
      - grep -n "spec_change" src/tld/plan/manifest.py matches in TOP_KEYS and validate
  - id: p4-spec-record-and-guards
    title: Register the spec command in the status record and the guards
    depends_on: []
    complexity: M
    touches:
      - src/tld/board/record.py
      - src/tld/schema/status-record.schema.json
      - src/tld/guard/board_gate.py
      - src/tld/guard/plan_gate.py
      - tests/core/test_status_record.py
      - tests/core/test_hook_board_gate.py
      - tests/core/test_hook_plan_gate.py
      - tests/core/test_contracts.py
    brief: |
      Read first: src/tld/board/record.py (line 42 area), src/tld/guard/board_gate.py (lines 25-30), plan section 3.7.
      1. src/tld/board/record.py: add "spec" to COMMANDS (line 42) after "questions".
      2. src/tld/schema/status-record.schema.json: add "spec" to the `command` enum (line 201 area) and to the sentence listing commands in the description (line 198 area), in the same order as COMMANDS.
      3. src/tld/guard/board_gate.py: add "spec" to RECORD_COMMANDS and `"spec": ("init",)` to RECORD_MODES, exactly like `docs` (only `/tld:spec init` must write a record; `/tld:spec` and `/tld:spec check` must not).
      4. src/tld/guard/plan_gate.py: add "spec" to OPENING.
      5. tests/core/test_contracts.py: add "spec" to the `expected` set of test_record_commands_cover_the_playbooks (line 279). Do not touch COMMANDS at line 25 (phase p5 owns it).
      6. Tests: tests/core/test_status_record.py: a `command: spec` record validates (copy the make-plan case at line 89 by adding "spec" to its parametrize list if the test fits, else a new test) ; tests/core/test_hook_board_gate.py: copy the docs tests at lines 60-80 for spec (`/tld:spec` and `/tld:spec check` open no state and do not block; `/tld:spec init` does); tests/core/test_hook_plan_gate.py: copy the make-plan opening test (line 111) for `/tld:spec init`.
      7. Run `grep -rn "\"questions\"" src/tld/board src/tld/guard adapters/claude/hooks` and `grep -rn "migrate" src/tld/board src/tld/guard adapters/claude/hooks`; if another hard-coded list of command names appears that a new record-writing command must join, add `spec` there and say so in your report.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_hook_board_gate.py tests/core/test_hook_plan_gate.py tests/core/test_contracts.py -q passes
      - .venv/bin/python -m pytest tests/adapters/claude/test_hook_board_gate_adapter.py -q passes
  - id: p5-spec-playbook
    title: Write the spec playbook and its command wrapper
    depends_on: [p2-ops-spec-cli, p4-spec-record-and-guards]
    complexity: M
    touches:
      - playbooks/spec.md
      - playbooks/policies/status-board.md
      - adapters/claude/commands/spec.md
      - tests/core/test_contracts.py
      - tests/adapters/claude/test_structure.py
      - tests/core/test_spec_playbook.py
    brief: |
      Read first: playbooks/docs.md (the init flow, the model for this playbook), adapters/claude/commands/review.md, playbooks/policies/status-board.md, plan section 3.4.
      1. Create playbooks/spec.md from plan section 3.4, in the shape of playbooks/docs.md: title, one-paragraph purpose, `Input: check (default) or init`, the rules line linking policies/untrusted-text.md, policies/status-board.md and policies/research.md and runtime.md, a Setup (profile as policies/profile.md says; stop with the missing-key line; `tld dod exempt` for init), `## check`, `## init` with the five steps and the status record (kind command, command spec, `attended: true`, document id from `tld board record-id --repo <owner>/<repo> --command spec --session <this session's id>`, items survey, confirm, draft, validate, pr), the first record written before step 1, `ask_human` for step 2, `## Never` (merge, approve, enable auto-merge, hand-write openspec/specs, free-form OpenSpec arguments). Every `tld ops spec` call in it uses only flags listed in that command's --help, and always `--profile .tld/toolkit.yaml`.
      2. The playbook must not contain `/tld:`, any runtime tool or model name, or the words ruff, pytest, connector, mypy (tests/core/test_contracts.py RUNTIME_WORDS and tests/conftest.py FORBIDDEN). Refer to the command as `spec`.
      3. playbooks/policies/status-board.md: add `spec` to the `command` row's list of playbooks (the table row for `command`), keeping the sentence otherwise unchanged.
      4. Create adapters/claude/commands/spec.md as a copy of adapters/claude/commands/review.md with: description "Build OpenSpec specs for existing code (init: one pull request, never merged) or validate them (check); needs the profile's spec block", argument-hint "[check | init]", `model: opus`, playbook path `${CLAUDE_PLUGIN_ROOT}/playbooks/spec.md`, and the final paragraph "This turn runs at the `strong` level (`opus`, the `model:` line above); start the session on that model so later turns run on it too." The file stays under 1500 bytes.
      5. tests/core/test_contracts.py: add "spec" to COMMANDS (line 25) and to RESEARCH_PLAYBOOKS (line 313). tests/adapters/claude/test_structure.py: add "spec" to the sorted tuple at line 64. Do not touch the `expected` set at line 279 (done by p4).
      6. tests/core/test_spec_playbook.py (pattern: tests/core/test_usage_playbook.py): the playbook names the six `tld ops spec` forms it uses, contains `attended: true`, the `Usage: spec [check | init]` line, and each of the five init step headings; and the wrapper names the playbook path.
      Stop condition: if any test in tests/core/test_contracts.py fails for a reason the brief does not cover, read the failing assertion, fix the playbook text, not the test; stop with status=blocked only if the test itself contradicts this brief.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_spec_playbook.py tests/adapters/claude/test_structure.py tests/core/test_no_project_words.py -q passes
      - .venv/bin/python cli/tld profile validate .tld/toolkit.yaml exits 0
  - id: p6-plan-playbooks
    title: Make make-plan write the spec change and implement archive it
    depends_on: [p2-ops-spec-cli, p3-manifest-spec-change]
    complexity: M
    touches:
      - playbooks/make-plan.md
      - playbooks/implement.md
      - tests/core/test_make_plan_spec.py
    brief: |
      Read first: playbooks/make-plan.md, playbooks/implement.md (sections 4 and 6), plan sections 3.5 and 3.6.
      1. playbooks/make-plan.md, Setup step 1: add a bullet: `"Spec parts" (the spec change, `spec_change`, the spec steps of the review) apply only with the profile's `spec` block; without it leave them out and never mention specs.`
      2. Section 0 step 2: with the spec block, add: read the existing capabilities with `tld ops spec list --profile .tld/toolkit.yaml --json` and `tld ops spec show <capability> --profile .tld/toolkit.yaml` for each related one before writing the Design.
      3. After section 2's Design description add a new subsection `### The spec change (spec parts)` containing plan section 3.5 items 2 to 4 in imperative form (decide whether behaviour changes; `tld ops spec new-change <plan slug>`; proposal.md and one delta per capability; MODIFIED is the whole existing block; no design.md or tasks.md; validate with `tld ops spec validate --profile .tld/toolkit.yaml --change <plan slug>` before the push; every `#### Scenario` is named by an acceptance item of the phase that makes it true). The files are committed to the feature branch together with the plan.
      4. The manifest block in section 2: add the line `spec_change: <plan slug>   # optional; spec parts only; the OpenSpec change this plan carries` after `closes`, and in the retirement-phase sentence add: with `spec_change` the retirement phase lists `openspec/**` in `touches`, runs `tld ops spec archive --profile .tld/toolkit.yaml <id>` then `tld ops spec validate --profile .tld/toolkit.yaml`, and no other phase touches `openspec/`; `final_checks` gets `tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/<spec_change> does not exist`.
      5. Small scope section: add a numbered step in the Steps list (spec parts): the delta files in full as text, then the steps new-change, write, validate, implement, archive, commit, and the two acceptance items of plan section 3.5.
      6. Section 4: add to the helper's list (spec parts) that every Scenario has an acceptance item, MODIFIED blocks are whole, deltas name no file or function.
      7. playbooks/implement.md Merge step 2: add one sentence: with `spec_change` in the manifest, a diff that touches `openspec/` in any phase but the last is sent back. Section 5 final reviewer brief: add: with `spec_change`, run `tld ops spec validate --profile .tld/toolkit.yaml`, check `openspec/changes/<spec_change>` is gone and that every scenario of the archived change under `openspec/changes/archive/` is covered by a test or an acceptance item; failing any is a blocking finding. Section 6 step 2: `final_checks` already covers it; add nothing.
      8. Keep both files free of `/tld:`, runtime tool names and the forbidden words (see p5's brief item 2). Do not renumber existing sections.
      9. tests/core/test_make_plan_spec.py (pattern tests/core/test_usage_playbook.py): make-plan.md names `spec_change`, `tld ops spec new-change` and `tld ops spec archive`, and says the spec parts apply only with the spec block; implement.md names `spec_change` and `openspec/`.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_make_plan_spec.py tests/core/test_contracts.py tests/core/test_no_project_words.py -q passes
      - grep -c "spec_change" playbooks/make-plan.md playbooks/implement.md both report at least 1
  - id: p7-docs-guide
    title: Write the spec guide and update the command lists
    depends_on: [p5-spec-playbook, p6-plan-playbooks]
    complexity: M
    touches:
      - docs/guides/spec.md
      - README.md
      - docs/architecture/design.md
      - docs/architecture/hooks.md
      - playbooks/setup.md
      - .claude-plugin/plugin.json
      - .claude-plugin/marketplace.json
    brief: |
      Read first: README.md (the Commands table, lines 56-71), docs/guides/questions.md (the shape of a guide), plan sections 3 and 5.
      1. Create docs/guides/spec.md: `# Specs with OpenSpec`, a summary of at most 3 lines, then: what it is and the opt-in (`spec.version`, an example profile snippet), Node.js 22.20+ and registry access, `/tld:spec init` and `check`, how make-plan writes the change and implement archives it in the last phase, the fence on `openspec/`, the supply-chain notes (exact pinned version, six fixed subcommands, telemetry off), how to bump the version (protected profile change), and the manual check ma1 from plan section 5. Under 120 lines. Report `docs-changed: added docs/guides/spec.md`.
      2. README.md: add a row to the Commands table after `/tld:migrate`: `/tld:spec [check \| init]` | builds OpenSpec specs for existing code (one pull request, never merged) or validates them; with a `spec` profile block make-plan also writes the spec change and implement archives it ([guide](docs/guides/spec.md)).
      3. docs/architecture/design.md lines 38-40 (the Playbooks paragraph): add `spec` to the list of playbooks; add one sentence on the spec layer: OpenSpec is wrapped, pinned and opt-in, and the plan's spec change is archived by the retirement phase.
      4. docs/architecture/hooks.md lines 265-266: add `spec` to the list of commands that open a session when plan-gate is on, and to the board-gate list that says which commands must write a record (only `spec init`).
      5. playbooks/setup.md line 52: add `spec` to the list of blocks that setup never writes.
      6. .claude-plugin/plugin.json line 4 and .claude-plugin/marketplace.json lines 7 and 13: add `/spec` to the command list in each description string (change nothing else; versions stay equal).
      Do not edit docs/README.md or CHANGELOG.md (phase p8).
    acceptance:
      - .venv/bin/python -m pytest tests/adapters/claude/test_structure.py tests/core/test_docs_links.py tests/core/test_contracts.py -q passes
      - grep -c "spec" .claude-plugin/plugin.json prints at least 1 and .venv/bin/python cli/tld profile validate .tld/toolkit.yaml exits 0
  - id: p8-retire
    title: Retire the plan - index row, changelog line, eval baseline
    depends_on: [p7-docs-guide]
    complexity: S
    touches:
      - docs/README.md
      - CHANGELOG.md
      - evals/baselines/default.json
    brief: |
      Read first: docs/README.md, CHANGELOG.md (the `## [Unreleased]` section), CONTRIBUTING.md (the baseline refresh, lines 80-84), plan section 3.
      Docs changed by earlier phases: added docs/guides/spec.md (add its index row).
      1. docs/README.md: in `## Guides` add after the `guides/questions.md` row: `- [guides/spec.md](guides/spec.md) - specs with OpenSpec: the profile's spec block, /spec init and check, the spec change a plan carries and its archive; read when setting up specs or changing the spec commands.`
      2. CHANGELOG.md: under `## [Unreleased]` add one line in the file's existing style: `/tld:spec builds OpenSpec specs for existing code; with a spec profile block /tld:make-plan writes the spec change and /tld:implement archives it in the last phase (#71).` No version heading.
      3. Refresh the eval baseline: `python3 evals/run.py baseline --refresh-hashes`, then `python3 evals/run.py check-baseline` must exit 0. Commit only evals/baselines/default.json from it.
      4. This repository's profile has no `spec` block and this plan has no `spec_change`, so nothing under `openspec/` changes; do not create it.
      5. Run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0.
      Stop condition: if check-baseline still fails after the refresh, stop with status=blocked and quote the output.
    acceptance:
      - python3 evals/run.py check-baseline exits 0
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - grep -n "guides/spec.md" docs/README.md matches
      - grep -n "OpenSpec" CHANGELOG.md matches under the Unreleased section
```
