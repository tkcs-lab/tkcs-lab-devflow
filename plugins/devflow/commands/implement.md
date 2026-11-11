---
description: Orchestrate a plan document with an implementation manifest — one child session per phase, merged into one feature branch, one PR to the main branch
argument-hint: "<GitHub URL of the plan file: https://github.com/<owner>/<repo>/blob/<ref>/<path>>"
model: sonnet
---

You are the **orchestrator** for the plan at:

$ARGUMENTS

You do not implement phases yourself. You start one child session per phase, merge each finished
phase into one feature branch, verify the merge, have one Opus session review the whole result,
and at the end open **one** pull request from that feature branch to `<main>` and drive it to green.
The user started you with this command. That is their explicit permission to create and push the
feature branch named in the manifest, and to push merge commits to it. It is not permission to
push anywhere else.

Plans for this command are written by `/make-plan`, which also defines the manifest's fields. Hand-written plans work too, as long as they have a manifest.

## Profile

This command is project-independent; everything specific to the repository comes from its
profile, `.claude/toolkit.yaml`. Before anything else, load the `project-profile` skill and follow
its "Loading the profile" section. If it reports an error, show the message verbatim and stop; never
substitute a value of your own for a missing key.
Skill names: the toolkit's skills carry a plugin prefix (`devflow:project-profile`,
`devflow:pr-steward`, `stack-python:stack-python`). Use whichever form the skill list shows. In this file:

- `<main>` is `git.main_branch`; `<branch pattern>` is `git.branch_pattern`.
- "the must-read docs" are the files in `docs.must_read`.
- "the docs index" is `docs.index`; "index parts" apply only when the profile has it.
- "the fast checks" are the commands in `verify.fast`.
- "the project's steward file" is `project_steward`, when the profile has one.
- "the stack skills" are the `stack-<name>` skills for each name in `stacks`; load them now.
- "the agent rules" are the profile's agents section, read through the `agent-dispatch` skill.

**Identity.** When the profile has `git.bot_login`, call `get_me` now. If its login differs, stop
with exactly `get_me returned <login> but git.bot_login is <bot_login>: connect the second GitHub
account at claude.ai/connect-github and start a new session.`

**Models.** This command runs on Sonnet (the `model:` line above). That covers the turn the user
starts it in; later turns (check-ins, wakes) run on the session's own model, so for a Sonnet
orchestrator throughout, start the session on Sonnet. The plan was sized for Sonnet workers by an
Opus planner, so judgement calls should be rare; when one comes up that the plan does not settle,
ask the user rather than deciding it. The orchestrator never runs an agent that has edit tools; it
only computes who is required and checks the reports.

| Session | `create_session` `model` |
|---|---|
| Phase worker, fix session, conflict session | the profile's `models.worker` (default `sonnet`), or `opus` when the phase has `worker_model: opus` |
| Final review (section 5) | the profile's `models.reviewer` (default `opus`) |

The aliases map to ids: `sonnet` is `claude-sonnet-5-5` and `opus` is `claude-opus-5-5`.

If `create_session` rejects a model id, use the newest Sonnet or Opus id your system prompt lists,
and say which one in the ledger.

**Guardrail hooks.** The plugin's `dod-gate` hook (off unless the profile turns it on, see `docs/hooks.md` in the claude-toolkit repo) is meant for sessions that change code and stop when they are done. This command is the orchestrator: it stops at `human_gate` phases and when it halts with a one-line error, and it writes no code itself. Its child phase sessions are not marked, so the gate applies to them. Mark this session exempt once, right after the profile is loaded: `python3 "<devflow root>/hooks/dod_gate.py" --exempt` (it writes a marker under the checkout's git directory and prints one line; a failure does not stop the run).

## 0. Load the plan

1. Parse the URL as `https://github.com/<owner>/<repo>/blob/<ref>/<path>`, then
   `git fetch origin <ref>` and read the file with `git show FETCH_HEAD:<path>`. Read it all.
