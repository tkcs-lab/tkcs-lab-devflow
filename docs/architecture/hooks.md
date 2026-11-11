# Guardrail hooks

The `devflow` plugin ships Claude Code hooks that turn the "never do X" rules in the commands into
checks that run before a tool call (`PreToolUse`) or before a session stops (`Stop`). They live in the
plugin (`plugins/devflow/hooks/hooks.json`, scripts called through `${CLAUDE_PLUGIN_ROOT}`), so every
repository that enables the plugin gets them without a per-repository copy. Project facts come from
[`.claude/toolkit.yaml`](../reference/profile-reference.md); the scripts contain none.

**Branch protection and CI stay the hard backstop.** A hook is the fast, in-loop layer: it stops the
agent a minute after the mistake instead of a day later, and it tells the agent what to do instead.
It is not a security boundary (see [what the hooks do not protect](#what-the-hooks-do-not-protect)).

## The hooks

| Hook | Event, tools | Denies | Why | One denied, one allowed |
|---|---|---|---|---|
| `no-merge` | PreToolUse: `Bash`, and the GitHub MCP tools that merge, approve or write to a branch | pull request merges, approvals, auto-merge, any push to the main branch | A human merges; a session opens the pull request and stops | `gh pr merge 12`, `git push origin HEAD:main`; `git push -u origin feature/x`, `git merge origin/main` |
| `no-force-push` | PreToolUse: `Bash` | `git push` with `--force`, `-f`, `--force-with-lease`, `--force-if-includes`, a `+` refspec; deleting a branch by push | History on origin is append-only; branches are deleted by the owner | `git push -f origin x`, `git push origin :old`; `git push -u origin x`, `git branch -d old` |
| `no-git-tag` | PreToolUse: `Bash` | creating, moving, deleting or pushing tags | Releases are cut by the release workflow in CI | `git tag v2`, `git push --tags`; `git tag -l`, `git describe`, `git ls-remote --tags` |
| `secret-scan` | PreToolUse: `Write`, `Edit`, `MultiEdit`, `NotebookEdit` | content that looks like a credential | A secret in a file ends up in history | a GitHub token or a private key block; `API_KEY = os.environ["API_KEY"]` |
| `protect-paths` | PreToolUse: `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `Bash` | edits to paths the profile lists | Some files are changed by people or by tools, not by hand | `echo x > .env`; `echo x > .env.example` |
| `dod-gate` | Stop | stopping while `verify.dod` is red (opt-in) | Work is not done until the definition of done passes | stop with a failing test; stop after `/dod` is green |

A denial is exit code 2 with the reason on stderr, which Claude Code hands back to the agent. Every
message says what to do instead, for example `Open a pull request from your feature branch and stop;
a human reviews and merges it.`

### `no-merge`

Denies, in a Bash command: `gh pr merge` (any flags, including `--auto`), `gh pr review --approve` / `-a`,
`gh api` calls to the merge endpoint (`pulls/<n>/merge`), to the review endpoints with `event=APPROVE`, to
`merges` with the main branch as base, to `git/refs/heads/<main>`, to `contents/...` that commit to the main
branch (no `branch` field means the default branch), GraphQL mutations that merge, enable auto-merge, move
a ref or approve (a GraphQL `--input` file, or a `-F query=@file` field, is read; one that cannot be read, such as stdin, is denied), a `gh alias`
(could hide a merge), a `curl` to the merge endpoint, `gh api` calls that fast-forward or merge upstream into the
main branch (`merge-upstream`) or rename it, `gh repo sync` of the main branch (or with `--force`), and a `git push`
whose refspec or destination is the main branch (`git.main_branch`): `git push origin main`, `HEAD:main`,
`HEAD:refs/heads/main`, `+x:main`, `:main`, a pattern such as `refs/heads/*:refs/heads/*`, `--all`, `--branches`,
`--mirror`.

A `git push` without a refspec (`git push`, `git push origin`) is resolved from the git configuration, as git would:
the remote (`--repo`, `branch.<b>.pushRemote`, `remote.pushDefault`, `branch.<b>.remote`, else `origin`), then
`remote.<name>.push`, then `push.default` (`simple` and `current` push the current branch, `upstream` the configured
upstream, `nothing` nothing). It is denied when the result is the main branch, and also when the destination cannot be
determined (a mirror remote, a pattern or a run-time value in `remote.<name>.push`, `matching`, a detached `HEAD`, no
upstream, or a failed `git` lookup). A `-c remote.*`, `-c push.*` or `-c branch.*` option on the push is denied, because it
changes where the push writes. `git send-pack`, `git http-push` and `git subtree push` are checked like `git push`.

It also covers the GitHub MCP tools sessions use where there is no `gh`: `merge_pull_request`,
`enable_pr_auto_merge`, `pull_request_review_write` with `event: APPROVE`, and `push_files` /
`create_or_update_file` / `delete_file` on the main branch.

It does **not** block local `git merge`. `/implement` merges phase branches and `origin/<main>` into the feature
branch, and `/land` merges on its own `chore/land-*` branch. `git merge origin/main` on a feature branch and
`git merge --no-ff origin/<phase branch>` are tested as allowed.

### `no-force-push`

Denies `git push` with `--force`, `-f` (also inside a cluster such as `-fu`), `--force-with-lease[=...]`,
`--force-if-includes`, any unambiguous abbreviation of those (git accepts `--force-w`), a refspec starting with
`+`, a refspec starting with `:`, and `--delete`, `-d`, `--prune`, `--mirror`. It also denies the API forms of branch
deletion: `gh api -X DELETE .../git/refs/heads/...` and `gh pr close --delete-branch`. A word that is only known at run time
(`git push "$OPT" origin x`) where a push option could stand is denied, because it could be `--force`. Local `git branch -d`,
`git fetch --prune`, `git revert` and `git merge --abort` are fine.

### `no-git-tag`

Denies `git tag <name>` (and `-a`, `-s`, `-f`, `-d`, `-m`, ...), `git push --tags`, `--follow-tags`, `git push origin tag <name>`,
`refs/tags/...` refspecs, `git push origin <name>` when `<name>` is a tag in the local repository (a bare name is a tag
push only if the repository has such a tag), a push that tags through configuration (`push.followTags=true`, a
`remote.<name>.push` that names `refs/tags/`, or a `-c remote.*.push` / `-c remote.*.mirror` option), `git update-ref
refs/tags/...` and `git update-ref --stdin` (its input cannot be read), `gh release create` / `delete`, `gh release edit
--tag`, and the API calls that create or move tag refs, tag objects and releases or edit or delete a release.

Releases are cut by the release workflow, so a session may not start it either: `gh workflow run devflow-release.yml`, the
`dispatches` API of that workflow, and the GitHub MCP `actions_run_trigger` with `run_workflow` for it are denied
(`run_workflow` with a workflow id instead of a file name is denied too, since it cannot be checked). Other workflows,
such as those in `ci.dispatchable`, stay allowed. Reading stays allowed: `git tag -l`, `--list`, `-n`,
`--contains`, `--points-at`, `--merged`, `-v`, `git describe`, `git fetch --tags`, `git ls-remote --tags`, `gh release list`.
The release workflow itself runs in CI and is not affected; the template (`devflow-release.yml`) runs in the `release`
GitHub environment, so a human approves each run there.

### `secret-scan`

Scans what a `Write`, `Edit`, `MultiEdit` or `NotebookEdit` call would write (not what it removes) for private key
blocks, AWS, GitHub, Google, Slack, Stripe, Anthropic, OpenAI-style, npm, PyPI, SendGrid and Azure storage credentials,
and for generic assignments: a name ending in `key`, `token` or `secret` (`API_KEY`, `client_secret`, `apiKey`,
`deploy-token`) set to a literal of at least 20 characters with a digit, a letter and Shannon entropy of at least 3.5
bits per character that is not an obvious placeholder (`example`, `changeme`, `your-...`, `xxxx`) and not a `public`
key. A name ending in `password`, `passwd` or `pwd` needs only 12 characters (a digit, a letter, entropy of at least 3.0).
It also matches credentials in a URL (`scheme://user:password@host`), `Bearer` tokens of 20 or more characters and JSON web
tokens. The message names the pattern and the line, never the value:

```
devflow secret-scan: blocked: line 12 of the new file content for src/cfg.py looks like a GitHub token (pattern: github-token).
The value is not shown. Do not write a credential into a file: read it from the environment or a secret store ...
```

For a test fixture or a documented example, build the value at run time, or end the line with `secret-scan:allow`; the mark must be the last thing on the line.
A line of more than a million characters is not checked for generic assignments. A secret written by a Bash command (`echo $TOKEN > file`) is not seen.

### `protect-paths`

Denies edits to the paths in `hooks.protect_paths`. The path is checked as written and with symlinks resolved. In Bash
the hook sees redirections (`>`, `>>`, `>|`, `&>`, `2>`), `tee`, `sed -i`, `perl -i`, `cp`, `mv`, `install`, `ln`, `rm`,
`unlink`, `shred`, `truncate`, `touch`, `dd of=`, `git rm`, `git mv`, `git checkout -- <path>` and `git restore <path>`; it
expands globs against the file system and `{a,b}` braces (up to 64 results, more is denied), and follows `cd`. A write
whose target is a hard link to a protected file is denied (same device and inode, found by walking the repository), and so
is `ln` with a protected file as its source, since a link would let a later write through. `git config` writes to
`alias.*`, `remote.*`, `push.*`, `branch.*` and `include*` keys are denied, because they can redirect pushes or run commands. A program that writes a file itself (`npm install` updating its lockfile, a Python one-liner)
is not seen, which is why lockfiles are protected from hand edits and not from tools.

Default list (a list in the profile replaces it): `.claude/toolkit.yaml`, `.env`, `.env.*`, `*.lock`, `package-lock.json`,
`go.sum`, `.github/workflows/**`. Always protected, whatever the profile says: `.claude/settings.json`,
`.claude/settings.local.json`, `.git/config`, `.git/hooks/**`, and anything under `$CLAUDE_PLUGIN_ROOT` (the installed
plugin). Always allowed, whatever the profile says: `.env.example`, `.env.sample`,
`.env.template`, `.env.dist`, and the two workflow files the toolkit's own commands install
(`.github/workflows/devflow-land.yml` from `/land`, `.github/workflows/devflow-release.yml` from `repo-admin`). That is how
"workflow files unless a command explicitly owns them" is decided: the command's file is on the built-in allow list;
add your own with `hooks.protect_paths_allow`.

Patterns: one without a slash matches the file name at any depth (`*.lock`); one with a slash is anchored at the
repository root (`.github/workflows/**`); `**` crosses directories, `*` and `?` do not; a trailing slash means a directory.
Paths outside the repository are not this hook's business.

**The `/setup` exemption.** `/setup` has to write `.claude/toolkit.yaml`. Before its first write it runs
`python3 "<devflow root>/hooks/protect_paths.py" --allow-profile`, which writes the marker
`protect-paths-profile.json` into `<git dir>/devflow/` (so it is per checkout and never committed). For two hours from
that moment the hook lets the path `.claude/toolkit.yaml` (exactly) through and nothing else: `.env*`, lockfiles and
workflow files stay denied. After its last write `/setup` runs `--end-allow`, which removes the marker; a marker that
is forgotten lapses after the two-hour TTL. The deny message for the profile says it is changed by people or by
`/setup`. This is a convention like the `dod-gate` marker below: any session that can run a command can write the
marker. Branch protection and the pull request review stay the hard control.

### `dod-gate`

Opt-in, off by default. When `hooks.dod_gate.enabled` is true, the Stop hook runs the profile's `verify.dod` commands
(each in its `cwd`, all of them, so the report is complete) and, if any fails, blocks the stop and hands the failing
commands and the tail of their output back to the agent. Rules that keep it from getting in the way:

- **Nothing to check, nothing run.** It does nothing when the working tree is clean and `HEAD` has no commit that
  `origin/<main>` lacks, so a question-and-answer session never runs the gate.
- **Not run twice on the same tree.** A passing run, and a give-up, are remembered per session and tree
  (`HEAD`, status and diff); the next stop of an unchanged tree is allowed without a rerun.
- **No endless loop.** It honours `stop_hook_active` (Claude Code sets it when the session is already continuing because a
  Stop hook blocked it) and counts failed attempts per session. After `hooks.dod_gate.max_attempts` failed attempts
  (default 3) it lets the session stop and shows the user a message saying that the definition of done is still red, which
  commands failed and why it gave up. If the counter cannot be saved and `stop_hook_active` is set, it also lets the
  session stop. After a give-up the gate comes back only when the tree changes.
- **Missing keys fail loudly.** With the gate on and no `verify.dod`, or no `git.main_branch`, it blocks with
  `toolkit.yaml: missing required key '...'`. A profile error of any kind (a malformed `hooks.dod_gate`, a `max_attempts`
  outside 1..10, a malformed `hooks.disable`) counts as a failed attempt and its message ends with `(attempt N of M)`.
  After the limit (`max_attempts`, or 3 when that value is itself invalid) the gate lets the session stop and shows the
  message in `systemMessage`, so it gives up after the attempt limit also for profile errors.

## How the dod-gate recognises a session

The question is which sessions the gate must **not** block. The `/implement` orchestrator legitimately stops at
`human_gate` phases, at check-ins and when it halts with a one-line error; its child phase sessions are single-session work
that ends with `/dod` and should be gated. `/make-plan` and `/review` write documents, `/land` only merges pull request
branches on an integration branch.

Decision: **a session is gated unless it marked itself exempt.** A command that is not code work runs, once, right after the
profile is loaded:

```
python3 "<devflow root>/hooks/dod_gate.py" --exempt
```

`dod_gate.py --exempt` writes `<git dir>/devflow/dod-gate-exempt.json` (inside `.git`, so it is never committed). The marker is per checkout:

- `/implement` (the orchestrator), `/make-plan`, `/review` and `/land` write it. Each says so in its "Guardrail hooks"
  paragraph.
- `/implement` child phase sessions run in a fresh clone in which no command wrote it, so they are gated. So is a session
  where a person simply works with Claude.
- The marker lapses 24 hours after the exempt session last stopped; every Stop of an exempt session refreshes it, so an
  orchestrator that keeps stopping stays exempt, and a marker left in a reused container does not switch the gate off for the
  next session for long.
- `/deps` and `/upstream` are not exempt: they already require `verify.dod` to pass before they push, so the gate agrees
  with them.

Why a marker the command writes instead of detecting the command from the transcript: it needs no knowledge of Claude
Code's transcript format, it is one line to audit, and a command that forgets it fails safe (the gate blocks a few times,
then gives up). Not marking is the default, so work done outside any command is gated.

## Configuration

All hook settings are optional and live in the profile's `hooks` section. The scripts apply the defaults themselves
(they are not part of `validate_profile.py --resolved`).

```yaml
hooks:
  disable: []                # names of hooks to switch off in this repository
  protect_paths:             # replaces the default list when set
    - .claude/toolkit.yaml
    - .env
    - ".env.*"
    - "*.lock"
    - package-lock.json
    - go.sum
    - ".github/workflows/**"
  protect_paths_allow: []    # exceptions on top of the built-in ones
  dod_gate:
    enabled: false           # opt in
    max_attempts: 3          # 1..10; a value outside that range is a profile error
```

Project facts the hooks read from elsewhere in the profile: `git.main_branch` (`no-merge` when it sees a `git push` or a
call that could write to the main branch, and `dod-gate`), and `verify.dod` (`dod-gate`). A hook needs a key only when
it needs the fact: `gh pr merge` is denied in a repository with no profile. A `git push` (any branch) is also denied
there, because deciding whether it targets the main branch needs `git.main_branch`. When the key is missing the hook
blocks with `toolkit.yaml: missing required key 'git.main_branch'`, the same message the commands give. Plugins are enabled
per Claude Project, so every repository in a Project that enables `devflow` needs a profile with at least that key.

Reference: [profile-reference.md](../reference/profile-reference.md).

### Disabling a hook

`hooks.disable` is the escape hatch, per repository and off by default:

```yaml
hooks:
  disable: [protect-paths]   # any of no-merge, no-force-push, no-git-tag, secret-scan, protect-paths, dod-gate
```

`hooks.disable` is read from the profile as committed on the main branch (`origin/<main>`, else `<main>`), not from the
working tree, so a feature branch cannot switch a guardrail off for itself; when the working tree's `hooks` section differs
the hook shows a notice and applies only the committed list. In a repository with no commit yet, the working tree's list
is used. The list must be a list of names; anything else, in the working tree or on the main branch, is a profile
error (see Parsing) even though only the committed list is applied. Two gaps are accepted: a branch can change
`git.main_branch`, and the committed copy is read from local refs (`origin/<main>`, then `<main>`), which a session can
rewrite, for example with `git update-ref refs/remotes/origin/main <sha>`. Branch protection stays the backstop.

It is a profile change, and `.claude/toolkit.yaml` is protected from edits by sessions, so a person does it. Prefer a narrower tool
first: `hooks.protect_paths_allow` for one more allowed path, a `secret-scan:allow` line mark for one false positive.
`no-merge`, `no-force-push` and `no-git-tag` have no narrower switch on purpose.

## Parsing

The three destructive hooks need to see through the ways a command can be written, so they do not match text. A small
tokenizer (`hooks/_shell.py`, standard library) splits the command into simple commands: `&&`, `||`, `;`, `|`, `&`,
newlines, subshells and groups, `$(...)`, backticks and `<(...)`, heredoc bodies (not scanned as commands, except that
an unquoted heredoc still runs its substitutions), comments, and redirections; each command's words are split by `shlex`
(POSIX quoting and escapes), and `$'...'` quoting is decoded to its literal value (`$'--force'` is `--force`). It then
strips prefixes and wrappers (`FOO=1`, `env` including `env -S`, `sudo`, `nice`, `timeout`, `time`, `flock`, `script -c`,
`command`, `exec`, `if/then/do` and a few more), unpacks `bash -c '...'` and `eval`, follows `xargs` and `find -exec`
(only when `git` or `gh` follows), tracks `cd`, understands `git -C <dir>`, `-c k=v`, `--config-env` and `--git-dir`,
reads `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_<n>` / `GIT_CONFIG_VALUE_<n>` from the command's own assignments or the
environment, and resolves git aliases (from `-c alias.x=...` and from the repository's config, including `!shell`
aliases). Mentions are not commands: `echo "gh pr merge"` and a commit message that says "never git push -f" pass.

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

## Compatibility with the commands

The hooks must not break the commands. This table lists every git and gh operation the commands document and the
verdict. `tests/test_hooks_compat.py` keeps it honest: it has one test per command, runs each documented operation through
the Bash hooks, fails when a command file stops containing the phrase that documents the operation, and sweeps every
`git ...` / `gh ...` code span in the commands and skills through the hooks as well.

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
| `/land` | `git fetch origin <main>`; create `chore/land-<stamp>` from `origin/<main>`; `git merge --no-ff` of pull request heads in order; `git merge --abort`; normal push of a pull request branch; `git push -u origin chore/land-<stamp>`; `chore/devflow-land-workflow` and its push | allowed |
| | write `.github/workflows/devflow-land.yml` | allowed (on the built-in `protect-paths` allow list) |
| | "Never approve, merge, enable auto-merge, force-push, push to `<main>`, delete a branch or tag" | now enforced |
| `/deps` | check out a Dependabot branch and push a normal commit to it; `chore/deps-<ecosystem>-<date>` from the default branch and its push; MCP `update_pull_request_branch`; the profile's lock and audit commands | allowed (lockfiles are changed by the lock commands, which `protect-paths` does not see) |
| | "Never merge, approve, enable auto-merge or force-push" | now enforced |
| `/upstream` | `git ls-remote --tags <url>` (via `upstream_sync.py plan`), `git fetch`, `upstream_sync.py prepare` (runs git itself), one commit, `git push -u origin chore/upstream-<tag>` | allowed (reading tags is allowed; the script's own git calls are not hook-visible) |
| | "Never merge, approve or enable auto-merge; never force-push; no prerelease or branch as target" | now enforced for the first two |
| `/review` | `git fetch origin <main>`, `git log -p --all`, `git show FETCH_HEAD:<path>`, `git push -u origin review/<slug>` and later pushes to it | allowed |
| | "Never run anything that pushes a tag" | now enforced |
| `/make-plan` | `git fetch origin <ref>`, `git show FETCH_HEAD:<path>`, `git checkout -b plan/<slug> origin/<main>`, `git push -u origin plan/<slug>` | allowed |
| | "never push to `<main>` or any branch but `plan/<slug>`" | pushes to `<main>` are enforced; other branches are not checked |
| `/dod` | `git diff --stat origin/<main>...HEAD` and the profile's commands | allowed |
| `/board` | none | n/a |

What changed in the commands: `/implement`, `/make-plan`, `/review` and `/land` gained one paragraph that marks the session exempt from
`dod-gate` (see above). No git or gh operation of any command changed.

## What the hooks do not protect

- **Sessions without the plugin.** Hooks exist only where `devflow` is enabled. A session that does not load the plugin, a
  person at a terminal, another tool, and a CI job are not covered.
- **Branch protection and CI remain the hard enforcement.** Require a pull request, required reviews, status checks, no
  force pushes and no deletions on the main branch, and a release workflow that owns tags, in the repository's rules.
  The hooks make the agent stop early; the rules make sure nothing gets through if the agent, a plugin setting or a
  hook is wrong.
- **Anything a parser cannot see.** Expansions are not evaluated (`git push origin "$BRANCH"` is allowed; a variable that
  holds `main` is not noticed), a script file run with `bash script.sh` is not read (a shell fed by a pipe or a file is denied instead, see Parsing), a program that merges or writes files
  itself (`python -c`, a Makefile target) is not seen, git aliases that exist only in a global config of another machine are
  not known, and `curl` against the API is checked only for the merge endpoint.
- **Writes the agent does not make through its tools:** secrets in Bash output, in a command line or in a commit message.
- **A hook switched off** with `hooks.disable` on the main branch, or a profile edited by someone who may edit it. A
  branch can still change `git.main_branch` in its own working tree, and a session can rewrite the local refs the committed
  copy is read from.
- **A hook that has a bug.** The destructive hooks fail closed; the others fail open.

## Installing and checking

Requirements: `python3` 3.11 or newer and PyYAML on the session's `PATH`; the hooks use nothing else. Without PyYAML the
hooks behave as if there were no profile (the reason is `PyYAML is not installed`), so the destructive hooks deny every
`git push` that needs `git.main_branch`, while `protect-paths` and `dod-gate` fall back to their defaults or do nothing.

To confirm the hooks are loaded in a session, run `/hooks` and look for the `devflow` entries, or run
`git tag probe`: with `no-git-tag` active the call is denied with `devflow no-git-tag: blocked` and no tag is created.

Loading the hooks from plugins that a Claude Project syncs into a cloud session is **not verified end to end** (see
[delivery.md](../delivery.md)). The tests exercise the scripts directly, not Claude Code's loading of `hooks.json`.

## Tests

`python -m pytest tests -q` covers each hook with a table of allowed and denied inputs (including the bypass forms above), run
through the same code path as the script (JSON in, exit code and stderr out), plus a subprocess contract test per script. Tokens in the
`secret-scan` tests are assembled at run time, so the repository never contains a credential-looking string.
