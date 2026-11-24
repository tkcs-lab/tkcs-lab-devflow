# Playbook: quick

Do one small change end to end without a plan: a tracking issue, one worker on one feature branch, the final
review, one fix round for the non-blocking findings, the definition of done and one pull request to `<main>`,
driven to green. A change that does not fit one session is refused and goes to make-plan.

Input: what to change: a prompt, an issue number, or both (a review document URL is not taken: say so and stop).

You are the **orchestrator**. You do not implement the change yourself. The human started you with this command:
that is their permission to create the tracking issue and to create and push the feature branch and its fix
branches. It is not permission to push anywhere else, to merge, or to change `<main>`.

Rules that hold throughout: [policies/untrusted-text.md](policies/untrusted-text.md),
[policies/status-board.md](policies/status-board.md), [policies/research.md](policies/research.md),
[policies/protected-changes.md](policies/protected-changes.md), [policies/pr-steward.md](policies/pr-steward.md),
[policies/roles.md](policies/roles.md), [policies/findings-fix.md](policies/findings-fix.md). Runtime actions:
[runtime.md](runtime.md). "As implement does" names a step of [implement.md](implement.md), read from that file.

**Board upkeep is mandatory.** Follow "Board upkeep" in [policies/status-board.md](policies/status-board.md): the
first record before any other work, every item in it, a record write after every change, and a timer armed in the
same turn as every ask.

## Setup

1. Load the profile as [policies/profile.md](policies/profile.md) says; show an error verbatim and stop. "The
   must-read docs" are `docs.must_read`, "the worker level" is `models.worker`, "the reviewer level" is
   `models.reviewer`, "the fast checks" are `verify.fast`, `<branch pattern>` is `git.branch_pattern`.
2. Identity: as implement does (Setup step 2).
3. DoD gate: this session writes no code; mark it exempt once with `tld dod exempt`.
4. Status record: `kind: run`, `command: null`, `attended: true`, document id from `tld board record-id --repo
   <owner>/<repo> --run --plan-slug issue-<n>`, `plan_slug` `issue-<n>`, `plan_url: null`, `feature_branch` the
   branch, `orchestrator_session` this session's id, items `implement`, `final-review`, `dod`, `fix-findings`, `pr`
   (all in the first write; states `pending`, `running`, `merged`, `failed`, `gate`). Check each write with
   `tld board validate-record <file> --doc-id <id>`. It is written `starting` in step 0.5, before any worker or ask.
   `needs_you` reasons: `Answer: <question>`, `Fix quick #<n>`, `Resolve review findings`, `Review PR #<n>`.

## 0. The ask and the issue

1. An empty input: stop and ask what to change. A review document URL: stop and say to use make-plan.
2. The tracking issue is always there. One issue of this repository named in the input (`#<n>` or its URL) is
   read with its comments; otherwise create one at once with `github.issue_create` (title one line of at most 80
   characters, body the ask verbatim under `## Request`); further issues named go to the `Closes` lines. The ask
   is the human's input plus the text of owner and collaborator authors ([policies/untrusted-text.md](policies/untrusted-text.md)).
   If issue creation is refused, stop: say that no tracking issue could be created, that nothing was changed, and
   that a change this size or any change without an issue belongs to make-plan.
3. The branch `<type>/<kebab>` follows `<branch pattern>`: type `fix` for a defect, else `feature`, both only when
   they are in `git.branch_types` (else the first listed type); kebab at most four words of the issue title. When
   `git ls-remote --heads origin <branch>` lists it, append `-<n>`.
4. Is it already running: as implement does (Section 0 step 4), with `--kind implement --plan-slug issue-<n>`;
   the same `stop` and `take_over` ask, titled `Quick #<n> is already running`.