2. Find the fenced ` ```yaml ` block under the plan's `## Implementation manifest` heading and
   parse it. If there is no manifest, stop and tell the user: this command only runs plans that
   have one. Do not invent phases from prose.
3. Validate the manifest before starting anything: save the plan file to a temporary path and run
   `python3 <devflow root>/scripts/validate_manifest.py <file> --profile .claude/toolkit.yaml`
   (the `project-profile` skill says where `<devflow root>` is). It checks that every `depends_on`
   names an existing phase id, that the graph has no cycles, that every phase has `brief` and
   `acceptance`, that `complexity`, when present, is `S` or `M`, that a `worker_model: opus` phase
   has a `worker_model_reason`, and that two phases that could run at the same time (neither
   reaches the other through `depends_on`) share no path in `touches`. Report any error and stop.
   An older manifest's `manual:` list means the same as `manual_after:`.
4. **Manual steps before anything starts.** If `manual_before` is non-empty, the ledger does not
   already record the user's confirmation, and the feature branch does not exist on origin yet (it
   is only created after this confirmation, so its existence means a resumed run), stop here. Send the user the `manual_steps_artifact`
   link and the `manual_before` items (title and `done_when`), and ask one question: are these
   done? Do not create the feature branch, start any session or arm a check-in while you wait; the
   reply wakes you. Where a `done_when` is something you can check from here (an environment
   variable is set, a host is reachable), check it after they answer and say what you found.
   Record the confirmation in the ledger, then continue.

## 1. The feature branch

- `feature_branch` comes from the manifest (it must follow `<branch pattern>`).
- **If it does not exist on origin yet:** create it from `<ref>` (the plan's own branch, so the plan
  and this command travel with it), then merge `origin/<main>` into it (a merge commit, not a rebase)
  and push. Try `git push -u origin <feature_branch>` first. If the git proxy refuses the push
  (403, or "not allowed"), create the branch with the GitHub MCP `create_branch` tool from
  `<ref>`'s SHA, then retry the push. If the push is still refused, stop and tell the user in one
  line. Do not quietly fall back to your own session branch, because child sessions would then
  merge somewhere the user did not choose.
- **If it already exists:** this is a resumed run. Check it out and continue from "Scheduling" below. A phase is
  done if the feature branch's history holds a merge commit whose message carries the trailer
  `Plan-Phase: <plan slug>/<phase id>` (`git log --grep`). Do not re-run done phases.

## 2. Scheduling

Keep an orchestration ledger as a comment on a GitHub issue if the manifest names `tracking_issue`.
Otherwise keep it in your own replies: for each phase record its state (`pending` / `running` /
`merged` / `failed`), its session id, and its branch. Update the ledger on every state change.

If the manifest names `tracking_issue`, also post these event comments on that issue, one comment
each, short and with exactly these texts (a failed comment is noted once and the run continues):

- `Implementation started on <feature_branch>.` after the `manual_before` confirmation and the
  branch push.
- `Phase <phase id> merged.` after each Merge (section 4, step 6).
- `Waiting for you: <needs_you_reason>.` each time `needs_you` goes from false to true.
- `Phase <phase id> failed after retry: <short cause>.` when a phase fails after its retry.
- `Final review: approve.` or `Final review: changes (<n> blocking).` when a final review ends.
- `PR opened: <url>.` after the pull request is opened.

Every post ends with the attribution footer the session rules require; the exact text comes before
it. Without `tracking_issue` none of this happens: no event comments and no `Closes` lines.

A phase is **ready** when every phase in its `depends_on` is `merged`, and, if any of those
phases is marked `human_gate: true`, the user has approved it (see "Merge" step 7 below). Start every ready phase at
once, up to `max_parallel` (manifest, default 2). Phases in the same wave touch different files by
design. If a merge conflicts anyway, "Waiting, collecting and merging" below handles it.

## 3. Starting a phase session

