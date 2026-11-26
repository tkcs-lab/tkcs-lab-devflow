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
cli/tld ops repo-admin whoami --org your-org
cli/tld ops repo-admin audit --policy .tld/admin-policy.yaml
```

The token comes from `GH_TOKEN`, `GITHUB_TOKEN` or `gh auth token`, in that order. It is sent only to
the GitHub API (`GITHUB_API_URL` selects a GitHub Enterprise Server) and never printed. A classic token
with `repo`, `workflow`, `admin:org` and `admin:org_hook` can run most checks; the fine-grained token check (`tokens`) may need a
GitHub App token with the organisation permission "Personal access tokens" (read and write), and answers `unavailable` otherwise. A fine-grained token
runs the checks its permissions allow; for each other check the report says `unavailable` and names the
endpoint that answered 401, 403 or 404, so you know which permission to grant.

## Use it in a project

There are four kinds of file (the layers of one effective policy):

| Kind | Where it lives | `org` | Holds |
|---|---|---|---|
| **run file** | the policy file you give to `--policy`, in a private checkout | required | the organisation's own settings, `extends`, `repos` |
| **shared base** | any file `extends` names, in any repository (public too) | absent | settings every organisation shares |
| **organisation file** | a private file `extends` names (for example in `<org>/git-ops`) | absent | the organisation-level sections: `org_settings`, `members`, `apps`, `tokens`, `secrets`, `variables` and the rest |
| **repository override** | `.tld/admin-policy.yaml` in each repository | absent | that repository's differences only |

A small organisation (or a single repository) needs only the first one:

1. Copy [`src/tld/templates/admin-policy.yaml`](../../src/tld/templates/admin-policy.yaml)
   to `.tld/admin-policy.yaml` (or anywhere in the repository), set `org` and edit.
2. Set `admin.policy: .tld/admin-policy.yaml` in `.tld/toolkit.yaml` (see [profile-reference.md](../reference/profile-reference.md)).
3. `tld ops repo-admin validate-policy <file>` checks the policy against
   [`schema/admin-policy.schema.json`](../../src/tld/schema/admin-policy.schema.json). An unknown key is an error.
4. Run the `repo-admin` skill, or the script yourself.

Many repositories share most of their policy. Then an organisation keeps three files: its policy (run file, with
`org` and `extends`), its private file (the organisation-level sections), and the shared base (the starters are
`admin-policy.yaml`, `admin-policy-org.yaml` and `admin-policy-base.yaml` in `src/tld/templates/`); every repository
keeps a small override file. A section you leave out is not managed. `repos.include` and `repos.exclude` (in the run
file only) choose the repositories. The audit is always run with the organisation's policy file: given a
repository's override file (a file without `org`), the `repo-admin` skill stops and names the file to use.

## Commands

| Command | |
|---|---|
| `validate-policy POLICY` | Check the file. Exit 1 with one message per problem; exit 2 when `--public` is used without `--kind base`, or when only one of `--org-policy` and `--repo-name` is given. It resolves `extends` through the API (needs the token; `--offline` skips it). `--kind auto\|run\|override\|base` (default `auto`: run when the file has `org`, else override), `--public` (with `--kind base`: the file goes into a public repository), `--resolved`, `--explain`, `--org-policy FILE` with `--repo-name NAME`: see below |
| `latest-pin OWNER/REPO/PATH` | Print `{"sha": ..., "tag": ...}`, the commit to pin an `extends` entry to |
| `whoami [--org ORG]` | Print the account the token belongs to and its role in the organisation. Exit 3 when it is not an owner. |
| `audit --policy P` | Read only. `--format md` (default) or `json`, `--out FILE`, `--repo NAME` and `--check NAME` (repeatable), `--no-detect` (no proposals from the repositories). Exit 0 nothing out of policy, 3 differences, 1 a check failed (the report is then incomplete). |
| `apply --policy P` | Recompute the findings and print the calls it would make. Nothing changes without `--yes`. `--only ID` (repeatable, ids from the audit) limits it, `--allow-delete` allows the irreversible ones, `--no-detect` as for `audit`. Exit 1 when a change failed. |

`--repo owner/name` (every `--repo` in that form) fetches just those repositories instead of listing
the organisation. The organisation-level "unused secret or variable" checks then stand down, because they
must see every repository.

## Inheriting the policy

Order, later wins: the files `extends` lists (in that order), the run file, then the repository's override file.
Mappings merge key by key; lists and scalars replace. The first two layers are the **organisation policy**; with the
override it is the **effective policy** of one repository. A policy without `extends` behaves exactly as before.

**`extends`** (run file only) is a list of one to four pins, each `<owner>/<repo>/<path>@<40-hex commit>`; a tag or a
branch is refused (put the tag in a trailing comment). The file is read through the API with your token, so a private
file works without a checkout, and the commit must be on the default branch of its repository. An extended file
cannot extend another. Files are checked for credentials, anchors, shape and key class; a base never holds a
credential. `tld ops repo-admin latest-pin <owner>/<repo>/<path>` prints the pin to write.

**Key classes.**

| Class | Keys | Where it may be set |
|---|---|---|
| run only | `org`, `extends`, `repos` | the run file |
| organisation-private | `org_settings`, `members`, `apps`, `tokens`, `secrets`, `variables` | the run file, or a file of a private repository |
| organisation-level | the private ones plus `labels`, `webhooks`, `deploy_keys`, `branches`, `branch_protection`, `profile`, `git_ops` | the run file or any extended file; never an override |
| overridable | `repo_settings`, `security`, `actions`, `rulesets`, `agent`, `release`, `workflow_lint`, `config_dirs`, `workflows`, `workflow_params` | the run file, a base and an override |
| per repository | `rulesets.default_branch.required_status_checks`, `workflow_params`, `config_dirs.known`, `workflows[].params` | an override or the run file; never a base |

`null` is refused in a base and an override, so an override cannot delete a section. An override may set only the
overridable sections; its `workflow_params.release` and its `workflows[].params` may hold only `tag_prefix`,
`version_style`, `check_script` and `create_release`, and a `workflows` entry only `template`, `params` and `remove`.
A base lists templates without parameters (`workflows: [{template: release}, {template: land}]`); a repository writes
`workflow_params` instead of restating the list, or lists only its own templates (lists replace). A file of a repository that is public, internal or of
unknown visibility may not set the private sections.

**Guarded keys.** An override may not loosen these; the organisation's value is put back and the `policy` check warns
(`loosen:<key>`): `security.*`, `rulesets.tags`, `workflow_lint.require_permissions`,
`workflow_lint.forbid_pull_request_target` (must stay true); `rulesets.default_branch.admin_bypass` and
`actions.can_approve_pull_request_reviews` (must stay false); `actions.default_workflow_permissions`,
`workflow_lint.pin_actions` and `agent.branch_policy` (not weaker); `repo_settings.allow_merge_commit`,
`allow_squash_merge`, `allow_rebase_merge` (equal to the organisation's); `config_dirs.forbid` and
`config_dirs.require` (a list may not shrink). Only keys the organisation policy sets are guarded: **an organisation
must list every guarded key it cares about**, because a key it omits is not guarded against an override. The run file
may let a repository loosen a key: `repos.allow_loosen: {"<repo name glob>": ["<guarded key>"]}`. The run file's own
loosening of its bases is reported, not put back; it is the owner's file.
An override of `agent.agent_login`, `release.reviewer_login` or `release.environment` is applied with a warning
(`login:<key>`, `release:<key>`); `release.environment` equal to the agent's environment (`tld-agent`) is always
dropped with a warning, and when the effective agent and reviewer logins are equal (without case) the organisation's
logins apply (`login:same`). Where the organisation sets no login, a dropped reviewer login stands the release check
down and a dropped agent login is derived from the repository's profile as when it is absent. Where the organisation's
own logins are equal, the reviewer login is dropped, the release check stands down and the agent role part is skipped.

**Irreversible switches.** A base or an override cannot turn on `secrets.delete_unused`, `variables.delete_unused`,
`labels.delete_unused`, `labels.delete_unlisted`, `webhooks.delete`, `deploy_keys.delete_unused`,
`branches.delete_merged`, `tokens.fine_grained.max_unused_days` or `tokens.fine_grained.revoke_expired`; only the policy
file you run can, and `revoke_expired` (default true) is set to false when a base supplies `tokens.fine_grained` and
the run file does not. `--yes` and `--allow-delete` are unchanged. Pull-request deletions through
`config_dirs.forbid` are not held by `--allow-delete`: they are reviewed pull requests, and a base may set
`config_dirs.forbid`, which opens one in every repository. A repository override may add `config_dirs.forbid` patterns, empty its required status checks and remove or omit
workflow templates; none of these is a guarded key, so an organisation that needs a workflow kept or a minimum set of
checks has to review override pull requests for them.

**Absent is not empty.** With `extends`, a `rulesets.default_branch` without
`required_status_checks` keeps the checks the live ruleset requires, with their app binding (only an explicit `[]`
removes the rule), and a missing `tld-main` is created without a check rule. The release template without
`workflow_params.release` or `params`, or in a repository whose profile has no `release` section or exists but cannot be read or resolved, is not
installed or rewritten: an `info` finding says so. A repository whose override file cannot be listed on a truncated tree is read
directly, never treated as absent. The `tld-release` environment is checked in every repository whose effective
policy gives it a `release` section, so a base with one makes it a requirement everywhere.

**Derived logins.** When the effective policy has an `agent` or a `release` section, `agent.agent_login` and
`release.reviewer_login` need not be set (without the section nothing is derived or checked): they are taken from the
repository's resolved profile (`git.bot_login`; `git.owner_login`, else the one `git.codeowners` entry). The profile
is read at the default branch, so it is written by the repository and is untrusted: each derived login is a
`login:derived:<key>` warning that names the account the changes will use. An explicit value wins and the profile is
not read for it (it is still read for a release section without an agent section, to compare the reviewer with
`git.bot_login`). With no agent login, a `warn` finding says so (`login:agent`) and only the agent role part is skipped (the
environment and secret part still run). With no reviewer login, a `warn` finding says so (`login:reviewer`) and only
the release check is skipped for that repository. Deriving needs the profile features of the
same tld: the `profile` and `git_ops` sections, the resolved profile of a repository and its `git.bot_login`,
`git.owner_login` and `git.codeowners` keys (the changelog names the release that ships them).

**Detection.** For a repository whose effective policy has `rulesets.default_branch` without
`required_status_checks`, or the release template without parameters, the `policy`
check reads the newest ten merged pull requests of the default branch (check runs and commit statuses), its tags,
its manifests and its workflows, and proposes an override file (`override:propose`, a `fix` finding) that `apply`
opens as one pull request; the owner merges it, or corrects the values in it. It never writes to a branch. A check is
proposed only when it concluded `success` on every sampled pull request, with at least three; excluded checks are
listed with the first reason: flaky, failed, skipped, pending, or seen on only some of the pull requests (a path
filter or a new check). `check_script` is never guessed. A repository that writes its own release workflow (its
profile names one other than `tld-release.yml`) gets a `workflows` list without the release template. The proposal
keeps every key the repository wrote, and repeats on every audit until it is merged (a repository with fewer than
three merged pull requests repeats indefinitely); `--no-detect` skips it. A whole old policy in a repository file
(it has `org`) is converted to an override in the same pull request (`override:convert`).

**Reading the result.** `validate-policy <run file> --resolved` prints the merged policy; `--explain` prints one line
per value with its source (`run`, `base <label>` or `override <repo>`); with an override file,
`validate-policy <override> --org-policy <organisation policy> --repo-name <name> --resolved` prints that
repository's effective policy. `--kind base --public` checks a base file locally before it goes into a public
repository. The OK line ends `, repository override` or `, base` for those kinds.

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
| `profile` | `profile-no-extends` and `profile-invalid-extends` (a repository with a profile but no valid `tld.extends`, or one that names another base; warn, the step is to run setup in update mode), `profile-pin-old` (the pin is not the newest tagged commit, or not the commit `profile.pin` names), `profile-guarded-override` (info: the repository's own profile overrides guarded keys the base allows), `profile-merge-style` (the repository's merge settings do not match `git.merge_style`; the starter policy allows merge commits only) | `profile-pin-old`: a pull request, through the API, that rewrites only the `extends:` line, titled `chore: bump the tld base to <tag>`; the rest is reported |
| `git_ops` | `git-ops-workflow` and `git-ops-allowlist` (the shipped `tld-git-ops.yml` and an allowlist naming every audited repository are missing or differ in the central repository), `git-ops-environment` and `git-ops-token` (the `git-ops` environment limited to the default branch and the `GIT_OPS_TOKEN` secret in it: open items with manual steps, never created) | a pull request into the central repository for the workflow and the allowlist; the rest is manual |
| `policy` | Only for a policy that has `extends`. The run file's own loosening of its bases (`loosen:<key>`, warn); per repository: problems of the override file (`override:invalid`, error; the repository is then audited with the organisation policy alone), guarded settings an override tried to loosen (`loosen:<key>`, warn; the organisation value applies unless `repos.allow_loosen` lets it), changed logins and `release.*` values, a whole old policy in the override file (`override:convert`), `workflow_params` for a template the repository does not list. The subjects are `override:propose:invalid` (warn: a proposal detected from the repository failed validation or would loosen a guarded key, and was dropped), `override:invalid:N`, `login:<section>.<key>`, `login:same`, `release:<key>` and `workflow_params:<template>`; `login:derived:<key>`, `login:agent`, `login:reviewer` and `login:same` also come from the `agent` and `release` checks, not only from this one; `override:propose` is the proposed override pull request (a detected proposal, `fix`) or, when nothing could be proposed, an `info` finding. A detection proposes no `required_status_checks` when the live `tld-main` already requires some, and its pull request names every `path` workflow that a proposed `workflows` list leaves out | `override:convert`: a pull request that replaces the file with the repository's differences only; the pull request body lists what was dropped under "Detected values (the owner confirms them)" |
| `secrets_scope` (runs with the `git_ops` section) | A repository or organisation Actions secret, or a secret of an environment any branch may deploy to; an environment limited to the default branch is not reported. A pushed branch's workflow runs with repository-level secrets before anyone reads it, so only environment secrets limited to the default branch are safe from it | nothing: reported with the manual steps |

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
| `extends` | Files the policy inherits: a list of one to four pins, each `<owner>/<repo>/<path>@<40-hex commit>`; an empty list means none. Only the policy file you run may set it |
| `repos.override_path` | Where each repository keeps its override file; default `.tld/admin-policy.yaml`, a path below the repository root |
| `repos.allow_loosen` | Repository name globs mapped to the guarded keys an override of those repositories may loosen |
| `workflow_params` | Per repository, in its override file: parameters of a workflow template, copied into the matching `workflows` entries |
| `workflow_params.release.tag_prefix`, `workflow_params.release.version_style`, `workflow_params.release.check_script`, `workflow_params.release.create_release` | The only parameters of the `release` template a repository may set; `main_branch` and the environment come from the policy and the repository |
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
| `rulesets.default_branch.required_status_checks`, `rulesets.default_branch.admin_bypass` | Checks that must pass (none: no checks rule); `admin_bypass: true` lets the admin role bypass `tld-main` through a pull request. Default false (the single-repository starter keeps it, the shared base starter sets true; this repository sets it true so its single owner can merge their own pull requests) |
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
| `profile.base` | The base file as `<owner>/<repo>/<path>`, without a pin; required inside `profile`. See [org-base.md](org-base.md) |
| `profile.pin` | `latest-tag` (default: the newest tagged commit of the base) or a 40-hex commit; a tag name is rejected |
| `profile.guarded_overrides` | `report` (default: list each guarded key a repository overrides with the base's permission) or `ignore` |
| `git_ops.repo` | The central repository as `<owner>/<repo>` (the repository's own owner and `git-ops` when the project profile has an origin) |
| `git_ops.workflow` | The workflow file name in the central repository (default `tld-git-ops.yml`) |
| `git_ops.allowlist` | The file in the central repository naming every audited repository. Entries are compared ignoring case; an entry that matches every repository, uses a wildcard on the owner or reaches a repository the audit did not see is reported, not written |
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
  With `admin_bypass: true` (this repository, which has one human) the owner, who has the admin role, may merge a
  pull request without a second reviewer. The bypass is in `pull_request` mode: no direct push, force push or
  deletion. It skips every rule of `tld-main` for that pull request, the required checks included, so the owner
  waits for green CI. The agent account keeps `write` and is never a bypass actor. Leave it `false` where a second
  human can review (the single-repository starter `admin-policy.yaml` does). The shared base starter
  `admin-policy-base.yaml` sets it `true`, so an organisation that extends it gets `true` unless its own policy file sets `false`
  (a guarded key: an override cannot turn it on then).
  Because of `require_last_push_approval`, the owner's approval counts only when the latest push to the pull request
  came from someone else. **Do not press "Update branch" on an agent's pull request**: that push is the owner's, so no
  approval of the owner can merge it until the agent pushes again. Ask the agent to bring the branch up to date (the
  `tld-land` workflow does this with the agent's token).
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

`template: release` installs `.github/workflows/tld-release.yml`. Parameters:

| Parameter | Default | |
|---|---|---|
| `tag_prefix` | `v` | the tag is `<tag_prefix><version>` |
| `release_environment` | `release.environment`, else `tld-release` | the environment the job runs in |
| `version_style` | `semver` | `semver` (`1.4.0`, `1.4.0-rc.1`) or `pep440` (`1.4.0`, `1.4.0a1`, `1.4.0b2`, `1.4.0rc1`) |
| `check_script` | empty: none | a repository-relative script run before the tag, with the version (without the prefix) as its one argument; `.py` runs with `python3`, `.sh` with `bash`, anything else must be executable. A non-zero exit stops the release |
| `create_release` | `true` | `false`: only the tag; the repository's own `on: push: tags` workflow makes the GitHub release |

`tld ops repo-admin validate-policy` checks `version_style`, `create_release` and that `check_script` is a path
inside the repository.

The pattern for many repositories is one release workflow everywhere: `tld-release` cuts every tag, and each
repository's own workflows react to the tag (`on: push: tags`) to build and publish. Set `create_release: false`
where such a workflow already creates the GitHub release, and point `check_script` at a repository's own
pre-release checks (version sequence, changelog section) instead of keeping a second tagging workflow.

- The owner runs it by hand: Actions, `tld-release`, Run workflow, on the main branch, and approves the run in the
  environment. It has no other trigger. What stops anyone else from tagging is the `tld-tags` ruleset and the
  environment above, not the workflow's branch check.
- Inputs: `version` (for example `1.4.0`; empty bumps the newest `<tag_prefix>x.y.z` tag by `bump`: `patch`, `minor`, `major`),
  `prerelease`, `skip_checks`, and `dry_run`, which is ticked by default. A dry run shows the tag and the generated notes in the run summary.
- With a `check_script`, every run (a dry run too) clones the repository with every tag, checks out the main branch
  at the commit to be tagged, and runs the script there. The read-only workflow token is used for the fetch only; the
  script gets no token.
- Unticked, it checks that every check run on the head commit succeeded (the rule of `tld ops release-check`: a check run still running or not success, skipped or neutral stops it, as does a commit status that is failure, error or pending with at least one status), creates an
  annotated tag on that commit and, unless `create_release` is `false`, a GitHub release with generated notes. It stops if the tag exists.
  To roll an updated template out, run `apply`; each repository gets one pull request.
- Its `GITHUB_TOKEN` only reads (`contents: read`); the notes, the tag and the release are made with
  `TLD_RELEASE_TOKEN`, and the run stops when that secret is missing. A tag made with it starts other workflows (a
  build, a publish). It is separate from `TLD_AGENT_TOKEN` so the release never runs as the agent.
- It uses no third-party action and passes inputs to the shell only through environment variables.

## Not covered

Rulesets other than `tld-main` and `tld-tags`, the organisation's Actions allow list, environments other than
`tld-agent` and `tld-release`, and the values of any secret, Codespaces secrets, OAuth
authorisations, classic personal access tokens (in a SAML organisation `GET /orgs/{org}/credential-authorizations` lists them), and people (adding or removing members). The report says so where it
matters (`info`). Scheduling an audit (a weekly workflow that opens an issue) is left to you.
