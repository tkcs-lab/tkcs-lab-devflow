# Review of claude-toolkit @ 4c14071 (main, after PR #24)

Four reviews run in parallel: security, tests, consistency and gaps, and how tightly the code is tied to Claude.
Findings marked [V] were checked by running something. The rest come from reading the code with file:line evidence.

## Security

### Critical
- S1 [V] `hooks/_common.py:117-139`. `trusted_disable` reads `hooks.disable` from the local `origin/main` ref, which a session can rewrite.
  One `hash-object` → `mktree` → `commit-tree` → `update-ref` chain switches off every guardrail.
  After that, a force-push to main and a tag push were both allowed.
- S2 [V] `hooks/no_merge.py:63`. A dynamic refspec (`B=main; git push origin HEAD:$B`) is skipped, and main gets pushed.
- S3 [V] `hooks/_gitgh.py:147-161`. A dynamic command name (`G=git; $G push --force …`) is classed as "other", so every Bash hook allows it.

### High
- S4 [V] `_gitcfg.py:53`, `_gitgh.py:98`. Config from `-c include.path=…`, `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_PARAMETERS` is never seen.
  Push destinations and aliases set there go through unchecked.
- S5 [V] `no_merge.py:53-70`. `git push origin :` (the matching refspec) pushes main.
- S6 [V] `_shell.py:302-386`. Indirect execution gets past the hooks: `python -c`, `bash script.sh`, `fish -c`, `find -exec sh -c`, `xargs git push`.
- S7 [V] `protect_paths.py:360-366`. The session can run `--allow-profile` itself, then edit the profile to set `protect_paths: []`.
  `dod_gate.py --exempt` lets it exempt itself from the DoD gate in the same way.
- S8 [V] `protect_paths.py:27`. Paths outside the project are not protected: `~/.claude/settings.json`, `.mcp.json`, `~/.gitconfig`.
- S9 [V] `no_git_tag.py:139`. `git push origin tags/v1` pushes the tag.

### Medium
- S10 `no_git_tag.py`. These are not caught: `gh api …/git/refs --input`, numeric workflow ids in Bash, and a rerun of a past release run.
- S11 `no_merge.py`. A merge through `curl` or GraphQL is not caught, and neither is `gh pr review --approve=true`.
- S12. With `dry_run=false`, git-ops can create real tags while the hooks stay silent. The only safeguard is the prompt's "ask the user".
- S13 `_common.py:26`. The session can rewrite `devflow-land.yml` and run its own edited copy with `DEVFLOW_AGENT_TOKEN`.
- S14 `implement.md:62`. `/implement` runs `verify_after_merge` shell commands taken from a plan on any ref.
- S15 `make-plan.md:54`. Issue comments are taken as "the ask", and nothing says they are untrusted text.
  `/implement`, `/review` and `/setup` have no rule about untrusted text either.

### Low
- S16. `secret_scan` only looks at Write and Edit, so secrets written from Bash are missed. It also has pattern gaps: `glpat-`, `API_KEY_1=`, and unquoted passwords.
- S17. `protect_paths` misses `git apply`, `patch`, `git checkout <ref> <path>`, dynamic redirects and `core.hooksPath`.
- S18. `board_client` sends its token along when it follows a redirect.
- S19. The MCP bridge exposes `board_delete` with no gate.

What is in good shape: the workflow templates (input goes through `env:`, actions are pinned, an environment gate), the board server, and every script (none uses `shell=True`).

## Tests
- 2321 tests pass. Line coverage, counting subprocesses, is 93%. 48 of 61 hand-made mutants were killed.
- About 160 test functions only grep markdown for strings. They catch reworded text, not wrong behaviour, and some needles are nearly meaningless (`"low"`, `"3b"`).
- Mutants that no test caught:
  - DELETE or POST to the contents API in `no_merge`
  - five `secret_scan` patterns
  - a `/setup` marker dated in the future
  - `protect_paths` treating a trailing `dir/` as a directory
  - seven type checks in `validate_manifest`