Phase branch: `<feature_branch>--<phase id>` (for example `feature/org-mode-mobile--p2-settings`).
Before starting, record the feature branch's current SHA as the phase's base.

Call `create_session` with:

- `source_url`: the repository's git URL
- `source_revision`: `<feature_branch>` (so the child sees every phase already merged)
- `outcome_branch`: the phase branch
- `title`: `<plan slug> <phase id>: <phase title>`
- `model`: the worker model from the table at the top
- `permission_mode`: omit it, so the child inherits yours. Never `plan`, because nobody is watching
  a child to approve a plan.
- `prompt`: the **child brief** below, filled in.

Index parts: for the retirement phase (the phase whose brief deletes the plan document) append to the brief `Docs changed by earlier phases: <the ledger list Docs changed>; update the docs index for each.`

> You are implementing **one phase** of a multi-phase plan. An orchestrator session will merge your
> branch; you do not open a pull request, and you do not push to any branch except
> `<phase branch>`.
>
> Plan: `<path>` in this checkout. Read it in full first; it has the context, constraints and
> measurements this brief does not repeat. Your phase is `<phase id>`, "<phase title>". Its entry
> in the plan's `## Implementation manifest` is authoritative. Here it is verbatim:
>
> ```yaml
> <the phase's manifest entry>
> ```
>
> Rules:
> 1. Stay inside this phase's `brief`, and inside its `touches` list if it has one. If you find
>    work that belongs to another phase, note it in your final report; do not do it. If the brief
>    turns out to be wrong or impossible, or leaves a decision open that the plan's Design section
>    does not settle, stop and say so in your final report instead of improvising a different
>    design. Never do anything the plan lists under `manual_before` or `manual_after`; if a step
>    needs something from the user, stop with `status=blocked` and say what.
> 2. Follow <the must-read docs, as a list of paths>, <the project's steward file, if any>, and the
>    `pr-steward` skill. <Index parts: Read the docs your brief's `Read first:` line names; open the docs index `<docs.index>` only if they are not enough, and read no other doc. Do not edit the index or `CLAUDE.md` unless your phase is the retirement phase. If you add, move or delete a doc, put one line `docs-changed: <added|moved|deleted> <path>` per doc in your report.> <If the profile has `docs.changelog`: Add user-visible changes under
>    `<docs.changelog.file>`'s `<docs.changelog.section>`. Never add a version heading.>
> 3. <If the profile has stacks: also follow the `stack-<name>` skills.> Before your last push, run `/dod`. Every blocking row must pass. Also check every item in
>    your phase's `acceptance` list, and say how you checked each one.
> 3b. **Required agents.** Write the names of the files you changed
>    (`git diff --name-only origin/<feature_branch>...HEAD`) to a temporary file, run
>    `python3 <devflow root>/scripts/agents.py required --profile .claude/toolkit.yaml --at implement_phase --changed <that file>`,
>    and dispatch every agent it lists as the `agent-dispatch` skill says, before your last push: the
>    four edit agents (tech-writer, website-maintainer, debugger, refactorer) in edit mode, every
>    other agent in review mode. Fix every blocking finding yourself and dispatch that agent again;
>    its new report line is the one that counts. Print each agent's `AGENT-REPORT` line bare into
>    your PHASE-REPORT after the `/dod` table. Save the JSON and the report text and run
>    `agents.py verify --required <json> --report <text>`; it must exit 0.
> 4. Your final commit message ends with the trailer `Plan-Phase: <plan slug>/<phase id>`.
> 5. End your last turn with a report in exactly this shape, which the orchestrator reads:
>    `PHASE-REPORT <phase id> status=<done|blocked> head=<sha>` on its own line, then the `/dod`
>    table, the `AGENT-REPORT` lines (they follow the `/dod` table), the acceptance checklist, and
>    any out-of-scope findings.
> 6. After the final `PHASE-REPORT` line, call `send_message` with `session_id: "@parent"` and
>    exactly the text `PHASE-REPORT <phase id> status=<done|blocked> head=<sha>` (the same first
>    line). It only tells the orchestrator to look; the report stays the authority.

