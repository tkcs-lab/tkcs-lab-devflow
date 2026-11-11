# Plan: generic agents, profile-driven mandatory use, and `/setup`

Tracking issue: https://github.com/tkcs-lab/claude-toolkit/issues/17

## Goal

devflow gains ten generic agents (architect, code-reviewer, security-reviewer, test-architect,
tech-writer, website-maintainer, ux-reviewer, debugger, dependency-auditor, refactorer) that ship
inside the `devflow` plugin. A project decides in `.claude/toolkit.yaml` which of them are
**mandatory** at which point of the workflow (`/make-plan`, each `/implement` phase, the final
review, `/review`, `/dod`), whether a finding from them **blocks**, and how strict the security
reviewer is (`posture`). A required agent that did not run fails visibly. A new command `/setup`
surveys a repository and creates or updates `.claude/toolkit.yaml`, including this `agents` block,
and delivers it as one pull request that it never merges.

Nothing project-specific enters the toolkit: a security-critical repository and a UI-only app use the
same ten agents and differ only in their profile.

## Current state

- `plugins/devflow/` ships commands (`commands/*.md`), skills (`skills/*/SKILL.md`), hooks, scripts and
  schemas. There is no `agents/` directory. The `review-checklist`, `secure-code-review`, `test-review`
  and `docs-review` skills already hold the checklists the agents wrap.
- The profile schema (`plugins/devflow/schema/profile.schema.json:7`) has `additionalProperties: false`,
  so `agents` and `docs.website` need schema entries. `validate_profile.py:125` (`semantic_checks`) holds
  the cross-key rules. Only `docs.plan_dir` and `models` have defaults (`validate_profile.py:112`).
- `/implement` runs a Sonnet worker per phase (child brief, `commands/implement.md:136`), merges after an
  adversarial diff review (`:200`), and runs one Opus final review whose prompt ends with
  `REVIEW-REPORT` (`:272`). `/dod` reports a table and "does not fix anything" (`commands/dod.md:43`).
  `/review` runs one subagent per dimension (`commands/review.md:123`). `/make-plan` is this command.
- The `protect-paths` hook denies every edit of `.claude/toolkit.yaml`
  (`hooks/protect_paths.py:87`, default list in `hooks/_common.py:21`). The `dod-gate` hook shows the
  marker pattern commands use to mark a session (`hooks/dod_gate.py:50-70`).
- `tests/test_no_project_words.py` forbids the words `privacyfence`, `ruff`, `pytest`,
  `src/privacyfence` and `connector` under `plugins/devflow`, `plugins/stack-*`, `templates` and
  `.claude-plugin`. `tests/test_structure.py:28` requires all five `plugin.json` versions to be equal
  and `:61` pins the exact set of skill names. `:98` requires every schema key to appear, backticked,
  in `docs/profile-reference.md`.
- The status board accepts maintenance commands `deps`, `upstream`, `land` only
  (`schema/status-record.schema.json:61`, `scripts/validate_status_record.py:34`).
- Eval fixtures are builders `build(dest, **params) -> dict` in `evals/fixtures/` that use
  `init_repo` (`evals/fixtures/__init__.py`).

## Design

Every name, string and shape below is decided. Briefs point here instead of repeating it.

### D1. The ten agents

Files: `plugins/devflow/agents/<name>.md`, one per agent. Front matter, exactly these four keys:

```
---
name: <name>                 # equals the file name without .md
description: <one sentence of at least 40 characters: what it does and when to use it>
tools: <comma separated, see below>
model: opus | sonnet
---
```

Body sections, in this order, each a `##` heading under one `# <Title>` line: `Role`, `Inputs`,
`Method`, `Report`, `Limits`.

| Agent | model | Skill it wraps (`Load the \`<skill>\` skill and follow it.` in Method) | edit tools |
|---|---|---|---|
| `architect` | opus | none; reads the must-read docs, the ADR index if the prompt names one, and the code | no |
| `code-reviewer` | opus | `review-checklist` | no |
| `security-reviewer` | opus | `secure-code-review` | no |
| `test-architect` | opus | `test-review` | no |
| `ux-reviewer` | opus | none; reads the `stack-*` skills named in the prompt | no |
| `dependency-auditor` | sonnet | none; runs the audit commands the prompt lists | no |
| `tech-writer` | sonnet | `docs-review` | yes |
| `website-maintainer` | sonnet | `docs-review` (its "Website checks" section) | yes |
| `debugger` | sonnet | none | yes |
| `refactorer` | sonnet | none | yes |

`tools` for a read-only agent: `Read, Grep, Glob, Bash, Skill`. For an edit agent: `Read, Grep, Glob, Bash, Skill, Edit, Write`.
Read-only means no `Edit` and no `Write`; `Bash` is there for `git diff` and running checks.

**Inputs** section lists these prompt fields (the dispatcher fills them, see D3): `Scope`, `Mode`
(`review` or `edit`, default `review`), `Security posture` (default `standard`), `Extra context`,
`Must-read docs`, `Stack skills`, plus the agent-specific fields: `Audit commands` (dependency-auditor),
`Website build` and `Website links` (website-maintainer), `Verify (fast)` (refactorer),
`Changelog target` (tech-writer). It says: a field missing from the prompt is read from
`.claude/toolkit.yaml` through the `project-profile` skill, and when it is not there either the agent
says so in its report and continues with the default.

**Report** section ends with the exact line format of D3 and the finding format
`<n>. blocking|non-blocking · path:line · what is wrong · the fix` (the `review-checklist` format
without the phase id).

**Per-agent method points** (each is a sentence or bullet in Method):

- `architect`: at least two options with trade-offs, one recommendation, the module and interface
  boundaries, names of anything new, risks, and a list of decisions that may need an ADR. It does not
  write the plan.
- `code-reviewer`: `review-checklist`; reads the code, not the author's account of it.
- `security-reviewer`: `secure-code-review`, with the posture rules: **critical** starts the report
  with a `## Threat model` section (assets, entry points, trust boundaries and data flows the scope
  touches), reviews every changed file in full, and grades any finding about authentication,
  authorization, cryptography, secret handling or data leaving the system `blocking` unless it is
  clearly unreachable; **standard** applies the checklist as written; **low** applies only checklist
  items 1 (secrets) and 7 (supply chain), writes no threat model, and says so in the report.
- `test-architect`: `test-review`; for each changed behaviour names the level (unit, integration,
  e2e) that should prove it, finds tests that cannot fail (no assertion, an always-true assertion, the
  subject mocked away), and specifies each missing test as name, level, fixture and assertion. In
  review mode it never writes a test.
- `ux-reviewer`: the primary flow, the empty, error and loading states, keyboard and assistive
  technology access, contrast and target sizes, and the wording of labels and messages; evidence is
  `path:line` of the UI code; applies the UI rules of the stack skills named in `Stack skills`.
- `dependency-auditor`: runs each `Audit commands` entry, reads manifests and lockfiles, reports
  vulnerable, unpinned, unmaintained and newly added dependencies. It changes nothing; updating is `/deps`.
- `tech-writer`: `docs-review`; in `edit` mode fixes the documents the change makes wrong, and adds the
  line under `Changelog target` when the prompt gives one; in `review` mode only reports.
- `website-maintainer`: `docs-review` website checks; runs `Website build` then `Website links` from
  the website directory; in `edit` mode brings the site content in line with the docs and code; with no
  `Website build` field it reports verdict `n/a` and why.
- `debugger`: reproduce first (a failing test or command), find the cause (bisect when the history helps),
  state the root cause in one sentence, and in `edit` mode make the smallest fix with a test; in `review`
  mode report the cause and the proposed fix.
- `refactorer`: runs `Verify (fast)` before and after, stops when it is red before it starts, changes no
  behaviour, and in `review` mode only proposes the steps.

No agent file names a project, a tool brand from the forbidden-words list, or a project path.

### D2. Profile keys

`docs.website` (optional object, `additionalProperties: false`): `dir` (required, string, directory
relative to the repo root, `.` for the root), `build` (required, string, command run from `dir`),
`links` (optional string, command run from `dir`).

`agents` (optional object, `additionalProperties: false`), **no `default` entries in the schema**:

- `posture.security`: `critical` | `standard` | `low`. Missing means `standard`.
- `disable`: list of agent names. Missing means none.
- `required`: list of `{agent, at, blocking?, when?}` (`additionalProperties: false`). `agent` is one of
  the ten names; `at` is a non-empty list of points; `blocking` is a boolean, missing means `false`;
  `when` is a non-empty list of globs matched against the changed files.
- `extra_context`: list of non-empty strings.

Points (the only values `at` accepts): `make_plan`, `implement_phase`, `implement_final`, `review`, `dod`.
Agent names in `agents.disable` and `agents.required[].agent` use the same ten-name enum.

Semantic errors added to `semantic_checks` (exact texts, `{i}` is the index, `{agent}` the name):

- `'agents.required[{i}]': '{agent}' is listed in 'agents.disable'`
- `'agents.required[{i}]': 'website-maintainer' needs 'docs.website'`
- `'agents.required[{i}].when': needs a diff, but 'at' is only 'make_plan'`

Defaults are applied by `scripts/agents.py` (D4), the way the hooks apply theirs: `--resolved` output of
a profile without these keys does not change. A profile without `agents` means all agents are available and
none is mandatory.

Worked example (also the test fixture `tests/fixtures/agents-toolkit.yaml`):

```yaml
agents:
  posture:
    security: critical
  disable: [dependency-auditor]
  required:
    - {agent: security-reviewer, at: [implement_phase, implement_final], blocking: true}
    - {agent: ux-reviewer, at: [implement_final], when: ["app/views/**"], blocking: false}
    - {agent: test-architect, at: [make_plan]}
    - {agent: tech-writer, at: [dod, review]}
    - {agent: website-maintainer, at: [dod], when: ["site/**", "docs/**"]}
  extra_context:
    - "Every outbound request must pass the approval gate."
```

### D3. Dispatch points, modes, reports and gates

