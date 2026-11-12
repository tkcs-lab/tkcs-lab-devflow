# Plan: plans on the feature branch, deviations log, cheapest worker level, Opus warning hook

## 1. Goal

Four changes to the plan / implement workflow, requested in
[issue #14](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/14):

1. The `plan/<slug>` branch goes away. `/tld:make-plan` commits the plan to the feature branch itself, at
   `docs/plans/<issue number>/plan.md`; it reaches `main` with the feature and stays there as a historical record.
2. `/tld:implement` writes `docs/plans/<issue number>/deviations.md` next to the plan and checks that every
   deviation from the plan is recorded.
3. `/tld:make-plan` assigns each phase the cheapest level that can do it mechanically: `fast` (Haiku) where the
   brief is literal edits, `standard` (Sonnet) by default, `strong` (Opus) only with a reason. Every review stays at
   the reviewer level (`strong`).
4. A new hook, `model-check`, warns when a tld command starts in a session that runs on the `strong` level (Opus)
   although the command is meant for a cheaper one.

**This plan is executed by the current playbooks.** It lives on `plan/plans-on-feature-branch`, and its last phase
deletes it, as today. The new flow applies from the next plan on. Judgement of the four changes (efficiency and
concept) is in section 3.

## 2. Current state

- `playbooks/make-plan.md:124-132` creates `plan/<slug>` from `<main>`; `:13-15` says a plan branch is never merged
  and that the last phase deletes the plan. `playbooks/implement.md:35-39` accepts a plan only from `<main>` or
  `plan/<slug>`; `:62-69` cuts the feature branch from the plan branch.
- `src/tld/plan/phases.py:57-87` (`check_url`) implements that rule; `:108-112` (`branch_name`) prints
  `plan/<slug>`; `:215` registers `check-url` ("main or plan/* branch").
- `src/tld/ops/docs_index.py:60` (`PLAN_NAME`, used at `:437`) excepts files named `*-plan.md`/`*-review.md` from
  the index; `playbooks/policies/docs.md:14,16` says plans are "deleted when they land".
- `src/tld/plan/manifest.py:225-229` validates `worker_level` (`strong`, `standard`, `fast` already allowed).
  `playbooks/make-plan.md:203-227` (Sizing) never assigns `fast`; every phase runs at `models.worker`.
- Hooks: `adapters/claude/hooks/hooks.json` has no SessionStart entry. `tests/adapters/claude/test_structure.py:52`
  (`test_no_session_start_wording_in_the_plugin`) forbids the word "SessionStart" anywhere in the plugin, and
  `docs/architecture/design.md:111-113` records "a SessionStart hook that installs the toolkit" as rejected.
  `adapters/claude/commands/{make-plan,review}.md` have `model: opus`, `implement.md` `model: sonnet`.
- A UserPromptSubmit hook event has no model field. A SessionStart event has an optional `model`. A transcript
  (`transcript_path`, in every hook event) holds the model in each assistant entry's `message.model`.

## 3. Design

### 3.1 Judgement of the four changes

| # | Verdict | Why |
|---|---|---|
| 1 | Accept, with a pin | One branch fewer, no cut-from-plan step, the plan reviewed in the same PR as the code. Cost: the plan can no longer be trusted by its location (S14: the owner confirms `verify_after_merge` on a plan they reviewed). A feature branch also carries merged worker content. So the confirmed plan is **pinned by its blob SHA** in a start commit (3.3). |
| 2 | Accept, owned by the orchestrator | One file written by one writer: no merge conflicts between parallel phases, and worker text (untrusted) is summarised, not pasted. A mechanical `check` makes "all deviations recorded" testable. |
| 3 | Accept, with limits | Cost is dominated by phase workers. `fast` only for complexity `S` phases whose brief is literal. A research sweep at `fast` is risky for "how does X work", so only locate/enumerate sweeps use it. Fix, revision and conflict workers of a `fast` phase run at `standard`. |
| 4 | Accept, narrowed | The cost of the mistake is real (every child session and wake on Opus). It must not nag: `make-plan` and `review` are Opus commands by design, so no warning for a command whose own level is `strong`. A warning is only a `systemMessage`; the hook never blocks. The Opus level seen may come from the previous turn of `/tld:make-plan`; the text says so. |

### 3.2 Plan location

- Plan: `<plan_dir>/<n>/plan.md`, `<n>` = the tracking issue number (`<plan_dir>/<slug>/plan.md` when issue creation
  was refused). Deviations: `<plan_dir>/<n>/deviations.md`. Plan URL form implement takes:
  `https://github.com/<owner>/<repo>/blob/<feature branch>/<plan_dir>/<n>/plan.md`.
- make-plan creates the manifest's `feature_branch` from `origin/<main>`, commits the plan to it and pushes it. No
  `plan/` branch. The first line under the title of every plan is
  `> Historical record once merged: read it only to understand why a change was made.`
- `tld plan check-url URL --repo O/N --main B [--plan-dir D]` (default `D` = `docs/plans`): the URL must end in
  `/<D>/<segment>/plan.md`; everything between `blob/` and that suffix is the **ref** (branch names contain `/`).
  The ref must be `<main>` or look like `<type>/<kebab>` (`^[a-z0-9]+/[a-z0-9-]+$` and contain no `--`, which would be a phase branch). **Deprecated, still accepted for
  one release, with a warning on stderr** `tld plan: warning: old-layout plans are deprecated`: a ref `plan/<slug>`
  with any path, and `<main>/<anything>`. A legacy plan's deviations file is `<dir of the plan>/<slug>-deviations.md`. Output JSON gains `"legacy": true|false`.
- `tld plan validate-manifest PLAN --profile P --ref REF` (new optional flag): error unless REF is the profile's
  `git.main_branch`, equals the manifest's `feature_branch`, or (legacy) equals `plan/<plan_slug>`, which only prints
  the warning `manifest: old-layout plan on 'plan/<slug>' (deprecated)`. A plan that sits on any other branch is
  refused (the plan cannot vouch for itself from somewhere else).
- `tld plan validate-manifest` also errors on a phase whose `touches` has an entry that is exactly a plan record:
  `<plan_dir>/<segment>/plan.md` or `<plan_dir>/<segment>/deviations.md` (`re.fullmatch`). `--profile` supplies
  `docs.plan_dir`. Old plans (`docs/x-plan.md` deleted by their retirement phase) stay valid. That no worker diff
  touches the plan directory is enforced by the implement merge review, not by the validator.
- Pin: after the owner confirmed the start ask, implement commits `Start <slug>` to the feature branch with the
  trailer `Plan-Started: <plan slug> <blob>`, `<blob>` = `git rev-parse HEAD:<plan path>`, and the deviations
  skeleton in the same commit, then pushes. `tld plan phase-status` gains `started` (bool) and `plan_blob`
  (string or null) from the newest non-reverted `Plan-Started` trailer of this slug on the first-parent history. A
  resumed run whose current plan blob differs from `plan_blob` stops and asks the start ask again. The merge review
  rejects a worker diff under `<plan_dir>/<n>/`.
- make-plan revises a plan in place only while its feature branch has no `Plan-Started` commit; otherwise it stops
  and tells the human to start a new plan.
- `docs_index.py`: one predicate `is_plan_record(rel, plan_dir)` is true for `<plan_dir>/<segment>/plan.md` and
  `<plan_dir>/<segment>/deviations.md`; it is used wherever `PLAN_NAME` is used (check, size, stale), in addition to
  `PLAN_NAME`, **except in `move`'s file scan** (a kept plan still has its relative links rewritten, because
  `tests/core/test_docs_links.py` checks every `*.md`). `PLAN_NAME` also learns `-deviations` (legacy file names). A
  `plan.md` or `deviations.md` anywhere else is indexed like any doc.