## 4. Waiting, collecting and merging

The orchestrator is woken by a child's doorbell message (rule 6 of the brief, sent to `@parent`), by a
`<child-session-event>`, or by a safety-net timer. On a doorbell it ignores a message whose sender
is not one of its recorded child sessions; otherwise it reads that child with `get_session` and
continues exactly as for a check-in. Never poll with `sleep`; between wakes, end your turn.
Safety-net timers: while any child, fix, conflict or review session is running, arm one
`send_later`, **15 minutes** from now when a running phase has complexity `S`, otherwise
**30 minutes** (a running `M` phase, a phase without `complexity`, a final-review, fix or conflict
session); with several running, the shortest applies. After every wake cancel the armed timer
(`delete_trigger` with the id `send_later` returned) and re-arm the same way for what is still
running. When a timer wake finds a finished phase whose doorbell never arrived, the ledger line
says `no doorbell` and the orchestrator uses **5 minutes** for the rest of the run (the doorbell is
not reaching it). A `<child-session-event>` wake (a failed turn or a restarted worker) is handled
immediately.

On each check-in, for each `running` phase, call `get_session`:

- `status_bucket` `working`: leave it alone.
- `blocked` or `review_ready`/`completed`: read its last report. Find the `PHASE-REPORT` line.
  - `status=done`: go to **merge** below.
  - `status=blocked`, or no report: read why. If the fix is small and clearly inside the phase,
    send the child a steering message (`send_message`, if you have it) or start a follow-up
    session on the same phase branch with the specific instruction. Otherwise mark the phase
    `failed` and **ask the user**, quoting the child's reason, and post `Phase <phase id> failed
    after retry: <short cause>.` and `Waiting for you: <needs_you_reason>.` on the tracking issue
    (if any). Do not start dependent phases.
- `failed`: start one retry session on the same phase branch, with a brief that says what the
  first attempt got to (read the branch). If a second session also fails, mark the phase `failed`
  and ask the user, and post `Phase <phase id> failed after retry: <short cause>.` on the
  tracking issue (if any), followed by `Waiting for you: <needs_you_reason>.`

**Merge** (one phase at a time, even when several finish together):

1. `git fetch origin <phase branch> <feature_branch>`. The phase branch head must equal the
   reported `head=` SHA, and its tip commit must carry the `Plan-Phase` trailer. Otherwise it is not
   done.
2. Review the diff against the phase's recorded base (`git diff <base>...origin/<phase branch>`)
   adversarially: is it inside the brief, does it change paths outside its `touches` (a small,
   explained addition such as a shared test fixture is fine; anything else goes back), does it
   touch files other phases own, has it disabled or
   skipped a test, has it deleted an `xfail` that belongs to a different phase? Anything wrong
   goes back to the child, as above.
2b. **Required agents.** Save the names of the files in `git diff --name-only <base>...origin/<phase branch>`
   to a file, run `python3 <devflow root>/scripts/agents.py required --profile .claude/toolkit.yaml --at implement_phase --changed <file>`
   (save its JSON) and `agents.py verify --required <json> --report <the child's PHASE-REPORT text>`.
   Exit 1 goes back to the child like any other defect, with the output of `verify` as the
   instruction.