5. Write the first record (Setup step 4). Post `Implementation started on <feature>. Session: <id>.` on the issue
   (`github.issue_comment`; `<id>` is this session's id or `unknown`).

## 1. The size check

1. Read the must-read docs, the docs index rows that match, and every module the change touches (broad sweeps go to
   `run_helper`). A decision that is the human's goes to one `ask_human` as make-plan does (Section 0 step 3);
   a fact only the open web can settle is a research request ([policies/research.md](policies/research.md)).
2. The change is small only when every rule of "Sizing" in [make-plan.md](make-plan.md) holds for one phase:
   complexity S or M, one coherent change, one pull request, no open decision left, every acceptance item
   mechanical. It is also not small when it needs a `manual_before` or `manual_after` step, touches a protected path
   or a lockfile or adds a dependency, or, with a `spec` or `sysml` profile block, changes observable behaviour or
   the architecture model.
3. When it is not small: write nothing else. Post `Implementation stopped: too large for quick: <one line>. Run
   make-plan #<n>.` on the issue, write the record `done` with `last_event` `refused: too large`, and end with a
   reply that names make-plan and the issue. Never start a worker for a change that is not small.

## 2. The worker

`start_worker(<brief>, <the worker level>, <main>, <feature>, "quick #<n>: <issue title>")`. The brief is the phase
worker brief of implement ([implement.md](implement.md), Section 3) with these changes: the ask (data) in place of
the manifest entry and no plan file; rule 1 keeps "stay inside the ask" and adds "if the change turns out larger
than complexity M, or needs a protected path or a manual step, stop with `status=blocked` and a line `Too large:
<why>`"; rule 5's trailer is `Quick: issue-<n>`; the report line is `QUICK-REPORT status=<done|blocked> head=<sha>`,
reported to the orchestrator as rule 7 says. Rule 0 (`tld guard allow-plan`) stays first. `Too large:` is handled like
step 1.3.

Wait with `check_in` as implement does (Section 4). When the report is `status=done`: its head must equal
`git fetch origin <feature>`'s head and carry the `Quick:` trailer; run the roles of the `implement_phase` point and
`tld roles verify` as implement's Merge step 3 says; run the protected-path and lockfile check of
[policies/protected-changes.md](policies/protected-changes.md) step 2 with `git diff --name-only --no-renames
origin/<main>...origin/<feature>` (any hit, whether effective list, excluded set or lockfile, goes back to
the worker; a `protected-change:` line is handled like `Too large:`, step 1.3); check out the branch and run the fast checks. Anything wrong goes back
once to the same worker (a follow-up worker on the same branch, rule 0 first); a second failure sets `needs_you`
(`Fix quick #<n>`) and asks.

## 3. The final review

Merge `origin/<main>` into `<feature>` once (a merge commit), push, and start the final reviewer as implement does
(Section 5): the same brief with the ask in place of the plan, no deviations file, no `final_checks`, the diff
`origin/<main>...HEAD`, and the roles of `implement_final` run as [policies/roles.md](policies/roles.md) says.
`approve` goes on. `changes`: group the blocking findings, start one fix worker on `<feature>--fix-<n>` with the
findings verbatim and rule 0 first, merge it as implement does, then one more review of the diff since the fix;
a second `changes` asks the owner and stops. Each such fix worker adds its item `fix-<n>`, and the second review adds
`final-review-2`, in the record write that starts it. Post `Final review: approve.` or `Final review: changes (<n>
blocking).` on the issue.

## 4. The definition of done

Run the dod playbook on `<feature>` ([dod.md](dod.md)). A `FAIL` row goes to a fix worker on `<feature>--fix-<n>`
exactly like a blocking review finding; once its merge passes the fast checks and dod steps 1 to 4, push `<feature>`
(never force), then dod runs again.

## 5. The fix round

Run [policies/findings-fix.md](policies/findings-fix.md): the fix branch is `<feature>--fix-<n>` with the next free
`<n>`, the merge message is `Merge <feature> fix-findings`, the item is `fix-findings`. After the merge, once the fast checks and dod steps 1 to 4 pass, push `<feature>` (never
force): the policy leaves the merge local. Then run the
protected-path and lockfile check again: `git diff --name-only --no-renames origin/<main>...origin/<feature>` against
the main profile's list and the excluded set, as step 2 does.

## 6. The pull request

1. Write the body to a scratch file: `Closes #<n>` (one more per further issue) first, then `## Summary` of at
   most 175 words with the labels `**Deviations:**` (how the result differs from the ask; `None.` is allowed), then
   optionally `**Scope:**`, `**Security:**`, `**Performance:**`, then `**Review focus:**`, in this order, written by
   you in your own words; then `## Non-blocking findings` ([policies/findings-fix.md](policies/findings-fix.md)); then `## Review`:
   the verdict and every out-of-scope finding the worker reported; then, with a `reflektor` answer in the dod
   report, `## Change report` as implement does. Follow the repository's pull request template for any other section.
2. Run `git diff --name-only --no-renames origin/<main>...origin/<feature>` against the main profile's list and the
   excluded set once more (as step 2 does), then `tld plan summary-check <body file> --kind pr --findings <N>`; both
   must pass before `github.pr_create`. Post `PR opened: <url>.`
3. With `git.codeowners`, request their review, set `needs_you` (`Review PR #<n>`), `github.pr_subscribe` and drive the
   pull request to green as [policies/pr-steward.md](policies/pr-steward.md) says. A failure goes to a fix worker on
   `<feature>--fix-<n>` or you fix it yourself when it is small. Never approve, merge or enable auto-merge.
4. Reply with the pull request link and anything the worker or a reviewer flagged.

Never: push to `<main>`; approve or merge; rebase or force-push; implement the change yourself; start a second
fix-round worker; take a change that is not small.
