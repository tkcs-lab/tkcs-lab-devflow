# Guardrail hooks: parsing and command compatibility

How the guards read a shell command, and which commands of the playbooks they must allow. The hooks themselves are in
[hooks.md](hooks.md).

### Parsing

The three destructive hooks need to see through the ways a command can be written, so they do not match text. A small
tokenizer (`hooks/_shell.py`, standard library) splits the command into simple commands: `&&`, `||`, `;`, `|`, `&`,
newlines, subshells and groups, `$(...)`, backticks and `<(...)`, heredoc bodies (not scanned as commands, except that
an unquoted heredoc still runs its substitutions), comments, and redirections; each command's words are split by `shlex`
(POSIX quoting and escapes), and `$'...'` quoting is decoded to its literal value (`$'--force'` is `--force`). It then
strips prefixes and wrappers (`FOO=1`, `env` including `env -S`, `sudo`, `nice`, `timeout`, `time`, `flock`, `script -c`,
`command`, `exec`, `if/then/do` and a few more), unpacks `bash -c '...'`, `fish -c`, `busybox sh -c` and `eval`, follows
`xargs` and `find -exec` into the command they run (unpacking a `sh -c` there, and treating the run-time arguments `xargs`
or `find … +` append as a word that could be `--force`), tracks `cd`, understands `git -C <dir>`, `-c k=v`,
`--config-env` and `--git-dir`, reads `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_<n>` / `GIT_CONFIG_VALUE_<n>` from the
command's own assignments or the environment, and resolves git aliases (from `-c alias.x=...` and from the repository's
config, including `!shell` aliases). Mentions are not commands: `echo "gh pr merge"` and a commit message that says
"never git push -f" pass.

Two whole-command checks run first, on every destructive guard (`src/tld/guard/integrity.py`): a command whose **name**
is only known at run time followed by a git/gh write word (`G=git; $G push --force …`) is denied (S3), unless the name
is the toolkit's launcher `"${CLAUDE_PLUGIN_ROOT}/launcher/tld"` (also `"${CLAUDE_PLUGIN_ROOT}"/launcher/tld`) on a command line
that does not set `CLAUDE_PLUGIN_ROOT` itself, which the commands use; any other `$X/launcher/tld` or `$X/tld` is denied (S20); and a git command that pulls configuration from a file or the
environment (`-c include.*` / `includeIf.*`, `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM` / `GIT_CONFIG_PARAMETERS`,
`GIT_DIR`) is denied, because it can set a push destination or an alias the parser cannot see (S4).

What is and is not unpacked: a shell given a command string (`bash -c`, `eval`) and a shell fed a herestring or heredoc
(`bash <<< 'git push -f'`, `bash <<EOF ... EOF`) are parsed like any command line. A shell that reads its commands from
stdin in any other way (`curl ... | bash`, `bash < file`, a bare `bash`) is **denied** by the three destructive hooks
("a shell that reads its commands from stdin cannot be checked"). `xargs bash` and similar are not flagged. A script file
(`bash script.sh`, `bash "$f"`) counts as running a script and is not read.

A command it cannot tokenise (an unterminated quote or substitution) is **denied** by `no-merge`, `no-force-push` and
`no-git-tag` with "cannot parse this command ... rewrite it as plain, separate commands", and so is an internal
error in one of them, a hook that fails to load, a `git` lookup that fails (`git` cannot run, times out or exits with an
unexpected status), and a hook that runs longer than its 15 s budget (below the 20 s Claude Code timeout). `secret-scan`,
`protect-paths` and `dod-gate` report their own errors and let the call through (exit code 1, shown to the user only),
and a timeout in them allows the call, because blocking every edit on a bug in a helper would do more harm than good.

A profile problem is different: a malformed `hooks` value (not a mapping, or a list key such as `protect_paths` that is not a
list of non-empty strings, or a `hooks.disable` that is not a list) is a profile error that blocks with exit 2 and names the
key, in every hook that reads it. `dod-gate` counts it as a failed attempt instead (see above).

### Compatibility with the commands

