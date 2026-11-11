# Auditing and updating organisation and repository settings

`plugins/devflow/scripts/repo_admin.py` compares a GitHub organisation and its repositories with a
**policy file** and either lists the differences (`audit`) or removes them (`apply`). The
`repo-admin` skill drives it with you: it audits, tells you what it found in words, asks what to apply,
shows a dry run, applies, and audits again. The script also works on its own, from a terminal or from a
workflow.

It is the tool for the housekeeping nobody schedules: tokens nobody uses, apps nobody remembers
installing, labels that differ from repository to repository, a `.archon` directory left in forty
repositories, a release process that is a different checklist in each one.

## Where it runs

Not in a Claude Code on the web session. Such a session can reach only the repositories attached to it
and cannot read organisation settings, tokens or secrets. Run the script where an organisation owner's
token is available:

```
gh auth login                      # or: export GH_TOKEN=...
python3 plugins/devflow/scripts/repo_admin.py whoami --org your-org
python3 plugins/devflow/scripts/repo_admin.py audit --policy .claude/admin-policy.yaml
```

The token comes from `GH_TOKEN`, `GITHUB_TOKEN` or `gh auth token`, in that order. It is sent only to
the GitHub API (`GITHUB_API_URL` selects a GitHub Enterprise Server) and never printed. A classic token
with `repo`, `workflow`, `admin:org` and `admin:org_hook` can run most checks; the fine-grained token check (`tokens`) may need a
GitHub App token with the organisation permission "Personal access tokens" (read and write), and answers `unavailable` otherwise. A fine-grained token
runs the checks its permissions allow; for each other check the report says `unavailable` and names the
endpoint that answered 401, 403 or 404, so you know which permission to grant.

## Use it in a project

1. Copy [`plugins/devflow/templates/admin-policy.yaml`](../plugins/devflow/templates/admin-policy.yaml)
   to `.claude/admin-policy.yaml` (or anywhere in the repository), set `org` and edit.
2. Set `admin.policy: .claude/admin-policy.yaml` in `.claude/toolkit.yaml` (see [profile-reference.md](reference/profile-reference.md)).
3. `repo_admin.py validate-policy <file>` checks the policy against
   [`schema/admin-policy.schema.json`](../plugins/devflow/schema/admin-policy.schema.json). An unknown key is an error.
4. Run the `repo-admin` skill, or the script yourself.

One policy file governs one organisation. A section you leave out is not managed. To treat some
repositories differently, use `repos.include` and `repos.exclude` and keep a second policy file.

## Commands

| Command | |
|---|---|
| `validate-policy POLICY` | Check the file. Exit 1 with one message per problem. |
| `whoami [--org ORG]` | Print the account the token belongs to and its role in the organisation. Exit 3 when it is not an owner. |
| `audit --policy P` | Read only. `--format md` (default) or `json`, `--out FILE`, `--repo NAME` and `--check NAME` (repeatable). Exit 0 nothing out of policy, 3 differences, 1 a check failed (the report is then incomplete). |
| `apply --policy P` | Recompute the findings and print the calls it would make. Nothing changes without `--yes`. `--only ID` (repeatable, ids from the audit) limits it, `--allow-delete` allows the irreversible ones. Exit 1 when a change failed. |

`--repo owner/name` (every `--repo` in that form) fetches just those repositories instead of listing
the organisation. The organisation-level "unused secret or variable" checks then stand down, because they
must see every repository.

## Safety

- **Dry run is the default.** `apply` without `--yes` prints every call and changes nothing.
- **Irreversible changes need `--allow-delete`:** deleting a label, secret, variable, webhook, deploy key or branch,
  and revoking a token. Without it they are listed as held back. Every policy switch that causes one is off in the starter.
- **File changes are never pushed to an existing branch.** Removing a directory, installing or updating a
  workflow goes into one commit on a new branch `chore/repo-admin-<yyyymmdd>` and one pull request per repository.
  The script never merges, approves or enables auto-merge; you review the pull request (and `/land` can order
  several). Writing workflow files needs the token's `workflow` permission.