| Point | Who dispatches | Mode | Failure of a required agent |
|---|---|---|---|
| `make_plan` | the planner session, with the `Agent` tool | review | a blocking finding is resolved in the plan before it is pushed; a non-blocking one goes to the plan's Risks |
| `implement_phase` | the phase's worker session (child brief rule 3b) | edit | the orchestrator sends the phase back; it is not merged |
| `implement_final` | the final review session | review | a blocking finding is a blocking finding of the review (`verdict=changes`) |
| `review` | the `/review` session, alongside the dimension subagents | review | its findings join the triage; a blocking-required agent's findings are at least `high` |
| `dod` | the `/dod` session | review | row `FAIL` |

`edit` mode is only ever used inside a worker session or when the user asks an agent directly; at every
other point an edit-capable agent is dispatched in `review` mode and reports only.

Every agent ends its answer with exactly one line (the report line):

```
AGENT-REPORT <agent> at=<point|adhoc> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>
```

`verdict=findings` when `blocking + non_blocking > 0`, `pass` otherwise, `n/a` when the agent could not
run (the reason is on the lines before it). A required agent whose line says `n/a` counts as **did not run**.
`blocking` entries fail the gate when `blocking=<n>` with `n > 0`.

Dispatch prompt (the `agent-dispatch` skill holds this text; fields as in D1):

```
You are the <agent> agent, running at <point> in <review|edit> mode.
Scope: <diff range or paths>
Security posture: <critical|standard|low>
Extra context:
- <each agents.extra_context line>
Must-read docs: <paths>
Stack skills: <names>
<agent-specific fields>
End with the AGENT-REPORT line described in your Report section.
```

The plugin's agents are dispatched with the `Agent` tool; the `subagent_type` is the name in the agent list
(the plugin prefix form `devflow:<name>` when that is how the list shows it).

### D4. `plugins/devflow/scripts/agents.py` and the `agent-dispatch` skill

Standard library plus PyYAML. Imports sibling modules the way `scope_check.py` imports `validate_manifest`.
Uses `validate_manifest.path_matches(path, pattern)` for `when` globs.

```
agents.py required --profile FILE --at POINT [--changed FILE]
agents.py verify   --required FILE --report FILE
```

`--changed` is a file with one repo-relative path per line (`-` reads stdin). `required` validates the
profile with `validate_profile.validate` (errors are printed as the validator prints them, exit 1) and prints
JSON on stdout:

```json
{"point": "dod",
 "posture": {"security": "critical"},
 "extra_context": ["..."],
 "disabled": ["dependency-auditor"],
 "required": [{"agent": "tech-writer", "blocking": false, "matched": ["always"]}],
 "not_applicable": [{"agent": "website-maintainer", "why": "no changed file matches 'when'"}]}
```

Rules: an entry applies when its `at` contains the point and (it has no `when`, or some changed file
matches some `when` glob; `matched` then lists the matching globs, otherwise `["always"]`). Several applicable
entries for one agent merge into one item, `blocking` is the OR, `matched` the union. An entry for a point whose `at` matches but whose `when`
matches nothing goes to `not_applicable`. An unknown point, an unreadable profile, or an applicable entry with
`when` and no `--changed` is an error: stderr `agents.py: <message>`, exit 1 (the last case's message is
`--changed is needed: agents.required has entries with 'when'`).

`verify` reads the JSON of `required` and the report text, finds lines matching
`^AGENT-REPORT (?P<agent>[a-z-]+) at=(?P<at>[a-z_]+) verdict=(?P<verdict>pass|findings|n/a) blocking=(?P<b>\d+) non_blocking=(?P<nb>\d+)$`
(multi-line search; when an agent has several lines for the same point the last one counts), and prints one
line per required item and a summary:

```
OK <agent> at=<point> blocking=<n>
MISSING <agent> at=<point>              # no line, or verdict=n/a
BLOCKED <agent> at=<point> blocking=<n> # item blocking is true and n > 0
agents: ok (<n> required)               # or: agents: FAILED (<m> of <n> required)
```

Exit 0 when no `MISSING` and no `BLOCKED`, else 1. Python functions the tests call:
`required(profile: dict, point: str, changed: list[str] | None) -> dict` and
`verify(required: dict, report: str) -> tuple[list[str], bool]`.

The skill `agent-dispatch` (`plugins/devflow/skills/agent-dispatch/SKILL.md`, front matter `name`,
`description` of at least 40 characters, `user-invocable: false`) has the headings `## Resolve` (run
`agents.py required`), `## Dispatch` (the D3 prompt and the `Agent` call), `## Modes` (the D3 mode table),
`## Report` (the report line and finding format), `## Gate` (run `agents.py verify`; the D3 failure table),
`## Not required` (a non-required, non-disabled agent may be dispatched on judgement and no failure rule applies to it).

### D5. Wiring into the commands

Each command loads the `agent-dispatch` skill and runs `agents.py required` for its point. The exact
insertions are in the briefs of `p5-wire-plan-dod-review` and `p6-wire-implement`. In short:

- `/make-plan`: for a large scope, dispatch `architect` (unless it is in `disabled`) before writing the
  Design, then every other required agent at `make_plan`; final reply gets an `Agents:` line.
- `/implement`: the child brief gets rule 3b (workers dispatch required agents at `implement_phase` in edit mode
  and put their report lines into the `PHASE-REPORT`); the orchestrator re-checks them at merge with
  `agents.py verify`; the final review prompt requires the `implement_final` agents.
- `/review`: required agents at `review` run in parallel with the dimension subagents; findings get the id prefix `AGT`.
- `/dod`: required agents at `dod` give a row each and a subsection with the agent's full report.

### D6. The `/setup` command and the `profile-setup` skill

`plugins/devflow/commands/setup.md` (front matter: `description`, `argument-hint: "[optional: create | update]"`,
`model: sonnet`). It must contain the words `project-profile` and `never substitute` (an existing test checks
every command for both). Headings, in order: `## Profile`, `## Guardrail hooks`, `## 1. Survey`, `## 2. Decide`,
`## 3. Ask`, `## 4. Write`, `## 5. Check`, `## 6. Deliver`, `## Status board`.

- **Profile**: find `<devflow root>` with the `project-profile` skill's first step. With `.claude/toolkit.yaml`
  present the mode is *update* (validate it first with `validate_profile.py`; if invalid show the messages and stop);
  without it the mode is *create*. `create` or `update` as the argument forces a mode and stops with a one-line error
  when the file does not match it. The create path loads no profile; it says so and never invents a key.
- **Guardrail hooks**: run `python3 "<devflow root>/hooks/dod_gate.py" --exempt` once, and
  `python3 "<devflow root>/hooks/protect_paths.py" --allow-profile` before the first write of the profile and
  `python3 "<devflow root>/hooks/protect_paths.py" --end-allow` after the last one, also when a step failed.
- **1. Survey**: `python3 "<devflow root>/scripts/profile_survey.py" . > <scratchpad>/survey.json`.
- **2. Decide**: load the `profile-setup` skill; build one table `key | proposed value | evidence`.
  `verify.fast` and `verify.dod` are chosen from `evidence.verify_evidence` by the skill's rules.
- **3. Ask**: one `AskUserQuestion` call, at most four questions: the security posture (always asked, with the
  proposal as the recommended option), every entry the proposal marks `blocking: true`, and whatever the survey could
  not determine (no test command, no main branch). Nothing else is asked.
- **4. Write**: *create*: copy `<devflow root>/templates/toolkit.yaml` (the starter, see D6a) to
  `.claude/toolkit.yaml` and fill it in from the table of step 2 with the Edit tool, uncommenting only the blocks
  that have a value. *update*: `profile_patch.py diff` first, show the new, changed and stale keys, then
  `profile_patch.py set-block` for `agents` and `docs.website`, and the Edit tool for single other keys.
- **5. Check**: `validate_profile.py .claude/toolkit.yaml` with file checks, then each `verify.fast` command once
  (one retry never); list what was not verified and why.
- **6. Deliver**: branch `chore/toolkit-profile` from `origin/<main>` (a session that cannot push that name uses
  its assigned branch and puts `chore` in the PR title, as `pr-steward` says), commit only `.claude/toolkit.yaml`,
  push, open one pull request with `create_pull_request`, never merge, subscribe and follow `pr-steward`. When no pull
  request can be opened (no GitHub access), stop after the commit and say what remains.
- **Status board**: follow D11.

D6a (where create mode finds the starter): the starter profile is `templates/toolkit.yaml` in the claude-toolkit
repository, which is not inside the installed plugin. Therefore **p1 also copies the starter into the plugin as
`plugins/devflow/templates/toolkit.yaml`** and a test keeps the two files byte-identical; create mode copies
`<devflow root>/templates/toolkit.yaml`.

The skill `plugins/devflow/skills/profile-setup/SKILL.md` (`name: profile-setup`, `user-invocable: false`) holds:
`## Choosing verify commands`, `## Mapping evidence to keys`, `## Questions`, `## Pull request body`, `## Never`.

- *Choosing verify commands*: `verify.fast` is the one command that runs the unit tests (a Makefile target
  `test`, a package script `test`, or the CI step that runs them), with an install step joined by `&&` in front
  when CI has one. `verify.dod` is, in workflow order, the de-duplicated commands the CI workflows triggered by
  `pull_request` or `push` run, without deploy or publish steps, the first one carrying the install step. If the
  survey finds no test command, ask (section Questions).
- *Mapping evidence to keys*: `stacks`, `git.main_branch`, `docs.*`, `ci.dispatchable`, `agents.*` are copied from
  `proposal.profile`; `git.branch_pattern` is `<type>/<kebab-case>` and `git.branch_types` the prefixes in
  `evidence.git.branch_prefixes` with at least three branches, else the default `[feature, fix, chore]`;
  `docs.must_read` from the proposal; `hooks`, `deps`, `upstream`, `admin`, `git_ops`, `land` are never written.
- *Questions*: the posture question offers `critical`, `standard`, `low` with the proposal first and
  "(Recommended)" on it.
- *Pull request body*: title `chore: add .claude/toolkit.yaml` (create) or `chore: update .claude/toolkit.yaml`;
  sections `## What this changes`, `## Inferred values` (the table with evidence), `## Decisions for a human`
  (security posture and every `blocking: true` entry, each with the evidence that led to it), `## Not verified`.
- *Never*: guess a value without evidence, write `blocking: true` without the user's confirmation, edit any file
  except `.claude/toolkit.yaml`, merge, or enable auto-merge.

### D7. Survey modules: contracts

