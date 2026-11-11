# The central git-ops workflow

A Claude Code session on the web cannot push a tag and cannot delete a remote branch: its git proxy refuses
both, and a token saved on the environment is never used for GitHub hosts. The toolkit therefore ships one
GitHub Actions workflow, `tld-git-ops`, to run in a central private repository. A session starts it, and it
creates the tag or deletes the branch with a fine-grained token that only that repository's `git-ops` environment
holds. The `git-ops` skill drives it; the profile key `git_ops.repo` names the central repository.

## How it works

1. The session (or you) starts the workflow with the inputs `repo` (target as `owner/name`), `action`
   (`create-tag` or `delete-branch`), `name` (the tag or branch), optionally `ref` (create-tag only: a commit SHA
   or a branch; empty means the head of the target's default branch) and `message` (create-tag only: the tag
   message; empty means `Tag <name>`), and `dry_run` (default on).
2. The workflow checks the request against `git-ops-allowlist.json` and a set of guards, does a dry run unless
   told otherwise, and writes what it did or would do to the run summary.

Files:

| File | Installed as |
|---|---|
| [`src/tld/templates/tld-git-ops.yml`](../../src/tld/templates/tld-git-ops.yml) | `.github/workflows/tld-git-ops.yml` in the central repository |
| [`src/tld/templates/git-ops-allowlist.json`](../../src/tld/templates/git-ops-allowlist.json) | `git-ops-allowlist.json` at the root of the central repository |
| the `git-ops` skill | in the `tld` plugin |
| `git_ops.repo`, `git_ops.workflow` | in each project's `.tld/toolkit.yaml`, see [profile-reference.md](../reference/profile-reference.md) |

The template has no placeholders; copy it as it is. The secret is `GIT_OPS_TOKEN`, the environment is `git-ops`.
Anyone with write access to the central repository can run the workflow, so keep that group small.

## Set up once

**1. The central repository.** Create a private repository of its own (this page writes `your-org/git-ops`).
It holds only the workflow and the allowlist. Protect `main`: pull requests only, and if you can, a Code Owners
rule for `.github/workflows/` and `git-ops-allowlist.json`. Keep the group with write access small.

**2. The token and the environment.**
- Create a fine-grained personal access token: resource owner the organisation, repository access only the
  repositories you want to tag or clean up, permissions Contents read and write and Pull requests read, nothing
  else, expiry 90 days. If the organisation requires approval, have an owner approve it. Never paste the token
  into chat.
- In the central repository open Settings, Environments, create `git-ops`, set Deployment branches to
  "Selected branches" with only `main`, and add the environment secret `GIT_OPS_TOKEN` (an environment secret,
  not a repository secret).

**3. Install the workflow and the allowlist.** Copy `tld-git-ops.yml` to `.github/workflows/` and
`git-ops-allowlist.json` to the root of the central repository through a pull request into `main` (GitHub offers
"Run workflow" only for a file on the default branch). Edit the allowlist:

```json
{
  "owner": "your-org",
  "repos": ["repo-one", "app-*"],
  "protected_branches": ["main", "master", "develop", "release/*", "gh-pages"],
  "tag_pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.]+)?$"
}
```

`owner` is the one owner the workflow may act on; `repos` lists repository names or globs; `protected_branches`
(optional) lists branch globs that are never deleted (`*` also matches `/`); `tag_pattern` (optional) is a
regular expression every new tag name must match. The workflow reads this file from the central repository's
default branch, never from the dispatched ref.

**4. The first real run.** From the Actions tab run `tld-git-ops` with a harmless branch, for example
`action=delete-branch`, `name=chore/git-ops-test`, `dry_run` ticked; read the summary; then untick `dry_run`.
This proves the token works and that a branch name with a slash is handled.

**5. In each project,** after the plugin is updated, add to `.tld/toolkit.yaml`:

```yaml
git_ops:
  repo: your-org/git-ops           # required inside the section
  workflow: tld-git-ops.yml    # optional; this is the default
```

## Use it

- **Through Claude:** ask for a named tag or named branches; the `git-ops` skill lists the items, dry-runs each,
  shows the result, and runs it for real only after your yes.
- **By hand:** Actions tab, `tld-git-ops`, Run workflow, on `main`.
- **With the CLI:** `gh workflow run tld-git-ops.yml -R <owner>/<central> -f repo=<owner>/<target> -f action=create-tag -f name=v1.2.3 -f dry_run=true`
  (add `-f ref=<sha>` or `-f message=...` for a tag; use `-f dry_run=false` to do it).

Tags made with a personal token start other workflows, unlike tags made with the default workflow token. This is
wanted: a release build can run on the tag.