- The retirement phase of a plan no longer deletes the plan; `final_checks` replaces "plan is deleted" with
  `tld plan deviations check`. `playbooks/policies/docs.md` says plans stay, are never indexed and never read by
  default.

### 3.3 Deviations

New module `src/tld/plan/deviations.py`, command group `tld plan deviations`:

- `init --plan PLAN --out FILE`: writes
  `# Deviations: <slug>`, a two-line explanation, then `## <phase id>` for each manifest phase in order, then
  `## Final review` and `## Finishing`; each section's only line is `- pending`.
- `add --file FILE --section NAME --tag TAG (--text TEXT | --none)`: replaces a `- pending` line, or appends,
  with `- <TAG>: <TEXT>` or, with `--none`, `- None.`. TAG is one of `worker`, `review`, `scope`, `retry`,
  `conflict`, `gate`, `level`, `final`. TEXT is one line: control characters become `?`, cut at 500 characters.
  Exit 1 with `deviations: <message>` on an unknown section or tag.
- `check --file FILE --plan PLAN [--done ID[,ID...] | --all] [--scope-results FILE]`: exit 1 listing every problem when
  (a) a section of a `--done` phase (or, with `--all`, any section) still says `- pending`; (b) with
  `--scope-results` (the JSON list of `tld plan scope-check`), a path in an entry's `out_of_scope` does not appear in
  the section named by the entry's `label` (a label that is `fix-<n>` maps to `Final review`; a label
  `<phase id>-rev<n>` maps to `<phase id>`). Exit 0 prints `deviations: OK`.
- Who writes: **the orchestrator only**, after a phase merge has passed its verification, in this order:
  merge → verify (`verify.fast`, `verify_after_merge`) → record deviations → commit (`Record deviations for
  <phase id>`) → push. (A red verification is undone by `git reset --hard HEAD~1` before the deviations commit exists.)
  What it records, per phase section: the worker's `Deviations:` report line (workers must always print one,
  `Deviations: none` included), its own diff-review findings, each out-of-scope path (`scope: <path>`), a retry or
  send-back (`retry:`), a conflict resolution (`conflict:`), a gate change request (`gate:`), a level change
  (`level:`). A final-review finding the orchestrator fixes goes under `## Final review` (`final:`); anything about
  the pull request step under `## Finishing`. A section with nothing to record gets `- None.`.
- The final reviewer checks `deviations.md` against the diff and the plan; a deviation the diff shows and the file
  lacks is a blocking finding that the orchestrator fixes by adding the entry.

### 3.4 Worker levels

- Sizing in `playbooks/make-plan.md` gains: **`worker_level: fast`** is allowed only for a phase that is complexity
  `S`, whose brief gives the literal text or the literal edit for every change (docs, strings, config values,
  renames, fixture or baseline refreshes), contains no new control flow or function, and whose acceptance is a named
  test or a grep. Default is the worker level (omit the key). `strong` keeps its existing rule (needs a reason).
- `tld plan validate-manifest` errors on `worker_level: fast` with `complexity` other than `S`: message
  `phase '<id>': worker_level: fast needs complexity S`.
- Implement: fix, revision and conflict workers of a phase whose level is `fast` run at `standard`, recorded as a
  `level:` deviation. A `fast` phase sent back once is rerun at `standard`.
- make-plan: `run_helper` sweeps that only locate or enumerate use level `fast`; sweeps that explain behaviour use
  `standard`; all reviews of the plan or prompt use the reviewer level. A small-scope prompt may name `fast` as its
  start level when its steps are literal.
- The playbooks name levels only (`fast`, `standard`, `strong`); model names stay in the runtime skill
  (`tests/core/test_contracts.py::test_core_content_names_no_runtime_tool_or_model`,
  `::test_model_ids_live_in_one_file`).

### 3.5 Hook `model-check`

- Hook name `model-check` (add to `_common.HOOK_NAMES`, the `hooks.disable` enum in `profile.schema.json`,
  `GUARDS` in `claude_adapter.py`). On by default; `hooks.disable: [model-check]` turns it off. Never denies.
