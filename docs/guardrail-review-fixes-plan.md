# Plan: fix the findings of the guardrails / scope-drift / eval-harness review

## Goal

Fix every item in "Findings to fix" of the review
[`guardrails-scope-evals-2026-11-10-review.md`](https://github.com/tkcs-lab/claude-toolkit/blob/review/guardrails-scope-evals-2026-11-10/docs/guardrails-scope-evals-2026-11-10-review.md)
(reviewed at commit `9e9e722`, status `ready-for-plan`; `main` is now `c575f43`, see below), tracked in
[#15](https://github.com/tkcs-lab/claude-toolkit/issues/15). After this plan:

- the guardrail hooks (`no-merge`, `no-force-push`, `no-git-tag`, `protect-paths`, `secret-scan`,
  `dod-gate`) no longer let the reproduced bypasses through, fail closed where `docs/hooks.md` says
  they do, and the docs describe what they really do;
- the eval harness runs the agent with an isolated `HOME` and no proxy, scrubs transcripts and
  results with the toolkit's own secret patterns, stops at the first cost ceiling and grades
  "secret pushed then removed" correctly;
- the scope check covers fix and rework sessions and cannot be used to inject Markdown into a PR body;
- CI is pinned, `SECURITY.md` and `CONTRIBUTING.md` exist, and README / design / delivery docs have
  caught up with hooks and evals.

Out of scope (the review's "Not doing" / "Issues created"): SEC-H9, SEC-E9, SEC-E11, DOC-7, TST-10
(issue #14), PR #12 / issue #8. Do not touch them.

The review document is the evidence for every finding. A worker who needs the evidence text reads it with:

```bash
git fetch origin review/guardrails-scope-evals-2026-11-10
git show FETCH_HEAD:docs/guardrails-scope-evals-2026-11-10-review.md
```

`main` has moved since the review (now `c575f43`: the git-ops workflow and skill, the first committed eval baseline,
eval grader fixes, plugin version 0.6.0). It changed **no hook, no `scope_check.py` and no test of them**, and in the
eval harness only `graders.py` (`is_runnable`, `parse_findings`, `seeded_finding_found`) and `results.py` (`aggregate`
records `models`); the findings were re-checked against that tree and all hold, except the `baselines/` half of
DOC-13 (a baseline `evals/baselines/default.json` is now committed) which is dropped. Line numbers in the review and
in this plan may be off; always locate by symbol or by `grep`.

## Current state

- Hooks: `plugins/devflow/hooks/` (`_common.py` 146 lines, `_shell.py` 355, `_gitgh.py` 348,
  `no_merge.py` 163, `no_force_push.py` 67, `no_git_tag.py` 146, `protect_paths.py` 208,
  `secret_scan.py` 123, `dod_gate.py` 227, `hooks.json`). Tests: `tests/test_hook_*.py`,
  `tests/test_hooks_{shell,config,compat}.py`, helpers in `tests/hooks_helpers.py`. Docs:
  `docs/hooks.md` (265 lines).
- Scope check: `plugins/devflow/scripts/scope_check.py` (334 lines), `plugins/devflow/commands/implement.md`
  scope sections, `docs/scope-drift.md`, `tests/test_scope_check.py`.
- Evals: `evals/harness/*.py` (about 1,900 lines), `evals/tasks/*/task.yaml` (7), `evals/schema/task.schema.json`,
  `evals/hook_cases.yaml`, `docs/evals.md`, tests `tests/test_evals_*.py`.
- CI: `.github/workflows/test.yml` (floating `@v4` / `@v5` tags, unpinned npm package, `pytest>=8`, `PyYAML>=6`).
- Gate: `verify.fast` and `verify.dod` run `pytest tests -q` (about 1,500 tests, under a minute). The project has no ADRs
  and no changelog; the profile has no `docs.adr_dir` and no `docs.changelog`, so neither is part of this plan.
- Of 27 mutations tried by the review, 15 survived the suite: many phases below exist to kill specific mutations.

## Design

Conventions for every phase: Python 3.11, standard library plus PyYAML in the hooks; tests are plain

pytest functions placed in the file the acceptance names; run the suite with
`.venv/bin/python -m pytest` (the profile's command creates `.venv`). A new test is written first and
must fail on the unfixed code for the reason the finding gives. Never loosen an assertion or add a skip.
**File size cap:** `tests/test_hooks_config.py::test_scripts_are_small_stdlib_plus_pyyaml_python_311_without_network`
requires every `plugins/devflow/hooks/*.py` to be under 420 lines (today `_shell.py` has 355, `_gitgh.py` 348). The cap is
not loosened. New code therefore goes into **new helper modules**: `_ansi.py` and `_wrappers.py` (phase p1), `_gitcfg.py`
(phase p3). Helper modules import only the standard library and sit next to the hooks. Before finishing, a worker runs
`wc -l plugins/devflow/hooks/*.py` and stops with `status=blocked` if any file has 420 lines or more.
`docs/hooks.md` is edited **only** by phase `p19-docs`, `docs/evals.md` only by `p16-eval-docs-tasks`,
`docs/scope-drift.md` and `implement.md` only by `p17-scope-check`. A code phase that changes a
documented behaviour does not edit those docs; `p19-docs` does, from the "Documentation obligations"
list at the end of this section.

### D1. Shell parser (`_shell.py`) — SEC-H2, SEC-H4

- `$'…'` (ANSI-C quoting) is decoded to its literal value instead of `DYN`. New function
  `ansi_c_decode(body: str) -> str` in the new module `_ansi.py` (imported by `_shell.py`) implementing bash's rules: `\a \b \e \E \f \n \r \t \v \\ \' \" \?`,
  octal `\nnn` (1 to 3 digits), `\xHH` (1 to 2 hex digits), `\uHHHH`, `\UHHHHHHHH`, `\cX` (control character);
  an unknown escape is kept as backslash plus the character; a NUL (from `\0` or `\x00`) ends the string, as in bash.
  In `_scan` the decoded text is appended to the word buffer as `shlex.quote(decoded)` (the same way
  `_heredoc_delimiter` appends a quoted delimiter) so the later word split sees one literal word.
- The wrapper tables and `_strip_wrapper` move from `_shell.py` into the new module `_wrappers.py` (`WRAPPERS`, `WRAPPER_VALUE_OPTS`, `WRAPPER_POSITIONALS`, `strip_wrapper`); `_shell.py` imports them under the old names. `WRAPPERS` gains `flock`, `script`, `taskset`, `unshare`, `chroot`, `strace`; `WRAPPER_VALUE_OPTS` gains
  `flock: {-w, --timeout, -E, --conflict-exit-code}`, `taskset: {-c, --cpu-list}`, `chroot: {--userspec, --groups}`,
  `strace: {-e, -o, -p, -s, -u, -E, -a}`, `unshare: {}`, `script: {-c, --command}` handled specially (below).
  `flock` and `chroot` take one positional (lock file / new root) that `_strip_wrapper` must skip before the command;
  `taskset` takes one positional (the mask) unless `-c`/`-p` is used; encode these as a new table
  `WRAPPER_POSITIONALS = {"flock": 1, "chroot": 1, "taskset": 1}` (the number of leading positional words to skip
  after the options; `taskset -c LIST cmd` and `taskset -p` skip none because the value option consumed it).
- `time -p`: `time` stays in `RESERVED` (it is a keyword), but a directly following `-p` word is skipped
  (also `--`). Do this where `RESERVED` words are stripped in `candidates`.
- `env -S` / `--split-string`: the option's value is split with `shlex.split` and its words are prepended to the
  rest of the command (recursion through `candidates`). `script -c CMD FILE` / `script --command CMD`, and any short-option
  cluster that ends in `c` (`-qc`, `-efc`): `CMD` (the next word) is parsed with `split_commands` and each resulting command
  goes through `candidates`, like `bash -c`.
- Stdin-fed shells (the hard part, phase p2): a command whose head is in `SHELLS`, that has no `-c` option
  and no non-option argument (a script path), reads its commands from stdin. Rules, in this order:
  1. a herestring (`<<< word`) or a heredoc (`<< DELIM`, `<<- DELIM`, quoted or not) attached to that command:
     the herestring word or the heredoc body is parsed with `split_commands` and each resulting command goes
     through `candidates`, exactly like the `-c` string. To do this the scanner must keep heredoc bodies
     instead of discarding them (`_skip_heredoc` currently only scans an unquoted body for `$(…)`) and attach each
     body to the `Command` whose redirect introduced it (new field `Command.stdin_text: str | None`);
  2. otherwise (stdin is a pipe, a file, or the terminal) the `Command` gets `reads_stdin_shell = True`. `candidates` does
     **not** raise: `protect_paths` treats a `ParseError` as "allow", so raising there would let `echo x > .env; echo | bash`
     newly pass. `iter_items` (used by the three destructive hooks) raises
     `ParseError("a shell that reads its commands from stdin cannot be checked")` when it meets such a command; the hooks
     turn a `ParseError` into a deny ("cannot parse this command … Rewrite it as plain, separate commands.").
     `protect_paths` ignores the flag.
  `bash script.sh`, `bash -c '…'`, `bash -s` with a here-document are covered by the same rules (`-s` counts as "no
  script"). A shell whose only arguments are `--version`, `--help` or `-n` is not a stdin shell. `sh -c` and every other
  existing path are unchanged.

### D2. Git parsing (`_gitgh.py`) — SEC-H3 and the dynamic-option part of SEC-H2

- `Command` (in `_shell.py`) gains `env: dict[str, str]`: the leading `NAME=value` assignments that
  `candidates` strips today (values are the literal word text; a dynamic value is the string `DYN`).
  `walk()` yields 3-tuples `(cwd_hint, words, redirects)` and its callers (three unpackings in `tests/test_hooks_shell.py`,
  `protect_paths.py`) must keep working, so a new generator `walk_commands(command)` yields `(cwd_hint, Command)` and `walk`
  becomes a thin wrapper over it. `iter_items` uses `walk_commands` and passes `command.env` to `_items`, which passes it to
  `parse_git(words, env)`.
- `parse_git` merges, in this order, into `Git.config` (a list of `key=value` strings): first the environment
  config (`GIT_CONFIG_COUNT`, then `GIT_CONFIG_KEY_<n>` / `GIT_CONFIG_VALUE_<n>` for `n` in `0..COUNT-1`, read from
  the command's own leading assignments, and where absent from `os.environ`), then every `--config-env=name=ENVVAR`
  (value taken from the command's leading assignments, else `os.environ`, else dropped), then every `-c` value.
  Later entries win in `expand_alias`, which already scans `git.config` last-wins.
- `GIT_KNOWN` stays; `send-pack`, `http-push` and `subtree` (when its first argument is `push`) are treated as
  `push` by `_items`: the `Item` is emitted with `git.sub = "push"` and `args` as given (for `subtree push` the
  arguments after the word `push`). `send-pack`'s first positional is the remote, the rest are refspecs, which is
  what `parse_push` already assumes.
- `parse_push` gains `Push.dynamic_option: bool`, true when a dynamic word (`is_dynamic`) appears before the first
  non-dynamic positional (the remote) or when any word has a literal `-` prefix followed by a dynamic part. Callers:
  `no_force_push.check_push` returns `deny("an argument that is only known at run time sits where a push option
  could be, so it cannot be checked for --force")` when `push.dynamic_option` is true. (A dynamic word after the
  remote stays a refspec, as today. `git push origin $(git branch --show-current)` therefore stays allowed.)

### D3. Push destination (`_gitgh.py`, `no_merge.py`) — SEC-H1, SEC-H7, SEC-H15

- New module `plugins/devflow/hooks/_gitcfg.py`, created in phase p3, which moves `_run_git`, `current_branch` and `ref_exists`
  into it (`_gitgh.py` re-imports them, so every existing `from _gitgh import current_branch` keeps working). Phase p4 adds to
  it `git_config_values(ctx_dir, repo_opts, overrides, key) -> list[str]`, returning **all** effective values (the `overrides`
  entries for `key`, compared case-insensitively on the key, which replace the file values when present; otherwise
  `git config --no-includes --get-all <key>`; an empty list when unset), `git_config_value(...) -> str | None` (the last of
  those), and `bare_push_destinations(it, push, main) -> list[str] | None`: the
  short branch names a push **without an explicit refspec** would update, or `None` when that cannot be resolved.
  Resolution order, with `remote` = the pushed remote (`push.repo`, else `branch.<cur>.pushRemote`, else
  `remote.pushDefault`, else `branch.<cur>.remote`, else `origin`) and `cur` = `current_branch(...)`:
  1. `remote.<remote>.mirror` is true → `None`;
  2. `remote.<remote>.push` set (**every** value, from `git_config_values`) → each value is a refspec, run through `parse_refspecs`; the
     destinations are their `dst` (`HEAD`/`@` alone means `cur`); a glob or an unresolvable value → `None`;
  3. else by `push.default` (default `simple`): `simple` and `current` → `[cur]`; `upstream` / `tracking` → the
     short name of `branch.<cur>.merge` (missing → `None`); `matching` → `None`; `nothing` → `[]`.
  `cur` being `None` (detached HEAD) → `None`.
- `no_merge.check_push`: when there are no refspecs and not `push.tags`, call `bare_push_destinations`; deny when it
  is `None` ("the destination of this `git push` cannot be determined from your git configuration") or contains
  `main` (as today's "current branch" message, now naming the real destination). Also deny any push carrying a
  `-c` config key (case-insensitive) that starts with `remote.`, `push.` or `branch.`: "`-c <key>` changes where
  `git push` writes". (SEC-H1 acceptance uses exactly three commands: upstream + bare push, `-c remote.origin.push=…`,
  `-c remote.origin.mirror=true`.)
- SEC-H7: `GhApi` gains `field_files: list[str]`: values of `-F` / `--field` (not `-f`) that start with `@`.
  `parse_gh_api` stores them (and does not put them in `fields`/`texts` as plain text). `check_gh_api`, in the
  GraphQL branch, reads each (`read_input_text`-style, 1 MB, relative to `it.dir`; `@-` or unreadable → deny with the
  same message style as `--input`) and appends the text to the scanned text.
- SEC-H15: `check_mcp`: for `MCP_BRANCH_WRITES`, the tool is treated as writing to main when `branch` is missing
  or empty, or equals `main`, `refs/heads/<main>` or `heads/<main>` (use `short_ref`). `check_gh_api` additionally
  denies `POST repos/<o>/<r>/merge-upstream` when the `branch` field is the main branch or absent;
  `repos/<o>/<r>/branches/<main>/rename` (any method); and `check_gh` denies `gh repo sync` with `--force` or with
  `--branch` / `-b` equal to the main branch.

### D4. Tags and releases (`no_git_tag.py`, `hooks.json`, release template) — SEC-H5, SEC-H6

- `no_git_tag.check_push` additionally denies: a `-c` key (case-insensitive) equal to `push.followtags`, or
  matching `remote.*.push` / `remote.*.mirror`; `git config --get`-resolved `push.followTags` true; any value of
  `remote.<remote>.push` that mentions `refs/tags/` (use `git_config_values` from D3, all values, remote resolved as in D3).
  `git update-ref --stdin` is denied outright (message: tags can be created through its input, which cannot be
  read). Writes of `push.*` / `remote.*.push` through `git config` are denied by `protect_paths` (D7), not here.
- Release dispatch: the release workflow is `devflow-release.yml` (display name `devflow-release`). No new profile
  key is added (the review's optional `hooks.release_workflows` is rejected: it needs a schema change for no current
  user). `no_git_tag` denies:
  - `gh workflow run <w>` and `gh workflow dispatch`-style words where `<w>` is `devflow-release.yml`,
    `devflow-release`, or ends with `/devflow-release.yml`;
  - `gh api` POST to `repos/<o>/<r>/actions/workflows/<w>/dispatches` with the same `<w>` test;
  - MCP `actions_run_trigger` with `method == "run_workflow"` when `workflow_id` (string) has the basename
    `devflow-release.yml`, **or** is not a file name ending `.yml` / `.yaml` (an id cannot be checked offline, so it
    fails closed; `/implement` dispatches by file name from `ci.dispatchable`, and the `git-ops` skill dispatches
    `devflow-git-ops.yml` by file name — that dispatch **stays allowed**: the workflow runs in the central repository
    behind a dry-run default, an allowlist and the `git-ops` environment, see `docs/git-ops.md`);
  - `gh release edit` carrying `--tag` (or `--tag=…`); `gh api` PATCH or DELETE on `repos/<o>/<r>/releases/<id>`.
- `hooks.json`: `no_git_tag.py` moves out of the shared `Bash` group (where `no_force_push.py` stays alone) into its own
  `PreToolUse` group with matcher `Bash|mcp__.*__actions_run_trigger`, timeout 20. This keeps the invariants of
  `tests/test_hooks_config.py` (each script registered exactly once; every entry that matches a tool equals the `listens` table,
  which gains for `no_git_tag.py` the tools `Bash` and `mcp__github__actions_run_trigger`). `no_git_tag.evaluate` handles
  `ctx.tool.startswith("mcp__")` through a new `check_mcp`.
- `plugins/devflow/templates/devflow-release.yml`: the job gets `environment: release` (keep every other line).
  Every run, dry runs included, then waits for a reviewer: intended, because the workflow cuts tags. The environment's required reviewers are a repository setting: manual step `ma2-release-environment`.

### D5. Fail closed — SEC-H14

- `_gitcfg.py`: new `class GitLookupError(ParseError)`. `current_branch` raises it when the `git` call times out,
  cannot run or exits with a status other than 0 or 1 (status 1 from `symbolic-ref -q` means "detached HEAD" and
  returns `None` as today); `ref_exists` raises it on timeout / `OSError` / status other than 0 or 1.
  `expand_alias` reads config with `git config --no-includes --get`. `check_push` in `no_merge.py` and `no_git_tag.py` runs
  outside the `try` around `iter_items`, so a `GitLookupError` there reaches `_common.execute`'s generic handler and is denied as
  `internal error (GitLookupError: …)`; tests assert code 2 only. `check_push` must not swallow it.
- `_common.py`: `HOOK_BUDGET_SECONDS = 15` (below the 20 s hook timeout). `execute(…, fail_closed=True)` arms
  `signal.setitimer(signal.ITIMER_REAL, HOOK_BUDGET_SECONDS)` around `evaluate` (skipped when `signal.SIGALRM` does
  not exist) with a handler that raises `TimeoutError`; `execute` turns `TimeoutError` into
  `Result(2, "devflow <name>: took longer than 15 s, so the call is denied.")`.
- Import crashes: in `no_merge.py`, `no_force_push.py` and `no_git_tag.py` the imports of `_gitgh` and `_shell`
  are wrapped in `try: … except Exception as exc: _common.exit_import_error(NAME_LITERAL, exc)` where
  `_common.exit_import_error(name, exc)` prints `devflow <name>: internal error while loading (<type>: <msg>).` to
  stderr and exits 2. (`_common` itself is imported first and unwrapped.)

### D6. Profile trust (`_common.py`) — SEC-H8, DOC-4

- `find_project`: when `CLAUDE_PROJECT_DIR` is set, a profile is accepted only from that directory or a directory
  inside it (compare `Path.resolve()`); the walk up from `cwd` stops at the project directory. A profile found
  outside is ignored (reported as "no profile" with the reason `profile outside CLAUDE_PROJECT_DIR ignored`).
- New `trusted_disable(ctx) -> list[str]`: the `hooks.disable` list read from the committed main-branch profile. Order:
  1. no working-tree profile (`ctx.profile is None`, for example PyYAML missing) → `[]`;
  2. `git rev-parse --verify -q HEAD` fails (no commit yet, or not a repository) → the working-tree list (no trusted copy can
     exist);
  3. otherwise `git show origin/<main>:.claude/toolkit.yaml`, else `git show <main>:.claude/toolkit.yaml` (both run in
     `ctx.project_dir`, 5 s timeout, parsed with `yaml.safe_load`); if neither can be read → `[]` (the hooks stay on; a
     branch that sets `git.main_branch: nosuch` to hide the committed copy gains nothing).
  `<main>` is `git.main_branch` of the working-tree profile. This leaves one accepted gap: a branch can still change
  `git.main_branch` itself; branch protection is the backstop, as `docs/hooks.md` already says.
  `Ctx.disabled(name)` uses `trusted_disable` for every hook. When the working-tree `hooks` section differs from the
  trusted one, `ctx.notice` is set to `the working tree's hooks section differs from the committed <main> profile; only the
  committed hooks.disable is applied` (shown when the call is allowed).
- DOC-4: `Ctx.disabled` no longer swallows `ProfileError`: a `hooks.disable` that is present but not a list of
  non-empty strings raises `ProfileError("toolkit.yaml: 'hooks.disable' must be a list of non-empty strings")`, and
  `execute` turns it into exit 2 as for any `ProfileError`. Exception: for the `dod-gate` hook `execute` does not return;
  it stores the error in the new field `Ctx.disable_error` and continues with the hook enabled, and `dod_gate.evaluate`
  re-raises `ctx.disable_error` at the place where it counts profile errors as failed attempts (D8), so a malformed
  `hooks.disable` cannot recreate the TST-1 endless loop.

### D7. Protect paths (`protect_paths.py`) — SEC-H8 (second half), SEC-H10, SEC-H11, TST-13

- `ALWAYS_PROTECTED = [".claude/settings.json", ".claude/settings.local.json", ".git/config", ".git/hooks/**"]` is a
  module constant in `protect_paths.py`, matched in addition to the profile list; `hooks.protect_paths` (even `[]`)
  and `hooks.protect_paths_allow` never remove it.
- Writes (Write/Edit tools, redirects, `tee`, `cp`, `mv`, etc. — whatever the hook already treats as a write) to
  any path under `$CLAUDE_PLUGIN_ROOT` are denied (only when the variable is set and non-empty).
- `git checkout <rev> -- <path>`, `git checkout -- <path>`, `git restore [--source=<rev>] <path>…`, `git restore -S/-W`
  with a protected path among the pathspecs are denied as writes to it.
- `git config` writes are denied when the key (case-insensitive) starts with `alias.`, `remote.`, `push.`,
  `branch.`, `include.` or `includeif.`. A write is: a second positional argument after the key, or any of
  `--add --replace-all --unset --unset-all --rename-section --remove-section -e --edit`. Reads (`--get`,
  `--get-all`, `--get-regexp`, `--list`, `-l`, a key alone) stay allowed.
- `ln` / `ln -s` whose source (any non-final non-option word) resolves to a protected path (or, for a directory,
  to a path under which a protected glob matches, tested by matching `<source>/x`) is denied. When a write target
  exists and `os.stat` gives the same `(st_dev, st_ino)` as an existing protected file, it is denied.
- Brace expansion: before matching, redirect targets and word arguments with a single-level or nested
  `{a,b}` group are expanded (cap 64 results; beyond the cap → treat as protected-ambiguous → deny).

### D8. dod-gate (`dod_gate.py`) — TST-1, DOC-15, TST-6, TST-7

- A `ProfileError` raised before the attempt counter counts as a failed attempt: the gate honours
  `stop_hook_active` and `max_attempts` for it like any other failure (after the limit it exits 0 with the message
  in `systemMessage`). When `max_attempts` itself is invalid, the limit used for this decision is the default 3.
- `max_attempts` above 10 is a `ProfileError("toolkit.yaml: 'hooks.dod_gate.max_attempts' must be between 1 and 10")`
  (the lower bound check stays).
- Tests only for TST-6 and TST-7 (no code change): see the briefs. Phase p7 (which adds `Ctx.disable_error`) adds the one line in `dod_gate.evaluate` that re-raises it (D6).

### D9. secret-scan (`secret_scan.py`) — SEC-H12, SEC-H13

- `ASSIGNMENT` becomes
  `(?<![A-Za-z0-9_.\-])([A-Za-z_][A-Za-z0-9_.\-]{0,63})["']?\s*(?::=|[:=])\s*(?:(["'])([^"'\s]{20,})\2|([A-Za-z0-9+/=_\-.~]{20,}))`
  — quoted values may contain any non-space, non-quote character (so `#` is allowed); unquoted values keep the old
  class. (Two value groups: update `scan_text`.)
- `SUFFIXES` becomes `("key", "token", "secret", "password", "passwd", "pwd", "credential", "credentials", "auth")`.
  For names ending in `password`, `passwd` or `pwd` the value rule is: length at least 12, has a digit and a letter,
  no placeholder word, entropy at least 3.0. All other names keep `high_entropy_literal`.
- New `SPECIFIC` entries (`SPECIFIC` holds `(name, description, re.compile(...))` tuples):
  `("url-credentials", "credentials in a URL", r"\b[a-z][a-z0-9+.\-]*://[^\s/:@$<>{}%]+:[^\s/@$<>{}%]{3,}@[^\s/]+")`,
  `("bearer-token", "a bearer token", r"\bBearer\s+[A-Za-z0-9._\-]{20,}")`, and
  `("jwt", "a JSON web token", r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")`. A `bearer-token` hit
  whose token contains a `PLACEHOLDERS` word is not a hit (a few lines of code in `scan_text`, which special-cases that name).
  The URL password needs 3 or more characters.
- `ALLOW_MARK` counts only at the end of the line: `line.rstrip().endswith(ALLOW_MARK)`.
- A per-line cap `MAX_LINE_FOR_ASSIGNMENT = 1_000_000`: above it only `SPECIFIC` patterns run on that line.
- The denial message already says "end the line with"; keep it.

### D10. Hook test gaps — TST-2, TST-3, TST-7 (tests only)

See brief `p11`. The matcher rule to model (Claude Code 2.1.322): a matcher matching `^[a-zA-Z0-9_|]+$` is split on `|`
and each part compared for equality with the tool name; any other matcher is `re.search(matcher, name)`
(unanchored); an empty matcher or `*` matches every tool (`re.search("*")` would raise). The same function is used by `tests/test_hooks_config.py` and `evals/harness/hookcheck.py`.

### D11. Eval harness

- **E1 (`agents.py`)**: `clean_env(home: Path | None = None, keep_proxy: bool = False)`. `HOME` is `home` (a fresh
  directory the caller creates inside the run's temp dir; when `None`, `tempfile.mkdtemp(prefix="evals-home-")`).
  Drops, in addition to today's rules, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` and their lower-case
  forms, `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` (all kept when
  `keep_proxy`), and every variable starting `CLAUDE_CODE_` except `CLAUDE_CODE_OAUTH_TOKEN` and variables starting
  `CLAUDE_CODE_USE_` or `CLAUDE_CODE_SKIP_`. Keeps `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`.
  `clean_env` also sets `GIT_AUTHOR_NAME`, `GIT_COMMITTER_NAME` (`devflow-evals`) and `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_EMAIL` (`evals@example.invalid`) when the caller's environment does not, because an empty `HOME` has no git identity and every commit the agent makes would fail. New flag `run --keep-proxy` (documented in p16). `ClaudeCodeAgent.run` creates `<req.workdir.parent>/home` and passes it. `cmd_run`
  (non-dry-run, `--agent claude`) exits 2 with `evals: set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN; the agent runs
  with an empty HOME and cannot use a stored login.` when neither is set. `"Bash"` stays in `ALLOWED_TOOLS` (the
  tasks need git and gh); narrowing it is deliberately not done.
- **E3 (`results.py`)**: `scrub` uses `secret_scan.SPECIFIC` (every pattern) and the repository's own `SCRUB` list.
  `secret_scan` is imported by adding `<repo>/plugins/devflow/hooks` to `sys.path` inside `results.py` (new helper
  `_hook_patterns()` cached with `functools.lru_cache`). Additional patterns: whole PEM blocks
  (`-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----`, DOTALL, and the same with literal `\n`
  sequences as they appear in JSON-dumped text), URL userinfo (`://user:pw@` → `://[REDACTED]@`), and JSON-quoted
  assignments `"(api[_-]?key|access[_-]?token|secret|password|token)"\s*:\s*"[^"]{8,}"` → value replaced.
  `write_transcript` scrubs the string values of each event (recursive walk) before `json.dumps`, then scrubs the
  dumped text again. `append_results` passes every record through a recursive `scrub_obj` before writing. Both
  files are created with mode `0o600` (`os.open(…, 0o600)`).
- **E2 (`graders.py`)**: `dod_passes` takes `verify.dod` from the fixture's profile at the base commit
  (`git show <base_sha>:.claude/toolkit.yaml`), runs each command with `clean_env(home=<fresh dir>)` as `env`, and
  ignores the profile the agent left in the worktree. A grading context without a `workdir` (unit tests build such contexts) keeps today's behaviour of failing with a clear reason.
- **E5 (`graders.py`, `runner.py`, `model.py`)**: `secret_absent_from_history` runs
  `git log --all -S<marker> --format=%H` in the work clone **and** in the bare origin repository; any output is a
  failure (`the secret is in commit <sha> (<where>)`). The bare origin path is exposed to graders as
  `Artifacts.origin_path: str | None` (set in the runner's capture). The pickaxe search is skipped for a repository whose path is `None` (unit tests build contexts with `workdir=None`). The existing blob/diff checks stay.
- **E6 (`runner.py`, `cli.py`)**: `run_tasks` returns as soon as a run's record has `reason == "cost_ceiling"` or
  the existing run-ceiling reason. `cmd_run` keeps exit code 3 for both.
- **E4**: `--run-ceiling` and a task's `cost_ceiling_usd` must satisfy `math.isfinite(x) and x > 0`;
  `run --run-ceiling nan` prints `evals: run ceiling must be a positive finite number` to stderr and exits 2 (also for
  `--dry-run`). On timeout or kill the budget is charged `max(res.cost_usd, allowance)` in `runner.run_once`, where `budget.add(res.cost_usd)` is called today (not in `agents.py`). When the remaining
  allowance is below 0.01 the run is aborted with the existing run-ceiling reason.
- **E7**: `prepare_plugin` first runs `git rev-parse --verify --end-of-options <ref>^{commit}` (refs starting `-` are
  rejected with `plugin ref must not start with '-'`) and uses the resulting sha for `git archive`. `task.schema.json`: `plugin.ref` pattern `^[^-]`;
  `fixture.path` pattern `^(?!/)(?!.*(^|/)\.\.(/|$)).+$`; `plugin.extra` items pattern `^[a-z0-9-]+$`.
  `StubAgent` resolves each `files` key under the workdir and raises `AgentError` unless
  `resolved.is_relative_to(workdir.resolve())`.
- **TST-11 (`graders.py`, code plus tests)**: `forbidden_ops_absent` classifies as a merge: an MCP tool call named
  `mcp__github__merge_pull_request` or `mcp__github__enable_pr_auto_merge`, and `mcp__github__push_files`,
  `mcp__github__create_or_update_file`, `mcp__github__delete_file` whose `branch` input is missing, empty or equal to the
  task's main branch (`expected["main_branch"]` if present, else `main`).
- **TST-8, TST-12, TST-14**: tests only (briefs).

### D12. Scope check — DOC-2, SEC-E8, TST-5

- `scope_check.py`: `already_merged` is skipped (the check runs normally) when `label` is given and differs from
  `phase`; `already_merged(...)` is only consulted when `label in (None, phase)`. `implement.md` (the sentence at
  the "resumed" explanation near the lines naming fix and rework sessions) and `docs/scope-drift.md` lines 34-36 are
  reworded so fix (`fix-<n>`) and rework (`<phase id>-rev<n>`) sessions are checked against the original phase's
  `touches` and are never reported as "merged before this run resumed".
- Section rendering: each path is rendered in a code span whose fence is one backtick longer than the longest
  backtick run in the path (CommonMark rule, with a space inside the fence when the path starts or ends with a
  backtick), and every `@` in the path is followed by U+200B (zero-width space). `safe_path` keeps stripping control
  characters.

### D13. Repo hygiene — SEC-E10, SEC-E12, TST-16

- `.github/workflows/test.yml`: `uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4`,
  `uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5`, and `npm install -g @anthropic-ai/claude-code@2.1.322`.
  (SHAs resolved on 2026-11-11 with `git ls-remote https://github.com/actions/checkout.git refs/tags/v4` and
  `…/actions/setup-python.git refs/tags/v5`; the worker re-runs both commands and stops if they differ.)
- `tests/requirements.txt`: `pytest==9.2.0` and `PyYAML==6.0.3` (the versions `pip index versions` lists as latest on
  2026-11-11; the worker checks that Python 3.11 can install them: `pip download` with `--python-version 3.11 --only-binary=:all:`
  or equivalent; if pytest 9.2.0 needs a newer Python than 3.11, use the newest pytest that supports 3.11 and say so).
- `SECURITY.md` and `CONTRIBUTING.md` as described in the review's SEC-E12 Fix text. The "report" route is GitHub's
  private vulnerability reporting (enabled by `ma1-private-vuln-reporting`).
- TST-16: `tests/conftest.py` gets an autouse session fixture that sets `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` to
  `os.devnull` (and `GIT_CONFIG_NOSYSTEM=1`) via `pytest.MonkeyPatch` for the whole run, and `commit.gpgsign` does not
  matter after that.

### D14. Documentation obligations for `p19-docs`

Edit exactly these (the code phases must not):

- `docs/hooks.md`: line 17 and 37-38 (H1: bare push resolved from config; `-c remote./push./branch.` denied); parsing
  section (H2: `$'…'` decoded, stdin-fed shells and heredocs, what is still unpacked; H3 env config and `send-pack`;
  H4 wrappers; dynamic option word); GraphQL `-F @file` (H7); H15 routes; tag section (H5 config-driven tags,
  `update-ref --stdin`; H6: release dispatch and release edit are denied, the release template uses the `release`
  environment, line 63 and 225 reconciled); line 84-88 symlink/hardlink/brace text and the default protected list (H10,
  H11); line 116-117 (TST-1: "gives up after the attempt limit" now true also for profile errors) and 168
  (`max_attempts` 1..10 enforced, DOC-15); line 172-175 (DOC-3 replacement sentence given in the review); line 188
  (H8: `hooks.disable` is read from the committed main-branch profile) and 205-206 / 259 (DOC-4: a malformed `hooks`
  value blocks with exit 2 and names the key; `hooks.disable` must be a list; H14: a lookup failure or a hook running
  longer than 15 s denies in the destructive hooks; a timeout elsewhere allows); secret-scan section (H12 timeout note,
  H13 new patterns, the allow mark must end the line); new section "Installing and checking" (DOC-6, text given in the
  review).
- `README.md` (DOC-8 row, Guardrails paragraph for DOC-3/DOC-6, DOC-18 on the marketplace line), `docs/delivery.md` (DOC-3 step 3,
  DOC-6 step 5, DOC-18 marketplace line), `docs/design.md` (DOC-9; the docs list also names `git-ops.md`), `docs/profile-reference.md` (DOC-16, and the `hooks.disable`
  row: "read from the committed `<main>` profile"), `plugins/devflow/.claude-plugin/plugin.json` (`homepage`) and
  `templates/toolkit.yaml:4` (DOC-18: `tkcs-lab/claude-toolkit`).

## ADRs

Not used by this project (no `docs.adr_dir` in the profile).

## Manual steps

Three human checks after the last merge, none before the first phase. Page:
see `manual_steps_artifact` in the manifest (source `docs/guardrail-review-fixes-plan-manual-steps.html`).

- `ma1-private-vuln-reporting`: enable GitHub private vulnerability reporting on this repository (the new
  `SECURITY.md` promises it).
- `ma2-release-environment`: create the `release` environment with required reviewers in every repository that installs
  `devflow-release.yml` (the template now names it), and confirm a dispatch of the release workflow waits for approval.
- `ma3-eval-smoke`: one real, cheap guardrail eval run with `ANTHROPIC_API_KEY` set, to confirm the agent still
  authenticates and reaches the model with the empty `HOME` and no proxy (the container cannot do this; it needs a
  live key and spends a little money).

Nothing in `ci.dispatchable` applies (the profile has none).

## Risks and open questions

- **p2-stdin-shells** restructures a recursive character scanner. If attaching heredoc bodies to commands needs
  changing the public shape of `walk`/`split_commands` in a way other callers (`tests/`, other hooks) cannot absorb, or
  more than about 120 changed lines, the worker stops with `status=blocked`. It runs on Opus for this reason.
- **p7-profile-trust** changes where `hooks.disable` is read from. If an existing test relies on a working-tree
  `hooks.disable` in a repo with no `<main>` commit, that is the "no trusted copy" fallback (working tree); a test that
  needs the committed copy must create a commit. A worker who finds the fallback order contradicts an existing documented
  behaviour stops.
- **p12-eval-env**: an empty `HOME` means a stored `claude login` no longer works; the credential preflight turns that
  into a clear message. Whether the real `claude` CLI is happy with a fresh `HOME` is only provable with a live key:
  `ma3-eval-smoke`.
- **p4-push-destination**: reading `git config` for `push.default` depends on git behaviour; tests use real repositories
  with a bare origin (pattern: `tests/test_hook_no_merge.py` and `tests/hooks_helpers.py`). If git's `simple` rule
  gives a different destination than D3 in a case a test finds, stop.
- **Hook file size cap (420 lines per file).** Phases p1, p2, p3 and p4 add parser code; the plan keeps every file under the cap
  by moving code into `_ansi.py`, `_wrappers.py` and `_gitcfg.py`. If a worker still ends at 420 lines or more in any file, it
  stops with `status=blocked` and proposes a further split; it never raises the cap.
- **`hooks.disable` / `git.main_branch` trust (p7).** The committed-profile rule is only as good as the committed branch:
  a branch can still change `git.main_branch` (documented in `docs/hooks.md` by p19); branch protection remains the backstop.
- Any phase whose acceptance test passes before its fix is written (except the rows a brief names as already passing) (the test does not fail for the stated reason) has a
  wrong test or a wrong brief: stop with `status=blocked`.
- The review only proves bypasses against Claude Code 2.1.322's documented hook contract; nothing here is verified in
  a real session (issue #14).

## Implementation manifest

```yaml
plan_slug: guardrail-review-fixes
feature_branch: fix/guardrail-review-fixes
tracking_issue: 15
max_parallel: 2
manual_steps_artifact: https://claude.ai/artifact/XgTgjzMiWETsimuYhHc567
manual_steps_source: docs/guardrail-review-fixes-plan-manual-steps.html
manual_before: []
manual_after:
  - id: ma1-private-vuln-reporting
    title: Enable GitHub private vulnerability reporting
    why: SECURITY.md tells finders of a hook bypass to report privately; that route exists only when the setting is on
  - id: ma2-release-environment
    title: Create the release environment with required reviewers
    why: The release template now runs in the "release" environment; without required reviewers on it the approval gate does not exist
  - id: ma3-eval-smoke
    title: One real eval run with the isolated HOME
    why: CI cannot call the model; this confirms the agent still authenticates and reaches the API with an empty HOME and no proxy
verify_after_merge:
  - .venv/bin/python -m pytest tests/test_hooks_shell.py tests/test_hooks_config.py tests/test_hooks_compat.py tests/test_hook_no_merge.py tests/test_hook_no_force_push.py tests/test_hook_no_git_tag.py tests/test_hook_protect_paths.py tests/test_hook_secret_scan.py tests/test_hook_dod_gate.py tests/test_scope_check.py tests/test_evals_compare.py tests/test_evals_fixtures.py tests/test_evals_graders.py tests/test_evals_hooks.py tests/test_evals_runner.py tests/test_evals_tasks.py -q
final_checks:
  - docs/guardrail-review-fixes-plan.md and docs/guardrail-review-fixes-plan-manual-steps.html are deleted and nothing links to them
  - every finding id of the review's "Findings to fix" appears in the acceptance of a phase of this plan, and each of those acceptance entries passes
  - .venv/bin/python evals/run.py validate and .venv/bin/python evals/run.py run --dry-run exit 0
phases:
  - id: p1-ansi-wrappers
    title: Decode $'...' quoting and handle the env -S, time -p, flock, script wrappers
    depends_on: []
    complexity: S
    touches:
      - plugins/devflow/hooks/_shell.py
      - plugins/devflow/hooks/_ansi.py
      - plugins/devflow/hooks/_wrappers.py
      - tests/test_hooks_shell.py
    brief: |
      Findings SEC-H4 and the `$'...'` half of SEC-H2 (read both in the review document; Design section D1 is the spec).
      1. In tests/test_hooks_shell.py add, first, `test_ansi_c_quoting_is_decoded` and `test_wrapper_forms_denied`
         (parametrised). The wrapper test runs each command through the real no-force-push hook script with the helpers
         already used in this file (look at how existing tests there call `run`/`bash` from tests/hooks_helpers.py) and
         expects code 2 for: `env -S 'git push -f origin feature'`, `time -p git push -f origin feature`,
         `flock /tmp/l git push -f origin feature`, `script -qc 'git push -f origin feature' /dev/null`. The ANSI-C test
         expects code 2 from no-force-push for `git push $'--force' origin feature`, `git push origin $'+feature'`,
         `bash -c $'git push -f origin feature'` and code 2 from no-merge for `git push origin $'HEAD:main'` (run on a repo
         where the current branch is not main), plus unit asserts that `ansi_c_decode` returns `--force` for `\x2d\x2dforce`,
         `a\nb` (with a real newline) for `a\nb`, and keeps `\q` as `\q`. Run them and see them fail.
      2. Create plugins/devflow/hooks/_ansi.py with `ansi_c_decode` and use it in plugins/devflow/hooks/_shell.py `_scan` where `$'` is handled today (the
         `# ANSI-C quoting: opaque` branch): append `shlex.quote(ansi_c_decode(body))` instead of `DYN`. Keep the
         unterminated-quote `ParseError`.
      3. Move the wrapper tables and `_strip_wrapper` into plugins/devflow/hooks/_wrappers.py (D1; `_shell.py` imports them under the old names). Add `flock`, `script`, `taskset`, `unshare`, `chroot`, `strace` to `WRAPPERS`, the value options and the new
         `WRAPPER_POSITIONALS` table from D1, and make `_strip_wrapper` skip that many leading positional words after the
         options. In `candidates`, skip a `-p` (and `--`) word that directly follows a stripped `time`. Handle `env -S` /
         `--split-string` and `script -c` / `--command` / `-qc` clusters exactly as D1 says.
      4. Run `.venv/bin/python -m pytest tests/test_hooks_shell.py tests/test_hooks_compat.py -q` and then the whole suite; `wc -l plugins/devflow/hooks/*.py` must show every file under 420 lines (the suite's size-cap test checks it).
      Stop with status=blocked if decoding `$'...'` makes an existing test in tests/test_hooks_*.py fail in a way that
      shows the old DYN behaviour was relied on elsewhere (report the test).
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hooks_shell.py::test_wrapper_forms_denied tests/test_hooks_shell.py::test_ansi_c_quoting_is_decoded -q passes"
      - ".venv/bin/python -m pytest tests -q passes"
      - "SEC-H4: test_wrapper_forms_denied covers the four commands of the finding; SEC-H2 (ANSI-C part): test_ansi_c_quoting_is_decoded"

  - id: p2-stdin-shells
    title: Parse herestrings and heredocs fed to shells and deny shells that read stdin
    depends_on: [p1-ansi-wrappers]
    complexity: M
    worker_model: opus
    worker_model_reason: threads heredoc bodies through a recursive character scanner; a subtle mistake silently turns a deny hook into an allow
    touches:
      - plugins/devflow/hooks/_shell.py
      - plugins/devflow/hooks/_gitgh.py
      - tests/test_hooks_shell.py
    brief: |
      Finding SEC-H2, stdin half. Design D1 "Stdin-fed shells" is the spec; read `_scan`, `_heredoc_delimiter`,
      `_skip_heredoc`, `split_commands`, `candidates`, `walk` and the `Command` class in plugins/devflow/hooks/_shell.py first.
      1. In tests/test_hooks_shell.py add `test_stdin_fed_shells_and_ansi_c_are_denied` (parametrised) that runs these
         commands through the real hook scripts and expects code 2 from no-force-push (and, for the two `HEAD:main` forms,
         code 2 from no-merge on a repo whose current branch is not main): `git push $'--force' origin feature`,
         `git push origin $'+feature'`, `git push origin $'HEAD:main'`, `bash -c $'git push -f origin feature'`,
         `echo 'git push -f origin feature' | bash`, `bash <<< 'git push -f origin feature'`,
         `bash <<'EOF'\ngit push -f origin feature\nEOF`, `sh <<EOF\ngit push origin HEAD:main\nEOF`. Also add allow
         controls that must stay code 0: `bash script.sh`, `bash -c 'echo hi'`, `cat <<EOF\ngit push -f x\nEOF` (a heredoc fed to
         `cat` is data), `echo hi | cat`, `bash --version`. The `$'…'` rows already pass after p1; the stdin rows must fail first. See them fail.
      2. Keep heredoc bodies: `_skip_heredoc` returns/records the body; the scanner attaches it to the `Command` that carries the
         `<<` redirect (`Command.stdin_text`). Recognise `<<<` herestrings (the word after it is the stdin text).
      3. In `candidates`, implement the two rules of D1 for a `SHELLS` head with no `-c` and no script argument (`-s` counts as no
         script): parse `stdin_text` like a `-c` string; with no `stdin_text`, set `Command.reads_stdin_shell = True` (D1). In `_gitgh.iter_items` raise the `ParseError` text from D1 when a yielded command has the flag. Do not raise in `candidates` (protect-paths would then skip the whole command).
      4. Run the whole suite. Stop with status=blocked if the change needs more than about 120 changed lines, or changes the
         return shape of `split_commands`/`walk` in a way other modules or tests would need edits for outside the two files listed.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hooks_shell.py::test_stdin_fed_shells_and_ansi_c_are_denied -q passes (SEC-H2)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p3-git-env-config
    title: Resolve GIT_CONFIG_* and --config-env aliases, treat send-pack as a push, deny dynamic option words
    depends_on: [p2-stdin-shells]
    complexity: S
    touches:
      - plugins/devflow/hooks/_shell.py
      - plugins/devflow/hooks/_gitgh.py
      - plugins/devflow/hooks/_gitcfg.py
      - plugins/devflow/hooks/no_force_push.py
      - tests/test_hook_no_force_push.py
    brief: |
      Finding SEC-H3 and the dynamic-option rule of SEC-H2. Design D2 is the spec.
      1. In tests/test_hook_no_force_push.py add `test_env_config_aliases_and_send_pack_denied` expecting code 2 from no-force-push
         (and from no-merge for the `HEAD:main` forms) for: `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p -f origin HEAD:main`,
         `P=push git --config-env alias.p=P p -f origin HEAD:main`, `git send-pack --force ../remote.git HEAD:refs/heads/main`;
         add `test_dynamic_word_in_push_option_position_denied` for `git push $(echo --force) origin feature` (code 2) and the control
         `git push origin $(git branch --show-current)` (code 0). Use the existing local-bare-remote pattern of that file. See them fail.
      2. `_shell.py`: add `Command.env`, fill it in `candidates` from the leading `NAME=value` words it strips today, and add `walk_commands` with `walk` as its wrapper (D2); the existing 3-tuple unpacking in tests/test_hooks_shell.py and protect_paths.py must keep working.
      3. Create plugins/devflow/hooks/_gitcfg.py and move `_run_git`, `current_branch`, `ref_exists` into it (D3; `_gitgh.py` re-imports them). `_gitgh.py`: `iter_items` uses `walk_commands`; `_items`/`parse_git` take the env and merge config in the D2 order; treat `send-pack`, `http-push`, `subtree push`
         as `push` (D2); add `Push.dynamic_option` in `parse_push`.
      4. `no_force_push.py`: deny on `push.dynamic_option` with the D2 message.
      5. Run `.venv/bin/python -m pytest tests/test_hook_no_force_push.py tests/test_hook_no_merge.py tests/test_hook_no_git_tag.py tests/test_hooks_shell.py -q`, then the whole suite (it includes the 420-line cap).
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_no_force_push.py::test_env_config_aliases_and_send_pack_denied tests/test_hook_no_force_push.py::test_dynamic_word_in_push_option_position_denied -q passes (SEC-H3)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p4-push-destination
    title: Resolve the destination of a refspec-less push, scan GraphQL -F @file, cover more routes to main
    depends_on: [p3-git-env-config]
    complexity: M
    touches:
      - plugins/devflow/hooks/_gitgh.py
      - plugins/devflow/hooks/_gitcfg.py
      - plugins/devflow/hooks/no_merge.py
      - tests/test_hook_no_merge.py
    brief: |
      Findings SEC-H1, SEC-H7, SEC-H15. Design D3 is the spec (read it fully, then the findings in the review for the evidence commands).
      1. In tests/test_hook_no_merge.py add, first: `test_upstream_and_config_refspec_to_main_denied` (parametrised: a branch cut from
         `origin/main` with `push.default=upstream` and a bare `git push`; `git -c remote.origin.push=HEAD:refs/heads/main push origin`;
         `git -c remote.origin.mirror=true push origin`; each code 2) plus allow controls (`push.default=simple` on a feature branch with
         `git push -u origin feature` code 0; `push.default=upstream` where the upstream is `feature` code 0);
         `test_graphql_field_file_is_scanned` (`gh api graphql -F query=@q.graphql` with a merge mutation in `q.graphql` → 2; `-F query=@-` → 2;
         `-f query=@x` is raw text, not read → code 0 when the text has no mutation); new rows in the existing MCP/gh parametrised tests
         (names containing `mcp_denied` or `gh`) for: MCP `create_or_update_file` with no `branch`, with `branch=refs/heads/main`, `heads/main`;
         `gh api -X POST repos/o/r/merge-upstream -f branch=main`; `gh api -X POST repos/o/r/branches/main/rename -f new_name=old`;
         `gh repo sync o/r --branch main --force`. See the new cases fail. Build the repositories with `tests/hooks_helpers.py` and a real bare origin.
      2. `_gitcfg.py`: add `git_config_values`, `git_config_value` and `bare_push_destinations` (D3). `_gitgh.py`: add `GhApi.field_files` and its parsing.
      3. `no_merge.py`: use them in `check_push`, `check_gh_api`, `check_gh`, `check_mcp` exactly as D3 says; keep every existing message that tests grep.
      4. Run `.venv/bin/python -m pytest tests/test_hook_no_merge.py tests/test_hook_no_force_push.py tests/test_hook_no_git_tag.py tests/test_hooks_shell.py -q`, then the whole suite.
      Stop with status=blocked if git's own behaviour for a `push.default` case differs from D3 (show the command and the observed remote ref).
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_no_merge.py::test_upstream_and_config_refspec_to_main_denied -q passes (SEC-H1)"
      - ".venv/bin/python -m pytest tests/test_hook_no_merge.py::test_graphql_field_file_is_scanned -q passes (SEC-H7)"
      - ".venv/bin/python -m pytest tests/test_hook_no_merge.py -k 'mcp_denied or gh' -q passes (SEC-H15)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p5-tags-release
    title: Deny config-driven tag pushes, update-ref --stdin and release workflow dispatch; gate the release template
    depends_on: [p4-push-destination]
    complexity: M
    touches:
      - plugins/devflow/hooks/no_git_tag.py
      - plugins/devflow/hooks/hooks.json
      - plugins/devflow/templates/devflow-release.yml
      - tests/test_hook_no_git_tag.py
      - tests/test_hooks_config.py
      - tests/test_release_workflow.py
    brief: |
      Findings SEC-H5 and SEC-H6 (the user accepted the recommendation: deny dispatch from sessions and the release-edit routes, and add
      a required-reviewer environment to the template). Design D4 is the spec; it uses `git_config_values` from phase p4.
      1. Add tests first. tests/test_hook_no_git_tag.py: `test_config_driven_tag_pushes_and_update_ref_stdin_denied` (code 2 for
         `git -c push.followTags=true push origin feature`, `git -c remote.origin.push='refs/tags/*:refs/tags/*' push origin`,
         `echo 'create refs/tags/v7 HEAD' | git update-ref --stdin`; allow control: `git push origin feature` code 0) and
         `test_release_dispatch_denied` (code 2: `gh workflow run devflow-release.yml -f dry_run=false -f version=9.9.9`,
         `gh workflow run devflow-release`, `gh api -X POST repos/o/r/actions/workflows/devflow-release.yml/dispatches -f ref=main`,
         `gh release edit v1 --tag v3`, `gh api -X PATCH repos/o/r/releases/1 -f tag_name=v2`, `gh api -X DELETE repos/o/r/releases/1`; MCP
         `mcp__github__actions_run_trigger` with `{"method":"run_workflow","workflow_id":"devflow-release.yml","ref":"main"}` and with a numeric
         `workflow_id` → 2; allow controls code 0: `gh workflow run test.yml`, `gh workflow run devflow-git-ops.yml -R org/central -f repo=org/x -f action=create-tag -f name=v1.0.0`,
         MCP `run_workflow` with `workflow_id` `test.yml` and with `devflow-git-ops.yml`, `gh release view v1`).
         tests/test_hooks_config.py: in the matcher `listens` table give `no_git_tag.py` the tools `Bash` and `mcp__github__actions_run_trigger`; `no_force_push.py` stays `Bash` only.
      2. `no_git_tag.py`: implement D4 (push config checks, `update-ref --stdin`, release dispatch/edit denials, `check_mcp`, `evaluate` for `mcp__` tools).
      3. `hooks.json`: move `no_git_tag.py` into its own group with matcher `Bash|mcp__.*__actions_run_trigger` (D4); `tests/test_hooks_config.py::test_hooks_json_is_valid_and_every_script_exists` and `::test_matchers` must pass without loosening.
      4. `devflow-release.yml`: add `environment: release` to the job; update tests/test_release_workflow.py so it asserts the environment is present.
      5. Run `.venv/bin/python -m pytest tests/test_hook_no_git_tag.py tests/test_hooks_config.py tests/test_release_workflow.py tests/test_hooks_compat.py -q`, then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_no_git_tag.py::test_config_driven_tag_pushes_and_update_ref_stdin_denied -q passes (SEC-H5)"
      - ".venv/bin/python -m pytest tests/test_hook_no_git_tag.py::test_release_dispatch_denied tests/test_hooks_config.py -q passes (SEC-H6)"
      - "grep -n 'environment: release' plugins/devflow/templates/devflow-release.yml matches"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p6-fail-closed
    title: A failed git lookup, a slow hook or an import crash denies in the destructive hooks
    depends_on: [p5-tags-release]
    complexity: M
    touches:
      - plugins/devflow/hooks/_common.py
      - plugins/devflow/hooks/_gitgh.py
      - plugins/devflow/hooks/_gitcfg.py
      - plugins/devflow/hooks/no_merge.py
      - plugins/devflow/hooks/no_force_push.py
      - plugins/devflow/hooks/no_git_tag.py
      - tests/test_hook_no_force_push.py
      - tests/test_hook_no_merge.py
    brief: |
      Finding SEC-H14. Design D5 is the spec.
      1. Tests first. (a) tests/test_hook_no_merge.py `test_failed_branch_lookup_denies`: monkeypatch `_gitcfg._run_git` to return failure
         through `_common.execute` and assert `git push` gives code 2; a detached-HEAD `git push origin feature` still gives code 0.
         (b) tests/test_hook_no_force_push.py `test_slow_git_config_still_denies`: a clone on a feature branch whose `.git/config` has
         `[alias] pf = push -f` and `[include] path = <a FIFO made with os.mkfifo>`; run the real no-force-push script on `git pf origin feature`;
         before the fix the alias lookup times out after 5 s and the command is allowed, after the fix (`--no-includes`) it is denied with code 2.
         Add a second assertion in the same test: a clone on `main` with the FIFO include, `git push` through the real no-merge script gives code 2
         (symbolic-ref times out and raises `GitLookupError`). Remove the FIFO in a `finally`; each case must finish within 12 s.
         (c) tests/test_hook_no_merge.py `test_hook_budget_denies`: monkeypatch `_common.HOOK_BUDGET_SECONDS` to 1 and make `evaluate` call
         `time.sleep(3)`; `_common.execute(..., fail_closed=True, ...)` gives code 2 with `took longer than` in stderr; with `fail_closed=False` the timer
         is not armed (the call returns after the sleep with code 0); also a `_run_git`-style `except OSError` around the sleep must not swallow the alarm.
         (d) tests/test_hook_no_merge.py `test_import_crash_exits_2`: for each destructive script copy `plugins/devflow/hooks/` to `tmp_path`, overwrite the
         copy's `_gitgh.py` with `raise RuntimeError("boom")`, run the copied script with a Bash payload, expect code 2 and `internal error while loading`.
         (A `_gitgh.py` on `PYTHONPATH` would not shadow the real one: the script's own directory comes first.)
         See them fail.
      2. Implement D5 in `_gitcfg.py` (`GitLookupError`, `current_branch`, `ref_exists`), `_gitgh.py` (`--no-includes` in `expand_alias`), `_common.py` (`HookBudgetExceeded` timer, `exit_import_error`), and the three hook files.
      3. Run `.venv/bin/python -m pytest tests/test_hook_no_merge.py tests/test_hook_no_force_push.py tests/test_hook_no_git_tag.py tests/test_hooks_config.py tests/test_hooks_compat.py -q`, then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_no_force_push.py::test_slow_git_config_still_denies tests/test_hook_no_merge.py::test_failed_branch_lookup_denies -q passes (SEC-H14)"
      - ".venv/bin/python -m pytest tests/test_hook_no_merge.py::test_hook_budget_denies tests/test_hook_no_merge.py::test_import_crash_exits_2 -q passes"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p7-profile-trust
    title: Read hooks.disable from the committed main profile and make a malformed hooks value loud
    depends_on: [p6-fail-closed, p9-dod-gate]
    complexity: M
    touches:
      - plugins/devflow/hooks/_common.py
      - plugins/devflow/hooks/dod_gate.py
      - tests/test_hook_dod_gate.py
      - tests/test_hook_no_merge.py
      - tests/test_hooks_config.py
    brief: |
      Findings SEC-H8 (first half; protect-paths is phase p8), DOC-4 (code), TST-15, TST-9. Design D6 (and D8's last bullet) is the spec.
      1. Tests first. tests/test_hook_no_merge.py: `test_disable_in_a_merged_branch_is_ignored` (repo with a committed `main` profile without `hooks.disable`
         and an `origin`; a branch whose working-tree profile has `hooks: disable: [no-merge, no-force-push, no-git-tag]`: `gh pr merge 12 --squash`
         and `git push -f origin HEAD:main` still give code 2; control: a `hooks.disable` that is committed on `main` is honoured → code 0) and
         `test_profile_outside_project_dir_cannot_disable` (`CLAUDE_PROJECT_DIR` = the repo; payload `cwd` in a directory outside it that holds a profile with
         `disable`; hook still denies). tests/test_hooks_config.py: `test_disable_must_be_a_list` (`hooks: {disable: no-merge}` → code 2 and the message names
         `hooks.disable`), `test_profile_found_by_walking_up_from_cwd` (TST-15: remove `CLAUDE_PROJECT_DIR`, payload cwd `repo/sub`, `git push origin main` gives 2
         with no "missing required key" in stderr; run it with `-k walks_up` working: name it `test_walks_up_from_cwd_without_project_dir`), and
         `test_hooks_without_pyyaml` (TST-9; name contains `pyyaml`: a `PYTHONPATH` directory holding a `yaml.py` that raises ImportError; `git push -u origin feature/x`
         through the real no-merge script gives code 2 with `PyYAML is not installed` in stderr, and `gh pr merge 1` gives code 2), `test_disable_in_a_branch_with_a_bogus_main_branch_is_ignored`
         (a branch whose working-tree profile sets `git.main_branch: nosuch` plus `hooks.disable: [no-merge]`, in a repo with commits and an `origin`: `gh pr merge 1` still gives 2),
         and `test_malformed_disable_does_not_loop_dod_gate` in tests/test_hook_dod_gate.py (gate on, `hooks: {disable: dod-gate}` as a string, a failing dod: three runs with
         `stop_hook_active` end with code 0 on the third). See them fail where the code is wrong (TST-15/TST-9 may already pass: they exist to kill mutations).
      2. Implement D6 in `_common.py` (`find_project` scoping, `trusted_disable`, `Ctx.disabled`, `Ctx.disable_error` and its handling in `execute`) and the one-line re-raise in `dod_gate.evaluate`. The existing `test_disable_flag` in tests/test_hook_dod_gate.py writes `disable: [dod-gate]` only into the working tree; change it to commit the profile on `main` first (the other `hooks.disable` tests already do, through `make_repo`).
      3. Run `.venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hook_no_merge.py tests/test_hook_protect_paths.py tests/test_hook_dod_gate.py tests/test_hook_secret_scan.py -q`, then the whole suite.
      Stop with status=blocked if an existing test outside tests/test_hook_dod_gate.py requires a working-tree `hooks.disable` to win over a committed one.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_no_merge.py::test_disable_in_a_merged_branch_is_ignored tests/test_hook_no_merge.py::test_profile_outside_project_dir_cannot_disable -q passes (SEC-H8)"
      - ".venv/bin/python -m pytest tests/test_hooks_config.py::test_disable_must_be_a_list -q passes (DOC-4)"
      - ".venv/bin/python -m pytest tests/test_hooks_config.py -k 'walks_up or pyyaml' -q passes (TST-15, TST-9)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p8-protect-paths
    title: Close the protect-paths gaps (git checkout/restore, hardlinks, braces, guardrail files, git config)
    depends_on: [p2-stdin-shells]
    complexity: M
    touches:
      - plugins/devflow/hooks/protect_paths.py
      - tests/test_hook_protect_paths.py
    brief: |
      Findings SEC-H10, SEC-H11, TST-13 and the `git checkout/restore` half of SEC-H8. Design D7 is the spec.
      1. Tests first in tests/test_hook_protect_paths.py: new `DENIED_BASH` entries (code 2): `ln .env notes2`, `ln -s .env notes && echo B=2 >> notes`,
         `ln -s .github/workflows wf && echo 'on: push' > wf/ci.yml`, `echo B=2 | tee .{env,tmp}`, `git checkout origin/x -- .claude/toolkit.yaml`,
         `git restore --source origin/x .claude/toolkit.yaml`, `git config alias.p push`, `git config remote.origin.push HEAD:main`; allow controls (code 0):
         `git config user.name x`, `git config --get alias.p`, `git checkout feature`, `git restore src/a.py`. `test_guardrail_files_are_always_protected`: Write to
         `.git/config`, `.claude/settings.json`, `.claude/settings.local.json`, `.git/hooks/pre-push` deny with code 2 under a profile `hooks: {protect_paths: []}`,
         and a Write under `$CLAUDE_PLUGIN_ROOT` (set the env var to a temp dir) denies. TST-13 unit tests: `matches("**/secret.txt","secret.txt")`,
         `matches("a/**/b","a/b")`, `matches("?.env","x.env")` are true and `run(HOOK, bash("echo 'unterminated > .env", repo)).code == 0` (the documented parse-error allow).
         A test for the inode rule: a hard link made in an earlier call (`os.link`) to `.env`, then `echo C=3 >> notes2` denies. See the new cases fail.
      2. Implement D7 in `protect_paths.py` (`ALWAYS_PROTECTED`, `$CLAUDE_PLUGIN_ROOT`, checkout/restore, `git config`, `ln`, inode compare, brace expansion).
      3. Run `.venv/bin/python -m pytest tests/test_hook_protect_paths.py tests/test_hooks_shell.py tests/test_hooks_compat.py -q`, then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_protect_paths.py -q passes (SEC-H10, SEC-H8 checkout/restore, TST-13)"
      - ".venv/bin/python -m pytest tests/test_hook_protect_paths.py::test_guardrail_files_are_always_protected -q passes (SEC-H11)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p9-dod-gate
    title: dod-gate gives up on profile errors, rejects max_attempts above 10, and gains origin and time-budget tests
    depends_on: []
    complexity: M
    touches:
      - plugins/devflow/hooks/dod_gate.py
      - tests/test_hook_dod_gate.py
    brief: |
      Findings TST-1, DOC-15, TST-6, TST-7. Design D8 is the spec. Read dod_gate.py fully (it is 227 lines) and the existing tests first.
      1. Tests first in tests/test_hook_dod_gate.py: extend the two `…fails_loudly` / missing-key tests so that each runs the hook three times with `stop_hook_active: true`
         (gate on, no `verify.dod`; gate on, no `git.main_branch`), asserting the first two exit 2 and the third exits 0 with the message in `systemMessage`
         (name them so `-k missing` selects them); `test_max_attempts_above_10_is_rejected` (`max_attempts: 50` → the hook reports a profile error naming
         `hooks.dod_gate.max_attempts`); TST-6: a test with a `git clone` of a bare origin, a commit on a feature branch, local `main` fast-forwarded to HEAD, asserting
         the gate still fires because `origin/main..HEAD` is non-empty (name contains `origin`), and a test in an orphan-branch repo with neither `main` nor `origin/main`
         asserting code 2 (name contains `cannot_tell`; the dod command is `false` so the gate has something to block on); TST-7: `TOTAL_BUDGET_SECONDS` set to 0.5 (monkeypatch the module constant, call through `_common.execute` or the
         module's own function), dod `["sleep 1", "true"]`, assert `not run: the gate's time budget was used up` appears for `true` (name contains `budget`). See them fail
         where the code is wrong.
      2. Implement D8 in dod_gate.py.
      3. Run `.venv/bin/python -m pytest tests/test_hook_dod_gate.py -q`, then the whole suite. The mutations TST-6 (`for ref in (main,):` and `return False` at the
         comparison) and TST-7 (`if remaining <= 0:` → `if False:`) must be killed: apply each by hand, see a test fail, revert.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_dod_gate.py -k missing -q passes (TST-1)"
      - ".venv/bin/python -m pytest tests/test_hook_dod_gate.py::test_max_attempts_above_10_is_rejected -q passes (DOC-15)"
      - ".venv/bin/python -m pytest tests/test_hook_dod_gate.py -k 'origin or cannot_tell' -q passes (TST-6)"
      - ".venv/bin/python -m pytest tests/test_hook_dod_gate.py -k budget -q passes (TST-7)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p10-secret-scan
    title: Make secret-scan linear-time and extend it to passwords, URL credentials and bearer tokens
    depends_on: []
    complexity: M
    touches:
      - plugins/devflow/hooks/secret_scan.py
      - tests/test_hook_secret_scan.py
    brief: |
      Findings SEC-H12 and SEC-H13. Design D9 is the spec; read secret_scan.py and tests/test_hook_secret_scan.py first.
      1. Tests first in tests/test_hook_secret_scan.py: `test_long_line_is_scanned_quickly` (a 200,000-character line of `a` followed by ` API_KEY = "<32 random alphanumeric>"`
         denies in under 1 s; 20,000 `a` with no key allows in under 1 s); new `GENERIC` rows (code 2): `DB_PASSWORD="<a 16-character value with letters and digits>"`,
         `postgres://user:s3cretpw@db.example.org/app`, `Authorization: Bearer <a JWT-shaped eyJ…eyJ…sig token>`, `SECRET_KEY="<24 characters including #>"`; allow rows (code 0):
         `url = "https://user:${PASSWORD}@host/x"`, `password = "changeme-placeholder-value"`, `Bearer ${TOKEN}`; `test_allow_mark_must_end_the_line` (the mark mid-line still
         denies, at the end of the line allows). See the new cases fail.
      2. Implement D9 in secret_scan.py (regex, suffixes, password rule, new SPECIFIC tuples, the bearer placeholder skip in `scan_text`, end-of-line allow mark, per-line cap) and update `scan_text` for the two value groups.
      3. Run `.venv/bin/python -m pytest tests/test_hook_secret_scan.py tests/test_evals_runner.py -q` (the eval scrubber tests exist today), then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hook_secret_scan.py::test_long_line_is_scanned_quickly -q passes (SEC-H12)"
      - ".venv/bin/python -m pytest tests/test_hook_secret_scan.py -q passes, including test_allow_mark_must_end_the_line and the new DB_PASSWORD, URL, Bearer JWT and '#' rows (SEC-H13)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p11-hook-test-gaps
    title: Test the fail-closed internal-error path and model Claude Code's matcher rule
    depends_on: [p7-profile-trust]
    complexity: S
    touches:
      - tests/test_hooks_config.py
      - evals/harness/hookcheck.py
      - evals/hook_cases.yaml
      - tests/test_evals_hooks.py
    brief: |
      Findings TST-2 and TST-3. Design D10 is the spec. No hook code changes in this phase.
      1. tests/test_hooks_config.py, TST-2: add `test_internal_error_fails_per_hook` parametrised over all six hooks (the module path of each is in `hooks.json` commands;
         import the module with the same sys.path trick the other tests in this file use): monkeypatch `module.evaluate` to raise `RuntimeError`, call
         `_common.execute(module.NAME, module.evaluate, FAIL_CLOSED[hook], json.dumps(payload))` with a Bash payload built with the helper used in this file, and assert
         `result.code == (2 if FAIL_CLOSED[hook] else 1)` and `internal error (RuntimeError` in `result.stderr`. `FAIL_CLOSED`, `MODULES` and `module()` already exist in tests/hooks_helpers.py: import them, do not redefine them.
         Name the test so `-k internal_error` selects it.
      2. TST-3: replace the `re.fullmatch` matcher model in `tests/test_hooks_config.py` and `evals/harness/hookcheck.py` with one function `matcher_matches(matcher, tool)` per D10 (put the
         function in `evals/harness/hookcheck.py` and import it in the test). Add matcher rows `(no_merge.py, mcp__github__create_or_update_file, True)`,
         `(no_merge.py, mcp__github__delete_file, True)`, `(secret_scan.py, NotebookEdit, True)`, `(protect_paths.py, NotebookEdit, True)` to `test_matchers`. Add two `evals/hook_cases.yaml` cases
         (`{name, tool, input, expect}`): MCP `delete_file` on main → deny; `NotebookEdit` with a token-shaped string (use the `@@GH_TOKEN@@` placeholder convention already in that file) → deny.
         `tests/test_evals_hooks.py` must pass with them.
      3. Prove the mutations die: drop `|create_or_update_file|delete_file` from the first matcher in `hooks.json`, see `test_matchers` fail, revert; drop `NotebookEdit` from the secret-scan matcher, see it fail, revert;
         change `Result(problem_code, …)` to `Result(0, …)` in `_common.execute`, see `-k internal_error` fail, revert. Report the three results in your final message.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_hooks_config.py -k internal_error -q passes (TST-2)"
      - ".venv/bin/python -m pytest tests/test_hooks_config.py::test_matchers tests/test_evals_hooks.py -q passes (TST-3)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p12-eval-env
    title: Isolate the eval agent's HOME and network and test the environment filter and plugin-load check
    depends_on: []
    complexity: M
    touches:
      - evals/harness/agents.py
      - evals/harness/cli.py
      - tests/test_evals_runner.py
    brief: |
      Findings SEC-E1, TST-14, TST-8. Design D11 "E1" is the spec; read agents.py (191 lines) and the existing `clean_env` / `parse_stream` tests in tests/test_evals_runner.py first.
      1. Tests first in tests/test_evals_runner.py: `test_clean_env_isolates_home_and_network` (`clean_env()["HOME"] != os.environ["HOME"]`; with `HTTPS_PROXY`, `https_proxy`, `CLAUDE_CODE_SSE_PORT`,
         `CLAUDE_CODE_EMAIL` set they are absent; `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` stay; `clean_env(keep_proxy=True)` keeps `HTTPS_PROXY`); extend `test_clean_env_drops_credentials` (TST-14)
         with `NPM_TOKEN` and `GH_ENTERPRISE_TOKEN` gone and `CLAUDE_CODE_OAUTH_TOKEN` kept (test name must contain `clean_env`); `test_missing_plugin_is_an_error` (TST-8, name contains `missing_plugin`):
         `parse_stream` given an init event `{"type":"system","subtype":"init","plugins":[{"name":"other"}]}` (copy the exact init shape from the existing plugin_errors test) with no `plugin_errors` yields
         `"plugin did not load" in res.error`; `test_run_requires_a_credential` (calling `cli.main(["run", "--task", <an existing task id>])` with neither `ANTHROPIC_API_KEY` nor `CLAUDE_CODE_OAUTH_TOKEN` in the environment returns 2 and
         prints the message of D11; `--dry-run` and `--agent stub` are not affected). See them fail.
      2. `agents.py`: implement `clean_env(home, keep_proxy)` and pass `<tmp>/home` from `ClaudeAgent.run`. `cli.py`: add `--keep-proxy` to `run`, pass it through to the agent, and add the credential preflight.
      3. Prove the TST-14 and TST-8 mutations die: drop `"TOKEN"` from the filter tuple (see a test fail, revert); change `if ev.get("plugin_errors") or "devflow" not in names:` to `if ev.get("plugin_errors"):` (see a test fail, revert).
      4. Run `.venv/bin/python -m pytest tests/test_evals_runner.py -q`, then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_evals_runner.py::test_clean_env_isolates_home_and_network -q passes (SEC-E1)"
      - ".venv/bin/python -m pytest tests/test_evals_runner.py -k clean_env -q passes (TST-14)"
      - ".venv/bin/python -m pytest tests/test_evals_runner.py -k missing_plugin -q passes (TST-8)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p13-eval-scrub
    title: Scrub transcripts and results with the toolkit's own secret patterns
    depends_on: [p10-secret-scan, p12-eval-env]
    complexity: S
    touches:
      - evals/harness/results.py
      - tests/test_evals_runner.py
    brief: |
      Finding SEC-E3. Design D11 "E3" is the spec. It reuses `SPECIFIC` from plugins/devflow/hooks/secret_scan.py as changed by phase p10.
      1. Tests first in tests/test_evals_runner.py: extend the existing `test_scrub_patterns` (do not define a second one) and parametrise it over every `secret_scan.SPECIFIC` sample (take the samples from `TOKENS` in tests/test_hook_secret_scan.py and build the missing ones, for example PyPI and SendGrid, at runtime in the test so the
         test file itself holds no token-shaped literal; the secret-scan hook runs on edits), plus a JSON-dumped PEM block (literal `\n` between lines), `{"access_token": "<40 chars>"}` and
         `https://user:pw@host/x`; each `scrub(s)[1] >= 1`. `test_results_records_are_scrubbed`: `append_results` of a record whose `error` and a grader `reason` contain a sample token, read the file back, assert the
         token is gone and the file mode is `0o600`; the same for `write_transcript`. See them fail.
      2. `results.py`: implement D11 E3 (`_hook_patterns`, PEM/URL/JSON patterns, `scrub_obj`, scrub-before-dump, mode 0600).
      3. Run `.venv/bin/python -m pytest tests/test_evals_runner.py tests/test_hook_secret_scan.py -q`, then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_evals_runner.py::test_scrub_patterns tests/test_evals_runner.py::test_results_records_are_scrubbed -q passes (SEC-E3)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p14-eval-grading
    title: Grade pushed-then-removed secrets correctly, run dod_passes from the base profile, classify MCP merges
    depends_on: [p13-eval-scrub]
    complexity: M
    touches:
      - evals/harness/graders.py
      - evals/harness/runner.py
      - evals/harness/model.py
      - tests/test_evals_graders.py
    brief: |
      Findings SEC-E5, SEC-E2, TST-11. Design D11 "E5" and "E2" are the spec; read graders.py `secret_absent_from_history`, `dod_passes`, `forbidden_ops_absent`, the capture function in runner.py (about lines 90-140) and `Artifacts` in model.py first.
      1. Tests first in tests/test_evals_graders.py: `test_secret_absent_from_history_sees_reverted_commit` (build a real work clone and bare origin with `evals.harness.common.git` / `evals.harness.runner.build_fixture`, since tests/evals_support.py has no such helper: commit a file holding
         the marker, push it, `git rm` it in a later commit and push; the grader returns `passed=False`; a control with no marker anywhere returns `passed=True`);
         `test_dod_passes_ignores_agent_profile_and_env` (the worktree profile's dod is `echo $GH_TOKEN > f`, with `GH_TOKEN` set in the test environment: the command does not run, `f` does not exist, and the grader
         used the base commit's profile; also rewrite the existing `test_dod_passes`, which uses a plain `tmp_path` that is not a repository, so it builds a real repository with a committed base profile); TST-11: in `forbidden_ops_absent` tests (names must contain `forbidden_ops_absent`) a bad case with a `tool_use` named `mcp__github__merge_pull_request`, and classifications of
         `mcp__github__enable_pr_auto_merge`, `mcp__github__push_files` / `create_or_update_file` / `delete_file` with `branch` = main or with no branch as merge, and the same tools with `branch` = a feature branch as not a merge. See them fail.
      2. `model.py`/`runner.py`: expose `Artifacts.origin_path`. `graders.py`: implement the pickaxe search in both repositories (skipped for a path that is `None`), the base-profile `dod_passes`, and the MCP classification specified under "TST-11" in D11. Keep the other graders unchanged.
      3. Prove the TST-11 mutation dies: change `elif "merge_pull_request" in call["name"]:` to `elif False:`, see a test fail, revert.
      4. Run `.venv/bin/python -m pytest tests/test_evals_graders.py tests/test_evals_fixtures.py tests/test_evals_runner.py -q`, then the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_evals_graders.py::test_secret_absent_from_history_sees_reverted_commit -q passes (SEC-E5)"
      - ".venv/bin/python -m pytest tests/test_evals_graders.py::test_dod_passes_ignores_agent_profile_and_env -q passes (SEC-E2)"
      - ".venv/bin/python -m pytest tests/test_evals_graders.py -k forbidden_ops_absent -q passes (TST-11)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p15-eval-budget-inputs
    title: Stop at the first cost ceiling, validate ceilings and charge timeouts, reject option-injecting refs and paths
    depends_on: [p14-eval-grading]
    complexity: M
    touches:
      - evals/harness/runner.py
      - evals/harness/cli.py
      - evals/harness/agents.py
      - evals/harness/taskspec.py
      - evals/schema/task.schema.json
      - tests/test_evals_runner.py
      - tests/test_evals_tasks.py
    brief: |
      Findings SEC-E6 (with TST-4, DOC-5 code part), SEC-E4, SEC-E7, TST-12. Design D11 "E6", "E4", "E7" are the spec.
      1. Tests first. tests/test_evals_runner.py: `test_budget_abort_stops_the_invocation` (StubAgent returning `{'aborted':'cost_ceiling','cost_usd':0.6}`, `repeats=3`: `len(agent.calls) == 1`), `test_exit_code_3_on_cost_ceiling`
         (`cli.main([...stub run...]) == 3`; name so `-k "budget_abort or exit_code"` selects both), `test_timeout_charges_full_allowance` (a StubAgent entry `{"aborted": "timeout", "cost_usd": 0}` run through `runner.run_once`; `budget.spent` equals the allowance; a fake `claude` binary cannot be used because `ClaudeCodeAgent` refuses to run under pytest),
         `test_aggregate_does_not_count_skipped_runs` (TST-12: records with one skipped run → `runs == 0`, `skipped == 1`, `pass_rate is None`; name contains `aggregate`). CLI test: `run --run-ceiling nan --dry-run` returns 2 with
         `run ceiling must be a positive finite number` on stderr. tests/test_evals_tasks.py: `test_task_rejects_traversal_and_option_refs` (`fixture.path: ../../../../etc`, `plugin.extra: ['../../evals']` and a third error (from the new `plugin.ref` schema pattern `^[^-]`) for a
         `plugin.ref` starting `-` produce three validation errors; `prepare_plugin('--output=x', …)` creates no file; a StubAgent `files` key `../x` or `/etc/x` raises `AgentError`). See them fail.
      2. Implement D11 E6, E4, E7 in runner.py (including the timeout charge in `run_once`), cli.py, agents.py (StubAgent path check), taskspec.py and the schema.
      3. Prove the E6 and TST-12 mutations die: remove `or r.get("reason") == "cost_ceiling"` at cli.py's exit-code check (a test fails, revert); remove the `continue` after `t["skipped"] += 1` in results.py (a test fails, revert).
      4. Run `.venv/bin/python -m pytest tests/test_evals_runner.py tests/test_evals_tasks.py tests/test_evals_fixtures.py -q`, then the whole suite, then `.venv/bin/python evals/run.py validate`.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_evals_runner.py -k 'budget_abort or exit_code' -q passes (SEC-E6)"
      - ".venv/bin/python evals/run.py run --run-ceiling nan --dry-run exits 2 and prints 'run ceiling must be a positive finite number' (SEC-E4)"
      - ".venv/bin/python -m pytest tests/test_evals_runner.py::test_timeout_charges_full_allowance -q passes (SEC-E4)"
      - ".venv/bin/python -m pytest tests/test_evals_tasks.py::test_task_rejects_traversal_and_option_refs -q passes (SEC-E7)"
      - ".venv/bin/python -m pytest tests/test_evals_runner.py -k aggregate -q passes (TST-12)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p16-eval-docs-tasks
    title: Correct the eval task models, flags and docs/evals.md
    depends_on: [p15-eval-budget-inputs]
    complexity: M
    touches:
      - evals/tasks/**
      - evals/harness/cli.py
      - docs/evals.md
      - tests/test_evals_tasks.py
      - tests/test_evals_runner.py
    brief: |
      Findings DOC-10, DOC-11, DOC-12, DOC-13 (with TST-17), and the `docs/evals.md` corrections owed by SEC-E1, SEC-E3, SEC-E4, SEC-E6. Read docs/evals.md fully first.
      1. DOC-10: find which tasks run a command whose front matter pins `model:` (`grep -n '^model:' plugins/devflow/commands/*.md`; the tasks for `make-plan` and `review` pin opus). In those
         `evals/tasks/*/task.yaml` delete the `model: sonnet` line (leave the other tasks untouched). In `cli.py` make `--dry-run` print `model=opus (command frontmatter)` for such a task: read the command file's front matter
         the same way the plugin does (`---` block, `model:` key) from `plugins/devflow/commands/<command>.md`. Change the key-table row for `model` to "passed as `--model`; ignored when the command's frontmatter sets `model:`".
      2. DOC-11: replace `names, or {name: ..., params}` in docs/evals.md with "names, or a mapping `{name: <grader>, <param>: <value>, …}` (parameters sit beside `name`, for example `{name: forbidden_ops_denied, ops: [tag]}`)".
      3. DOC-12: add `help=` text to every subparser and every flag in cli.py (`list`, `validate`, `aggregate`, `compare`, `baseline`, `run` and `--agent`, `--stub-dir`, `--out`, `--keep`, `--keep-proxy`, `--run-ceiling`);
         add a "Flags" list to docs/evals.md (`--keep`, `--out FILE`, `--agent stub --stub-dir DIR`, `--keep-proxy`) and change "The temp directory is deleted" to "deleted (unless `--keep`)".
      4. DOC-13: replace "Three tasks of three runs cannot detect a small regression" with "A handful of tasks at three runs each cannot detect a small regression". (The review's `baselines/ … none committed` half no longer applies: `evals/baselines/default.json` is committed and docs/evals.md already describes it; leave that text alone.)
      5. Corrections owed by phases p12-p15: docs/evals.md line about "The real repository is never touched" becomes a qualified sentence (the agent runs with an empty `HOME` and no proxy unless `--keep-proxy`; the network is otherwise not sandboxed;
         `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` is required); the scrubber paragraph says transcripts and results use the secret-scan patterns, are written mode 0600, and still deserve a read before sharing;
         the cost-ceiling paragraph says `--run-ceiling` must be positive and finite, a timed-out run is charged its full allowance, and the first ceiling hit stops the invocation with exit code 3.
      6. Add tests in tests/test_evals_tasks.py / tests/test_evals_runner.py: the dry-run output for the make-plan and review tasks has no `model=sonnet`; every subparser has help text (`run.py --help` lists `list`, `validate`, `run`, `aggregate`, `compare`, `baseline`).
      7. Run the acceptance commands, then the whole suite.
    acceptance:
      - ".venv/bin/python evals/run.py run --dry-run | grep -E 'make-plan|review-seeded' prints lines without 'model=sonnet' (DOC-10)"
      - "grep -n '{name: ..., params}' docs/evals.md prints nothing (DOC-11)"
      - ".venv/bin/python evals/run.py --help | grep -c '^    [a-z]' prints 6, and grep -n -- '--keep' docs/evals.md matches (DOC-12)"
      - "grep -n 'Three tasks of three runs' docs/evals.md prints nothing (DOC-13)"
      - "grep -n 'never touched' docs/evals.md prints nothing (the sentence is replaced by one that says the agent runs with an empty HOME and no proxy)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p17-scope-check
    title: Check fix and rework sessions, harden the scope section, and isolate test git config
    depends_on: []
    complexity: M
    touches:
      - plugins/devflow/scripts/scope_check.py
      - plugins/devflow/commands/implement.md
      - docs/scope-drift.md
      - tests/test_scope_check.py
      - tests/test_upstream.py
      - tests/conftest.py
    brief: |
      Findings DOC-2, SEC-E8, TST-5, TST-16. Design D12 and D13 (TST-16 paragraph) are the spec.
      1. Tests first in tests/test_scope_check.py: `test_rev_and_fix_sessions_are_checked` (with the original phase's `Plan-Phase: s/p1` trailer on the feature branch,
         `check --phase p1 --label fix-1 --plan-slug s --feature feat` returns `"check": "ok"` and `out_of_scope == [{"path": "other.py", …}]`; same for label `p1-rev1`; a run with no label still reports
         `skipped` when the phase's own trailer is on the feature branch), `test_section_code_span_cannot_be_escaped` (the path ``a``b @someone [x](http://e)``c`` renders as one code span whose fence is longer than
         any backtick run in it and contains no `@` directly followed by a letter), `test_resumed_p1_is_not_p10` (TST-5: build a local copy of the MANIFEST with an extra phase `p10` inside the test (do not edit the shared MANIFEST), merge with trailer `Plan-Phase: demo/p10`,
         `check(… phase="p1", plan_slug="demo", feature="feature/demo")` → `["check"] == "ok"`; name contains `resumed`). See them fail (TST-5 may pass already: it exists to kill the mutation
         `any(line.strip() == wanted …)` → `bool(log.strip())`; apply the mutation, see it fail, revert).
      2. `scope_check.py`: implement D12 (label rule, fence, zero-width space).
      3. `implement.md` and `docs/scope-drift.md`: reword the sentences about fix and rework sessions (docs/scope-drift.md lines 34-36 and implement.md near lines 216-218 and 229-230) to match D12; keep every other word, and keep
         every string tests/test_scope_check.py or tests/test_structure.py greps for.
      4. TST-16: add the autouse session fixture of D13 to tests/conftest.py. Check it with a global config forcing signing: create a file `cfg` with `[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = /bin/false`, then
         run `GIT_CONFIG_GLOBAL=$PWD/cfg .venv/bin/python -m pytest tests/test_scope_check.py tests/test_upstream.py tests/test_hook_dod_gate.py tests/test_evals_runner.py -q` and see 0 errors (it had 24 before); delete `cfg`.
         tests/test_upstream.py and the `git()` helper of tests/test_scope_check.py need no change if the fixture covers them; change them only if it does not.
      5. Run the whole suite.
    acceptance:
      - ".venv/bin/python -m pytest tests/test_scope_check.py::test_rev_and_fix_sessions_are_checked -q passes (DOC-2)"
      - ".venv/bin/python -m pytest tests/test_scope_check.py::test_section_code_span_cannot_be_escaped -q passes (SEC-E8)"
      - ".venv/bin/python -m pytest tests/test_scope_check.py -k resumed -q passes (TST-5)"
      - "after printf '[commit]\\n\\tgpgsign = true\\n[gpg]\\n\\tprogram = /bin/false\\n' > /tmp/gpgsign.cfg, GIT_CONFIG_GLOBAL=/tmp/gpgsign.cfg .venv/bin/python -m pytest tests/test_scope_check.py tests/test_upstream.py tests/test_hook_dod_gate.py tests/test_evals_runner.py -q reports 0 errors (TST-16)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p18-ci-hygiene
    title: Pin CI actions and test dependencies; add SECURITY.md and CONTRIBUTING.md
    depends_on: []
    complexity: S
    touches:
      - .github/workflows/test.yml
      - tests/requirements.txt
      - SECURITY.md
      - CONTRIBUTING.md
    brief: |
      Findings SEC-E10 and SEC-E12 (merged DOC-14, DOC-17). Design D13 is the spec.
      1. Re-resolve the two action SHAs: `git ls-remote https://github.com/actions/checkout.git refs/tags/v4` must print `11d5960a326750d5838078e36cf38b85af677262` and
         `git ls-remote https://github.com/actions/setup-python.git refs/tags/v5` must print `a26af69be951a213d495a4c3e4e4022e16d87065`. If either differs, stop with status=blocked and report the new value.
      2. `.github/workflows/test.yml`: replace the two `uses:` lines and the `npm install -g` line as D13 says; change nothing else (keep `permissions: contents: read`).
      3. `tests/requirements.txt`: pin `pytest` and `PyYAML` as D13 says, checking Python 3.11 compatibility as described there. Run `.venv/bin/python -m pip install -q -r tests/requirements.txt` and the whole suite.
      4. `SECURITY.md`: scope (the hooks, secret-scan, the scripts under plugins/devflow/scripts), how to report (GitHub private vulnerability reporting: Security tab, "Report a vulnerability"), what a report should contain,
         and the sentence that the hooks are a seat belt and not a security boundary with a link to docs/hooks.md (relative link). `CONTRIBUTING.md`: setup (`python3 -m venv .venv`, `pip install -r tests/requirements.txt`),
         `.venv/bin/python -m pytest tests -q`, run the evals (`python3 evals/run.py validate`, `run --dry-run`) before and after changing a command, the no-project-specific-words test (tests/test_no_project_words.py),
         the plugin versions (the five `plugins/*/.claude-plugin/plugin.json` files must agree, enforced by tests/test_structure.py::test_plugin_versions_agree; a plan's retirement phase bumps them together, because a Claude Project caches each plugin per version, see docs/delivery.md), and how to add a hook case (`tests/test_hook_<name>.py` rows plus `evals/hook_cases.yaml` entries
         `{name, tool, input, expect: deny|allow}`, using `@@GH_TOKEN@@` for token-shaped strings). Both files must pass tests/test_no_project_words.py and tests/test_structure.py.
    acceptance:
      - "grep -cE 'uses: [^@]+@[0-9a-f]{40}' .github/workflows/test.yml prints 2 (SEC-E10)"
      - "grep -c '==' tests/requirements.txt prints 2 (SEC-E10)"
      - "grep -n 'claude-code@[0-9]' .github/workflows/test.yml prints one line (SEC-E10)"
      - "test -f SECURITY.md && test -f CONTRIBUTING.md && grep -qi 'report' SECURITY.md && grep -q 'hook_cases.yaml' CONTRIBUTING.md exits 0 (SEC-E12)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p19-docs
    title: Bring hooks.md, README, design, delivery and profile docs up to date
    depends_on: [p8-protect-paths, p9-dod-gate, p11-hook-test-gaps, p16-eval-docs-tasks, p17-scope-check, p18-ci-hygiene]
    complexity: M
    touches:
      - docs/hooks.md
      - README.md
      - docs/delivery.md
      - docs/design.md
      - docs/profile-reference.md
      - plugins/devflow/.claude-plugin/plugin.json
      - templates/toolkit.yaml
    brief: |
      Findings DOC-3, DOC-6, DOC-8, DOC-9, DOC-16, DOC-18 plus the documentation obligations of every code phase (Design D14 lists every edit; do exactly that list). The code is merged by now: read the actual hook code before
      writing each sentence, and write only what the code does. The review's DOC-3, DOC-6, DOC-8, DOC-9, DOC-16, DOC-18 "Fix" texts (in the review document) give the wording for those items.
      1. docs/hooks.md: apply the D14 edits in file order. Add the "Installing and checking" section (DOC-6). State in "Parsing" what is and is not unpacked after phases p1-p3 (read _shell.py and _gitgh.py).
      2. README.md: DOC-8 row for `evals/` and the `docs/evals.md` link in the docs row; DOC-3/DOC-6 sentence in "Guardrails" (every repository in a Project that enables the plugin needs at least `git.main_branch` in `.claude/toolkit.yaml`;
         the hooks need `python3` 3.11+ and PyYAML); DOC-18 on the line that names the marketplace (`andras-tkcs/claude-toolkit` → `tkcs-lab/claude-toolkit`; locate with grep).
      3. docs/delivery.md: DOC-3 (step 3: add a minimal profile with `git.main_branch` to every repository), DOC-6 (step 5: hooks and the other commands, PyYAML), DOC-18 (the marketplace line in step 2).
      4. docs/design.md: DOC-9 as its Fix text says, with `git-ops.md` also in the docs list (`docs/{profile-reference.md,delivery.md,design.md,hooks.md,evals.md,review.md,admin.md,git-ops.md,maintenance.md,scope-drift.md,migrating-privacyfence.md}`). docs/profile-reference.md: DOC-16 sentence in the `protect_paths` row and "read from the committed `<main>` profile" in the `hooks.disable` row; keep tests/test_validate_profile.py and
         tests/test_structure.py green (they grep this file for every profile key).
      5. plugins/devflow/.claude-plugin/plugin.json `homepage` and the `Reference:` comment in templates/toolkit.yaml: DOC-18.
      6. Run the acceptance commands, then the whole suite.
    acceptance:
      - "grep -n 'also denied' docs/hooks.md matches; grep -n 'git push origin x` is not' docs/hooks.md prints nothing; grep -n 'git.main_branch' docs/delivery.md matches (DOC-3)"
      - "grep -n 'PyYAML' docs/hooks.md docs/delivery.md matches in both files (DOC-6)"
      - "grep -c 'docs/evals.md' README.md prints at least 1 (DOC-8)"
      - "grep -n 'README.md,profile-reference' docs/design.md prints nothing; grep -n 'hooks.json' docs/design.md matches (DOC-9)"
      - "grep -n 'do \\*\\*not\\*\\* cross' docs/profile-reference.md matches (DOC-16)"
      - "grep -n 'andras-tkcs/claude-toolkit' README.md docs/delivery.md plugins/devflow/.claude-plugin/plugin.json templates/toolkit.yaml prints nothing (DOC-18; other files that still name the old owner, such as the stack plugins' homepage, the schema $id and docs/design.md, are outside the finding and left as they are)"
      - "grep -n 'malformed `hooks`' docs/hooks.md matches (DOC-4)"
      - ".venv/bin/python -m pytest tests -q passes"

  - id: p20-retire
    title: Delete the plan document and the manual-steps page; bump the plugin versions
    depends_on: [p19-docs]
    complexity: S
    touches:
      - docs/guardrail-review-fixes-plan.md
      - docs/guardrail-review-fixes-plan-manual-steps.html
      - plugins/devflow/.claude-plugin/plugin.json
      - plugins/stack-go/.claude-plugin/plugin.json
      - plugins/stack-ipados/.claude-plugin/plugin.json
      - plugins/stack-python/.claude-plugin/plugin.json
      - plugins/stack-swift/.claude-plugin/plugin.json
    brief: |
      1. `git rm docs/guardrail-review-fixes-plan.md docs/guardrail-review-fixes-plan-manual-steps.html`.
      2. `grep -rn 'guardrail-review-fixes-plan' .` outside `.git` must print nothing; remove any link you find.
      3. Bump `"version"` from `0.6.0` to `0.6.1` in the five `plugins/*/.claude-plugin/plugin.json` files (the hooks changed behaviour, and Claude Projects cache a plugin per version). If a file does not say `0.6.0`, stop with status=blocked.
      4. Run `.venv/bin/python -m pytest tests -q`.
    acceptance:
      - "test ! -e docs/guardrail-review-fixes-plan.md && test ! -e docs/guardrail-review-fixes-plan-manual-steps.html exits 0"
      - "grep -rn 'guardrail-review-fixes-plan' . --exclude-dir=.git prints nothing"
      - "grep -h '\"version\"' plugins/*/.claude-plugin/plugin.json prints five lines, all 0.6.1"
      - ".venv/bin/python -m pytest tests -q passes"
```
