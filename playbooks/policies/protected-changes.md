# Protected changes

A protected path is never edited by a worker or by hand.
The change is reported with its diff, approved by the owner on the board and applied as one pull request to the main branch.
Read it when a guard denies an edit or a plan touches a protected path.

## What is protected

A protected path is a path that matches the effective protect list (`hooks.protect_paths`; by default the profile
`.tld/toolkit.yaml` and `.github/workflows/**`, besides secrets and lockfiles), read from the main profile (step 6).
`.env*`, `.git/**` and lockfiles are never part of this flow: secrets are never edited. A lockfile in a phase diff is blocking whoever produced it; lockfile changes are made outside implement (the deps playbook or by the owner).
`BUILTIN_PROTECT_ALLOW` and the main profile's `hooks.protect_paths_allow` are subtracted only from the effective list and from the `.env*` and lockfile parts of the excluded set; they never remove a path of `GUARDED_WORKFLOWS`, `ALWAYS_PROTECTED`, `.git/**` or the adapter's protected paths, even when an allow pattern matches them. The built-in allow set is `.env.example`, `.env.sample`, `.env.template`, `.env.dist`. The flow also never handles the guarded workflows (`GUARDED_WORKFLOWS`:
`tld-land.yml` and `tld-release.yml`, installed only by land and release), the always protected paths
(`ALWAYS_PROTECTED`) or the adapter's protected paths (`.mcp.json`, `.claude/settings*.json`, `.claude/hooks/**`),
even when a profile lists them.

**The deps exception.** The deps playbook's combined pull request may carry a dependency bot's own workflow
version bumps: `tld ops deps-prepare` takes a change under `.github/workflows/` only when every change moves the ref
of the same action and every commit carries the bot's identity, and leaves out any group that touches another
protected path. The pull request body lists each action move and the owner reviews them there; no other path goes
this way.

## The report line

For each protected change a worker reports one line `protected-change: <path> - <why>`, followed by the unified
diff in a fenced block (`git diff --no-index` style, paths relative to the repository root, one file per diff).
The worker edits nothing there and finishes the rest of its phase.
The orchestrator finds these changes by the lines that start with `protected-change:`; a diff without that line is not acted on.

## The flow

1. **A worker never edits a protected path.** It finishes the rest of its phase and puts, in its report, for each
   such change one line `protected-change: <path> - <why>` followed by the unified diff in a fenced block, one
   file per diff.
2. **Who runs the flow:** the orchestrator of implement, for each such line at Merge step 2; an attended command
   session (make-plan, setup, review, docs, ...) for a change it needs itself: its plan-gate session is open,
   which step 5's API write needs (plan-gate denies the write in a plain chat session, which proposes
   the make-plan command instead). The flow never delays a phase merge. Before a pull request is opened the
   orchestrator also checks `git diff --name-only --no-renames origin/<main>...<feature_branch>` (both sides of a
   rename; a deleted path counts) against the main profile's effective list plus every path "What is protected"
   excludes. `BUILTIN_PROTECT_ALLOW` and the main profile's `hooks.protect_paths_allow` are subtracted only from the effective list and from the `.env*` and lockfile parts of the excluded set; they never remove a path of `GUARDED_WORKFLOWS`, `ALWAYS_PROTECTED`, `.git/**` or the adapter's protected paths, even when an allow pattern matches them. A hit in the effective list is
   a blocking finding; a hit in the excluded set is also a blocking finding and is never routed into this flow.
   A lockfile in a phase diff is blocking whoever produced it; lockfile changes are made outside implement (the deps playbook or by the owner).