- Core `src/tld/guard/model_check.py`, neutral, names levels only:
  - `Action` gets two optional fields `session_level` and `command_level` (`strong`, `standard`, `fast` or `None`)
    and a new kind `session_start`.
  - Core code never contains the word `SessionStart` (it is scanned by `test_structure.py`); say `session_start`.
  - `evaluate(ctx) -> None` like every guard (a returned string would be a deny message). A warning is set as
    `ctx.notice = <text>`; `run_guard` adds the prefix `tld model-check: ` itself, so the text below starts after it.
  - `session_start` action with a `session_level`: store it in `<state dir>/model-check/<sha256(session id)[:16]>.json`
    (same directory scheme as `plan_gate.session_file`).
  - `prompt` action with `invoked` set: the session level is `action.session_level`, else the stored one; if it is
    `None` -> allow, silent. If the session level is `strong` and `command_level` is not `strong` -> allow with this
    `ctx.notice` (exact text, no prefix): `this session runs at the strong level, the most expensive. /tld:<cmd> is
    meant for the <command_level or standard> level, and its later turns (check-ins, wakes) run on the session's model.
    Switch the session's model before it continues (the level may come from your previous turn, for example a
    /tld:make-plan run).` Everything else -> silent, and `ctx.notice` is reset to `None` (so a trust-lookup notice does not surface as noise).
  - `run_guard` looks up `hooks.disable` for every guard but `plan-gate` before `evaluate` (a `git ls-remote`, up to
    12 s, over the hook's 10 s timeout). `model-check` joins that exception in `_common.run_guard`; `evaluate` calls
    `ctx.disabled(NAME)` only at the moment it would warn.
  - It uses only `systemMessage` (no `additionalContext`), so the model does not repeat the warning.
- Adapter (`claude_adapter.py` plus a shim `adapters/claude/hooks/model_check.py`, same shape as the other shims):
  - SessionStart event (`hook_event_name == "SessionStart"`) -> `Action("session_start", ...)` with `session_level`
    from the event's optional `model` string. `execute` treats SessionStart like a prompt event: it never exits
    non-zero (a profile error becomes a `systemMessage`).
  - UserPromptSubmit -> `session_level` from the newest assistant entry of `transcript_path` (read at most the last
    262144 bytes, parse lines from the end, the first object with `type == "assistant"` and a string
    `message.model`); `None` if unreadable. `command_level` from the `model:` front matter of
    `adapters/claude/commands/<invoked>.md` (`opus`->strong, `sonnet`->standard, `haiku`->fast); a skill or a command
    without it -> `standard`.
  - Model name to level: by family, case-insensitive substring `opus` / `sonnet` / `haiku` in the model string; any
    other string -> `None`. No model id appears in a file other than `adapters/claude/skills/runtime/SKILL.md`.
  - `hooks.json`: add `{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/model_check.py\"","timeout":10}]}`
    to `UserPromptSubmit` (as a second entry) and a new `SessionStart` array with the same command.
  - `tests/adapters/claude/test_structure.py::test_no_session_start_wording_in_the_plugin` is narrowed to: the word
    "SessionStart" may appear only in `adapters/claude/hooks/hooks.json`, `adapters/claude/hooks/claude_adapter.py`,
    `adapters/claude/hooks/model_check.py`, and the file `docs/architecture/hooks.md`/`design.md` (docs are outside
    the scanned dirs anyway); and `hooks.json`'s only SessionStart command is `model_check.py`.
  - `docs/architecture/design.md`'s rejected alternative stays; a sentence says the model-check SessionStart hook
    only records the session's model and installs or fetches nothing.
- Rejected: `PostModelSwitch` (not confirmed to exist in the Claude Code version this plugin targets); reading
  `ANTHROPIC_MODEL` or settings files (does not follow `/model`, unverified); `additionalContext` (the model would
  repeat the warning).

## 4. ADRs

None: the profile has no `docs.adr_dir`. The decisions are in this section and, afterwards, in `docs/architecture/design.md`
and `docs/architecture/hooks.md` (retirement phase).

## 5. Manual steps

### mb0-second-user: Second GitHub user ready (about 10 minutes, only if not yet done)

**Before implementation**

1. Follow the checklist at
   [docs/reference/profile-reference.md#second-github-user](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/plans-on-feature-branch/docs/reference/profile-reference.md#second-github-user).
2. Start a new Claude Code session and check that `identity()` returns `andras-tkcs-agent`.
3. Check that the main branch requires a Code Owner review (repository **Settings → Rules → Rulesets**).

Done when: `identity()` in a new session returns `andras-tkcs-agent` and the main branch requires a Code Owner review.

### ma2-evals-rerun: Re-run the model evals (about 15 minutes, costs money)

**After implementation**

1. On the feature branch run
   `python3 evals/run.py run --task make-plan-large --task make-plan-small --task implement-invalid-manifest --repeats 1 --run-ceiling 6`
   (cost: see [CONTRIBUTING.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/plans-on-feature-branch/CONTRIBUTING.md)).
2. If all three pass, run `python3 evals/run.py baseline <results.jsonl>`; if one fails, do not write the baseline.

Report back: pass/fail per task and the cost.

### ma1-opus-warning: The Opus warning appears (about 5 minutes)

**After implementation**

1. Install the new plugin version in the Claude Code CLI (see
   [docs/guides/delivery.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/plans-on-feature-branch/docs/guides/delivery.md)).
2. Start a new session and pick Opus with `/model`. Type `/tld:ask what does this repository do`. You should see a
   `tld model-check:` warning above the answer.
3. Start another session on Sonnet and type the same line. No warning appears.
4. Type `/tld:make-plan x` in an Opus session (then press Esc before it works). No warning appears.

Report back: pass/fail for steps 2, 3 and 4, and whether the warning also appeared in a fresh session (SessionStart
path) and after `/model` was changed mid-session (transcript path).

## 6. Risks and open questions

- **The session model may be unknown.** If a fresh session's SessionStart event has no `model` and the transcript has
  no assistant entry yet, the hook is silent (it never guesses). The p6 worker reports under `Deviations:` that no real
  event sample was available; the owner's manual step ma1 is the real check.
- **False warning after a strong command.** A `/tld:make-plan` turn runs on Opus by override; the next prompt may be
  warned although the session model is Sonnet. The warning text says so. If this is too noisy, the follow-up is to
  skip the warning when the previous user prompt was a strong tld command.
- **Fast workers.** If a `fast` phase fails or is sent back, it reruns at `standard`; widen the criteria only after
  seeing how often that happens. `create_session` must accept the `fast` level's model; if it rejects it the runtime
  falls back to the nearest model and the ledger notes it.
- **Old plans in `docs/plans/`** will appear in agents' grep results. Nothing is done about it here.
- **Legacy `plan/<slug>` plans** stay accepted for one release (warning). `branch-name --plan-slug` is kept and
  documented as deprecated.
- A phase that finds a test or doc that contradicts its brief (for example another test pinning `plan/` branches)
  stops with `status=blocked` and names the file.

## Implementation manifest

```yaml
plan_slug: plans-on-feature-branch
feature_branch: feature/plans-on-feature-branch
tracking_issue: 14
max_parallel: 2
manual_before:
  - id: mb0-second-user
    title: Second GitHub user ready
    why: The agent opens PRs as git.bot_login and the code owner's review is the gate
    done_when: identity() in a new session returns andras-tkcs-agent and the main branch requires a Code Owner review
manual_after:
  - id: ma1-opus-warning
    title: The Opus warning appears in a real CLI session
    why: Hook events and the transcript shape of the installed Claude Code cannot be exercised by CI
  - id: ma2-evals-rerun
    title: Re-run the three model evals and write the baseline
    why: The eval hashes were only refreshed, not re-measured, because a real run costs money
verify_after_merge:
  - .venv/bin/python -m pytest tests/core/test_validate_manifest.py tests/core/test_plan_phases.py tests/core/test_docs_index.py tests/core/test_contracts.py tests/adapters/claude -q
final_checks:
  - docs/plans/plans-on-feature-branch-plan.md is deleted and nothing links to it
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
  - python3 evals/run.py check-baseline exits 0
phases:
  - id: p1-manifest-rules
    title: "validate-manifest learns --ref, the plan-record ban and fast-needs-S"
    depends_on: []
    complexity: S
    touches:
      - src/tld/plan/manifest.py
      - tests/core/test_validate_manifest.py
    brief: |
      Read first: src/tld/plan/manifest.py, tests/core/test_validate_manifest.py, tests/fixtures/privacyfence-toolkit.yaml
      (note `plan_dir: docs/`).
      Design: sections 3.2 (validate-manifest bullets) and 3.4 (fast-needs-S) of the plan.
      1. In `src/tld/plan/manifest.py`, in the phase loop next to the `worker_level` checks (around line 225), add:
         when `wl == "fast"` and `cx != "S"`, append the error `phase '<id>': worker_level: fast needs complexity S`.
      2. In the same loop, for every string entry `t` of the phase's `touches` (after stripping a leading `./`): when
         `re.fullmatch(re.escape(plan_dir) + r"/[^/]+/(plan|deviations)\.md", t)`, append `phase '<id>': touches '<t>'
         is a plan record; a phase never edits a plan or its deviations file`. `plan_dir` is a new keyword argument of
         `validate` (default `"docs/plans"`, trailing `/` stripped). `main` reads it from `--profile` (`docs.plan_dir`,
         else the default); `phases.load_manifest` keeps calling `validate` without it (so paths like `docs/adr/x.md`
         with `plan_dir: docs/` stay valid, and legacy retirement phases that delete `docs/plans/<slug>-plan.md` stay valid).
      3. Add `--ref REF` to the command line (`ap.add_argument` near `--profile`). After the manifest validates, with
         `main_branch` = the profile's `git.main_branch` (default `main` without a profile): REF equal to `main_branch` or
         to `manifest["feature_branch"]` passes; REF equal to `"plan/" + manifest["plan_slug"]` passes and prints
         `manifest: old-layout plan on 'plan/<slug>' (deprecated)` on stderr; any other REF prints
         `manifest: the plan is on '<REF>', but it may only be on '<main>' or on its own feature branch '<feature_branch>'`
         on stderr and exits 1.
      4. Tests in `tests/core/test_validate_manifest.py`, in the style of the existing `worker_level` tests:
         `test_fast_worker_level_needs_complexity_s` (M phase with fast errors; S phase with fast passes),
         `test_a_plan_record_in_touches_is_an_error` (`docs/plans/14/plan.md` and `docs/plans/14/deviations.md` error;
         `docs/plans/`, `docs/plans/x-plan.md` and `docs/guides/plan.md` pass; with `plan_dir="docs"` the path
         `docs/adr/x.md` passes), `test_ref_must_be_main_or_the_feature_branch_or_the_legacy_plan_branch` (through
         `main([...])`: main, the feature branch and `plan/<slug>` exit 0, `plan/other` exits 1).
      Stop with `status=blocked` if `validate` is called from another module with positional arguments that the new
      keyword argument would shift; name the caller.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_manifest.py -q passes
      - grep -n "worker_level: fast needs complexity S" src/tld/plan/manifest.py matches
      - grep -n "\-\-ref" src/tld/plan/manifest.py matches
      - 'for m in tests/fixtures/privacyfence-*-manifest.yaml; do .venv/bin/python launcher/tld plan validate-manifest "$m" --profile tests/fixtures/privacyfence-toolkit.yaml || exit 1; done exits 0'

  - id: p2-plan-url
    title: "check-url finds the ref from the plan-dir suffix; phase-status reports Plan-Started"
    depends_on: []
    complexity: M
    touches:
      - src/tld/plan/phases.py
      - src/tld/cli.py
      - tests/core/test_plan_phases.py
    brief: |
      Read first: src/tld/plan/phases.py, tests/core/test_plan_phases.py (lines 30-100), src/tld/cli.py (lines 20-30).
      Design: section 3.2 (check-url, pin) of the plan.
      1. In `phases.py` change `check_url(url, repo, main)` (lines 67-87) to `check_url(url, repo, main,
         plan_dir="docs/plans")`. After the repository check let `rest` be the group `rest`. Build
         `suffix = re.compile(r"^(?P<ref>.+)/(?P<path>" + re.escape(plan_dir.strip("/")) + r"/[^/]+/plan\.md)$")`.
         If it matches: the ref must equal `main`, or match `^[a-z0-9]+/[a-z0-9-]+$` and not contain `--`; otherwise raise
         `PlanError("the plan must be on '<main>' or on a <type>/<kebab> feature branch, not on '<ref>'")`. Return
         `{"owner","repo","ref","path","legacy": False}`.
         If it does not match, fall back to the existing `main/` and `plan/<slug>/` logic unchanged and return the same
         dict with `"legacy": True`; the final `else` message becomes `the plan must be at <plan_dir>/<n>/plan.md on
         '<main>' or on its feature branch`.
      2. Add `--plan-dir` (default `docs/plans`) to the `check-url` parser (line ~214); its handler passes it to
         `check_url` and, when the result has `legacy` true, prints `tld plan: warning: old-layout plans are
         deprecated; make-plan now commits the plan to the feature branch` on stderr (stdout JSON otherwise unchanged).
      3. In `trailers(...)` add
         `started_rx = re.compile(r"^Plan-Started:\s*" + re.escape(slug) + r"\s+([0-9a-f]{7,40})\s*$", re.M)` and return a
         third value: the blob of the newest active, non-revert commit having the trailer (`None` when none). Update
         every caller. `phase_status(...)` takes it as new argument `plan_blob` and adds
         `"started": plan_blob is not None, "plan_blob": plan_blob` to its dict.
      4. `--plan-slug` of `branch-name` stays; its help text starts with `deprecated:`.
      5. In `src/tld/cli.py` the `check-url` description becomes `"accept a plan URL (<plan_dir>/<n>/plan.md on main or
         its feature branch; plan/* deprecated)"`. If a test compares this text with `docs/reference/cli.md`, report it
         as an out-of-scope finding; the docs phase edits that doc.
      6. Tests in `tests/core/test_plan_phases.py`: change the expectations at lines ~50-51 that assert the old message
         "must be on 'main' or on a plan/<slug> branch" to the new `else` message; extend the parametrised accept cases
         with `main`, `feature/my-thing` and `fix/a-b` refs plus `docs/plans/14/plan.md` (`legacy` false); refuse cases
         `plans/x`, `feature/Upper` and `feature/x--p1`; keep `plan/tags` + `docs/tags-plan.md` accepted with `legacy`
         true; add `test_phase_status_reports_plan_started` (two commits on a feature branch, the newest with the trailer
         `Plan-Started: <slug> abc1234`: `started` true and `plan_blob` `abc1234`; after a revert commit of it: false),
         using the `feature_repo` fixture pattern of the existing tests.
      Stop with `status=blocked` if a caller of `trailers` outside `phases.py` exists; name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_plan_phases.py -q passes
      - '.venv/bin/python launcher/tld plan check-url https://github.com/o/r/blob/feature/x/docs/plans/3/plan.md --repo o/r --main main prints JSON containing "ref": "feature/x" and "legacy": false'
      - grep -n "Plan-Started" src/tld/plan/phases.py matches

  - id: p3-docs-index-plans
    title: "docs-index excepts <plan_dir>/<n>/plan.md and deviations.md"
    depends_on: []
    complexity: S
    touches:
      - src/tld/ops/docs_index.py
      - tests/core/test_docs_index.py
    brief: |
      Read first: src/tld/ops/docs_index.py (lines 20-25, 55-65, 95-120, and every `PLAN_NAME` use), tests/core/test_docs_index.py.
      Design: section 3.2 (docs_index bullet) of the plan.
      1. Change `PLAN_NAME` to `re.compile(r"-(plan|review|deviations)(-manual-steps)?\.(md|html)$")`.
      2. Add `is_plan_record(rel: str, plan_dir: str) -> bool` next to it: true when `rel` (posix path relative to the
         repository root) matches `^<plan_dir with slashes stripped>/[^/]+/(plan|deviations)\.md$`.
      3. `load_config` (lines ~99-116) gains `cfg["plan_dir"]` from the profile's `docs.plan_dir` (`rstrip("/")`, default
         `docs/plans`). At each use found with `grep -n PLAN_NAME src/tld/ops/docs_index.py` (lines ~206, 224, 233, 279)
         also treat a file as transient when `is_plan_record(<path relative to the repository root>, cfg["plan_dir"])`.
         **Do not change the use at line ~437 (`move`'s file scan)**: a kept plan keeps its links rewritten.
      4. Update the module docstring line `(transient docs named *-plan.md, ...` to add
         `<plan_dir>/<n>/plan.md and deviations.md`.
      5. Tests: `test_plan_and_deviations_files_in_a_plan_directory_need_no_index_row` (a tmp repo with
         `docs/plans/14/plan.md` and `deviations.md`, not linked: `check` reports no error),
         `test_plan_md_elsewhere_is_a_normal_doc` (`docs/guides/plan.md` unlisted: the error the other tests assert for an
         unlisted doc), `test_move_still_rewrites_links_in_a_plan_record` (`move --apply` of a doc linked from
         `docs/plans/14/plan.md` rewrites that link).
      Stop with `status=blocked` if a use of `PLAN_NAME` has no repository-relative path in scope.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_docs_index.py tests/core/test_docs_links.py -q passes
      - grep -n "def is_plan_record" src/tld/ops/docs_index.py matches

  - id: p4-deviations
    title: "tld plan deviations init, add and check"
    depends_on: [p2-plan-url]
    complexity: M
    touches:
      - src/tld/plan/deviations.py
      - src/tld/cli.py
      - tests/core/test_plan_deviations.py
    brief: |
      Read first: src/tld/plan/scope.py (the results JSON: `label`, `out_of_scope[].path`), src/tld/plan/manifest.py
      (`extract_manifest`), src/tld/plan/phases.py (`load_manifest`), src/tld/cli.py.
      Design: section 3.3 of the plan (names, tags and messages there are exact).
      1. Create `src/tld/plan/deviations.py` (stdlib and PyYAML, a module docstring in the style of `scope.py`, `main(argv)`
         returning an int, `class DeviationsError(Exception)` printed as `deviations: <message>`). Subcommands `init`,
         `add`, `check` with the flags of section 3.3. Phase ids come from the plan's manifest as `phases.load_manifest` does.
      2. `init` writes the first line `# Deviations: <plan slug>`, then these two lines exactly:
         `Written by the implement orchestrator after each phase merge; workers never edit this file.` and
         `Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.`, then the
         sections (`## <phase id>` per phase in manifest order, `## Final review`, `## Finishing`), each with the single
         line `- pending`, separated by blank lines.
      3. `TAGS = ("worker","review","scope","retry","conflict","gate","level","final")`. `add` normalises TEXT: replace each
         `[\x00-\x1f\x7f]` with `?`, cut at 500 characters. `add` replaces a section's `- pending` line when present, else
         appends after the section's last bullet. `--none` and `--text` are mutually exclusive and one is required.
      4. `check`: print each problem as `deviations: <problem>`; exit 1 if any, else print `deviations: OK`. Sections are
         found by their `## ` headings. Scope-results label mapping: `fix-<n>` -> `Final review`; `<id>-rev<n>` -> `<id>`;
         else the label itself; a label with no section is a problem.
      5. Register in `src/tld/cli.py`, in the style of `("plan", "scope-check")`:
         `("plan", "deviations"): ("tld.plan.deviations", (), "init | add | check: the deviations log next to a plan")`.
      6. Tests in `tests/core/test_plan_deviations.py` (use `tmp_path`; build the plan file from a two-phase manifest like
         those in `tests/core/test_plan_phases.py`): `test_init_writes_a_pending_section_per_phase`,
         `test_add_replaces_pending_and_appends`, `test_add_none_writes_none`, `test_add_cuts_and_cleans_text`,
         `test_add_rejects_an_unknown_section_and_tag`, `test_check_fails_on_a_pending_done_phase`,
         `test_check_all_fails_on_any_pending`, `test_check_requires_out_of_scope_paths_in_the_section`,
         `test_check_maps_fix_and_rev_labels`.
      Stop with `status=blocked` if `tests/core/test_contracts.py` rejects the new command because of a doc row; name the
      row (the docs phase adds it to `docs/reference/cli.md`).
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_plan_deviations.py -q --cov=tld.plan.deviations --cov-branch --cov-fail-under=90 exits 0
      - .venv/bin/python launcher/tld plan deviations --help exits 0

  - id: p5-model-check-core
    title: "Neutral core of the model-check hook"
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/model_check.py
      - src/tld/guard/action.py
      - src/tld/guard/_common.py
      - tests/core/test_hook_model_check.py
    brief: |
      Read first: src/tld/guard/plan_gate.py (the pattern: `state_dir`, session files, `evaluate`, its `ctx.disabled` use),
      src/tld/guard/action.py, src/tld/guard/_common.py (lines 222-255: `run_guard`), tests/core/test_hook_plan_gate.py.
      Design: section 3.5 of the plan, the core bullets (the notice text is exact).
      Never write the word `SessionStart` in anything under `src/tld/` (docstrings and comments included); say `session_start`.
      1. `action.py`: add `"session_start"` to `KINDS`; add to `Action` the fields `session_level: str | None = None` and
         `command_level: str | None = None`.
      2. `_common.py` line ~232: change the condition to `name not in ("plan-gate", "model-check") and ctx.disabled(name)`
         and extend its comment. Do NOT touch `HOOK_NAMES` (a later phase does).
      3. Create `src/tld/guard/model_check.py`: `NAME = "model-check"`, `NOTICE` (the exact text of section 3.5 with
         `{cmd}` and `{level}`), `session_file(project, sid)` (same directory scheme as `plan_gate.session_file`, under
         `model-check/`), and `evaluate(ctx) -> None` (like every guard: it never returns a `Decision`; it sets
         `ctx.notice`):
         - `session_start` with a `session_level` and a `session_id`: write `{"level": <level>}` to the session file (create
           parents); `ctx.notice = None`; return `None`;
         - `prompt` with `invoked`: `level = action.session_level or <stored level, else None>`; when `level == "strong"`,
           `command_level != "strong"` and `not ctx.disabled(NAME)`: `ctx.notice = NOTICE.format(cmd=invoked,
           level=command_level or "standard")`; otherwise `ctx.notice = None`; return `None`;
         - anything else: `ctx.notice = None`, return `None`. No exception escapes for a missing or unreadable session file.
      4. Tests in `tests/core/test_hook_model_check.py` (go through `_common.run_guard("model-check", evaluate, False,
         action)`, copying the setup helpers of `test_hook_plan_gate.py`): `test_warns_when_the_session_is_strong_and_the_command_is_not`
         (the decision is `allow` with a notice that starts `tld model-check: this session runs at the strong level`, once),
         `test_silent_when_the_command_is_strong`, `test_silent_when_the_session_level_is_unknown`,
         `test_silent_without_an_invoked_command`, `test_session_start_stores_the_level_and_a_later_prompt_uses_it`,
         `test_the_prompt_level_wins_over_the_stored_one`, `test_hooks_disable_switches_it_off`,
         `test_a_missing_or_corrupt_session_file_is_silent`, `test_the_notice_names_no_model` (no `opus|sonnet|haiku` in `NOTICE`).
      Stop with `status=blocked` if `Ctx.notice` cannot be assigned by a guard; name the field you found.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_hook_model_check.py tests/core/test_guard_plumbing.py -q --cov=tld.guard.model_check --cov-branch --cov-fail-under=90 exits 0
      - 'grep -rn "SessionStart" src/tld prints nothing'

  - id: p6-model-check-adapter
    title: "Claude adapter for model-check: events, transcript, front matter"
    depends_on: [p5-model-check-core]
    complexity: M
    touches:
      - adapters/claude/hooks/claude_adapter.py
      - adapters/claude/hooks/model_check.py
      - tests/adapters/claude/test_hooks_model_check.py
    brief: |
      Read first: adapters/claude/hooks/claude_adapter.py, adapters/claude/hooks/plan_gate.py (the shim),
      tests/adapters/claude/test_hooks_prompt.py, tests/hooks_helpers.py (`event`, `make_repo`),
      adapters/claude/skills/runtime/SKILL.md (the Levels table).
      Design: section 3.5 of the plan, the adapter bullets.
      1. `adapters/claude/hooks/model_check.py`: a copy of `plan_gate.py` with `main("model-check")`.
      2. `claude_adapter.py`:
         - `GUARDS["model-check"] = ("tld.guard.model_check", False)`;
         - `level_of(model: object) -> str | None`: lower-case; `opus` in it -> `strong`, `sonnet` -> `standard`, `haiku` ->
           `fast`; not a string or no family -> `None`;
         - `transcript_level(path: object) -> str | None`: if `path` is a readable file, read its last 262144 bytes (`seek` to
           `max(0, size - 262144)`, drop a first partial line), iterate the lines from the end, `json.loads` each in a try,
           and for the first object with `type == "assistant"` and a string `message.model` return `level_of(...)`; `None`
           otherwise; no exception escapes;
         - `command_level(name: str) -> str`: read `commands/<name>.md` next to the hooks directory
           (`Path(__file__).resolve().parents[1] / "commands"`), take the `model:` line of its front matter, map it with
           `level_of`; the file or the key missing -> `"standard"`;
         - `to_action`: for `hook_event_name == "SessionStart"` return `Action("session_start", project, cwd,
           session_id=_sid(payload), session_level=level_of(payload.get("model")))`; in the UserPromptSubmit branch pass
           `session_level=transcript_level(payload.get("transcript_path"))` and `command_level=command_level(invoked) if
           invoked else None`;
         - `execute`: `prompt = payload.get("hook_event_name") in ("UserPromptSubmit", "SessionStart")`, so neither event
           ever exits non-zero; `to_result(..., prompt=True)` already maps a notice to a `systemMessage` and a plain allow to
           `Result(0)`.
      3. Tests in the new `tests/adapters/claude/test_hooks_model_check.py`: `test_level_of_maps_families`,
         `test_transcript_level_reads_the_newest_assistant_model` (a tmp JSONL with an older and a newer assistant line),
         `test_transcript_level_is_none_for_a_missing_file_and_bad_json`, `test_command_level_reads_the_front_matter`
         (`make-plan` -> strong, `implement` -> standard, `ask` -> standard), `test_session_start_event_becomes_a_session_start_action`,
         `test_session_start_never_exits_non_zero` and an end-to-end `test_the_warning_is_a_system_message_only` running
         `execute("model-check", <json>)` with a transcript whose last assistant model contains `opus` and the prompt
         `/tld:implement x`: exit 0, stdout JSON has `systemMessage` and no `hookSpecificOutput`.
      4. Report under `Deviations:` whether any real SessionStart or transcript sample was available to you (none is expected).
      Stop with `status=blocked` if a test outside your `touches` fails because `GUARDS` now has an entry that `HOOK_NAMES` lacks
      (the next phase registers it); name the test.
    acceptance:
      - .venv/bin/python -m pytest tests/adapters/claude/test_hooks_model_check.py -q passes
      - 'grep -rn "claude-opus-\|claude-sonnet-\|claude-haiku-" adapters/claude/hooks prints nothing'

  - id: p7-model-check-register
    title: "Register model-check: hooks.json, hook names, schema, docs"
    depends_on: [p5-model-check-core, p6-model-check-adapter]
    complexity: M
    touches:
      - adapters/claude/hooks/hooks.json
      - src/tld/guard/_common.py
      - src/tld/schema/profile.schema.json
      - tests/hooks_helpers.py
      - tests/adapters/claude/test_hooks_config.py
      - tests/adapters/claude/test_structure.py
      - docs/architecture/hooks.md
    brief: |
      Read first: adapters/claude/hooks/hooks.json, tests/hooks_helpers.py (lines 20-35), tests/adapters/claude/test_hooks_config.py
      (lines 28-45, 125-135, 195-210), tests/adapters/claude/test_structure.py (line 52), docs/architecture/hooks.md.
      Design: section 3.5 of the plan.
      1. `src/tld/guard/_common.py`: add `"model-check"` to `HOOK_NAMES` after `"plan-gate"`. `profile.schema.json`: add
         `"model-check"` to the `hooks.disable` enum after `"plan-gate"`. `tests/hooks_helpers.py`: add `"model-check":
         "model_check"` to `MODULES`, `"model-check": "tld.guard.model_check"` to `CORE`, `"model-check": False` to `FAIL_CLOSED`.
      2. `hooks.json`: append `{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/model_check.py\"","timeout":10}]}`
         as a second entry of `UserPromptSubmit`, and add a `SessionStart` array with one entry running the same command.
      3. `test_hooks_config.py`: line ~31 the event set gains `SessionStart`; lines ~43-44 the expected scripts list
         `model_check.py` twice (UserPromptSubmit and SessionStart), like `plan_gate.py`; extend any other assertion that counts
         entries per event.
      4. `test_structure.py::test_no_session_start_wording_in_the_plugin`: rename it `test_session_start_is_only_used_by_model_check`;
         allow the word in exactly `adapters/claude/hooks/hooks.json`, `adapters/claude/hooks/claude_adapter.py` and
         `adapters/claude/hooks/model_check.py` (and nowhere under `src/tld`); and assert that the commands under
         `hooks.json`'s `SessionStart` are only `model_check.py`.
      5. `docs/architecture/hooks.md`: add a row to the hooks table (events `SessionStart`, `UserPromptSubmit`; denies nothing; why:
         the most expensive level is easy to forget; one warned, one silent example: strong session + `/tld:implement x` warns,
         strong session + `/tld:make-plan x` does not) and a `### model-check` section: levels by model family, the order
         transcript then stored session-start level, silent when unknown, `systemMessage` only, `hooks.disable: [model-check]`, the
         limits of plan section 6. The test `test_docs_cover_every_hook_and_key` needs the string `` `model-check` `` there.
      Stop with `status=blocked` if another test pins the list of hooks or events in a file outside your `touches`; name it.
    acceptance:
      - .venv/bin/python -m pytest tests/adapters/claude tests/core/test_hook_model_check.py tests/core/test_validate_profile.py -q passes
      - grep -c "model_check.py" adapters/claude/hooks/hooks.json prints 2
      - grep -n "model-check" docs/architecture/hooks.md matches

  - id: p8-make-plan-playbook
    title: "make-plan playbook: plan on the feature branch, cheapest level"
    depends_on: [p1-manifest-rules, p2-plan-url, p3-docs-index-plans, p4-deviations]
    complexity: M
    touches:
      - playbooks/make-plan.md
      - playbooks/policies/pr-steward.md
      - playbooks/policies/docs.md
      - playbooks/policies/profile.md
      - adapters/claude/commands/make-plan.md
    brief: |
      Read first: playbooks/make-plan.md, playbooks/policies/pr-steward.md (Branches table), playbooks/policies/docs.md,
      playbooks/policies/profile.md (the `docs.plan_dir` row, line ~34), adapters/claude/commands/make-plan.md.
      Design: sections 3.2 and 3.4 of the plan. The playbooks name levels only: never write a model name (`opus`, `sonnet`,
      `haiku`) in them (`tests/core/test_contracts.py`).
      1. `make-plan.md` intro (lines 3-15): the plan goes to the feature branch `feature_branch` at `<plan_dir>/<n>/plan.md` and
         is merged to `<main>` with the feature; delete the sentences saying a plan branch is never proposed for merge and that
         the last phase deletes the plan; the permission sentence names the feature branch instead of `plan/<slug>`.
      2. Replace section "1. The plan branch" with "1. The feature branch": slug as before; `<n>` is the tracking issue number (the
         slug when issue creation was refused); the manifest's `feature_branch` follows `<branch pattern>`; plan file
         `<plan_dir>/<n>/plan.md`. If the feature branch exists on origin: when `tld plan phase-status <plan file> --ref
         origin/<feature>` prints `"started": true`, stop and tell the human the plan is already running and a change needs a new
         plan; otherwise check it out and revise in place. If it does not exist: `git fetch origin <main> && git checkout -b
         <feature> origin/<main>`; after the plan is written commit and `git push -u origin <feature>`; if the push is refused,
         `github.branch_create` from `origin/<main>`'s SHA and push again; if still refused, stop.
      3. Section 2: the plan file path becomes `<plan_dir>/<n>/plan.md`; the file's first line under its title is `> Historical record
         once merged: read it only to understand why a change was made.`; the sentence in the last-phase paragraph that the retirement
         phase "deletes the plan document" and the index paragraph's "(the plan document is never indexed)" keep only the second; the
         `final_checks` first item becomes `tld plan deviations check --file <plan_dir>/<n>/deviations.md --plan
         <plan_dir>/<n>/plan.md --all exits 0`; add that `touches` never names the plan or its deviations file.
      4. Sizing: add the `worker_level: fast` bullet of section 3.4 (criteria verbatim) and the sentence that a phase sent back once
         reruns at `standard`; in Setup step 1 and section 0 step 2 the helper level for `run_helper(<question>, standard)` becomes:
         locate or enumerate -> `fast`, explain behaviour -> `standard`. Reviews keep "the reviewer level". The "Optional per phase"
         line mentions `worker_level: fast`. Small-scope final reply: add "(`fast` when every step is a literal edit)" to the
         start-level line.
      5. Section 4: the review also asks for "a `fast` phase that does not meet the fast bullet". The validation command becomes
         `tld plan validate-manifest <plan file> --profile .tld/toolkit.yaml --ref <feature branch>`.
      6. Section 5: every `plan/<slug>` becomes the feature branch; the plan URL form is
         `https://github.com/<owner>/<repo>/blob/<feature branch>/<plan_dir>/<n>/plan.md`; the "Never" line says "push to `<main>`
         or to any branch but the feature branch"; the Manual steps section's repository-docs link form uses `blob/<feature branch>/`.
      7. `policies/pr-steward.md` Branches table: delete the `plan` row; the feature row's "Made by" becomes `make-plan (with the plan),
         then implement`. `policies/profile.md`: the `docs.plan_dir` row says plans are `<plan_dir>/<n>/plan.md` and `deviations.md`.
      8. `policies/docs.md`: line 14 becomes "`docs/plans/` (`docs.plan_dir`): `<n>/plan.md` and `<n>/deviations.md` per change, kept as
         history, never indexed, never read by default; reviews are deleted when they land"; line 16's transient list adds them;
         Reading protocol rule 4 stays.
      9. `adapters/claude/commands/make-plan.md` description: replace "on its own plan/ branch" with "on its feature branch".
      Stop with `status=blocked` if another playbook or policy outside `touches` still instructs the old `plan/` flow and a contract
      test pins its text; name the file.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_docs_links.py -q passes
      - 'grep -n "plan/<slug>" playbooks/make-plan.md playbooks/policies/pr-steward.md prints nothing'
      - grep -n "worker_level: fast" playbooks/make-plan.md matches
      - grep -n "deviations check" playbooks/make-plan.md matches
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0

  - id: p9-implement-playbook
    title: "implement playbook: start commit with the pin, deviations log, level fallback"
    depends_on: [p1-manifest-rules, p2-plan-url, p4-deviations]
    complexity: M
    touches:
      - playbooks/implement.md
    brief: |
      Read first: playbooks/implement.md.
      Design: sections 3.2 (pin), 3.3 and 3.4 of the plan. No model name in the playbook.
      1. Section 0 step 1: `tld plan check-url <URL> --repo <owner>/<repo> --main <main> --plan-dir <plan_dir>`; it accepts the plan of
         this repository on `<main>` or on its feature branch; a `legacy` result (plan/<slug>) is still run, with the warning shown to
         the human. Step 3: validation is `tld plan validate-manifest <plan file> --profile .tld/toolkit.yaml --ref <ref>`.
      2. Section 0 step 4 and section 1. The feature branch normally exists already (make-plan made it) and holds the plan, so
         "exists on origin" no longer means "resumed". **A run is resumed only when `tld plan phase-status <plan file> --ref
         origin/<feature>` prints `"started": true`.** Otherwise the start ask is put and, once confirmed: check out `<feature>`, merge
         `origin/<main>` into it (merge commit), run `tld plan deviations init --plan <plan path> --out <deviations path>`
         (`<plan dir>/deviations.md` next to a `plan.md`; for a legacy plan `<dir of plan>/<slug>-deviations.md`), commit with the message
         `Start <plan slug>` and the trailer `Plan-Started: <plan slug> <blob>` (`<blob>` from `git rev-parse HEAD:<plan path>` taken
         before the commit), and push. A legacy `plan/<slug>` ref creates the feature branch from `<ref>` as before, then does the same
         commit. On a resumed run compare `git rev-parse origin/<feature>:<plan path>` with `plan_blob`; when they differ, stop and put the
         start ask again (the plan changed after the owner confirmed it); otherwise continue from section 2.
      3. Phase brief (section 3): rule 1 gains "never edit anything under `<plan dir>`"; rule 6's report adds a line `Deviations: <one line
         each, or "none">` right after the `PHASE-REPORT` line, required even when none. Retry, revision, conflict and follow-up workers of a
         phase whose level is `fast` start at the standard level; the orchestrator records a `level:` deviation.
      4. Section 4 Merge: step 2 also rejects a diff that touches `<plan dir>`. After step 6 (verify, unchanged text including the `git reset
         --hard HEAD~1` undo) add step 6a **Record deviations**: `tld plan deviations add` for the worker's `Deviations:` line, the
         orchestrator's own review findings, each scope-check path (`scope: <path>`), retries, conflicts, level changes, with `--none` when
         there is nothing; commit `Record deviations for <phase id>` and push together with the merge (step 7). The pushed-red path (revert)
         records a `retry:` entry the same way. State plainly that workers never write the file.
      5. Section 5 final review brief: the plan is read from `<ref>` as before; add "Read the deviations file; every deviation the diff shows
         and the file lacks is a blocking finding; it must pass `tld plan deviations check --file <deviations> --plan <plan file> --all
         --scope-results <results>`". The orchestrator fixes such a finding by adding the entry (`final:` under `Final review`).
      6. Section 6: step 1 runs `tld plan scope-check disposition` as before and then `tld plan deviations check ... --all --scope-results
         <results>` (exit 1 goes to the fix path of that step); the pull request body gets a `## Deviations` section with the file's content;
         step 6's last sentence about the plan branch becomes: the feature branch is the PR's head, and the plan and deviations stay in it.
         Nothing in the retirement-phase text deletes the plan.
      7. Ledger and status-record text: replace "plan branch" mentions; keep everything else.
      Stop with `status=blocked` if a flag you need (`--plan-dir`, `--ref`, `deviations`) is rejected by `tld plan <command> --help`; name it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py -q passes
      - grep -n "Plan-Started" playbooks/implement.md matches
      - grep -n "Deviations:" playbooks/implement.md matches
      - 'grep -n "plan/<slug>" playbooks/implement.md | grep -v -e legacy -e deprecated prints nothing'
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0

  - id: p10-evals
    title: "Eval fixtures follow the new plan location; refresh baseline hashes"
    depends_on: [p8-make-plan-playbook, p9-implement-playbook]
    complexity: S
    worker_level: fast
    touches:
      - evals/stubs/make-plan-large.json
      - evals/stubs/implement-invalid-manifest.json
      - evals/fixtures/commands.py
      - evals/tasks/implement-invalid-manifest/task.yaml
      - evals/harness/graders.py
      - tests/core/test_evals_fixtures.py
      - evals/baselines/default.json
    brief: |
      Read first: evals/fixtures/commands.py (lines 8-30 and 80-95), evals/stubs/make-plan-large.json, evals/harness/graders.py (line ~51).
      The fixtures use `plan_dir: docs/`, so the new plan path is `docs/1/plan.md`. Literal edits, in this order:
      1. `evals/fixtures/commands.py`: `PLAN_PATH = "docs/tags-plan.md"` becomes `PLAN_PATH = "docs/1/plan.md"`;
         `PLAN_URL = f"https://github.com/{REPO}/blob/plan/tags/{PLAN_PATH}"` becomes `PLAN_URL = f"https://github.com/{REPO}/blob/feature/tags/{PLAN_PATH}"`;
         `git("checkout", "-q", "-b", "plan/tags", cwd=dest)` becomes `git("checkout", "-q", "-b", "feature/tags", cwd=dest)`; in the module
         docstring (line ~11) "a plan on `plan/tags`" becomes "a plan on `feature/tags`", and, if the same sentence says implement stops "before it
         creates the feature branch", it says "before it starts a worker".
      2. `evals/tasks/implement-invalid-manifest/task.yaml`: replace `blob/plan/tags/docs/tags-plan.md` with `blob/feature/tags/docs/1/plan.md`, and
         "before it creates or pushes the feature branch" (line 2) with "before it starts a worker".
      3. `evals/stubs/implement-invalid-manifest.json`: replace each `plan/tags` with `feature/tags` and each `docs/tags-plan.md` with `docs/1/plan.md`
         (find them with `grep -n "plan/tags\|tags-plan" <file>`).
      4. `evals/stubs/make-plan-large.json`: `"branch": "plan/tags"` -> `"branch": "feature/tags"`; `"Plan on plan/tags."` -> `"Plan on feature/tags."`; the key
         `"docs/tags-plan.md"` -> `"docs/1/plan.md"`; in the two `actions` commands `plan/tags` -> `feature/tags`.
      5. `evals/harness/graders.py` line ~51: `ctx.docs("*-plan.md")` becomes `[*ctx.docs("*-plan.md"), *ctx.docs("*/plan.md")]`.
      6. `tests/core/test_evals_fixtures.py` line ~122: `plan/tags:{commands.PLAN_PATH}` becomes `feature/tags:{commands.PLAN_PATH}`.
      7. Run `python3 evals/run.py run --agent stub --repeats 1 --require-pass`, then `python3 evals/run.py baseline --refresh-hashes`. Your final commit message
         contains the sentence `Refresh eval hashes: the playbooks changed; a real re-run of the model tasks is left to the owner (ma2).`
      Stop with `status=blocked` if the stub run or `.venv/bin/python -m pytest tests/core/test_evals_fixtures.py tests/core/test_evals_graders.py -q` fails for a
      reason other than the strings above; name the file and the grader.
    acceptance:
      - python3 evals/run.py run --agent stub --repeats 1 --require-pass passes
      - python3 evals/run.py check-baseline exits 0
      - .venv/bin/python -m pytest tests/core/test_evals_fixtures.py tests/core/test_evals_graders.py tests/core/test_evals_baseline.py -q passes
      - 'grep -rn "plan/tags\|tags-plan" evals tests/core/test_evals_fixtures.py prints nothing'

  - id: p11-docs-reference
    title: "Reference docs, profile template and changelog"
    depends_on: [p7-model-check-register, p10-evals]
    complexity: M
    touches:
      - docs/reference/cli.md
      - docs/reference/profile-reference.md
      - docs/guides/docs-index.md
      - docs/README.md
      - src/tld/templates/toolkit.yaml
      - CHANGELOG.md
    brief: |
      Read first: docs/reference/cli.md (lines 30-36), docs/reference/profile-reference.md (lines 30-50 and 185-200 and the `hooks` section),
      docs/guides/docs-index.md (line ~22), docs/README.md (line 4), src/tld/templates/toolkit.yaml (line ~15), CHANGELOG.md (the
      `## [Unreleased]` block), and plan section 3.
      One fact lives in one doc; the others link to it.
      1. `cli.md`: the `check-url` row (`--plan-dir`; `plan/*` deprecated), the `validate-manifest` row (`--ref`), a new row `tld plan deviations
         init | add | check` (module `tld.plan.deviations`).
      2. `profile-reference.md`: every statement about plans at `<plan_dir>/<slug>-plan.md` or `plan/<slug>` (find them with `grep -n
         "plan/<slug>\|-plan.md\|plan branch" <file>`; lines ~36, ~47, ~193) says `<plan_dir>/<n>/plan.md` on the feature branch; the `hooks.disable`
         list gains `model-check`.
      3. `docs/guides/docs-index.md` line ~22 and `docs/README.md` line 4: plans (`<n>/plan.md`) and `deviations.md` are kept history, transient and not listed.
      4. `src/tld/templates/toolkit.yaml` line ~15: the comment on `plan_dir` says plans live at `<plan_dir>/<n>/plan.md`.
      5. `CHANGELOG.md` under `## [Unreleased]`: in `### Added` two bullets (the orchestrator-owned `deviations.md` and `tld plan deviations`; the
         `model-check` hook with `hooks.disable: [model-check]`). Create a `### Changed` heading after `### Added` if it does not exist, with bullets:
         plans now live on the feature branch at `docs/plans/<issue>/plan.md` and stay after the merge (`plan/<slug>` plans are deprecated for one
         release); `/make-plan` assigns the `fast` worker level to literal phases and `validate-manifest` requires complexity S for it. No version heading.
      Stop with `status=blocked` if a statement cannot be matched to the code that earlier phases merged; name the statement.
    acceptance:
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - .venv/bin/python -m pytest tests/core/test_docs_links.py tests/core/test_docs_index.py tests/core/test_contracts.py -q passes
      - grep -n "deviations" docs/reference/cli.md matches
      - '.venv/bin/python launcher/tld profile validate src/tld/templates/toolkit.yaml --no-file-checks exits 0'

  - id: p12-retire
    title: "Architecture docs and retirement of this plan"
    depends_on: [p11-docs-reference]
    complexity: M
    touches:
      - docs/architecture/design.md
      - docs/architecture/hooks-parsing.md
      - docs/architecture/evals.md
      - docs/guides/review.md
      - README.md
      - docs/plans/plans-on-feature-branch-plan.md
    brief: |
      Read first: docs/architecture/design.md (lines 70-80 and 108-115), docs/architecture/hooks-parsing.md (lines 54-58 and 70-80),
      docs/architecture/evals.md (lines ~204 and ~269), docs/guides/review.md (line ~14), README.md (lines ~51 and ~74), and plan section 3.
      1. `design.md` lines ~75-78: `/implement` runs plans from `main` or from the plan's own feature branch (`<plan_dir>/<n>/plan.md`, pinned by the
         `Plan-Started` trailer), the S14 text adjusted; one sentence under the rejected SessionStart alternative that the model-check session-start hook
         only records the session's model and installs or fetches nothing; a short paragraph on the orchestrator-owned `deviations.md` and one on the
         `fast` worker level.
      2. `hooks-parsing.md` lines ~56 and ~75-76: `git checkout -b plan/<slug> origin/<main>` becomes `git checkout -b <feature> origin/<main>`, and "any branch but
         `plan/<slug>`" becomes "any branch but the feature branch". `evals.md` lines ~204 and ~269: the `plan/tags` and `tags-plan.md` mentions follow the
         new fixture (`feature/tags`, `docs/1/plan.md`). `review.md` line ~14: the diagram's `plan/<slug>` becomes `feature branch`.
      3. `README.md` line ~51: "on a `plan/<slug>` branch" becomes "on its feature branch"; line ~74 (the list of hooks) gains `model-check`.
      4. Delete `docs/plans/plans-on-feature-branch-plan.md` (`git rm`), then run `.venv/bin/python launcher/tld ops docs-index check --profile
         .tld/toolkit.yaml` until it exits 0. Report no `docs-changed:` line (no doc is added or moved by this plan).
      Stop with `status=blocked` if a statement cannot be matched to the code that earlier phases merged; name the statement.
    acceptance:
      - .venv/bin/python launcher/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - .venv/bin/python -m pytest tests/core/test_docs_links.py tests/core/test_docs_index.py tests/core/test_contracts.py -q passes
      - 'grep -rn "plan/<slug>" docs/architecture/hooks-parsing.md docs/guides/review.md README.md prints nothing'
      - test ! -e docs/plans/plans-on-feature-branch-plan.md succeeds
```