Three modules in `plugins/devflow/scripts/`, standard library plus PyYAML, no word from the forbidden list.
Skipped directories everywhere: `.git`, `node_modules`, `.venv`, `venv`, `vendor`, `build`, `dist`, `Pods`,
`.build`, `__pycache__`, `DerivedData`. At most 5000 files are visited and a file larger than 200000 bytes is
not read. Lists of paths in outputs are sorted and cut to 20 entries (counts are not cut).

**`survey_signals.py`**: `scan(root: Path) -> dict`:

```json
{"source_files": 0, "markdown_files": 0,
 "security": {"categories": {"auth": {"count": 0, "files": []}, "crypto": {...}, "credentials": {...},
                             "egress": {...}, "user_data": {...}, "policy_docs": {...}},
              "firing": [], "score": 0},
 "ui": {"files": [], "globs": []},
 "tests": {"levels": {"unit": false, "integration": false, "e2e": false},
           "evidence": {"unit": [], "integration": [], "e2e": []}}}
```

- Source extensions: `.py .go .swift .js .ts .tsx .jsx .java .kt .rb .rs .c .cpp .m .php .cs .vue .svelte`.
  `source_files` counts them; `markdown_files` counts `*.md`.
- A **test path** is a path with a component in `{tests, test, __tests__, spec, specs}` or a component ending in
  `Tests`, or a file name matching `test_*.py`, `*_test.go`, `*.test.*`, `*.spec.*`, `*Tests.swift`.
- Security categories are matched, case-insensitively, against the text of files with a source extension that are
  not test paths: `auth` `\b(oauth|jwt|login|authenticat\w*|authoriz\w*)\b`; `crypto`
  `\b(encrypt\w*|decrypt\w*|hmac|aes|rsa|cipher\w*|keychain)\b`; `credentials`
  `\b(password|passwd|api[_-]?key|secret[_-]?key|credential\w*)\b`; `egress`
  `(\brequests\.(get|post|put)\b|\burllib\.request\b|\bhttpx\b|\burlsession\b|\bnet/http\b|\baxios\b|\bfetch\()`;
  `user_data` `\b(pii|gdpr|personal data|personally identifiable)\b`. `count` is the number of distinct files.
  `policy_docs`: a file `SECURITY.md` in the repo root, or a `*.md` file whose name or any directory name matches
  `threat[-_ ]?model|security[-_ ]?model`.
- A category **fires** when `count >= 2` (`policy_docs`: `count >= 1`). `firing` lists the firing names in the order
  auth, crypto, credentials, egress, user_data, policy_docs; `score` is `len(firing)`.
- UI files (not test paths): `.swift` files that contain `import SwiftUI` or `import UIKit`, and files with extension
  `.tsx .jsx .vue .svelte .xib .storyboard`. `globs`: take the directory of each UI file (a file at the repo root
  contributes its own file name), drop every directory that has an ancestor in the set, and emit `<dir>/**`, sorted.
- `levels.e2e`: any path component in `{e2e, end-to-end, playwright, cypress}` or ending in `UITests`.
  `levels.integration`: any component in `{integration, integrations, contract, contracts}`. `levels.unit`: at
  least one test path that is neither e2e nor integration. `evidence` holds up to 5 paths per level.

**`survey_docs.py`**: `scan(root: Path) -> dict`:

```json
{"must_read": ["README.md"], "adr_dir": null, "adr_index": null,
 "changelog": null, "website": null}
```