3. **Scope check (monitoring only, never a gate).** Before the merge, with `<feature_branch>` checked
   out, run (the plan file is the one saved in section 0; save it again if the session restarted;
   `<results>` is `scope-results.json` in your scratchpad directory):

   ```
   python3 <devflow root>/scripts/scope_check.py check --plan <plan file> --phase <phase id> \
     --base <feature_branch> --head origin/<phase branch> --profile .claude/toolkit.yaml \
     --plan-slug <plan slug> --feature <feature_branch> --results <results>
   ```

   It compares the files the phase branch changed since its merge base with `<feature_branch>` against
   the phase's `touches` (renames count as the old path deleted and the new path added), with the same
   glob matching as `validate_manifest.py`. A path no `touches` entry of this phase names, and that no
   scope ignore glob names, is **out of scope**; it is a **collision** when another phase's `touches`
   names it. The changelog file (`docs.changelog.file`) is always ignored, because the worker brief
   demands that line from every phase. It reads paths only, never file contents, diffs or commit
   messages, and it always exits 0: when the check itself fails it records `unavailable` with a short
   reason. A phase whose `Plan-Phase` trailer is already in the feature branch (a resumed run) is
   reported `skipped` and not checked again. For a fix session or a `-rev<n>` session pass the original
   phase's id as `--phase` and the session's own name as `--label` (`fix-<n>`, `<phase id>-rev<n>`);
   with a label that differs from the phase id the check always runs, and is never reported `skipped`.

   The result is **never a reason to hold the merge back**: carry on with step 4 whatever it says. Add
   one line to the ledger (`<phase id>: scope n out of scope, m collisions`, or `scope check
   unavailable`, or `scope none`). Out-of-scope paths are not a hard stop either: the guardrail hooks
   own the hard-stop list (workflow files, secrets, protected paths), and this command does not repeat
   it. Step 2's adversarial review stays as it is.
4. `git checkout <feature_branch> && git merge --no-ff origin/<phase branch>` with the message
   `Merge <plan slug> <phase id>: <title>` and the trailer `Plan-Phase: <plan slug>/<phase id>`.
   - **Conflict:** resolve it yourself only when it is mechanical (both sides added to the same
     list, or adjacent edits). Regenerate lockfiles and generated files with the repo's tools
     (the must-read docs say which), never by hand-editing. If a conflict is
     semantic, abort the merge and start a short session on the phase branch whose brief is "merge
     `<feature_branch>` into this branch and resolve the conflict"; then merge again.
5. Verify **after the merge**, on the feature branch: the fast checks, then the manifest's
   `verify_after_merge` commands. An entry of the form `dispatch <workflow>` is not a shell
   command: dispatch that workflow against the feature branch (GitHub MCP `actions_run_trigger`),
   wait for the run, and treat a red run like any other failed check. If anything is red, `git merge --abort` is no longer possible, so revert the merge commit
   (`git revert -m 1`), push, send the failure back to the phase, and mark the phase `running`
   again.
6. Push the feature branch. Add `agents ok` (or the failing agents) to the phase's ledger line. Mark the phase `merged`, post the comment `Phase <phase id> merged.`
   on the tracking issue (if any), and
   `archive_session` the child. If the manifest has `screenshots_after_merge`, run it and send the
   user the images (`SendUserFile`) with a one-line caption naming the phase, so they can watch
   the result take shape and object early.
   Append the phase branch to the ledger list `Branches left on origin`. Collect each `docs-changed:` line of the report into the ledger list `Docs changed`.
7. **Human gate.** If the phase is marked `human_gate: true`, stop scheduling. Send the user the
   phase's review material (its screenshots and its `PHASE-REPORT`), and ask one question:
   approve, or change what. Do not arm a check-in while you wait for their answer; the reply
   wakes you. On approval, record it in the ledger and continue. On requested changes, start a
   follow-up session on a fresh `<feature_branch>--<phase id>-rev<n>` branch cut from the
   feature branch, whose brief is the user's feedback verbatim plus the phase's original brief.
   Merge it the same way, and gate again.
8. Start any phases that just became ready.

## 5. Final review (Opus)

When every phase is `merged`, merge `origin/<main>` into the feature branch once more, push, and
start one review session with `create_session`: `source_revision` the feature branch, no
`outcome_branch`, `model` the review model from the table at the top, title
`<plan slug> final review`, and this prompt, filled in:

