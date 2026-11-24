# Deviations: deps-combined-pr

Written by the implement orchestrator after each phase merge; workers never edit this file.
Every deviation from the plan is listed under its phase. "None." means the phase followed the plan.

## p1-deps-prepare

- worker: merge-tree: only exit 1 is does-not-apply, other non-zero exits raise an error; a T type change is unexpected-change; .env.example and siblings exempt from every protect entry; lock_entries takes an optional resolved argument; test profiles set deps.cooldown_days and time_budget_minutes explicitly; the "no trusted copy" test moves refs/tld/trusted.
- review: Security review found three blocking issues; the rename-into-protected-path and case-folding ones were fixed (post-merge path-set check, NFC and casefold matching).
- retry: p1 was sent back once after the security review and re-run; the second review had no blocking finding.
- review: Accepted by the owner (ask a-3f7eeb33d2bf0e46): a tld-deps/* work ref skips the bot-identity check for its whole history, as plan 3.1 says; the workflow blob comparison and owner review remain the controls.
- review: Non-blocking, open: lockfile classification and a few Unicode or trailing-dot aliases are not case-folded; the post-merge path check requires equal sets, so an overlapping group may be left out as does-not-apply. Plan 3.1 should mention that check.
- review: tests/mutation/run_mutants.py deselects slow tests, so mutants whose tests are all slow count as killed; all p1 mutants were killed with a loop that includes slow tests. Needs a fix in another phase.

## p2-deps-body

- None.
- review: Decisions the plan left open were taken by the worker: entry index is 0-based, left-out count counts entries, file may be null, pr capped at 10^9, moves/files/reason/file optional. Non-blocking, open: ecosystem names in the Scope line are not in code spans.

## p3-deps-eval

- worker: The task file sets repeats: 3 instead of the plan repeats: 1, because test_evals_tasks.py asserts three repeats and is outside touches; the stub is deterministic. The task description is double-quoted because the plan text breaks YAML.
- review: Non-blocking, open: the fixture test inherits the real HOME and git config; the bot-PR grader misses some write operations (issue_write, gh global flags before the subcommand). docs/architecture/evals.md needs rows for the new graders and task (phase p5).

## p4-deps-playbook

- worker: In playbooks/deps.md section 4 step 6 the pull request title span is quoted inside the span, because the verbatim span made test_every_action_a_file_uses_is_defined_in_runtime read chore( as an action call. The baseline command hashes were refreshed (all 16 move because the shared policy files changed); the pr_update_branch MCP row of the hooks test was removed as the plan says.
- review: Non-blocking, open: the protected-changes exception says every commit carries the bot identity, but work refs skip that check (plan 3.1); the PR template appended to the body is read from the working tree and the closing-keyword filter misses the URL form; a fixed version taken from audit output is written to the manifest without a shape check.

## p5-retire

- pending

## Final review

- pending

## Finishing

- pending