- `must_read`: the existing files among `README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `SECURITY.md`, then the
  sorted files matching `docs/design*.md` and `docs/architecture*.md`.
- `adr_dir`: the first existing directory of `docs/adr`, `docs/adrs`, `docs/decisions`, `doc/adr`, `adr`;
  `adr_index`: `<adr_dir>/README.md` if it exists, else `<adr_dir>/index.md`, else null.
- `changelog`: the first existing of `CHANGELOG.md`, `CHANGES.md`, `HISTORY.md` as
  `{"file": ..., "section": <first line matching ^##\s+\[?Unreleased\]?, stripped, or null>}`.
- `website`: look at the repo root (`dir` `"."`) and then each top-level directory and `docs/` in sorted order for the
  first of these configs: `docusaurus.config.js|ts` (tool `docusaurus`), `mkdocs.yml` (`mkdocs`),
  `astro.config.mjs|js|ts` (`astro`), `.vitepress/config.js|ts|mjs` (`vitepress`), `_config.yml` (`jekyll`),
  `hugo.toml|yaml` or `config.toml` with a `content/` directory beside it (`hugo`), `conf.py` with `index.rst` beside
  it (`sphinx`). Result `{"dir", "tool", "build", "links", "evidence": [<config path>]}`. `build`: `npm run build` when
  a `package.json` beside the config has `scripts.build`; else `mkdocs build --strict`, `bundle exec jekyll build`,
  `hugo --minify`, `sphinx-build -b html . _build/html` for those tools; else null. `links`: `npm run <key>` for the
  first key of that `package.json`'s scripts matching `^(check[-:_]?links?|link[-:_]?check|linkcheck|links)$`, else null.
  When `build` is null the value of `website` is still returned (with `build: null`).

**`profile_survey.py`**: `survey(root: Path) -> dict`, CLI `profile_survey.py [ROOT]` (default `.`) prints the JSON,
2-space indented, exit 0. Shape:

```json
{"root": "...",
 "evidence": {"stacks": [{"name": "python", "evidence": ["pyproject.toml"]}],
              "ci": {"workflows": [{"file": ".github/workflows/ci.yml", "triggers": ["push"], "runs_on": ["ubuntu-latest"],
                                    "runs": [{"job": "test", "run": "..."}], "dispatch_inputs": []}],
                     "dispatchable": [{"workflow": "macos-tests.yml", "use_when": "...", "notes": "No inputs."}]},
              "verify_evidence": {"ci_runs": [{"workflow": "ci.yml", "job": "test", "run": "..."}],
                                  "make_targets": [], "package_scripts": {}},
              "git": {"main_branch": "main", "has_history": true, "branch_prefixes": {}},
              "docs": {...survey_docs.scan...}, "signals": {...survey_signals.scan...}},
 "proposal": null}
```

- Stacks, in the order python, go, swift, ipados: `python` when `pyproject.toml`, `setup.py` or `requirements.txt`
  exists at the root; `go` for `go.mod`; `swift` for `Package.swift` or a `*.xcodeproj` or `*.xcworkspace`
  directory; `ipados` (only with `swift`) when a `project.pbxproj` matches `TARGETED_DEVICE_FAMILY\s*=\s*"?[^;"]*2`
  or an `Info.plist` has `<key>UIDeviceFamily</key>` followed by an array containing `<integer>2</integer>`.
  A `package.json` is reported as `{"name": "node", "evidence": ["package.json"], "skill": false}` in a separate
  list `evidence.other_stacks` (there is no stack skill for it).
- YAML pitfall: PyYAML reads the workflow key `on` as the boolean `True`; read `data.get("on", data.get(True))`.
  `triggers` is the list of event names (the key set of a mapping, the items of a list, or the single string).
- `ci_runs` lists the `run` steps of workflows whose triggers include `push` or `pull_request`. `make_targets`: the names
  among `test tests check lint fmt format verify ci build` that appear as `^name:` lines of a root `Makefile`.
  `package_scripts`: the entries `test lint build check typecheck` of the root `package.json` `scripts`.
- `dispatchable`: workflows with the trigger `workflow_dispatch` whose `runs-on` labels contain `macos` or `windows`
  (case-insensitive). `use_when`: `Build or test on <macOS|Windows> (runs-on: <label>)`; `notes`: `No inputs.` or
  `Inputs: <names joined by ", ">`.
- `git`: `main_branch` from `git symbolic-ref --short refs/remotes/origin/HEAD` with `origin/` removed, else from
  `git rev-parse --abbrev-ref HEAD`, else null; `has_history` when `git rev-list --count HEAD` is at least 1;
  `branch_prefixes` counts the part before the first `/` of every branch name from
  `git branch --all --format=%(refname:short)` (a leading `origin/` removed, `HEAD` ignored). Outside a git repository:
  `{"main_branch": null, "has_history": false, "branch_prefixes": {}}`.

### D8. The proposal

`plugins/devflow/scripts/survey_proposal.py`: `build(evidence: dict) -> {"profile": dict, "rationale": list}`; the
CLI of `profile_survey.py` sets `"proposal"` to it. `profile` keys, each only when it has a value:

- `stacks`: the names (always present, may be `[]`).
- `git`: `{"main_branch": <git.main_branch>}`.
- `docs`: `must_read` (always), `adr_dir`, `adr_index`, `changelog` (only when its `section` is not null),
  `website` (only when found and `build` is not null: `{dir, build}` plus `links` when not null).
- `ci`: `{"dispatchable": [...]}` when not empty.
- `agents`: built as follows, keys in this order:
  - `posture.security`: `critical` when `signals.security.score >= 3`, else `standard`. Never `low`.
  - `disable`: `["website-maintainer"]` when `docs.website` is not in the profile; the key is left out when empty.
  - `required`, left out when empty and always empty when `signals.source_files == 0`. Entries in this order:
    1. `security-reviewer`: critical: `at: [implement_phase, implement_final]`, `blocking: true`; otherwise
       `at: [implement_final]`, `blocking: false`.
    2. `ux-reviewer`, when `signals.ui.globs` is not empty: `at: [implement_final]`, `blocking: false`, `when: <the globs>`.
    3. `test-architect`, when fewer than two test levels are true or `e2e` is false: `at: [make_plan]`, `blocking: false`.
    4. `tech-writer`, when `signals.markdown_files >= 8`: `at: [dod]`, `blocking: false`.
  - Each entry has the keys `agent`, `at`, `blocking` (and `when`) in that order.

`rationale` is a list of `{"key": <dotted key>, "value": <value>, "evidence": [<strings>]}`, one per proposed
top-level value and one per `agents.required` entry, with evidence such as the firing categories and their first
files, the config file of a website, the UI globs, the test levels found, or `markdown_files=<n>`.

### D9. `plugins/devflow/scripts/profile_patch.py`

Text-level edits that keep every other byte (comments included); no YAML round-trip.

```
profile_patch.py set-block PROFILE KEY VALUE.json [--write]
profile_patch.py diff PROFILE PROPOSAL.json [--root DIR]
```

`set-block`: `KEY` is `agents` (top-level) or `docs.website` (a child of `docs`, two-space indent). `VALUE.json` holds the
value. It renders `yaml.safe_dump({<last key part>: value}, sort_keys=False, default_flow_style=False)` at the right
indent and replaces the existing active block (the key line and all following lines that are blank-then-indented or
indented, up to but not including the next line that is non-blank, not a comment and at an indent not deeper than the key;
comment lines directly above the key are kept) or, when there is none, appends it: a top-level key at the end of the file
after one blank line, `docs.website` as the last child of the `docs:` block. Without `docs:` it exits 1 with
`profile_patch: no 'docs' block to add 'website' to`. Prints the new text on stdout, or writes the file with `--write`. Applying the same
value twice gives the same text.

`diff`: compares `PROPOSAL.json` (the `profile` object of D8) with the profile's parsed YAML and prints JSON
`{"new": [dotted keys], "changed": [{"key", "from", "to"}], "same": [dotted keys], "stale": [{"key", "value", "why"}]}`.
Compared keys: `stacks`, `git.main_branch`, `docs.must_read`, `docs.adr_dir`, `docs.adr_index`, `docs.changelog`,
`docs.website`, `ci.dispatchable`, `agents`. `stale` is computed from the existing profile only, against `--root`
(default: the repository root two levels above the profile): each path-valued key whose path does not exist
(`docs.must_read[]`, `docs.adr_dir`, `docs.adr_index`, `docs.adr_bar` before `#`, `docs.changelog.file`,
`docs.website.dir`, `verify.dod_doc` before `#`, `project_steward`, `admin.policy`, `.github/workflows/<workflow>` for each
`ci.dispatchable[].workflow`), and each `agents.required[].when` glob that matches no tracked or untracked file
(matched with `validate_manifest.path_matches`); `why` is `path not found` or `no file matches`.

### D10. The `protect-paths` exemption for `/setup`

In `hooks/protect_paths.py`: constants `PROFILE_MARKER = "protect-paths-profile.json"` and `PROFILE_TTL_SECONDS = 7200`.
`python3 protect_paths.py --allow-profile` writes `{"written_at": <UTC ISO>}` to `<state dir>/PROFILE_MARKER` (the
state directory function of `dod_gate.py`: `<git dir>/devflow`, so per checkout) and prints
`protect-paths: .claude/toolkit.yaml may be edited for the next 2 hours (<marker path>)`;
`--end-allow` removes it and prints `protect-paths: .claude/toolkit.yaml is protected again`. While the marker is
younger than the TTL, `violation()` lets the path `.claude/toolkit.yaml` (exactly) through and nothing else:
`.env*`, lockfiles and workflow files stay denied. The deny message for the profile keeps the words
`changed by people` and adds `or by /setup`. The exemption is a convention like the `dod-gate` marker; branch protection
and the pull request review stay the hard control (`docs/hooks.md`).

### D11. Board record for `/setup`

A maintenance record with `command: "setup"`, document id `<project>--setup`. For `setup` the `orchestrator_session`
is the real session id (a non-empty string); for `deps`, `upstream`, `land` it stays the literal `scheduled`. Items
are the steps `survey`, `confirm`, `write`, `verify`, `pr` using the item states the maintenance records already use.
Alerts follow the existing rule for maintenance records (push only, never a rename).

### D12. Eval and test fixture repositories

`evals/fixtures/setup_repos.py` has `REPOS = ("security_heavy", "ios_ui_app", "docs_website", "bare")` and
`build(dest, repo="security_heavy", with_profile=False) -> dict` using `init_repo` (branch `main`). The returned dict
holds `main_branch`, `repo`, `stacks`, `agents` (the expected `proposal.profile.agents`), `website` (expected
`proposal.profile.docs.website` or `None`) and `dispatchable` (expected workflow names). `with_profile=True` also writes
a minimal valid `.claude/toolkit.yaml` (main branch `main`, `verify` echo commands, `stacks: []`).

| repo | files | expected |
|---|---|---|
| `security_heavy` | `pyproject.toml`; `README.md`; `SECURITY.md`; `docs/threat-model.md`; `src/app/auth.py` and `src/app/session.py` (words `login`, `oauth`, `jwt`); `src/app/crypto.py` and `src/app/vault.py` (`encrypt`, `hmac`, `aes`); `src/app/secrets.py` and `src/app/config.py` (`password`, `api_key`, `credential`); `src/app/client.py` and `src/app/sync.py` (`requests.get`, `httpx`); `src/app/users.py` and `src/app/export.py` (`gdpr`, `personal data`); `tests/unit/test_auth.py`; `.github/workflows/ci.yml` (`on: [push, pull_request]`, ubuntu, a `run: python -m pytest -q` step) | stacks `["python"]`; website `None`; dispatchable `[]`; agents `{"posture": {"security": "critical"}, "disable": ["website-maintainer"], "required": [{"agent": "security-reviewer", "at": ["implement_phase", "implement_final"], "blocking": True}, {"agent": "test-architect", "at": ["make_plan"], "blocking": False}]}` |
| `ios_ui_app` | `Package.swift`; `App.xcodeproj/project.pbxproj` containing `TARGETED_DEVICE_FAMILY = "1,2";`; `README.md`; `Sources/App/Views/HomeView.swift` and `Sources/App/Views/Detail/DetailView.swift` (both `import SwiftUI`); `Sources/App/Model/Note.swift`; `Sources/App/Model/NetworkClient.swift` and `Sources/App/Model/Sync.swift` (both use `URLSession`); `Tests/AppTests/NoteTests.swift`; `Tests/AppUITests/LaunchTests.swift`; `.github/workflows/macos-tests.yml` (`on: [workflow_dispatch, pull_request]`, `runs-on: macos-latest`, a `run: xcodebuild test` step). No other file imports SwiftUI or UIKit. | stacks `["swift", "ipados"]`; website `None`; dispatchable `["macos-tests.yml"]`; agents `{"posture": {"security": "standard"}, "disable": ["website-maintainer"], "required": [{"agent": "security-reviewer", "at": ["implement_final"], "blocking": False}, {"agent": "ux-reviewer", "at": ["implement_final"], "blocking": False, "when": ["Sources/App/Views/**"]}]}` |
| `docs_website` | `go.mod`; `lib.go`; `lib_test.go`; `README.md`; `CHANGELOG.md` (with a line `## [Unreleased]`); `docs/index.md`, `docs/guide.md`, `docs/api.md`, `docs/faq.md`, `docs/design.md`, `docs/contributing.md`, `docs/notes.md`, `docs/adr/README.md`, `docs/adr/0001-record.md` (9 files); `website/docusaurus.config.js`; `website/package.json` with `"scripts": {"build": "docusaurus build", "check-links": "linkcheck ./build"}` | stacks `["go"]`; website `{"dir": "website", "build": "npm run build", "links": "npm run check-links"}`; dispatchable `[]`; agents `{"posture": {"security": "standard"}, "required": [{"agent": "security-reviewer", "at": ["implement_final"], "blocking": False}, {"agent": "test-architect", "at": ["make_plan"], "blocking": False}, {"agent": "tech-writer", "at": ["dod"], "blocking": False}]}` (no `disable`) |
| `bare` | `README.md` (one line); `.gitignore` | stacks `[]`; website `None`; dispatchable `[]`; agents `{"posture": {"security": "standard"}, "disable": ["website-maintainer"]}` |

`docs_website` has 11 Markdown files (README, CHANGELOG and the nine under `docs/`); it also expects `adr_dir`
`docs/adr`, `adr_index` `docs/adr/README.md`, and `changelog` `{"file": "CHANGELOG.md", "section": "## [Unreleased]"}`.
`ios_ui_app` has 1 Markdown file, `security_heavy` 3, `bare` 1.

### D13. Evals

New grader `agents_block_equals` (compares the `agents` key of the profile the run left in the work tree with
`expected["agents"]` of the fixture) and `result_matches` (`must` and `must_not` lists of strings searched in the final
result text). Builder `evals/fixtures/agents_demo.py`: `build(dest, posture="critical")` is the `tiny_app` repository with a
profile whose `agents` block is `posture.security: <posture>` and `required: [{agent: security-reviewer, at: [dod], blocking: false}]`.
Tasks (all `model: sonnet`, `repeats: 3`):

- `setup-security-heavy`: `/devflow:setup`, builder `setup_repos`, params `{repo: security_heavy}`, argument text says nobody can
  answer, accept every proposal, and the pull request cannot be opened; graders `profile_valid`, `agents_block_equals`.
- `agents-dod-critical`: `/devflow:dod`, builder `agents_demo` (posture `critical`); `result_matches` must contain
  `AGENT-REPORT security-reviewer at=dod` and `Threat model`.
- `agents-dod-low`: same with posture `low`; must contain `AGENT-REPORT security-reviewer at=dod`, must not contain `Threat model`.

### D14. Constraints for every phase

- No file under `plugins/`, `templates/` or `.claude-plugin/` contains the words `privacyfence`, `ruff`, `pytest` or
  `connector` (`tests/test_no_project_words.py`). Tests, docs and `evals/` may.
- Python scripts: standard library plus PyYAML, Python 3.11, `from __future__ import annotations`, a module docstring with
  the usage, and `main(argv=None) -> int`.
- New tests use the `.venv/bin/python -m pytest` environment `verify.fast` creates; shared helpers live next to
  `conftest.py` in `tests/`.
- All five `plugin.json` versions stay equal (`tests/test_structure.py:28`); the bump is only in the last phase.

## Manual steps

Two checks need a person, both after the pull request is merged and the plugin has synced: the agents and
`/devflow:setup` load in a real Project (`/agents` lists ten), and `/devflow:setup` proposes sensible profiles on
two real repositories. Nothing is needed before implementation. The step-by-step page is
https://claude.ai/artifact/TisYYUmuQkEbTVnwLVSbsp (source `docs/agents-and-setup-plan-manual-steps.html`).

## Risks and open questions

- **Agent front matter**: the `tools` list names `Skill` for the wrapping agents. If `claude plugin validate`
  (run in CI) or the tests the worker can run reject the front matter, `p3-agents-review` stops with `status=blocked`
  and reports the validator's message; do not drop `Skill` or invent keys on your own.
- **`on:` in workflow YAML** is read as `True` by PyYAML. A survey that reports no triggers for a workflow that has
  them has hit this; the fix is in D7.
- **Forbidden words**: a survey or agent file that needs a tool name from the forbidden list must describe it generically.
  A failing `tests/test_no_project_words.py` is the signal.
- **Heuristics are proposals**: the security score, UI globs and test levels can be wrong for a real repository. That is why
  `/setup` always asks about the posture and every `blocking: true` entry, and why the pull request lists the evidence.
- **The `protect-paths` exemption is a convention**, like the `dod-gate` marker: any session can write the marker.
  The pull request review and branch protection remain the hard control.
- **Comments in `.claude/toolkit.yaml`** are preserved only because `profile_patch.py` edits text; a worker that is
  tempted to round-trip the file through PyYAML must stop and use `set-block`.
- **A worker finds `plugins/devflow/templates/` already has a file named `toolkit.yaml`** or the byte-identical test
  cannot pass: stop and report.
- **Eval cost**: the three new tasks are not run by CI or `/dod`; run them by hand with `--dry-run` first.

## Implementation manifest

```yaml
plan_slug: agents-and-setup
feature_branch: feature/agents-and-setup
tracking_issue: 17
max_parallel: 3
manual_steps_artifact: https://claude.ai/artifact/TisYYUmuQkEbTVnwLVSbsp
manual_steps_source: docs/agents-and-setup-plan-manual-steps.html
manual_before: []
manual_after:
  - id: ma1-plugin-loads
    title: The agents and /setup load in a real Project
    why: CI validates the files, but only a live session shows the ten agents are offered and /devflow:setup is listed
  - id: ma2-setup-real-repos
    title: /setup proposes sensible profiles on two real repositories
    why: The survey is heuristic; only the owner can judge the security posture and the blocking choices
verify_after_merge:
  - ".venv/bin/python plugins/devflow/scripts/validate_profile.py templates/toolkit.yaml --no-file-checks"
  - ".venv/bin/python plugins/devflow/scripts/validate_profile.py .claude/toolkit.yaml"
  - ".venv/bin/python -m pytest tests/test_no_project_words.py tests/test_structure.py -q"
final_checks:
  - "docs/agents-and-setup-plan.md and docs/agents-and-setup-plan-manual-steps.html are deleted and nothing links to them"
  - "`ls plugins/devflow/agents/*.md | wc -l` prints 10"
  - "all five plugins/*/.claude-plugin/plugin.json say version 0.7.0"
  - "`.venv/bin/python plugins/devflow/scripts/profile_survey.py .` exits 0 and prints JSON with a non-null proposal"
phases:
  - id: p1-profile-schema
    title: Profile keys agents and docs.website, validation, starter copy
    depends_on: []
    complexity: M
    touches:
      - plugins/devflow/schema/profile.schema.json
      - plugins/devflow/scripts/validate_profile.py
      - templates/toolkit.yaml
      - plugins/devflow/templates/toolkit.yaml
      - docs/profile-reference.md
      - tests/test_profile_agents.py
      - tests/fixtures/agents-toolkit.yaml
    brief: |
      Implement Design D2 and D6a. Read plugins/devflow/schema/profile.schema.json,
      plugins/devflow/scripts/validate_profile.py, tests/test_validate_profile.py (how `vp` is used) and
      tests/test_structure.py:98 first.
      1. In profile.schema.json add `docs.website` and the top-level `agents` object exactly as D2 says: the ten agent
         names in an `enum` for `agents.disable` items and `agents.required[].agent`, the five points in an `enum` for
         `agents.required[].at` items, `additionalProperties: false` everywhere, and NO `default` keys.
      2. In validate_profile.py `semantic_checks` add the three errors of D2 with the exact texts. They run on the
         resolved profile; a profile without `agents` produces no new output of any kind.
      3. Add a commented `agents:` block and a commented `docs.website` example to templates/toolkit.yaml (comments only,
         same style as the other optional blocks, using the D2 worked example). Then copy the file byte for byte to
         plugins/devflow/templates/toolkit.yaml.
      4. In docs/profile-reference.md add table rows with the backticked dotted names `docs.website`, `docs.website.dir`,
         `docs.website.build`, `docs.website.links`, `agents`, `agents.posture`, `agents.posture.security`,
         `agents.disable`, `agents.required`, `agents.extra_context`; add a short `### agents` section (the points, the
         mandatory and blocking meaning from D3, the defaults) and extend the rule "Only two things have defaults" with the
         sentence that the `agents` defaults are applied by scripts/agents.py and are not part of `--resolved`.
      5. Create tests/fixtures/agents-toolkit.yaml: a valid complete profile (docs.must_read [], docs.website {dir: site,
         build: "npm run build", links: "npm run check-links"}, git, verify, stacks: []) plus the agents block of the D2 worked example.
      6. Create tests/test_profile_agents.py: the fixture validates (`vp.validate(yaml.safe_load(...))`, no errors, with
         `root_dir=None`); a profile without the keys gives a resolved dict with no `agents` and no `docs.website`;
         one test per error text of D2; an unknown agent name, an unknown `at` value, a non-boolean `blocking`, a posture
         other than the three, and an empty `when` are rejected; `website-maintainer` required with `docs.website` set is
         valid; tests/fixtures/privacyfence-toolkit.yaml still validates; plugins/devflow/templates/toolkit.yaml equals
         templates/toolkit.yaml byte for byte.
      Stop with status=blocked if adding the keys changes the `--resolved` output of an existing fixture.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_profile_agents.py -q passes"
      - ".venv/bin/python -m pytest tests/test_structure.py tests/test_validate_profile.py -q passes"
      - "`.venv/bin/python plugins/devflow/scripts/validate_profile.py templates/toolkit.yaml --no-file-checks` prints OK"
      - "`cmp templates/toolkit.yaml plugins/devflow/templates/toolkit.yaml` prints nothing"
      - "`grep -n 'agents.required' docs/profile-reference.md` matches"
  - id: p2-agent-dispatch
    title: agents.py (required, verify) and the agent-dispatch skill
    depends_on: [p1-profile-schema]
    complexity: M
    touches:
      - plugins/devflow/scripts/agents.py
      - plugins/devflow/skills/agent-dispatch/SKILL.md
      - tests/test_agents_dispatch.py
      - tests/test_structure.py
    brief: |
      Implement Design D3 and D4. Read plugins/devflow/scripts/scope_check.py (how it imports validate_manifest),
      validate_manifest.path_matches, tests/test_scope_check.py (how script tests are written) and
      tests/fixtures/agents-toolkit.yaml.
      1. Write plugins/devflow/scripts/agents.py with `required(profile, point, changed)`, `verify(required, report)`
         and the CLI of D4: exact JSON keys, exact output lines (`OK`, `MISSING`, `BLOCKED`, the `agents:` summary), exit codes,
         and the error texts. Defaults (`posture.security` standard, `blocking` false, `disable` [], `extra_context` [])
         are applied here and nowhere else. Follow D14.
      2. Write plugins/devflow/skills/agent-dispatch/SKILL.md with the headings of D4 (`## Resolve`, `## Dispatch`,
         `## Modes`, `## Report`, `## Gate`, `## Not required`), the dispatch prompt of D3 verbatim, the mode table and the
         failure table of D3, and the report line.
      3. In tests/test_structure.py:63 add `agent-dispatch` to the expected set of skill names. Change nothing else there.
      4. Write tests/test_agents_dispatch.py: `required` for every point on the fixture profile (which agents, `blocking`,
         `matched`); `when` matching and not matching (goes to `not_applicable`); `blocking` OR-merge of two entries;
         a profile without `agents` returns empty `required`; the three error cases; `verify` for ok, missing line,
         `verdict=n/a`, blocked, non-blocking entry with findings (ok), last line wins; a CLI round trip through
         `subprocess` for both subcommands with the exit codes; the skill file has every heading of D4 and the strings
         `AGENT-REPORT` and `agents.py required`.
      Stop with status=blocked if importing validate_profile or validate_manifest from the script needs a different
      pattern than scope_check.py uses.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_agents_dispatch.py tests/test_structure.py -q passes"
      - "`.venv/bin/python plugins/devflow/scripts/agents.py required --profile tests/fixtures/agents-toolkit.yaml --at make_plan` prints JSON whose required list names test-architect"
      - "`.venv/bin/python -m pytest tests/test_no_project_words.py -q` passes"
  - id: p3-agents-review
    title: The six read-only agents and the agent file validator
    depends_on: [p1-profile-schema]
    complexity: M
    touches:
      - plugins/devflow/agents/architect.md
      - plugins/devflow/agents/code-reviewer.md
      - plugins/devflow/agents/security-reviewer.md
      - plugins/devflow/agents/test-architect.md
      - plugins/devflow/agents/ux-reviewer.md
      - plugins/devflow/agents/dependency-auditor.md
      - tests/agents_support.py
      - tests/test_agents_review.py
    brief: |
      Implement Design D1 for architect, code-reviewer, security-reviewer, test-architect, ux-reviewer and
      dependency-auditor. Read the four wrapped skills (plugins/devflow/skills/review-checklist, secure-code-review,
      test-review, docs-review SKILL.md) and plugins/devflow/commands/implement.md:272 (the REVIEW-REPORT wording) first.
      1. Write the six files plugins/devflow/agents/<name>.md: the four-key front matter of D1 (model and tools from the
         D1 table), then `# <Title>` and the `## Role`, `## Inputs`, `## Method`, `## Report`, `## Limits` sections. Inputs lists
         the fields of D1; Report states the finding format and ends with the AGENT-REPORT line format of D3 with the
         agent's own name; Method carries the per-agent points of D1 (for security-reviewer the three posture rules, with
         the literal heading name `## Threat model` for critical); Limits says what the agent never does (read-only: no
         Edit, no Write; no network calls beyond what the prompt's commands do).
      2. Write tests/agents_support.py with the constants ALLOWED_TOOLS = {Read, Grep, Glob, Bash, Skill, Edit, Write},
         EDIT_AGENTS = {tech-writer, website-maintainer, debugger, refactorer}, EXPECTED = a dict of all ten agent names to
         (model, wrapped skill or None) from the D1 table, and `check_agent_file(path)` which asserts: the file has front
         matter with exactly the keys name, description, tools, model; name equals the file stem; description has at least
         40 characters; model equals EXPECTED; tools are a comma separated subset of ALLOWED_TOOLS containing Read, Grep,
         Glob, Bash and Skill; Edit and Write are present exactly for EDIT_AGENTS; the five `##` sections appear in order;
         the AGENT-REPORT format line with the agent's name is present; when the agent wraps a skill the text
         `Load the \`<skill>\` skill` is present.
      3. Write tests/test_agents_review.py: `check_agent_file` on each of the six files; security-reviewer contains
         `## Threat model`, `critical`, `standard` and `low`; architect contains `ADR`; dependency-auditor contains
         `Audit commands`; ux-reviewer contains `Stack skills`; every file lists the Inputs field `Mode`.
      Stop with status=blocked if the front matter of an agent file is rejected by any validator you can run
      (`claude plugin validate plugins/devflow` if the CLI exists); report its message verbatim.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_agents_review.py -q passes"
      - "`ls plugins/devflow/agents/*.md | wc -l` prints 6"
      - "`grep -n 'Threat model' plugins/devflow/agents/security-reviewer.md` matches"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p4-agents-edit
    title: The four edit-capable agents
    depends_on: [p3-agents-review]
    complexity: M
    touches:
      - plugins/devflow/agents/tech-writer.md
      - plugins/devflow/agents/website-maintainer.md
      - plugins/devflow/agents/debugger.md
      - plugins/devflow/agents/refactorer.md
      - tests/test_agents_edit.py
    brief: |
      Implement Design D1 for tech-writer, website-maintainer, debugger and refactorer, in the same file layout as the
      six agents p3 wrote (read one of them first, and tests/agents_support.py).
      1. Write the four files with `tools: Read, Grep, Glob, Bash, Skill, Edit, Write`, the models of the D1 table, the same
         sections, and the per-agent method points of D1. Each Limits section says: edits happen only when the prompt says
         `Mode: edit`; in `review` mode the agent reports and changes nothing; it never touches a file outside `Scope`.
      2. Write tests/test_agents_edit.py: `from agents_support import check_agent_file` on each of the four; tech-writer and
         website-maintainer contain `Load the \`docs-review\` skill`; website-maintainer contains `Website build`, `Website
         links` and `n/a`; refactorer contains `Verify (fast)`; debugger contains `root cause`; every file contains
         `Mode: edit` and `review mode`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_agents_edit.py tests/test_agents_review.py -q passes"
      - "`ls plugins/devflow/agents/*.md | wc -l` prints 10"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p5-wire-plan-dod-review
    title: Wire required agents into /make-plan, /dod and /review
    depends_on: [p2-agent-dispatch]
    complexity: M
    touches:
      - plugins/devflow/commands/make-plan.md
      - plugins/devflow/commands/dod.md
      - plugins/devflow/commands/review.md
      - tests/test_wire_plan_dod_review.py
    brief: |
      Implement the /make-plan, /dod and /review parts of Design D3 and D5. Read the three command files in full first
      (the line numbers in the "Current state" section are approximate).
      1. make-plan.md: in the Profile bullet list add `- "the agent rules" are the profile's agents section, read through the
         agent-dispatch skill; load it now.` In section 0 add a step 5 after the scope decision: "**Agents.** Run
         `python3 <devflow root>/scripts/agents.py required --profile .claude/toolkit.yaml --at make_plan`. For a large scope,
         dispatch the `architect` agent first (unless it is in `disabled`) with the ask, your research notes and the must-read
         docs, and use its options when you write the Design section. Dispatch every agent in `required`, each in review mode,
         as the agent-dispatch skill says. A blocking finding must be resolved in the plan before you push; a non-blocking one
         goes into the plan's Risks. Before the final reply run `agents.py verify` on the agents' reports; exit 1 stops you
         until the missing agent has run or the finding is resolved. Name each agent that ran, with its AGENT-REPORT line,
         under `Agents:` in the final reply." In the small-scope paragraph, add that step 5 of section 0 still applies and
         the agents that ran are named in one line before the prompt.
      2. dod.md: add after the manual-items paragraph: "**Required agents.** Run `python3 <devflow root>/scripts/agents.py
         required --profile .claude/toolkit.yaml --at dod --changed <file with the output of git diff --name-only
         origin/<main>...HEAD>`. Dispatch each agent in `required`, in review mode, as the agent-dispatch skill says. Each gives
         one row `agent: <name>`: `PASS`; `FAIL` when the item is blocking and its report has blocking findings, or when it did
         not run (`required agent did not run`); `needs attention (<n>)` when only non-blocking findings exist. After the table,
         one subsection per agent with its full report verbatim, ending in its AGENT-REPORT line." Extend the final verdict
         sentence: a `FAIL` agent row means the branch is not ready. Add `agent-dispatch` to the Profile paragraph's skill list.
      3. review.md: add this row to the dimension table in section 3: `| Required agents | AGT | the agent's own file (see the agent-dispatch skill) | one per agent in \`agents.py required --at review\`; run alongside the other subagents |`;
         below the table add one paragraph: required agents at `review` are dispatched in review mode with the same scope; their
         findings use the block format with ids `AGT-<n>`; an agent whose entry is `blocking: true` has every blocking finding
         graded at least `high`; run `agents.py verify` on their reports before section 4 and treat a `MISSING` line as an open
         item in the document.
      4. Write tests/test_wire_plan_dod_review.py: each file contains `agent-dispatch` and `agents.py required`; make-plan has
         `--at make_plan`, `architect`, `Agents:`; dod has `--at dod`, `AGENT-REPORT`, `required agent did not run`; review has
         `--at review`, `AGT`. The existing test `tests/test_structure.py::test_review_hands_over_to_make_plan` must still pass.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_wire_plan_dod_review.py tests/test_structure.py -q passes"
      - "`grep -c 'agents.py required' plugins/devflow/commands/make-plan.md plugins/devflow/commands/dod.md plugins/devflow/commands/review.md` prints a count of at least 1 for each file"
  - id: p6-wire-implement
    title: Wire required agents into /implement
    depends_on: [p2-agent-dispatch]
    complexity: M
    touches:
      - plugins/devflow/commands/implement.md
      - tests/test_wire_implement.py
    brief: |
      Implement the /implement part of Design D3 and D5. Read plugins/devflow/commands/implement.md in full first.
      1. In the Profile bullet list add `- "the agent rules" are the profile's agents section, read through the agent-dispatch
         skill.` and in the "Models" paragraph add one sentence: the orchestrator never runs an agent that has edit tools; it
         only computes who is required and checks the reports.
      2. Child brief (section 3): after rule 3 add rule `3b`: "Required agents. Write the names of the files you changed
         (`git diff --name-only <feature_branch>...HEAD`) to a temporary file, run `python3 <devflow root>/scripts/agents.py
         required --profile .claude/toolkit.yaml --at implement_phase --changed <that file>`, and dispatch every agent it lists in
         edit mode as the agent-dispatch skill says, before your last push. Fix every blocking finding. Put each agent's
         `AGENT-REPORT` line into your PHASE-REPORT after the `/dod` table. Save the JSON and the report text and run `agents.py
         verify --required <json> --report <text>`; it must exit 0." In rule 5 add that the AGENT-REPORT lines follow the `/dod`
         table.
      3. Merge (section 4): after step 2 insert step `2b`: "Required agents. Save the names of the files in
         `git diff --name-only <base>...origin/<phase branch>` to a file, run `agents.py required ... --at implement_phase
         --changed <file>` and `agents.py verify --required <json> --report <the child's PHASE-REPORT text>`. Exit 1 goes back to
         the child like any other defect, with the output of `verify` as the instruction." Add to the ledger line of a merged phase
         `agents ok` or the failing agents.
      4. Final review (section 5): in the reviewer prompt add: "Run `python3 <devflow root>/scripts/agents.py required --profile
         .claude/toolkit.yaml --at implement_final --changed <the files of git diff --name-only origin/<main>...HEAD>` and dispatch
         every agent it lists in review mode as the agent-dispatch skill says. Put their AGENT-REPORT lines before the
         REVIEW-REPORT line. A blocking finding of an agent whose item is blocking is a blocking finding of yours. Run `agents.py
         verify`; if it exits 1 your verdict is `changes`." After reading the report the orchestrator runs `agents.py verify`
         itself on the review text; exit 1 counts as `changes` and the findings go to a fix session as for any blocking finding.
      5. Write tests/test_wire_implement.py: the file contains `3b`, `--at implement_phase`, `--at implement_final`, `agents.py
         verify`, `AGENT-REPORT`, `agent-dispatch`; the orchestrator sentence about never running edit agents is present; and
         the existing guarantee still holds that the file contains `never substitute`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_wire_implement.py tests/test_structure.py -q passes"
      - "`grep -n 'agents.py verify' plugins/devflow/commands/implement.md` matches at least 3 lines"
  - id: p8-protect-paths-exemption
    title: protect-paths allows the profile only while /setup runs
    depends_on: []
    complexity: S
    touches:
      - plugins/devflow/hooks/protect_paths.py
      - tests/test_hook_protect_paths_setup.py
    brief: |
      Implement Design D10. Read plugins/devflow/hooks/protect_paths.py, plugins/devflow/hooks/dod_gate.py lines 36-70 and
      200-227 (`state_dir`, `mark_exempt`, `--exempt` handling) and tests/test_hook_protect_paths.py plus tests/hooks_helpers.py.
      1. In protect_paths.py add the constants of D10 and import `state_dir` from `dod_gate` (the hooks directory is on
         `sys.path` when the script runs; check that importing dod_gate has no side effect).
      2. Add `profile_allowed(project: str) -> bool` (marker exists and `written_at` younger than the TTL) and use it in
         `violation()` so that the single path `.claude/toolkit.yaml` is let through while it is true; nothing else changes.
      3. Handle `--allow-profile` and `--end-allow` in `__main__` before the normal stdin path, copying how dod_gate.py
         handles `--exempt`; print the two exact lines of D10. Add `or by /setup` to the profile deny message and keep the
         words `changed by people`.
      4. Write tests/test_hook_protect_paths_setup.py: without a marker Write to `.claude/toolkit.yaml` is denied (exit 2);
         after `--allow-profile` (run with `run_script` or by calling the function in a temp repo) it is allowed, while `.env`,
         `uv.lock` and `.github/workflows/ci.yml` are still denied; a marker with `written_at` three hours ago denies again;
         `--end-allow` denies again; a Bash `sed -i` on the profile follows the same rule; a marker in one repository does not
         allow the profile in another. Use `make_repo`/`fresh_repo` helpers.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_protect_paths_setup.py tests/test_hook_protect_paths.py tests/test_hooks_compat.py -q passes"
      - "`grep -n 'changed by people' plugins/devflow/hooks/protect_paths.py` matches"
  - id: p9-survey-fixtures
    title: The four /setup fixture repositories
    depends_on: []
    complexity: M
    touches:
      - evals/fixtures/setup_repos.py
      - tests/test_evals_fixtures.py
      - tests/test_setup_fixtures.py
    brief: |
      Implement Design D12. Read evals/fixtures/__init__.py, evals/fixtures/tiny_app.py (`build` and `init_repo`) and
      tests/test_evals_fixtures.py first.
      1. Write evals/fixtures/setup_repos.py with `REPOS`, one dict of files per repository with exactly the files of the D12
         table (file contents are short but contain the words the table names; the Markdown files of docs_website have at
         least one heading line; the workflow files are valid YAML), and `build(dest, repo="security_heavy",
         with_profile=False)` returning the dict of D12 (`main_branch`, `repo`, `stacks`, `agents`, `website`, `dispatchable`
         and also `adr_dir`, `adr_index`, `changelog`, which are None except for docs_website).
      2. In tests/test_evals_fixtures.py add `setup_repos` to the `BUILDERS` list and change nothing else.
      3. Write tests/test_setup_fixtures.py: for each repo the build succeeds in `tmp_path`; the listed files exist; the
         returned dict has the keys of D12; `with_profile=True` writes `.claude/toolkit.yaml` and it passes
         `validate_profile.py` (load `vp` from conftest); docs_website has exactly 11 `*.md` files, security_heavy 3, ios_ui_app 1 and
         bare 1; ios_ui_app has exactly two files containing `import SwiftUI`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_setup_fixtures.py tests/test_evals_fixtures.py -q passes"
      - "`grep -c 'import SwiftUI' evals/fixtures/setup_repos.py` prints a number of at least 2"
  - id: p10-survey-signals
    title: survey_signals.py
    depends_on: [p9-survey-fixtures]
    complexity: M
    touches:
      - plugins/devflow/scripts/survey_signals.py
      - tests/test_survey_signals.py
    brief: |
      Implement `survey_signals.py` exactly as Design D7 says (`scan(root)` and its output shape, the extensions, the test-path
      rule, the five regexes, `policy_docs`, `firing`/`score`, UI files and globs, test levels, the skip list and the
      limits). Follow D14: the word list of the forbidden-words test must not appear in the file, so describe regexes only by
      their patterns. Add a CLI `survey_signals.py [ROOT]` that prints `scan` as JSON.
      Write tests/test_survey_signals.py using `from evals.fixtures.setup_repos import build`:
      - security_heavy: `score` is 6, `firing` is the six names in order, `ui.globs` is `[]`, `levels` is unit only,
        `source_files` is greater than 0.
      - ios_ui_app: `firing` is `["egress"]`, `score` is 1, `ui.globs` is `["Sources/App/Views/**"]`, `levels.unit` and
        `levels.e2e` true, `levels.integration` false.
      - docs_website: `score` is 0, `markdown_files` is 11, `levels` is unit only.
      - bare: `source_files` is 0, everything empty or false.
      - unit tests on tmp files for: a category with one file does not fire; `policy_docs` fires with one file; node_modules
        and `.git` are skipped; a file over 200000 bytes is not read; the 20-entry cut leaves `count` intact.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_survey_signals.py -q passes"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p11-survey-docs
    title: survey_docs.py
    depends_on: [p9-survey-fixtures]
    complexity: S
    touches:
      - plugins/devflow/scripts/survey_docs.py
      - tests/test_survey_docs.py
    brief: |
      Implement `survey_docs.py` exactly as Design D7 says (`scan(root)`, `must_read`, `adr_dir`/`adr_index`, `changelog`,
      `website` with the config table, `build` and `links` rules). Follow D14. Add a CLI `survey_docs.py [ROOT]` printing JSON.
      Write tests/test_survey_docs.py using `from evals.fixtures.setup_repos import build`: docs_website gives `must_read`
      starting with `README.md`, `adr_dir` `docs/adr`, `adr_index` `docs/adr/README.md`, `changelog` file `CHANGELOG.md` and
      section `## [Unreleased]`, `website` dir `website`, tool `docusaurus`, build `npm run build`, links `npm run check-links`;
      bare gives `must_read == ["README.md"]` and the rest null; and tmp-path tests for: a root `mkdocs.yml` gives dir `.`,
      tool `mkdocs`, build `mkdocs build --strict`, links null; a docusaurus config without a `package.json` gives build null;
      a changelog without an Unreleased heading gives section null; `adr_index` falls back to `index.md`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_survey_docs.py -q passes"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p12-survey-assemble
    title: profile_survey.py (stacks, CI, verify evidence, git) and the CLI
    depends_on: [p10-survey-signals, p11-survey-docs]
    complexity: M
    touches:
      - plugins/devflow/scripts/profile_survey.py
      - tests/test_profile_survey.py
    brief: |
      Implement `profile_survey.py` as Design D7 says: `survey(root)`, the CLI (`profile_survey.py [ROOT]`, JSON on stdout,
      exit 0), the `evidence` keys `stacks`, `other_stacks`, `ci`, `verify_evidence`, `git`, `docs` (from `survey_docs.scan`)
      and `signals` (from `survey_signals.scan`), and `"proposal": null`. Import the two sibling modules the way
      scope_check.py imports its siblings. Follow D14, in particular the `on` key pitfall of D7.
      Write tests/test_profile_survey.py using `from evals.fixtures.setup_repos import build`:
      - security_heavy: stacks `["python"]`, `ci.workflows` has one entry with triggers `push` and `pull_request`,
        `verify_evidence.ci_runs` holds its run step, `ci.dispatchable == []`, `git.main_branch == "main"`, `has_history` true.
      - ios_ui_app: stacks names `["swift", "ipados"]`, `ci.dispatchable` has one entry with workflow `macos-tests.yml`,
        `use_when` containing `macOS` and `macos-latest`, notes `No inputs.`.
      - docs_website: stacks `["go"]`; `other_stacks` is `[]` (its `package.json` is in `website/`, and only a root
        `package.json` is reported).
      - bare: stacks `[]`, `ci.workflows == []`.
      - tmp-path tests: a root `package.json` with scripts gives `package_scripts` and `other_stacks`; a root Makefile gives
        only the whitelisted `make_targets`; a directory that is not a git repository gives the empty `git` object; a workflow
        with `on: workflow_dispatch` and inputs `a` and `b` on `windows-latest` gives notes `Inputs: a, b`; a workflow whose
        `on` is a list.
      - the CLI run in a subprocess on a fixture prints JSON with the keys `root`, `evidence`, `proposal`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_profile_survey.py -q passes"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p13-survey-proposal
    title: survey_proposal.py and the agents proposal
    depends_on: [p12-survey-assemble, p1-profile-schema]
    complexity: M
    touches:
      - plugins/devflow/scripts/survey_proposal.py
      - plugins/devflow/scripts/profile_survey.py
      - tests/test_survey_proposal.py
    brief: |
      Implement `survey_proposal.py` exactly as Design D8 says (`build(evidence)`, the `profile` keys and their order, the
      `agents` rules 1 to 4, `rationale` entries). In `profile_survey.py` make `survey()` set `"proposal"` to
      `survey_proposal.build(evidence)`. Follow D14.
      Write tests/test_survey_proposal.py using `from evals.fixtures.setup_repos import build`: for each of the four repos
      `survey(root)["proposal"]["profile"]["agents"] == expected["agents"]` (the dict `build` returns), `["stacks"]` equals
      `expected["stacks"]`, `["docs"].get("website") == expected["website"]` (compare `None` by absence), and
      `ci.dispatchable` workflows match `expected["dispatchable"]`; docs_website's profile also has the `adr_dir`, `adr_index`
      and `changelog` of the expected dict; every proposal validates: merge the profile fragment into a minimal valid profile
      (docs.must_read from the fragment, git with `branch_pattern`, `verify` echo commands) and check `vp.validate` returns no
      errors with `root_dir=None`; the rationale has an entry for `agents.posture.security` and one per required agent; a
      repository with `source_files == 0` has no `required`; `blocking: True` appears only for security-reviewer at critical.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_survey_proposal.py tests/test_profile_survey.py -q passes"
      - "`.venv/bin/python plugins/devflow/scripts/profile_survey.py .` exits 0 and prints a proposal that is not null"
  - id: p14-profile-patch
    title: profile_patch.py (set-block, diff, stale keys)
    depends_on: [p1-profile-schema]
    complexity: M
    touches:
      - plugins/devflow/scripts/profile_patch.py
      - tests/test_profile_patch.py
    brief: |
      Implement `profile_patch.py` exactly as Design D9 says (`set-block`, `diff`, the stale rules). Follow D14. Never round-trip
      the profile through a YAML dumper; only the block being replaced is rendered with `yaml.safe_dump`.
      Write tests/test_profile_patch.py on inline profile texts: replacing an existing `agents:` block keeps all other lines,
      comments included, byte for byte; a comment line directly above the key stays; appending when absent adds one blank line
      and the block at the end; `docs.website` is added as the last child of `docs:` and replaced when present; `docs.website`
      without a `docs:` block exits 1 with the exact message; applying the same value twice is idempotent; the result of every
      case still loads with `yaml.safe_load` and validates with `vp.validate`; `diff` reports `new`, `changed`, `same` for a
      small example, and `stale` for a missing `docs.must_read` file, a missing workflow of `ci.dispatchable`, and a `when` glob
      that matches no file (use `tmp_path` with `git init`-free plain files); the CLI is exercised with `subprocess` for both
      subcommands, including `--write`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_profile_patch.py -q passes"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p16-board-setup
    title: Status board record for /setup
    depends_on: []
    complexity: S
    touches:
      - plugins/devflow/schema/status-record.schema.json
      - plugins/devflow/scripts/validate_status_record.py
      - plugins/devflow/skills/status-board/SKILL.md
      - tests/test_status_record.py
    brief: |
      Implement Design D11. Read validate_status_record.py (the `COMMANDS` constant and the rule-2 block), the schema's
      `command` enum, the status-board skill and the existing maintenance cases in tests/test_status_record.py first.
      1. Add `setup` to the `command` enum of status-record.schema.json and to `COMMANDS` in validate_status_record.py; update the
         two error messages to say `'deps', 'upstream', 'land' or 'setup'`.
      2. Change the `orchestrator_session` rule for maintenance records: the literal `scheduled` for `deps`, `upstream`, `land`;
         a non-empty string for `setup`.
      3. In plugins/devflow/skills/status-board/SKILL.md add a short section `## /setup records` with the D11 facts (kind, command,
         document id, the five item ids, session id, push-only alerts).
      4. Extend tests/test_status_record.py: a valid `setup` maintenance record passes; `scheduled` is accepted for `setup` but a
         real session id is rejected for `deps`; the document id `<project>--setup` is checked; the old messages' wording is updated
         in any test that asserts it.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_status_record.py tests/test_status_board.py tests/test_board.py -q passes"
      - "`grep -n 'setup' plugins/devflow/schema/status-record.schema.json` matches"
  - id: p15-setup-command
    title: The /setup command and the profile-setup skill
    depends_on: [p13-survey-proposal, p14-profile-patch, p8-protect-paths-exemption, p2-agent-dispatch, p16-board-setup]
    complexity: M
    touches:
      - plugins/devflow/commands/setup.md
      - plugins/devflow/skills/profile-setup/SKILL.md
      - tests/test_structure.py
      - tests/test_setup_command.py
    brief: |
      Implement Design D6 and D6a. Read plugins/devflow/commands/deps.md (a command with the same Profile/status-board
      structure), plugins/devflow/skills/project-profile/SKILL.md, and the scripts you will call: profile_survey.py,
      profile_patch.py, validate_profile.py, and the hook flags of protect_paths.py and dod_gate.py.
      1. Write plugins/devflow/commands/setup.md with the front matter and the nine headings of D6, in that order. Step 4 *create*
         copies `<devflow root>/templates/toolkit.yaml` (D6a) and fills it from the table of step 2; replace nothing else. Section
         `## Status board` follows the status-board skill's `## /setup records` section. It contains the words `project-profile`
         and `never substitute`. It names these scripts and flags exactly: `profile_survey.py`, `profile_patch.py diff`,
         `profile_patch.py set-block`, `validate_profile.py`, `dod_gate.py" --exempt`, `protect_paths.py" --allow-profile`,
         `protect_paths.py" --end-allow`. It states that it never merges and that, when no pull request can be opened, it stops
         after the commit.
      2. Write plugins/devflow/skills/profile-setup/SKILL.md with the five headings of D6 and the rules listed there (verify
         command choice, mapping, questions, pull request body, never).
      3. In tests/test_structure.py:63 add `profile-setup` to the expected skill names (after p2's `agent-dispatch`). Change nothing else.
      4. Write tests/test_setup_command.py: the command has the front matter keys and `model: sonnet`; every heading of D6 in
         order; every script and flag string above; `chore/toolkit-profile`; `AskUserQuestion`; the skill has its five
         headings and the strings `Decisions for a human`, `blocking: true` and `Never`; `plugins/devflow/templates/toolkit.yaml`
         exists; running `profile_survey.py` on a fixture and `profile_patch.py set-block` with its `agents` block on a profile
         copy yields a profile that validates (an end-to-end check in `tmp_path`, using `evals.fixtures.setup_repos`).
    acceptance:
      - ".venv/bin/python -m pytest tests/test_setup_command.py tests/test_structure.py -q passes"
      - ".venv/bin/python -m pytest tests/test_no_project_words.py -q passes"
  - id: p17-docs
    title: Documentation for the agents and /setup
    depends_on: [p15-setup-command, p5-wire-plan-dod-review, p6-wire-implement, p4-agents-edit]
    complexity: M
    touches:
      - docs/agents.md
      - docs/setup.md
      - docs/design.md
      - docs/hooks.md
      - docs/maintenance.md
      - README.md
      - tests/test_docs_agents.py
    brief: |
      Write the documentation from Design D1 to D11; do not restate code. Read README.md, docs/hooks.md (the `protect-paths`
      section and "How the dod-gate recognises a session"), docs/maintenance.md and docs/design.md section 2 first.
      1. docs/agents.md: the roster table (name, model, wrapped skill, edit tools), the profile `agents` block with the worked
         example, the points table with modes and failure rules (D3), the report line, `agents.py required` and `verify`
         usage, the meaning of mandatory and blocking, and how to switch an agent off.
      2. docs/setup.md: the `/setup` flow in the order of D6 with the survey signals table of D8 (what makes the posture
         critical, the UI globs, the test levels), what is asked, what the pull request contains, the create and update modes,
         `profile_patch.py`, and what is never written.
      3. docs/design.md: append a numbered section "Agents and /setup" that records the decisions (agents in devflow not a new
         plugin; profile-driven posture; text-level patching; the protect-paths convention) and update the layout block's
         `agents/` and new scripts lines. Do not rewrite history sections.
      4. docs/hooks.md: in the `protect-paths` section document `--allow-profile`, `--end-allow`, the two-hour TTL, per-checkout
         scope, and that it is a convention. docs/maintenance.md: add the `setup` record to its record list.
      5. README.md: add `/setup` and the agents bullets to the command list, change "the eight commands" to the right count,
         make step 1 of "Use it in a project" `/setup` (keeping the manual copy as the fallback), add the scripts and the
         `agents/` directory to the "What is here" table.
      6. tests/test_docs_agents.py: docs/agents.md names all ten agents and the five points; docs/setup.md names `profile_survey.py`,
         `profile_patch.py` and `chore/toolkit-profile`; README mentions `/setup` and `docs/agents.md`; docs/hooks.md contains
         `--allow-profile`; every relative Markdown link in the four new or changed docs resolves to an existing file.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_docs_agents.py -q passes"
      - "`grep -n '/setup' README.md` matches"
      - "`grep -n 'allow-profile' docs/hooks.md` matches"
  - id: p18-evals
    title: Eval graders, fixtures and three tasks
    depends_on: [p15-setup-command, p5-wire-plan-dod-review, p6-wire-implement, p4-agents-edit]
    complexity: M
    touches:
      - evals/harness/graders.py
      - evals/fixtures/agents_demo.py
      - evals/tasks/setup-security-heavy/task.yaml
      - evals/tasks/agents-dod-critical/task.yaml
      - evals/tasks/agents-dod-low/task.yaml
      - tests/test_evals_graders.py
      - tests/test_evals_tasks.py
      - docs/evals.md
    brief: |
      Implement Design D13. Read evals/harness/graders.py (the `grader` decorator, `profile_valid`, `sections_present`),
      evals/fixtures/tiny_app.py, an existing task (evals/tasks/make-plan-small/task.yaml) and tests/test_evals_graders.py,
      tests/test_evals_tasks.py, docs/evals.md.
      1. In graders.py add graders `agents_block_equals` and `result_matches` following the `profile_valid` and
         `sections_present` patterns (`agents_block_equals` reads `.claude/toolkit.yaml` from the run's work tree and compares
         `agents` with `expected["agents"]`; `result_matches` takes the lists `must` and `must_not` from the grader spec).
      2. Write evals/fixtures/agents_demo.py: `build(dest, posture="critical")` is the tiny_app repository plus the profile of
         D13, using `init_repo`; it returns `{"main_branch": "main", "posture": posture}`.
      3. Write the three task.yaml files of D13 (ids, descriptions, commands, fixtures with params, graders, `repeats: 3`,
         `timeout_s: 900`, `cost_ceiling_usd` 3.0 for the setup task and 1.5 for the others, `requires` naming
         plugins/devflow/commands/setup.md or plugins/devflow/agents/security-reviewer.md).
      4. Extend tests/test_evals_graders.py with a case per new grader (pass and fail) and tests/test_evals_tasks.py only if it
         counts or lists tasks; `python3 evals/run.py validate` must accept the new tasks.
      5. In docs/evals.md add the three tasks to the task list and the two graders to the grader list.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_evals_graders.py tests/test_evals_tasks.py tests/test_evals_fixtures.py tests/test_evals_runner.py -q passes"
      - "`python3 evals/run.py validate` exits 0"
      - "`python3 evals/run.py list` prints setup-security-heavy, agents-dod-critical and agents-dod-low"
  - id: p19-release-retire
    title: Version bump, roster test, retire the plan
    depends_on: [p17-docs, p18-evals]
    complexity: S
    touches:
      - plugins/devflow/.claude-plugin/plugin.json
      - plugins/stack-python/.claude-plugin/plugin.json
      - plugins/stack-swift/.claude-plugin/plugin.json
      - plugins/stack-ipados/.claude-plugin/plugin.json
      - plugins/stack-go/.claude-plugin/plugin.json
      - .claude-plugin/marketplace.json
      - tests/test_agents_roster.py
      - docs/agents-and-setup-plan.md
      - docs/agents-and-setup-plan-manual-steps.html
    brief: |
      The retirement phase. There are no ADRs and no changelog in this repository, so only the steps below apply.
      1. Set `version` to `0.7.0` in all five plugin.json files. In plugins/devflow/.claude-plugin/plugin.json and
         .claude-plugin/marketplace.json add `/setup` to the command lists in the descriptions and mention the agents.
      2. Write tests/test_agents_roster.py: the set of file stems in plugins/devflow/agents equals the `enum` of
         `agents.disable` items in profile.schema.json, equals the `EXPECTED` keys of tests/agents_support.py, and equals the
         names in the roster table of docs/agents.md (every name appears there in backticks).
      3. Delete docs/agents-and-setup-plan.md and docs/agents-and-setup-plan-manual-steps.html with `git rm`, and check with `grep -rn
         "agents-and-setup-plan" .` that nothing else links to them (fix any link you find).
    acceptance:
      - ".venv/bin/python -m pytest tests -q passes"
      - "`grep -h '\"version\"' plugins/*/.claude-plugin/plugin.json | sort -u` prints exactly one line, `\"version\": \"0.7.0\",` or the same without the comma"
      - "`ls docs/agents-and-setup-plan*` fails with no such file"
```