> You are the final reviewer for a plan that Sonnet sessions implemented phase by phase. You do not
> change code and you push nothing. Read the plan (`<path>` at `<ref>` — `git fetch origin <ref>`,
> then `git show FETCH_HEAD:<path>`, since the retirement phase has deleted it from this branch),
> <the must-read docs, as a list of paths>. Then review
> `git diff origin/<main>...HEAD` against the plan's Design section and each phase's `acceptance`:
> behaviour that differs from the design, a design decision a worker made that the plan did not,
> seams between phases (a function one phase added and another calls wrongly, duplicated
> helpers, inconsistent names or strings), missing tests for an acceptance item, a weakened or
> skipped test, a security or privacy regression, docs that describe something other than what
> the code does, and every `final_checks` item. Index parts: run `docs_index.py check --profile .claude/toolkit.yaml`; every doc the diff adds, moves or deletes has its index row; `CLAUDE.md` is still at most 60 lines and only points to the index. Run <the fast checks, as a list of commands>
> yourself. Load the `review-checklist` and `secure-code-review` skills and apply them.
>
> Run `python3 <devflow root>/scripts/agents.py required --profile .claude/toolkit.yaml --at implement_final --changed <the files of git diff --name-only origin/<main>...HEAD>`
> and dispatch every agent it lists in review mode as the `agent-dispatch` skill says. Put their
> `AGENT-REPORT` lines before the `REVIEW-REPORT` line. A blocking finding of an agent whose item is
> blocking is a blocking finding of yours. Run `agents.py verify`; if it exits 1 your verdict is
> `changes`.
>
> End with `REVIEW-REPORT verdict=<approve|changes>` on its own line, then one numbered finding per
> line: `blocking|non-blocking`, `path:line`, the phase id it belongs to, and what is wrong and what
> the fix is. `changes` means at least one finding is blocking. Only something you would refuse to
> merge is blocking.

Wait for it with check-ins as in section 4. After reading the report, first run
`python3 <devflow root>/scripts/agents.py required --profile .claude/toolkit.yaml --at implement_final --changed <the files of git diff --name-only origin/<main>...HEAD>`
yourself, save the JSON, and run `agents.py verify --required <json> --report <the review text>`; exit 1
counts as `changes`, and the findings go to a fix session as for any blocking finding. Then:

- `approve`: post `Final review: approve.` on the tracking issue (if any) and go to Finishing.
- `changes`: post `Final review: changes (<n> blocking).` on the tracking issue (if any), then group the blocking findings by phase and start one Sonnet fix session per group on a
  `<feature_branch>--fix-<n>` branch, whose brief is the findings verbatim plus the phase's
  original entry. Merge each exactly as a phase (section 4's **Merge**, trailer
  `Plan-Phase: <plan slug>/fix-<n>`). Then start one more review session with the same prompt plus
  "Earlier review findings: <list>; confirm each is fixed and review only the diff since
  `<sha>`". If that second review still says `changes`, post `Final review: changes (<n> blocking).`
  and `Waiting for you: <needs_you_reason>.` on the tracking issue (if any), stop and ask the user,
  quoting the findings.

`archive_session` each review session once you have read its report. Non-blocking findings go into
the PR body.

## 6. Finishing

1. Run the full `/dod` on the feature branch. Index parts: also run `python3 <devflow root>/scripts/docs_index.py check --profile .claude/toolkit.yaml`; an error goes to a fix session like any failed check. Then settle what became of each scope drift:
   `scope_check.py disposition --results <results> --base origin/<main> --head <feature_branch>` marks each recorded
   out-of-scope path **accepted** while it is still in the feature branch's final diff against
   `<main>` (`git diff --name-only origin/<main>...HEAD`), and a phase **reverted** (or
   **partly reverted**) when a later commit removed all (or some) of them. It changes only the results
   file, and a failure leaves them as they were.
2. Check the manifest's `final_checks` (for example: no expected-failure marker left that this plan
   added, and the plan document is deleted, with its decisions extracted into ADRs when the
   profile has `docs.adr_dir`).
