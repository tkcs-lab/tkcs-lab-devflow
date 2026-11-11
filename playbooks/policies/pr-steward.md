# Stewarding a pull request

The generic policy for a session that owns a pull request. It sits alongside the project's own docs and the
profile's `project_steward` file; where the project's file is more specific, it wins. Load the profile first
([profile.md](profile.md)).

## Work that has to leave this machine

An agent's machine is usually Linux, has no code-signing identity, no other operating system and no live
credentials for external services. A project may also keep real credentials away from pull-request-triggered
workflows on purpose. None of that is a reason to skip a checklist row. If a CI workflow for the job
exists, a session can dispatch it **against its own branch** and read the result back.

The project's table is `ci.dispatchable`: for each entry, `workflow` is the file to dispatch, `use_when`
says when, and `notes` carries inputs and cautions. Show the relevant rows when you decide, dispatch with
`github.workflow_dispatch`, and read the run with `github.workflow_run` and `github.job_logs`. Without
`ci.dispatchable` nothing can be dispatched: say so, and name the row you could not verify.

- **The workflow must already be on the default branch.** GitHub only offers `workflow_dispatch` for
  workflows on the default branch; the `ref` you pass selects which checkout runs.
- **A queued run is correct behaviour, not a hang**, when the workflow declares a concurrency group. Wait; do
  not dispatch again.
- **A workflow that commits back to your branch** means you pull before you continue.
- **A recorded file is still a diff to read.** Fixtures, snapshots and generated files that arrived by
  dispatch get the same review as anything else: no account identifier, tenant URL, token or private
  content may enter the repository.
- **Never push a release tag.** There is one route to a tag: the release workflow `tld-release`, which the
  owner runs by hand on the main branch. Never dispatch it (the `no-git-tag` guard denies it); say in your
  report that a release is due. The git-ops playbook deletes branches only.
- **A missing credential or capability is not a test failure.** It is a dispatch.

## Which pull requests to follow

- **A pull request this session opened is this session's to drive to green.** Subscribe to it
  (`github.pr_subscribe`) and keep working it until CI passes and it is mergeable.
- **A review requested from a code owner waits on a person.** Set `needs_you` with the reason
  `Review PR #<n>`. Request the review once per pushed head. Never approve, merge or enable auto-merge on a
  pull request you opened.
- **Do not follow dependency-bot pull requests** unless the owner asks: a version bump is a supply-chain
  decision for a person. The deps playbook is that request. The project's steward file may name others to
  leave alone.
- **Stop at merge or close.** Nothing further is owed.

## A red check is real until proven otherwise

*A second red run on the same commit is real and must not be re-run away.*

- Never skip, disable, mark expected-failure or quarantine a test to get to green.
- Never push an empty commit, or close and reopen a pull request, to kick CI.
- A coverage or quality threshold failure means the new code needs tests or fixes, not a lower threshold.
- A static-analysis false positive is suppressed at the call site with a reason, never by loosening the
  project's configuration.
- Read the failing job's log (`github.job_logs`) before acting; do not guess from the check name.

## Branches (C12)

These are the branch kinds the playbooks use, and no others:

| Kind | Name | Made by |
|---|---|---|
| plan | `plan/<slug>` | make-plan (`tld plan branch-name --plan-slug <slug>`) |
| review | `review/<slug>` | review (`tld plan branch-name --review-slug <slug>`) |
| feature | the manifest's `feature_branch`, following `git.branch_pattern` | implement |
| phase | `<feature>--<phase id>`, `<feature>--<phase id>-rev<n>`, `<feature>--fix-<n>` | implement (`tld plan branch-name --manifest <plan> ...`) |
| chore | `chore/<what>-<date>` (`chore/toolkit-profile`, `chore/deps-<ecosystem>-<yyyymmdd>`, ...) | setup, docs, deps, upstream, land |

When the runtime refuses to push a branch name (a git proxy that allows only its own assigned branch), the
playbook says what to do: create the branch with `github.branch_create` and push again, and if that is also
refused, stop or use the session's assigned branch as the playbook allows, and put the kind in the pull
request title.

## Conventions that are easy to get wrong

- **Merge style.** With `git.merge_style: merge-commit` every commit message on the branch survives into
  the main branch's history; write each one for that audience.
- **Never open a version heading in the changelog on a feature branch** (when `docs.changelog` is set):
  entries go under `docs.changelog.section`.
- **A protected branch is protected like the main branch.** Work that targets a long-lived integration
  branch the project documents branches from it and is proposed back into it.