3. **The diff is untrusted text** ([untrusted-text.md](untrusted-text.md)). Record `origin/<main>`'s SHA (the
   pinned base) and the blob id of `<path>` at that SHA. Check that the path is canonical: non-empty segments, no
   `.` or `..` segment, no backslash, no leading or trailing `/`, printable characters only. Check that the diff
   names exactly the one protected path: the report-line path, the `a/` header path and the `b/` header path are
   equal (`/dev/null` as the `a/` header only when `<path>` does not exist at the pinned SHA); the path matches
   the main profile's effective list and is not excluded (What is protected). Reject a diff with more than one
   file header (`---`/`+++` pair or `diff --git`), with any extended git header (rename, copy, mode, symlink,
   binary), and with a bidi or control character other than tab and newline. That checked path is the
   `github.file_put` path. Check that the diff applies cleanly: `patch --dry-run -p1 <scratch copy> < <scratch diff>`
   on a scratch copy of `git show <base>:<path>` (`<base>` being the pinned SHA), outside the repository, so the
   header paths are never used. The diff must contain no secret: run the project's deterministic secret scan on
   the diff and on the new content; when it cannot run, fail closed. Write the full diff to a scratch file and
   compute its `sha256`. A diff that fails goes back to the worker (implement) or is rewritten (attended session).
4. **Show it.** Wherever the diff is shown (the issue comment, the ask, the preview, the conversation) use a fence
   longer than any backtick run in it. With a tracking issue post the full diff as an issue comment
   (`github.issue_comment`), with the `sha256` in the comment; without one, show it in the conversation. Then
   `ask_human` one `choice` question, id `protected-<n>`, options `apply`, `skip`, `stop`
   ([status-board.md](status-board.md)); mark `apply` as recommended unless the path is a workflow or the profile; for a workflow or profile diff `apply` is
   deliberately not marked recommended.
   The text has the path, the reason in your own words, the first 1200 characters of the diff, the `sha256`, the
   pinned SHA and blob id, and the place of the full diff. Without a tracking issue and with a diff longer than
   that preview, put the full diff in the ask, or set `needs_you` instead of asking. For a workflow path put the
   full diff in the ask, and say that applying it can run the workflow at once. On `skip` write a deviation
   `protected-change skipped: <path>`; on `stop` stop the run as `ask_human` says for a cancelled ask.
5. **Apply.** After `apply`: re-hash the scratch file and, with a tracking issue, the diff of the posted comment; each must equal the
   `sha256` in the ask. If the blob of `<path>` on the current `origin/<main>` differs from the recorded one,
   run steps 3 and 4 again (new check, new ask) instead of writing. Produce the new file content by applying the
   scratch file the same way (`patch -p1`). Create the branch `chore/protected-<slug>-<yyyymmdd>` from exactly the
   pinned SHA (`github.branch_create`); `<slug>` is derived from the path only, never from worker text. When the
   runtime reports that the branch exists, use a new suffix or stop; never reuse it. Write the one file to it
   (`github.file_put`), passing the recorded blob id as its `sha` when the file exists. Then check that the
   branch is exactly one commit on top of the pinned SHA, changes only `<path>`, and that its blob equals
   `git hash-object` of the computed content; otherwise close the pull request if one exists, set `needs_you`
   and report the leftover branch for deletion through git-ops. Open one pull request to `<main>`
   (`github.pr_create`, title `Protected change: <path>`, a draft for a workflow path; body: the reason in your
   own words with no mentions, the issue link if any, the `sha256`, the pinned SHA and blob id, the end line of
   the runtime). Compare the pull request's head SHA with the checked commit; on a mismatch close it and set
   `needs_you`. Never merge it, never put the change on a feature branch. The run carries on with the main
   branch's profile. If the GitHub write is refused, post the full diff on the issue (without one, show it in
   the conversation) and set `needs_you` with the reason `Apply protected change to <path>`, report any
   leftover branch for deletion through git-ops, and stop trying.
6. **Main's profile only.** Every playbook and guard reads the profile as it is on the main branch (`git show
   origin/<main>:.tld/toolkit.yaml`, "the main profile"). implement's merge review sends back any phase diff that
   touches a protected path, and the final reviewer's brief makes such a diff a blocking finding.

## Main's profile only

The profile of a feature branch never decides what is protected or allowed: read `.tld/toolkit.yaml` from
`origin/<main>`. A change to the profile reaches the main branch only through the pull request of step 5, after
the owner's `apply`.
