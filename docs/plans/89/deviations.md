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
- final: Final review: deps-prepare signs its commits as tld <tld@localhost> (the plan sets no identity), the git helper adds -c commit.gpgsign=false plus --no-ext-diff and --no-textconv, and the test list gained test_workflow_file_added_or_deleted_is_not_a_bump, test_a_rename_on_main_cannot_carry_a_group_into_a_protected_path and test_protected_paths_are_matched_case_folded (the added and deleted workflow cases moved out of test_workflow_files_only_as_action_ref_moves).

## p2-deps-body

- None.
- review: Decisions the plan left open were taken by the worker: entry index is 0-based, left-out count counts entries, file may be null, pr capped at 10^9, moves/files/reason/file optional. Non-blocking, open: ecosystem names in the Scope line are not in code spans.
- final: Final review: deps-body writes "It has no Dependabot pull request." for a left-out audit-only entry (a line the plan does not give); the cases of test_untrusted_values_refused were split into test_untrusted_input_refused, test_boundaries_pass and test_a_missing_file_is_refused; test_major_jumps_are_listed was added.

## p3-deps-eval

- worker: The task file sets repeats: 3 instead of the plan repeats: 1, because test_evals_tasks.py asserts three repeats and is outside touches; the stub is deterministic. The task description is double-quoted because the plan text breaks YAML.
- review: Non-blocking, open: the fixture test inherits the real HOME and git config; the bot-PR grader misses some write operations (issue_write, gh global flags before the subcommand). docs/architecture/evals.md needs rows for the new graders and task (phase p5).

## p4-deps-playbook

- worker: In playbooks/deps.md section 4 step 6 the pull request title span is quoted inside the span, because the verbatim span made test_every_action_a_file_uses_is_defined_in_runtime read chore( as an action call. The baseline command hashes were refreshed (all 16 move because the shared policy files changed); the pr_update_branch MCP row of the hooks test was removed as the plan says.
- review: Non-blocking, open: the protected-changes exception says every commit carries the bot identity, but work refs skip that check (plan 3.1); the PR template appended to the body is read from the working tree and the closing-keyword filter misses the URL form; a fixed version taken from audit output is written to the manifest without a shape check.
- final: Fix fix-1 after the final review: the playbook copied state applied from deps-prepare although deps-body accepts only included or left_out, so the body step would have been rejected; the playbook now maps applied to included and keeps a section 3 left_out entry as left_out. The superseded-PR rule also accepts commits by tld <tld@localhost>. deps_body.py prints the Security line when an entry has moves; docs wording for lockfile names and the bot identity was corrected.
- scope: docs/architecture/hooks-parsing.md (fix-1 touched a file outside the phase touches; see the final-review entry above)
- scope: docs/reference/profile-reference.md (fix-1 touched a file outside the phase touches; see the final-review entry above)
- scope: src/tld/ops/deps_body.py (fix-1 touched a file outside the phase touches; see the final-review entry above)
- scope: tests/core/test_deps_playbook_contract.py (fix-1 touched a file outside the phase touches; see the final-review entry above)
- scope: tests/core/test_ops_deps_body.py (fix-1 touched a file outside the phase touches; see the final-review entry above)
- final: Fix fix-2 after the second final review: fix-1 left groups the session itself leaves out (verify-red, conflicts-with-others, time-budget, lock-other-files, push-refused) without a reason; the playbook now gives them left_out, that reason and a null file. Contract tests now guard the playbook text; baseline hashes refreshed again.
- final: Fix fix-3 after the third final review: the playbook now gives an audit-only security group one updates item (package, from, fixed version) after a shape check of the fixed version before it reaches the manifest, gives groups stopped with needs_you no entry, gives unstarted groups the time-budget reason, and orders the clauses so only groups with a combine entry take its state. Non-blocking, open: the fixed-version check should say the whole value must match, the audited package name is only che

## p5-retire

- worker: Two spec scenarios (post-merge path-set check, case-folded protected paths) were added to the delta before archiving, because it lacked them. docs/reference/cli.md already had the two rows, so it was not touched.
- review: Non-blocking, open: profile-reference.md says any unlisted changed lockfile keeps its group out, but the code only does so for built-in lockfile names; hooks-parsing.md says a workflow change is taken only as a bump by the bot, which overstates the identity check (a claim, not proof).

## Final review

- final: First final review: changes, two blocking findings (p1 and p2 deviation entries missing), both fixed by adding the entries; the final code review also found the playbook state mapping blocking, fixed by fix-1 (see p4-deps-playbook).
- final: Second final review: the code-reviewer role found fix-1 left no reason for groups the session itself leaves out (verify-red, conflicts-with-others, time-budget, lock-other-files, push-refused); blocking, sent to fix-2. The reviewer worker approved.
- final: Second final review blocking finding fixed by fix-2 (merged, security review pass).
- final: Third final review: changes, two blocking findings in playbooks/deps.md section 4 step 4 that come from the plan itself: an audit-only security group gets an empty updates list (deps-body rejects it), and groups stopped with needs_you or not started because of the time budget have no entry rule. Put to the owner on the board (ask a-62b7165f5c2cbd09).
- final: Third final review blocking findings fixed by fix-3 (merged, security review without blocking findings), as the owner chose on the board (ask a-62b7165f5c2cbd09).

## Finishing

- pending
