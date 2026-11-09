# Design: devflow, a plan → implement toolkit for Claude Code on the web

Status: review 1 answered; this is the design as built. The three decisions in §8 are resolved.

Since devflow 0.4 the SessionStart-hook route and `toolkit.ref` no longer exist; plugins in the Claude Project are the only delivery route (see delivery.md). Section 3 is kept as the record of the probe that led to the first design.

## 1. What this is

PrivacyFence's `/make-plan`, `/implement` and `/dod` (plus the generic half of its `steward` skill)
moved into a plugin marketplace, with every project fact lifted into `.claude/toolkit.yaml`. The
commands keep their structure and wording; each hard-coded path or command becomes a lookup through
one skill, `project-profile`.

I read all of the PrivacyFence files you listed in full, plus the PrivacyFence docs they point at
(`docs/coding-and-testing-guidelines.md` §2.7, `docs/testing-policy.md`, `docs/adr/README.md`,
`.github/`), and Nightshift's marketplace, stack schema, `ns-python` stack and the four skills.
Nightshift's runtime is not used. From it I take: the marketplace shape, the `review-checklist` and
`secure-code-review` skills, and the idea that a stack is a skill the profile selects.

## 2. Layout

```
.claude-plugin/marketplace.json         # name: claude-toolkit; plugins: devflow, stack-python, stack-swift, stack-ipados, stack-go
plugins/devflow/
  .claude-plugin/plugin.json
  commands/{make-plan,implement,dod,review}.md   # review: see docs/review.md
  commands/{board,deps,upstream,land}.md         # maintenance commands: see docs/maintenance.md
  skills/project-profile/SKILL.md       # how every command reads, validates and quotes the profile
  skills/pr-steward/SKILL.md            # generic steward policy; table comes from ci.dispatchable
  skills/review-checklist/SKILL.md      # Nightshift, adapted (no run-ledger / R-AG rules)
  skills/secure-code-review/SKILL.md    # Nightshift, adapted; whole-repository section for /review
  skills/{test-review,docs-review}/SKILL.md   # checklists for /review's test and documentation dimensions
  skills/status-board/SKILL.md          # how a session writes its status record to the board
  scripts/validate_manifest.py          # CLI: validate_manifest.py <plan.md|manifest.yaml> [--profile P]
  scripts/validate_profile.py           # CLI: validate_profile.py [.claude/toolkit.yaml]
  scripts/review_decisions.{py,html}    # CLI: review_decisions.py <items.json> <out.html>, /review's decisions page
  scripts/{validate_status_record,build_board,board_stale,pick_release,upstream_sync,land_order}.py
  schema/profile.schema.json
  schema/status-record.schema.json
  board/                                # the status board page (board.html, rules.js)
  templates/devflow-land.yml            # the workflow /land installs
plugins/stack-python/skills/stack-python/SKILL.md
plugins/stack-swift/skills/stack-swift/SKILL.md
plugins/stack-ipados/skills/stack-ipados/SKILL.md
plugins/stack-go/skills/stack-go/SKILL.md
templates/toolkit.yaml                  # commented starter profile
docs/{README.md,profile-reference.md,delivery.md,design.md,maintenance.md,migrating-privacyfence.md}
docs/design/maintenance-spike.md        # record of the spike behind the maintenance commands
tests/                                  # pytest; fixtures from real PrivacyFence plans
.github/workflows/test.yml
```

I did not add `test-strategy` and `adr` as skills: `test-strategy` is Nightshift-run-specific
(`RUN/`, `ns:<id>` xfail reasons), and ADR guidance in PrivacyFence is project-owned
(`docs/adr/README.md`), so the profile points at it (`docs.adr_dir`, `docs.adr_bar`) instead of
shipping a competing template. Say so if you want a generic `adr` skill anyway.

Scripts are standard library plus PyYAML; the schema is checked by a small hand-rolled validator in
`validate_profile.py` (no `jsonschema` dependency), with `profile.schema.json` as the documented,
editor-friendly source of truth that a test keeps in sync with the code.

## 3. Delivery test result (real cloud session)

I started a real cloud session with `create_session` on this repo (Sonnet, `auto` permission mode)
whose committed `.claude/settings.json` ran a SessionStart hook. The hook wrote, at startup:

| written by the hook | location |
|---|---|
| command `probe-user-cmd` | `~/.claude/commands/` |
| skill `probe-user-skill` | `~/.claude/skills/probe-user-skill/SKILL.md` |
| command `probe-proj-cmd` | `<project>/.claude/commands/` |
| skill `probe-proj-skill` | `<project>/.claude/skills/probe-proj-skill/SKILL.md` |

plus two committed controls (`probe-committed`, `probe-committed-cmd`).

**Observed: all six were in the session's skill listing at the first turn, and all six were invoked
successfully through the `Skill` tool in that same session.** Hook log: started at
`…958.447`, finished at `…958.464` (17 ms of file writes); the session's first tool call was at
`…974`. So the hook finishes before the listing is built, and both locations are picked up with no
restart. Nothing needs to be installed a second time.

Two further facts from that run:

* **Project-level files are untracked files.** The session's stop hook
  (`~/.claude/stop-hook-git-check.sh`) immediately complained "There are untracked files in the
  repository. Please commit and push", which is the failure you want to prevent for workers.
  `~/.claude/` is outside the repo and has no such problem.
* `CLAUDE_CODE_REMOTE=true`, `HOME=/root`, `CLAUDE_PROJECT_DIR=/home/user/<repo>` were set in the hook.

**Decision: install into `~/.claude/` by default** (`commands/`, `skills/`, and the scripts under
`~/.claude/devflow/`). It cannot collide with the project's own `.claude/commands/` or `skills/`
(a project `steward` skill stays untouched), and it cannot be committed. `DEVFLOW_SCOPE=project`
switches to `<project>/.claude/` for people who want it; in that mode the script appends every
installed path to `.git/info/exclude`, as you asked. (In user scope the exclude is moot, so the script
does not write it.)

Not tested, and said so in `docs/delivery.md`:

1. **Route 1 (Claude Project plugins)**: it is a settings-UI feature of claude.ai and cannot be driven
   from a session. The marketplace is validated structurally (`claude plugin validate`, if the CLI is
   in the container, else by a test of the JSON against Anthropic's documented fields).
2. **Typing `/probe-user-cmd` in the web UI.** The `Skill` tool resolved the command names, which is
   the same registry; I did not drive the UI.
3. **Fetching the pinned tag from a PrivacyFence session**: from this container
   `git ls-remote https://github.com/andras-tkcs/claude-toolkit` and `codeload.github.com` both work.
   Whether a *private* toolkit repo is reachable from a project's session depends on the session's
   repo access. Decision 2 below.

The vendoring-script + PR-bot fallback you described is **not needed** and I will not build it.

## 4. The profile: `.claude/toolkit.yaml`

Rules: a key marked **required** that is absent makes the command stop with
`toolkit.yaml: missing required key 'verify.fast' (see docs/profile-reference.md)`, naming the key.
An optional key that is absent means "not used in this project". Only two keys have a stated
default, both from your brief: `docs.plan_dir` (`docs/`) and `models` (below). Unknown keys are an
error (typos must not be silent). Commands never fall back to a PrivacyFence value.

| Key | Req. | Meaning | PrivacyFence value |
|---|---|---|---|
| `toolkit.ref` | for hook | tag the SessionStart hook installs | `v0.1.0` |
| `project.name` | no | used in prose ("planner for X"); absent → the repo name | `PrivacyFence` |
| `docs.must_read` | **yes** (may be `[]`) | files planner, workers and final reviewer read first | `CLAUDE.md`, `CONTRIBUTING.md`, `docs/releasing.md`, `docs/coding-and-testing-guidelines.md`, `docs/testing-policy.md`, `docs/adr/README.md` |
| `docs.plan_dir` | no (default `docs/`) | where `<slug>-plan.md` and the manual-steps HTML live | `docs/` |
| `docs.adr_dir` | no | ADRs used iff present | `docs/adr` |
| `docs.adr_index` | no | index file that must list each new ADR | `docs/adr/README.md` |
| `docs.adr_bar` | no (with `adr_dir`) | where the "needs an ADR" criteria are written | `CONTRIBUTING.md#decisions-plans-and-adrs` |
| `docs.changelog.file` / `.section` | no | user-visible changes are added here; never a version heading | `CHANGELOG.md` / `## [Unreleased]` |
| `git.main_branch` | **yes** | base for plans, features, PRs | `main` |
| `git.branch_pattern` | **yes** | human-readable rule, used in prompts | `<type>/<kebab-case>` |
| `git.branch_types` | no | allowed `<type>` values | `[feature, fix, chore, tests]` |
| `git.merge_style` | no | `merge-commit` or `squash`; only quoted in worker/steward text | `merge-commit` |
| `verify.fast` | **yes** | run after every merge in `/implement` | `ruff check .`, `python3 -m pytest tests/unit -q` |
| `verify.dod` | **yes** | the blocking gate `/dod` runs, in order | see below |
| `verify.dod_conditional[]` | no | `{when: [globs], do: text}` rows `/dod` checks against the diff | 5 rows (connector clients, MCP dispatch, MCP auth/shim, dependencies, `cloudflare/downloads/`) |
| `verify.dod_manual[]` | no | judgement rows `/dod` reports `ok / needs attention / n/a` | 7 rows |
| `verify.dod_doc` | no | pointer to the project's human-readable DoD, quoted in the report | `docs/coding-and-testing-guidelines.md#27-…` |
| `ci.dispatchable[]` | no | `{workflow, use_when, notes?}`: work the container cannot do, dispatched against the session's own branch | 7 entries, see below |
| `stacks` | **yes** (may be `[]`) | stack skills to load | `[python]` |
| `models.planner/orchestrator/worker/reviewer` | no | default `opus / sonnet / sonnet / opus` | the defaults |
| `project_steward` | no | project skill with policy that fits no key | `.claude/skills/steward/SKILL.md` |

`verify.fast` and `verify.dod` entries are a string (`"ruff check ."`) or a mapping
`{run, cwd?, narrow?, skip_when_narrowed?}`. That carries PrivacyFence's `/dod` details without PF
words in the plugin: `cwd: mcpb/shim` for the `npm` rows; `narrow: "pytest -v {args}"` so `/dod
tests/unit/test_gate.py` narrows the run, and `skip_when_narrowed: true` on the coverage-floor row,
which `/dod` then reports as `n/a (partial run)` exactly as today. PrivacyFence's `verify.dod`:

```yaml
verify:
  fast: ["ruff check .", "python3 -m pytest tests/unit -q"]
  dod:
    - run: "pytest -v --cov=src/privacyfence --cov-branch --cov-report=term-missing --cov-report=json:coverage.json"
      narrow: "pytest -v {args}"
    - run: "python3 scripts/check_coverage_floor.py coverage.json"
      skip_when_narrowed: true
    - "ruff check ."
    - "bandit -c pyproject.toml -r src"
    - "python3 scripts/mypy_strict_modules.py"
    - {run: "npm test", cwd: mcpb/shim}
    - {run: "npm run typecheck", cwd: mcpb/shim}
```

`ci.dispatchable` for PrivacyFence: `qa-record-fixture.yml`, `connector-live-check.yml`,
`windows-graphical-session.yml`, `linux-graphical-session.yml`, `macos-graphical-session.yml`,
`build.yml`, `release.yml` (the "dry run first, maintainer decides" note goes in `notes`).
The container facts in the PrivacyFence steward file (concurrency group, "workflow must already be on
`main`", fixture-diff review, no tag push, Chromium via `PRIVACYFENCE_TEST_CHROMIUM`, "do not follow
Dependabot PRs") stay in the project's own `steward` skill via `project_steward`. "Workflow must be on
the default branch" is true everywhere, so it moves into the generic `pr-steward`.

### What moves where (every PrivacyFence fact I found)

| In the originals | Becomes |
|---|---|
| `CLAUDE.md`, `CONTRIBUTING.md`, `docs/releasing.md`, … read lists (make-plan §0.2, child brief rule 2, final reviewer) | `docs.must_read` |
| `docs/<slug>-plan.md`, `…-plan-manual-steps.html`, `final_checks` example | `docs.plan_dir` |
| `docs/adr/`, "CONTRIBUTING.md's ADR bar", next free ADR number, ADR `final_checks` line | `docs.adr_dir`, `adr_index`, `adr_bar`; whole ADR parts are skipped when absent |
| `CHANGELOG.md [Unreleased]` in briefs, retirement phase, `final_checks` | `docs.changelog` (skipped when absent) |
| `main`; `<type>/<kebab-case>`; "never `feat/`" | `git.main_branch`, `git.branch_pattern`, `git.branch_types` |
| `ruff check .` + `pytest tests/unit` after merge; in final review | `verify.fast` |
| `/dod` command list, conditional + manual rows | `verify.dod`, `verify.dod_doc` |
| steward dispatch table | `ci.dispatchable`; container facts → `project_steward` |
| Opus/Sonnet table | `models`; the command front-matter `model:` stays `opus`/`sonnet` |
| `src/privacyfence/…`, `pytest …` in the manifest example | stack skill supplies examples; the example in `make-plan.md` uses placeholders |
| "A missing QA credential is not a test failure" | generic: "a missing credential/capability is a dispatch, not a failure" (pr-steward) |
| `/cut-release`, `/qa-record` | stay in PrivacyFence |

Model ids stay in the commands as an alias table (`opus → claude-opus-5-5`, `sonnet →
claude-sonnet-5-5`), as in the original; the profile holds aliases. The `model:` line in command
front-matter is static, so `models.planner`/`orchestrator` only document intent and are checked
against it; `worker` and `reviewer` drive `create_session`.

### Manifest compatibility

Same fields as today, unchanged. `validate_manifest.py` checks exactly what `implement.md` §0.3 and
`make-plan.md` §4 list: YAML parses; required top-level keys; phase `id` unique; every `depends_on`
exists; no cycle; `brief` and `acceptance` present and non-empty; `complexity` ∈ {S, M} if present;
`worker_model: opus` needs `worker_model_reason`; same-wave (neither reaches the other) phases have
disjoint `touches` (glob-aware overlap, not just string equality); `manual_before`/`manual_after`
items have `id`/`title`; an old `manual:` is read as `manual_after`; `manual_steps_artifact` needs
`manual_steps_source`. It accepts a plan `.md` (extracts the block under `## Implementation
manifest`) or a bare YAML file. Exit 0/1, one error per line. I will run it against the real
manifests on `plan/atlassian-user-names` (7 phases) and `plan/plugin-framework`.

## 5. Commands: how they change

* **make-plan**: same sections and wording. Section 0.2 reads `docs.must_read` + the stack skills +
  `project_steward`. ADR bullets conditional on `docs.adr_dir`. Plan path from `docs.plan_dir`. The
  "can the steward table dispatch it?" check reads `ci.dispatchable`. The manifest example uses
  `<verify command from the stack skill>`. Inline Python in §4 → `validate_manifest.py`.
* **implement**: same. Section 0.3 → `validate_manifest.py`. Post-merge verification runs
  `verify.fast` + the manifest's `verify_after_merge`. The child brief's read list is `docs.must_read`.
  Final reviewer runs `verify.fast` and reads the same list. The PR is driven to green via `pr-steward`.
* **dod**: runs `verify.dod` (honouring `narrow`/`skip_when_narrowed`), then reads `verify.dod_doc`
  and walks its rows against `git diff --stat origin/<main>...HEAD`, then the manual items; if
  `dod_doc` is absent it says so and runs only the gate.
* **board**: publishes the status board page once; `/board prune` deletes stale records after one confirmation.
* **deps**: weekly unattended dependency triage; fixes red Dependabot and audit groups, opens pull requests, never merges.
* **upstream**: weekly unattended sync of a patch-carrying fork to the newest upstream release tag, one commit, one pull request.
* **land**: orders the bot's open pull requests, resolves conflicts before review, runs CI once, installs the land workflow.
* Every command starts with the same two lines: load `project-profile`, run `validate_profile.py`;
  a failure message is shown verbatim and the command stops.
* Finding the scripts: `project-profile` documents one resolution order (plugin root → `~/.claude/devflow`)
  so the same command text works under both delivery routes.

## 6. Stack skills

`stack-python`: venv at `.venv`, never the system `pip`; install `-e .[dev,test]` if extras exist; tool
conventions; how to write `acceptance` (named test node ids, `grep`, command + expected output) and
`verify_after_merge` (targeted `pytest <paths> -q`, never the whole suite per merge). Mentions ruff/pytest
by design (allowed in this plugin only).

`stack-swift`: `swift build` / `swift test` work in the container for SwiftPM packages (Linux
Foundation only, no UIKit/AppKit/SwiftUI); `xcodebuild`, simulators, signing do not. Workers write
code and tests; iOS/macOS verification is a `ci.dispatchable` macOS workflow, and the planner must put
it in `verify_after_merge` as `dispatch <workflow> on <branch>`, not as a shell command. A starter
workflow snippet goes in the skill. The profile key `ci.dispatchable` must contain a workflow whose
`use_when` mentions the macOS runner; `validate_profile.py` warns (not errors) when `stacks`
includes `swift` and `ci.dispatchable` is empty.

`stack-ipados` (added later): layered on `stack-swift`, never alone (the validator warns). A layout
that keeps models and view models in a local SwiftPM package (`swift test` here) and leaves a thin
app target with synchronized folders (no `.pbxproj` edits); the iPad behaviours a UI phase must name
(any window size, split view, scenes, keyboard, pointer, Pencil, drag and drop, accessibility);
a starter workflow that picks an iPad simulator by query. Same dispatchable warning as `swift`.

`stack-go` (added later): toolchain from `go.mod`, the project's task runner over bare commands,
the gofmt / vet / build / test / race / lint / govulncheck ladder, error, context and goroutine
conventions, table-driven tests with `httptest`, acceptance as `go test <pkg> -run '^Name$'`, and
`go.mod` as the usual overlap between parallel phases.

## 7. Tests and CI

pytest, stdlib + PyYAML: manifest (good; missing field; unknown `depends_on`; cycle; overlapping
`touches` in a wave; `worker_model: opus` without reason; real PrivacyFence manifests from git history
stored under `tests/fixtures/`), profile (good; each missing required key named; unknown key; bad
types; PrivacyFence profile), a **no-project-words test** that greps `plugins/devflow`,
`plugins/stack-swift`, `plugins/stack-ipados`, `plugins/stack-go` and `templates/` for `privacyfence|ruff|pytest|src/privacyfence|connector`
(case-insensitive; `stack-python` and `docs/` exempt), plus marketplace/plugin JSON structure. Workflow `.github/workflows/test.yml` runs it all on Python 3.11 and 3.13.

Note the string check also catches the word `connector` in the generic text: I will phrase
"live connector credentials" as "live external-service credentials".

## 8. Decisions (answered at review 1)

1. **Install location: user scope.** In claude.ai/code a session runs in a fresh Linux container whose
   `HOME` is `/root`; `~/.claude/` there is the container's own, re-created per session (the probe
   listed `/root/.claude/{skills,commands,plugins}`). Nothing touches your machine or the repo.
2. **Toolkit repo is public**; the hook needs no token.
3. **DoD lives in the profile.** `verify.dod_conditional` (`when` globs + `do` text) and
   `verify.dod_manual` (text rows) replace `verify.dod_doc`, which stays optional as a pointer only.
   PrivacyFence's rows are in its profile, copied to `tests/fixtures/privacyfence-toolkit.yaml`.

## 9. Housekeeping note

The probe commit (`WIP delivery probe`) is in this branch's history and removed again in the next
commit, so the final PR diff does not contain it.

## 10. devflow v2 and the maintenance commands

Version 0.4 added four commands and what they share. `/board` publishes a status board, one private
page that reads the status records every session writes through the `status-board` skill (format:
`schema/status-record.schema.json`). `/deps`, `/upstream` and `/land` are the maintenance commands:
the first two run unattended from a scheduled task, `/land` is run by the owner, and none of them
merges. `/make-plan` and `/implement` now keep a tracking issue for every plan. Profile sections
`deps`, `upstream`, `land` and the key `git.bot_login` configure the new commands. Delivery is by plugins
only. How to run and schedule the commands, the profile sections, the board and the secret and setting
`/land` needs are in [maintenance.md](maintenance.md); what a cloud session can and cannot do, which
shaped the design, is recorded in [design/maintenance-spike.md](design/maintenance-spike.md).
