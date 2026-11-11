# Auditing and updating organisation and repository settings

`src/tld/ops/repo_admin.py` compares a GitHub organisation and its repositories with a
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
bin/tld ops repo-admin whoami --org your-org
bin/tld ops repo-admin audit --policy .claude/admin-policy.yaml
```

The token comes from `GH_TOKEN`, `GITHUB_TOKEN` or `gh auth token`, in that order. It is sent only to
the GitHub API (`GITHUB_API_URL` selects a GitHub Enterprise Server) and never printed. A classic token
with `repo`, `workflow`, `admin:org` and `admin:org_hook` can run most checks; the fine-grained token check (`tokens`) may need a
GitHub App token with the organisation permission "Personal access tokens" (read and write), and answers `unavailable` otherwise. A fine-grained token
runs the checks its permissions allow; for each other check the report says `unavailable` and names the
endpoint that answered 401, 403 or 404, so you know which permission to grant.

## Use it in a project

1. Copy [`src/tld/templates/admin-policy.yaml`](../../src/tld/templates/admin-policy.yaml)
   to `.claude/admin-policy.yaml` (or anywhere in the repository), set `org` and edit.
2. Set `admin.policy: .claude/admin-policy.yaml` in `.tld/toolkit.yaml` (see [profile-reference.md](../reference/profile-reference.md)).
3. `tld ops repo-admin validate-policy <file>` checks the policy against
   [`schema/admin-policy.schema.json`](../../src/tld/schema/admin-policy.schema.json). An unknown key is an error.
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
  ruleset, and reports a difference otherwise. The rulesets `tld-main` and `tld-tags` are different: the script owns
  them by name and puts them back when they differ.
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
| `protection` | The branch of `branch_protection` has a rule or ruleset. Stands down for the default branch while `rulesets.default_branch` is set | adds a missing one; reports a weaker existing one |
| `rulesets` | The rulesets `tld-main` (`rulesets.default_branch`) and `tld-tags` (`rulesets.tags`) exist and match, rule for rule, with the same bypass actors | creates a missing one, puts back a changed one (a ruleset of another name is left alone) |
| `agent` | The role of `agent.agent_login`; the environment `tld-agent` and its deployment branches (`agent.branch_policy`); where `TLD_AGENT_TOKEN` lives | lowers a role above write to write; creates or narrows the environment. A role below write, and a token outside the environment, are reported |
| `release` | The environment `tld-release` (`release.environment`): default branch only, `release.reviewer_login` as its one required reviewer; where `TLD_RELEASE_TOKEN` lives | creates or corrects the environment; a token outside it is reported |
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
| `rulesets.default_branch.required_status_checks`, `rulesets.default_branch.admin_bypass` | Checks that must pass (none: no checks rule); `admin_bypass: true` lets the admin role bypass `tld-main` through a pull request. Default false |
| `rulesets.tags` | true: the tag ruleset `tld-tags` (only the admin role may tag) |
| `agent.agent_login` | **Required in `agent`.** The account sessions push as |
| `release.reviewer_login` | **Required in `release`.** The owner: the one required reviewer of the release environment |
| `release.environment` | Name of the release environment; default `tld-release` |
| `agent.branch_policy` | `default_branch` (default) or `protected_branches`: which branches may use the environment `tld-agent` |
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

## Rulesets, the agent account and the environments

Rulesets are the control; the hooks in a session are a seatbelt. A hook stops an agent that makes a mistake, but
an agent that runs `python -c` or has been manipulated can get past it. GitHub cannot be talked out of a ruleset.
The design assumes one owner account and a separate agent account that sessions push as: the agent opens pull
requests and the owner approves them.

- **`tld-main`** on `~DEFAULT_BRANCH`: `pull_request` (`required_approving_review_count: 1`,
  `dismiss_stale_reviews_on_push: true`, `require_last_push_approval: true`), `required_status_checks` from the
  policy (left out when the list is empty), `non_fast_forward` and `deletion`. No bypass actor unless
  `admin_bypass` adds the admin role (`RepositoryRole` 5) in `pull_request` mode. So the agent cannot push to the
  default branch, force-push it, delete it or merge without the owner's approval, and an approval goes stale with
  the next push.
- **`tld-tags`** on every tag (`~ALL`; `refs/tags/*` would miss names with a slash): `creation`, `update`,
  `deletion`. The one bypass actor is the admin role (`RepositoryRole` 5, `always`): the owner. No workflow is a
  bypass actor, so no workflow's `GITHUB_TOKEN` can tag, whatever permissions it asks for.
- **The environment `tld-release`** (`release` in the policy) is where `tld-release` runs and where the owner token
  `TLD_RELEASE_TOKEN` lives, the token the workflow tags with. Only the default branch may use it, and the owner is
  its one required reviewer (`reviewers: [{type: User, id: <owner id>}]`, the id from `GET /users/{login}`). So a
  workflow the agent pushes on a branch of its own cannot reach the token (the branch policy), a run from the
  default branch waits for the owner (the reviewer), and its `GITHUB_TOKEN` cannot tag (no bypass). A
  `TLD_RELEASE_TOKEN` that is a repository or organisation secret is reported, like the agent token.
- **The agent's role** is at most `write`. `apply` lowers `admin` or `maintain` to `write` (`push` in the API). A
  role that comes from a team or the organisation's base permission stays where it is; the next audit shows it.
- **The environment `tld-agent`** holds `TLD_AGENT_TOKEN` as an environment secret. Its deployment branches are a
  custom policy naming only the default branch (or, with `branch_policy: protected_branches`, protected branches).
  The land workflow names `environment: tld-agent` and runs on pushes to the default branch, so a run from another
  branch never gets the token. The script cannot read or move a secret's value: a `TLD_AGENT_TOKEN` that is a
  repository or organisation secret is reported with the `gh secret set ... --env tld-agent` command.

What only the owner can do:

1. Run `apply` with an owner token that has admin rights on the repositories (`gh auth login` as the owner, or
   `GH_TOKEN`; a fine-grained token needs Administration read and write, Environments read and write, and
   Secrets read). Never the agent's token: it must not be able to change the rules that bind it.
2. Set `TLD_AGENT_TOKEN` in the environment: `gh secret set TLD_AGENT_TOKEN --env tld-agent --repo <owner>/<repo>`,
   then delete the repository secret of that name if the audit reports one.
3. Create a fine-grained token of the owner (Contents read and write on the repositories) and set it:
   `gh secret set TLD_RELEASE_TOKEN --env tld-release --repo <owner>/<repo>`. It expires; renew it.
4. Rulesets, and required reviewers on environments, need a paid plan on private repositories; without one the check reports `unavailable`.

## The release workflow

`template: release` installs `.github/workflows/tld-release.yml`. Parameters: `tag_prefix` (default `v`) and
`release_environment` (default `release.environment`, else `tld-release`).

- The owner runs it by hand: Actions, `tld-release`, Run workflow, on the main branch, and approves the run in the
  environment. It has no other trigger. What stops anyone else from tagging is the `tld-tags` ruleset and the
  environment above, not the workflow's branch check.
- Inputs: `version` (for example `1.4.0`; empty bumps the newest `<tag_prefix>x.y.z` tag by `bump`: `patch`, `minor`, `major`),
  `prerelease`, `skip_checks`, and `dry_run`, which is ticked by default. A dry run shows the tag and the generated notes in the run summary.
- Unticked, it checks that every check run on the head commit succeeded (and the commit status is neither failing nor pending), creates an
  annotated tag on that commit and a GitHub release with generated notes. It stops if the tag exists.
- Its `GITHUB_TOKEN` only reads (`contents: read`); the notes, the tag and the release are made with
  `TLD_RELEASE_TOKEN`, and the run stops when that secret is missing. A tag made with it starts other workflows (a
  build, a publish). It is separate from `TLD_AGENT_TOKEN` so the release never runs as the agent.
- It uses no third-party action and passes inputs to the shell only through environment variables.

## Not covered

Rulesets other than `tld-main` and `tld-tags`, the organisation's Actions allow list, environments other than
`tld-agent` and `tld-release`, and the values of any secret, Codespaces secrets, OAuth
authorisations, classic personal access tokens (in a SAML organisation `GET /orgs/{org}/credential-authorizations` lists them), and people (adding or removing members). The report says so where it
matters (`info`). Scheduling an audit (a weekly workflow that opens an issue) is left to you.