3. Open **one** pull request from the feature branch to `<main>`, following the PR template if the
   repo has one. The body begins with one line `Closes #<tracking_issue>` and one more `Closes #<n>` line for each entry
   of the manifest's `closes`, before the phase list (no such lines without `tracking_issue`). It lists each phase with its merge commit, the combined acceptance
   checklist, the final review's verdict and its non-blocking findings, every out-of-scope
   finding the children reported, a **Scope** section (the output of
   `scope_check.py section --results <results>`, pasted as is: per phase the out-of-scope paths and collisions or `none`, at most 20
   paths each, then `and n more`; paths only), and a **Manual verification** section: each `manual_after`
   item as an unchecked box, with the `manual_steps_artifact` link.
   After opening it, post `PR opened: <url>.` on the tracking issue (if any).
   The body also has a section `## Branches left on origin` listing that ledger list, and the
   sentence "The owner deletes them in the GitHub UI."
   When the profile has `git.codeowners`, request a review from every login in it (GitHub MCP
   `update_pull_request` with `reviewers`) and set `needs_you` true with the reason `Review PR #<n>`.
   Never re-request for the same pushed head, and never approve, merge or enable auto-merge. If the
   tool cannot request a reviewer, still set `needs_you` (`Review PR #<n>`) and ask the user to
   request the review.
4. Subscribe to the PR and drive it to green as the `pr-steward` skill says (and the project's
   steward file, if any). You own this PR. A failure goes to a new phase-style session on a `<feature_branch>--fix-<n>` branch,
   merged the same way, or you fix it yourself when it is small.
5. Tell the user the PR link, the artifact link with the `manual_after` steps they now need to do,
   and anything a child or the reviewer flagged. The plan branch (`plan/<slug>`) can be deleted
   once the PR merges.

Never: push to `<main>`; approve or merge the PR yourself, or enable auto-merge on it; rebase or force-push the feature branch; run a phase's
work in your own session to "save time"; skip a phase whose dependency failed; do a `manual_*` step
on the user's behalf.

## Status board

Follow the `status-board` skill (whichever form the skill list shows) for where and how to write; a
board error never stops the run. `/implement` writes a record as follows.

- The first record (status `starting`) is written before any child session starts. After that, write at
  every ledger change and at every check-in.
- Fields: `kind` is `"run"` and `command` is `null`; `plan_slug`, `plan_url`, `feature_branch` come from
  the plan and `orchestrator_session` is this session; `phases` mirrors the ledger, with the states
  `pending`, `running`, `merged`, `failed` and `gate`.
- `status` follows the field rules of brief section 4 (`starting`, `running`, `waiting_user`,
  `reviewing`, `pr_open`, `done`, `failed`); `needs_you` is true exactly when you have asked the owner
  something or stopped on a failure, with a one-line reason.
- Each phase item gets the optional field `scope` at its Merge (step 3 of section 4):
  `scope_check.py record --results <results> --label <phase id>` prints it; paste that object as is. It
  is `check`, `in_scope`, `out_of_scope_count`, `collision_count`, `paths` (at most 20) and
  `disposition`; `check: unavailable` when the check failed, and no `scope` field when it printed
  `null` (skipped on a resumed run). After the dispositions are settled (Finishing, step 1) write the
  field again. It holds counts and paths only: never file contents, diffs or commit messages. The board
  record is overwritten, so the durable history is the pull request's **Scope** section, and a fix or
  `-rev` session's drift appears there under its own label only.
- `pr` is filled when the pull request is opened and kept current afterwards.
- `next_check_at` equals the time of the timer you have armed, or `null` when none is armed.
- `updated_at` is set on every write.

When `needs_you` changes, follow the `## Alerts` section of the `status-board` skill (rename the session, push once, rename back).

`/implement` sets `needs_you` true at these moments, with these reasons:

- the `manual_before` question: `Confirm manual steps`
- a `human_gate`: `Approve <phase id>`
- a phase failed after its retry: `Fix <phase id>`
- a second `changes` review: `Resolve review findings`
- a PR waiting for the code owner: `Review PR #<n>`