- **An existing branch protection is never replaced.** The script adds one where there is neither a rule nor a
  ruleset, and reports a difference otherwise.
- **`--repo` names a repository of the policy's organisation**, nothing else.
- **Nothing secret is read or printed.** The API never returns secret values. Webhook URLs are shown as scheme and
  host only (the path is often the secret), and deploy keys by title.
- **Text from the repositories is untrusted.** Label names, file names and hook hosts appear in the report; the skill
  treats them as data.

## The checks

`--check` takes the name in the first column.

| Check | What it looks at | Can change |
|---|---|---|
| `org` | The keys of `org_settings` against `GET /orgs/{org}` | all but `org_settings.two_factor_requirement_enabled` (read only: reported with the settings page) |
| `members` | `members.require_two_factor`: members with two-factor authentication off. `members.max_owners`: more owners than allowed | nothing, reported |
| `apps` | Installed GitHub Apps against `apps.allow`; suspended installations | nothing: GitHub has no endpoint to uninstall as a user, so the report links the page |
| `tokens` | Fine-grained tokens with access to the organisation: expired, or unused longer than `tokens.fine_grained.max_unused_days` (a never-used token counts from the day access was granted) | revokes (irreversible) |
| `repo` | The keys of `repo_settings` against each repository | yes |
| `security` | `security.vulnerability_alerts`, `security.automated_security_fixes`, `security.secret_scanning`, `security.secret_push_protection`, `security.private_vulnerability_reporting` | yes (secret scanning needs a plan that offers it) |
| `actions` | `actions.enabled`, `actions.default_workflow_permissions`, `actions.can_approve_pull_request_reviews` | yes (an organisation setting that overrides a repository one answers 409) |
| `protection` | The branch of `branch_protection` has a rule or ruleset | adds a missing one; reports a weaker existing one |
| `secrets` | Actions and Dependabot secrets that no workflow names; `secrets.required` names a repository lacks | deletes unused ones when `secrets.delete_unused` (irreversible); a missing one is reported with the `gh secret set` command |
| `variables` | The same for Actions variables | deletes when `variables.delete_unused` |
| `labels` | `labels.sync` against each repository: create, update colour or description, rename an alias; labels outside it | create and update yes; delete when `labels.delete_unused` (only labels on no issue or pull request) or `labels.delete_unlisted` (irreversible) |
| `webhooks` | Hooks of the organisation and repositories that are inactive, failing or never delivered. Failing means the last delivery failed *and* none of the latest 30 succeeded; otherwise it is reported as flaky | deletes the kinds listed in `webhooks.delete` (irreversible); never a flaky one or one whose deliveries cannot be read |
| `keys` | Deploy keys not used for `deploy_keys.max_unused_days`. A key GitHub has no last use for is only reported | deletes a key with a recorded old use when `deploy_keys.delete_unused` (irreversible) |
| `branches` | Branches whose every commit is already in the default branch, not protected, not the head or base of an open pull request, last activity older than `branches.min_age_days` | deletes when `branches.delete_merged` (irreversible, though the commits stay in the default branch) |
| `files` | `config_dirs.forbid` paths that exist; `config_dirs.require` files that are missing; top-level dot directories outside `config_dirs.known`; `workflows` missing or different from their template | pull requests (a missing required file is only reported) |
| `lint` | `workflow_lint`: actions not pinned to a commit SHA, workflows without top-level `permissions`, `pull_request_target` | nothing: read only |

How "unused" is decided, and where it can be wrong:

- **Secrets and variables.** A name is unused when no workflow (`.github/workflows/*`) or `dependabot.yml` of
  the repository refers to it as `secrets.NAME`, `vars.NAME` or `secrets['NAME']`. For an organisation-level one,
  no live repository of the organisation may refer to it, and the token must see every repository (the count of `GET /orgs/{org}` is compared; a non-owner
  token never passes), otherwise nothing is deleted. Only the default branch is read: a name used by a workflow that exists only on another branch is reported as unused. If any workflow uses `secrets: inherit`, a computed
  name or the whole context (`toJSON(secrets)`), the script cannot tell and says so instead of reporting. A name used by something other than a workflow
  (a deploy script on a server, an environment secret) belongs in `secrets.keep`. Environment secrets and Codespaces secrets are not looked at.