The hooks must not break the commands. This table lists every git and gh operation the playbooks document and the
verdict. `tests/adapters/claude/test_hooks_compat.py` keeps it honest: it has one test per command, runs each documented operation through
the Bash hooks, fails when a playbook stops containing the phrase that documents the operation, and sweeps every
`git ...` / `gh ...` code span in `playbooks/` through the hooks as well.

| Command | Operations it performs | Verdict |
|---|---|---|
| `/implement` | `git fetch origin <ref>`, `git show FETCH_HEAD:<path>` | allowed |
| | create the feature branch from the plan branch, merge `origin/<main>` into it (merge commit), `git push -u origin <feature_branch>`; on refusal the GitHub MCP `create_branch` and a second push | allowed (a feature branch is not the main branch) |
| | resume: check out the feature branch, `git log --grep` for `Plan-Phase` trailers | allowed |
| | `git fetch origin <phase branch> <feature_branch>`, `git diff <base>...origin/<phase branch>` | allowed |
| | `git checkout <feature_branch> && git merge --no-ff origin/<phase branch>`, conflict resolution, `git merge --abort` | allowed (local `git merge` is never blocked) |
| | `git revert -m 1 <merge>` and push the feature branch | allowed |
| | push the feature branch after each merge, follow-up branches `<feature_branch>--<phase id>-rev<n>` and `--fix-<n>` | allowed |
| | final `git merge origin/<main>` into the feature branch and push; `git diff origin/<main>...HEAD` | allowed |
| | MCP: `create_pull_request`, `update_pull_request` (reviewers), `actions_run_trigger` (the `ci.dispatchable` workflows), `add_issue_comment`, `create_branch` | allowed; dispatching the release workflow is denied by `no-git-tag` |
| | "Never push to `<main>`; never approve, merge or enable auto-merge; never rebase or force-push the feature branch" | now enforced for push, merge, approve, auto-merge and force-push; a local `git rebase` is not blocked |
| | child phase sessions: push `<phase branch>`, run `/dod` | allowed; **gated** by `dod-gate` when enabled |
| `/land` | `git fetch origin <main>`; create `chore/land-<stamp>` from `origin/<main>`; `git merge --no-ff` of pull request heads in order; `git merge --abort`; normal push of a pull request branch; `git push -u origin chore/land-<stamp>`; `chore/tld-land-workflow` and its push | allowed |
| | write `.github/workflows/tld-land.yml` | allowed between `tld guard allow-workflow-install tld-land.yml` and `tld guard end-allow` (S13) |
| | "Never approve, merge, enable auto-merge, force-push, push to `<main>`, delete a branch or tag" | now enforced |
| `/deps` | check out a Dependabot branch and push a normal commit to it; `chore/deps-<ecosystem>-<date>` from the default branch and its push; MCP `update_pull_request_branch`; the profile's lock and audit commands | allowed (lockfiles are changed by the lock commands, which `protect-paths` does not see) |
| | "Never merge, approve, enable auto-merge or force-push" | now enforced |
| `/upstream` | `git ls-remote --tags <url>` (via `tld ops upstream-sync plan`), `git fetch`, `tld ops upstream-sync prepare` (runs git itself), one commit, `git push -u origin chore/upstream-<tag>` | allowed (reading tags is allowed; the script's own git calls are not hook-visible) |
| | "Never merge, approve or enable auto-merge; never force-push; no prerelease or branch as target" | now enforced for the first two |
| `/review` | `git fetch origin <main>`, `git log -p --all`, `git show FETCH_HEAD:<path>`, `git push -u origin review/<slug>` and later pushes to it | allowed |
| | "Never run anything that pushes a tag" | now enforced |
| `/make-plan` | `git fetch origin <ref>`, `git show FETCH_HEAD:<path>`, `git checkout -b <feature> origin/<main>`, `git push -u origin <feature>` | allowed |
| | "never push to `<main>` or any branch but the feature branch" | pushes to `<main>` are enforced; other branches are not checked |
| `/dod` | `git diff --stat origin/<main>...HEAD` and the profile's commands | allowed |
| `/board` | none | n/a |

What changed in the commands: `/implement`, `/make-plan`, `/review` and `/land` gained one paragraph that marks the session exempt from
`dod-gate` (see above). No git or gh operation of any command changed.