## Guards

Every refusal is final; the workflow does not try another way.

| Guard | Where it is enforced | How to see it fail |
|---|---|---|
| The `GIT_OPS_TOKEN` secret only reaches runs from `main` | the `git-ops` environment's deployment branches | start the workflow from another branch: it waits for or is denied the environment |
| The job runs only on the central repository's default branch | `if:` on the job | dispatch on another ref: the job is skipped |
| Allowlist read from the default branch | step "Check the allowlist" | edit the file on a branch only: no effect |
| Dry run unless `dry_run` is exactly `false` | steps "Create the tag" and "Delete the branch" | run with `dry_run` ticked: only a summary line |
| One ref per run, no tag deletion or move, no force | the workflow has no such action | not possible |
| `repo must look like owner/name (got: $REPO)` | step "Validate the inputs" | `repo=x` |
| `action must be create-tag or delete-branch` | step "Validate the inputs" | `action=foo` |
| `name is not a valid branch or tag name (got: $NAME)` | step "Validate the inputs" | `name=a..b` |
| `ref is not a valid branch name or commit (got: $REF)` | step "Validate the inputs" | `ref=a b` |
| `message is longer than 500 characters` | step "Validate the inputs" | a 501-character message |
| `git-ops-allowlist.json is missing or invalid on $SELF_DEFAULT` | step "Check the allowlist" | break the JSON on `main` |
| `repository $REPO is not allowed by git-ops-allowlist.json` | step "Check the allowlist" | a repository not in `owner`/`repos` |
| `secret GIT_OPS_TOKEN is not set for the git-ops environment` | step "Look at the target" | remove the secret |
| `the token cannot see $REPO` | step "Look at the target" | a repository the token does not include |
| `$REPO is archived` | step "Look at the target" | an archived repository |
| `tag $NAME does not match tag_pattern` | step "Create the tag" | `name=release1` with the example pattern |
| `$target is not on the default branch $DEFAULT` | step "Create the tag" | `ref=` a commit of another branch |
| `tag $NAME already exists; this workflow never moves a tag` | step "Create the tag" | an existing tag name |
| `$NAME is the default branch` | step "Delete the branch" | `name=main` |
| `$NAME is protected by git-ops-allowlist.json` | step "Delete the branch" | `name=release/1.0` with the example list |
| `branch $NAME does not exist` | step "Delete the branch" | a misspelt branch |
| `$NAME is protected on GitHub` | step "Delete the branch" | a branch with classic branch protection |
| `branch $NAME is used by open pull requests: $PRS` | step "Delete the branch" | a branch that is head or base of an open pull request |

### Who may change what

Whoever has write access can run the workflow. A change to the workflow or the allowlist goes through a pull
request into `main`. With a second GitHub user and a Code Owners rule, GitHub enforces that review. With one
GitHub user only, protection of the central repository's `main` is policy, not enforcement: it rests on the rule
that a session never merges or approves its own pull request (see the `pr-steward` skill).

## Limits

- Tags: create only, annotated, on a commit that is on the target's default branch, never moved or deleted.
- Branches: one per run; never the default branch, a protected one, or one used by an open pull request.
- Only classic branch protection is seen; a ruleset that forbids the action is left to the API, whose error is
  shown. The workflow never bypasses a ruleset.
- The token expires after 90 days and must be renewed.
- Only repositories of the allowlisted `owner` that match `repos` are reachable.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Resource not accessible by personal access token`, or 403 or 404 on the target | The token lacks the repository or the permission, or has not been approved | Edit the token's repositories and permissions (Contents write, Pull requests read); have an owner approve it |
| The API refuses the ref | A ruleset on the target forbids it | The workflow never bypasses a ruleset; change the ruleset yourself if intended |
| The run waits | The environment has required reviewers | Approve the run or remove the reviewers rule |
| `secret GIT_OPS_TOKEN is not set for the git-ops environment` | The secret is on the repository, not the environment | Add it as an environment secret of `git-ops` |
| 401 from the API | The token expired | Create a new token and replace the secret |
| The dispatch is refused for a session | The GitHub App has no permission to start workflows | Start the workflow from the Actions tab or with `gh workflow run` |

## Alternatives

- `tld-release` cuts a release tag in the repository itself with the default workflow token.
- `tld ops repo-admin` with `branches.delete_merged` cleans up merged branches in bulk, with an organisation owner's
  token (see [admin.md](admin.md)).
- A GitHub App token instead of a personal token removes the 90-day renewal, at the price of an app, a private
  key and a token-minting step. It is the upgrade path.