- **Branches.** Merged means GitHub's compare of the default branch with the branch shows no commit of its own. A branch merged
  with a squash or rebase has such commits and is not detected. A branch cut yesterday with no commit of its own looks merged too, which
  is why only branches whose last activity (creation or push, from the repository activity API) is older than `branches.min_age_days` count; a branch with no readable activity is left alone, and so is one that an open pull request uses as its head or base; the commits of a deleted merged branch stay in the default branch.
- **Labels.** In use means at least one issue or pull request, open or closed, carries it.
- **Apps.** GitHub shows no "last used" time for an app. The only reliable test is your allow list.
- **Tokens.** Only fine-grained tokens granted access to the organisation can be listed, and they carry a last-used time.
  Classic personal access tokens and OAuth authorisations cannot be listed through the API; the report says to review them by hand.

## Policy reference

Every key is optional except `org`. The schema is the exact source of truth.

| Key | Meaning |
|---|---|
| `org` | **Required.** The organisation |
| `repos.include`, `repos.exclude` | Repository name globs; default all, none excluded |
| `repos.skip_archived`, `repos.skip_forks` | Default true |
| `org_settings.default_repository_permission` | `read`, `write`, `admin` or `none` |
| `org_settings.members_can_create_repositories`, `org_settings.members_can_create_public_repositories`, `org_settings.members_can_create_private_repositories`, `org_settings.members_can_create_internal_repositories` | Who may create repositories |
| `org_settings.members_can_create_pages`, `org_settings.members_can_fork_private_repositories` | |
| `org_settings.web_commit_signoff_required`, `org_settings.has_organization_projects`, `org_settings.has_repository_projects` | |
| `org_settings.two_factor_requirement_enabled` | Read only; a difference is reported |
| `members.max_owners`, `members.require_two_factor` | See `members` above |
| `apps.allow` | App slugs that may be installed. An empty list allows none |
| `tokens.fine_grained.max_unused_days`, `tokens.fine_grained.revoke_expired` | `revoke_expired` defaults to true |
| `repo_settings.allow_squash_merge`, `repo_settings.allow_merge_commit`, `repo_settings.allow_rebase_merge`, `repo_settings.allow_auto_merge`, `repo_settings.allow_update_branch`, `repo_settings.delete_branch_on_merge`, `repo_settings.allow_forking` | Merge and branch behaviour. `allow_auto_merge` is what `/land` needs |
| `repo_settings.has_issues`, `repo_settings.has_wiki`, `repo_settings.has_projects`, `repo_settings.has_discussions`, `repo_settings.web_commit_signoff_required` | Features |
| `repo_settings.squash_merge_commit_title`, `repo_settings.squash_merge_commit_message`, `repo_settings.merge_commit_title`, `repo_settings.merge_commit_message` | Commit message defaults (GitHub's enum values) |
| `security.vulnerability_alerts`, `security.automated_security_fixes`, `security.secret_scanning`, `security.secret_push_protection`, `security.private_vulnerability_reporting` | true or false |
| `actions.enabled`, `actions.default_workflow_permissions`, `actions.can_approve_pull_request_reviews` | `default_workflow_permissions` is `read` or `write` |
| `branch_protection.branch` | A name, or `default` (the default) |
| `branch_protection.require_pull_request`, `branch_protection.approvals`, `branch_protection.require_status_checks`, `branch_protection.strict` | Defaults true, 1, none, false |
| `branch_protection.enforce_admins`, `branch_protection.linear_history`, `branch_protection.allow_force_pushes`, `branch_protection.allow_deletions` | Defaults false |
| `secrets.required`, `secrets.keep`, `secrets.delete_unused`, `secrets.kinds` | `kinds`: `actions`, `dependabot`; default both |
| `variables.required`, `variables.keep`, `variables.delete_unused` | |
| `labels.sync` | List of `{name, color?, description?, aliases?}`. An alias is renamed to the name so issues keep the label |
| `labels.keep`, `labels.delete_unused`, `labels.delete_unlisted` | Labels outside `sync` |
| `branches.delete_merged`, `branches.min_age_days`, `branches.keep` | `min_age_days` defaults to 14; `keep` is branch name globs |
| `webhooks.delete`, `webhooks.keep_urls` | `delete`: `inactive`, `failing`. `keep_urls`: URL prefixes never reported |
| `deploy_keys.max_unused_days`, `deploy_keys.delete_unused` | |
| `config_dirs.forbid`, `config_dirs.require`, `config_dirs.known` | `forbid`: root-relative paths or globs with at least two literal characters (not the root, `.git` or a bare wildcard); `*` matches within one path segment, so `*.bak` is a top-level file only. `require`: root-relative files that must exist (for example `SECURITY.md`, `.github/CODEOWNERS`, `LICENSE`). `known`: more top-level dot directories to expect, added to the built-in `.github .claude .devcontainer .vscode .husky .config .changeset .githooks`; any other is reported |
| `workflow_lint.pin_actions`, `workflow_lint.require_permissions`, `workflow_lint.forbid_pull_request_target` | `pin_actions`: `third_party` (leaves `actions/*` and `github/*`) or `all` |
| `workflows` | List of workflow entries, below |

A `workflows` entry has exactly one of `template` (`release` or `land`) or `path` (your own template, below the directory of
the policy file: no absolute path, no `..`, no symbolic link out of it), and optionally `dest` (inside `.github/workflows/`), `params`, `repos` (name globs) and `remove: true`
(delete the file instead). In a template, `__UPPER_CASE__` words are placeholders, filled from `params` (lower
case keys). `main_branch` is the repository's default branch unless `params` sets it. Values, including the default branch name read from the repository, may contain only
letters, digits and `. _ / -`, so they cannot break out of the YAML or the shell; a repository whose default branch has other characters gets an `error` finding and no file. A file that already matches its
rendered template is left alone; one that differs is updated, so editing the template and running `apply` rolls the change out.

## The release workflow

`template: release` installs `.github/workflows/devflow-release.yml`. Parameter: `tag_prefix` (default `v`).

- Run it by hand: Actions, `devflow-release`, Run workflow, on the main branch. The branch check is a convenience, not a control: anyone who can push a branch can run an edited copy of the workflow. What stops a release is a tag ruleset (or branch protection) that only your release roles may bypass.
- Inputs: `version` (for example `1.4.0`; empty bumps the newest `<tag_prefix>x.y.z` tag by `bump`: `patch`, `minor`, `major`),
  `prerelease`, `skip_checks`, and `dry_run`, which is ticked by default. A dry run shows the tag and the generated notes in the run summary.
- Unticked, it checks that every check run on the head commit succeeded (and the commit status is neither failing nor pending), creates an
  annotated tag on that commit and a GitHub release with generated notes. It stops if the tag exists.
- Tags and releases made with the default workflow token do not start other workflows. If one must run on the tag
  (a build, a publish), add the secret `DEVFLOW_RELEASE_TOKEN`, a token that may write contents; the workflow uses it
  when it is set. It is separate from `DEVFLOW_AGENT_TOKEN` so the release does not run as the agent.
- It uses no third-party action and passes inputs to the shell only through environment variables.

## Not covered

Rulesets (the audit sees them only as "this branch is protected") and tag protection, the organisation's Actions allow list, environments and their
secrets, Codespaces secrets, OAuth
authorisations, classic personal access tokens (in a SAML organisation `GET /orgs/{org}/credential-authorizations` lists them), and people (adding or removing members). The report says so where it
matters (`info`). Scheduling an audit (a weekly workflow that opens an issue) is left to you.