- Weak coverage in `_ansi.py` (64%) and `_wrappers.py` (77%). Both are places where hooks can be bypassed.
- No command is tested end to end in CI. The evals need `claude -p` and an API key, nothing runs them automatically, and their baseline is stale (every hash differs). `/implement`, `/land`, `/deps`, `/upstream` and `/docs` have no eval.
- Possible flakiness:
  - timing assertions, including one test that takes 15 s
  - a session-scoped fixture that is changed and never restored
  - `GIT_CONFIG_COUNT` leaking into tests
  - the Playwright test silently skipped in CI

## Consistency and gaps
- C1 `setup.md:33-40`, `profile_patch.py:241`. `/setup update` writes the raw proposal, so the user's answers are lost and a hand-tuned agents block is overwritten. When the survey found no website it exits 1.
- C2. `/implement` says the orchestrator never runs agents that can edit files, but it does run `/dod`, which dispatches `tech-writer` and `website-maintainer`. Agents can also be dispatched twice in one phase.
- C3. The severity of a docs-index error disagrees across `docs-review` (blocking), `dod` and `docs-index` (never blocking) and `implement` (sends it to a fix session). `tech-writer` edits the index, which breaks the rule that only the retirement phase does.
- C4. This repo's profile has no `docs.index`. `plan_dir` is `docs/`, but docs-keeper uses `docs/plans/`. `docs_index move` never updates the profile, so moved docs leave stale paths behind.
- C5. `docs.md:31` says `move` applies the change, but without `--apply` it only does a dry run.
- C6. `/setup` and `/docs init` work against each other on `must_read` and `docs.index`.
- C7. The status-record model is muddled:
  - `/land` is run by the owner but treated as scheduled.
  - The rules for the project slug, final states and `/docs` are unclear.
  - `/review` and `/make-plan` write no record even while they wait for the user.
- C8. Tags have two routes (release workflow and git-ops), and the `no-git-tag` hook's message says the opposite of the git-ops skill. The hooks.md tables are out of date.
- C9. Which model runs is decided in four places: profile `models.*` (planner and orchestrator are read by nothing), hard-coded `opus` in make-plan and review, agent front matter, and model ids hard-coded in implement.md.
- C10. Docs that are wrong:
  - README says "nine commands"; there are ten.
  - README says "no server", but the board is a server.
  - `/docs` is missing from the marketplace description.
  - The owner is given as both `andras-tkcs` and `tkcs-lab`.
  - The PrivacyFence fixture, called a "complete example", is weeks old.
  - `design.md` still describes the SessionStart hook route.
- C11. Three ways to review overlap: agents, skills, and the subagents `/review` starts for each area. The same issue can be reported twice.
- C12. The branch names used (`plan/`, `review/`, `<feature>--<phase>`) don't match the profile's `branch_pattern`, and `pr-steward` says only `claude/…` branches can be pushed.
- C13. `tracking_issue` is "always set" in one place and optional in another.
- C14. PrivacyFence words remain in generic files: "approval gate" in the template's `extra_context`, plus Gemini and AI Studio examples. `maintenance-spike.md` records real logins and session ids.

## How tightly it is tied to Claude
- The Python is mostly neutral already. The ties are:
  - the hook input and output format
  - `.claude/toolkit.yaml`, about 200 times
  - `devflow:`, 36 times, and `DEVFLOW_*`, more than 100 times
  - tests that load files from `plugins/devflow/`
- About 60% of `implement.md` and `make-plan.md` is fixed procedure: phase scheduling, branch names, merge checks, timers, sizing rules, the brief template. Most of it could be code or a spec.
- The genuinely Claude-specific parts:
  - starting cloud sessions, `send_message` and `send_later`
  - Artifact pages and `AskUserQuestion`
  - subagents and model aliases
  - plugin and marketplace manifests, `hooks.json` and `.mcp.json`
  - `claude.ai` links on the board
  - the eval runner
