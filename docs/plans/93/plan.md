# Plan 93: one inherited repo-admin policy for every repository of an organisation

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** An organisation's own small policy file holds `org` and `extends: [<shared base pin>, <private org file pin>]`; each pin is `<owner>/<repo>/<path>@<40-hex commit>`. `tld ops repo-admin validate-policy` resolves it (`--resolved`, `--explain`), `audit` reads each repository's small `.tld/admin-policy.yaml` and audits the effective policy per repository, and `latest-pin` prints the pin to write. The audit also proposes, as pull requests, an override file written from what the repository shows (required checks, release parameters) and converts an old whole-policy file.

**Scope:** New policy model, `extends` fetch through the API, per-repository merge, derived logins, detection and the docs, schema, starters, playbook, evals and spec for them. Policies without `extends` behave as before. It depends on plan 90 (pin grammar, secret check, the remote profile reader, the pin and git-ops checks, which are this ask's item 8). No architecture change: the code stays inside the existing Ops part.

**Security:** The extended files and the override files are read with the owner's token and merged into what the audit may change, so each is checked for credentials, shape and key class; an override cannot set organisation-level keys, an override that loosens a guarded setting is clamped back and reported, and no inherited file can switch on a deletion or a revocation. `--yes`, `--allow-delete` and the dry run are unchanged.

**Performance:** Detection adds about 22 API calls per repository that has no override yet, once.

**Review focus:** The per-repository merge and the keep-live rules that stop inheritance from dropping a ruleset check or rewriting a tuned release workflow (3.7); the key classes and guarded table (3.3, 3.6); the dependency on plan 90 and the three names it must provide (3.12).

## 1. Goal

Make the repo-admin policy generic and inherited, as asked in [issue #93](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/93), the way plan 90 does it for the profile. Today each repository keeps a whole copy of the organisation policy and the copies drift. After this plan the organisation keeps one shared base (in `tkcs-lab/.github`, public) and a private file of organisation-level sections (in `<org>/git-ops`), each organisation has one small policy that extends both, and each repository keeps only its own overrides. The owner's answers: the `.github` repositories are public, the shared base lives in `tkcs-lab/.github` at `tld/admin-policy-base.yaml` and both organisations extend it, and the organisation-level sections go into a separate private file.

## 2. Current state

- One global policy: every check reads `ctx.p` (24 sites, `src/tld/ops/repo_admin.py:505` to `:1443`), loaded by `load_policy` (`:320`) after `validate_policy` (`:262`). `Ctx.repos` (`:406`) filters repositories by `repos`.
- The schema (`src/tld/schema/admin-policy.schema.json`) requires `org`, `agent.agent_login` (`:151`) and `release.reviewer_login` (`:163`) and rejects unknown keys. The starter is `src/tld/templates/admin-policy.yaml`; `tests/core/test_repo_admin.py:126-150` require every schema property in the starter and `:210-225` require every key and every check name in `docs/guides/admin.md`.
- The two real policies (`.tld/admin-policy.yaml` here, the second in the privacyfence repository) agree on `security`, `actions`, `rulesets.tags`, `admin_bypass`, the logins and `release.environment`; they differ in the status checks (2 against 10 names), `config_dirs.known`, the release parameters and the `workflows` list.
- `ruleset_bodies` (`:765`) builds `tld-main` without a status-check rule when `required_status_checks` is absent, and `ruleset_diffs` (`:808`) then reports `extra rules required_status_checks` so `apply --yes` would drop every required check. `check_tokens` (`:566`) revokes expired tokens unless `revoke_expired` is false (default true) and always revokes unused ones. The release template renders `v`, `semver`, `create_release true` when no params are given (`BUILTIN_TEMPLATES`, `:57`).
- `playbooks/repo-admin.md` is linked from no command, so it is in no hash of `evals/baselines/default.json`.
- Plan 90 (`origin/feature/org-base-profile`, planned, not merged) designs the pin grammar (`BaseRef`, `parse_extends`, 40-hex commit), `check_base_text`, `repo_admin_profile.py` (pin, merge-style and guarded-override checks) and `repo_admin_gitops.py`. Its p12 and p13 are this ask's item 8.

## 3. Design

The architect role designed 3.1 to 3.11; each choice names what was rejected. Names are final.

### 3.1 Layers and where the merge happens

Order, later wins: the files of `extends` in the order listed, the run file (the policy file given to `--policy`), then the repository's override file. Mappings merge key by key; lists and scalars replace (the owner's rule, as in plan 90). The result of the first two layers is the **organisation policy** (`ctx.p`). The **effective policy** of a repository is `ctx.pol(repo)`.

**Chosen:** `Ctx.p` stays the organisation policy; a new `Ctx.pol(repo)` returns one repository's effective policy and every per-repository check reads it inside its `one(repo)`. Without `extends` in the run file (`Ctx.inherited` false) `pol(repo)` returns `ctx.p` and nothing extra is read, so old files and every existing test behave identically. **Rejected:** a sub-`Ctx` per repository (the `only`/`partial`/`repos` properties and the organisation-wide "unused" scans would need special cases, finding order would change, every check test would change). The 24 sites split: organisation-level and unchanged: `check_org`, `check_members`, `check_apps`, `check_tokens`, `check_protection`, `check_secrets`, `check_variables`, `check_labels`, `check_webhooks`, `check_keys`, `check_branches`, and `Ctx.repos`; moved to `pol(repo)` inside `one(repo)`: `check_repo`, `check_security`, `check_actions`, `check_rulesets`, `check_agent`, `check_release`, `check_files` (`config_dirs`, `workflows`, `release.environment`), `check_lint`. `workflow_source` keeps `ctx.p` for `_dir` (a `path` template comes only from the run file). The early `if not want: return []` guards move inside `one(repo)`, because an override may write a section the organisation policy lacks.

### 3.2 The four file kinds

| Kind | Where it comes from | `org` | Checked as |
|---|---|---|---|
| run | the file given to `--policy`, a private local checkout | required | `validate_policy(kind="run")` (the default) |
| base | any file named by `extends`, public or private | absent | `key_errors(kind="base")` |
| override | a repository's `.tld/admin-policy.yaml` | absent | `key_errors(kind="override")` |
| legacy | a repository file that has `org` (an old whole policy) | present | converted in memory to an override |

`validate_policy(policy, base_dir=None, kind="run")` keeps its default so old callers are unchanged ( `{}` still gives `missing required key 'org'`). The command line has `--kind auto|run|override|base` (default `auto`: run when `org` is present, else override). A kind other than run validates against a copy of the schema without the top-level `required`.

### 3.3 Key classes (tables in `repo_admin_policy.py`)

- `RUN_ONLY = ("org", "extends", "repos")`: only the run file. `repos` holds the exceptions (`exclude`), `override_path` (default `.tld/admin-policy.yaml`, a relative path without `..`) and `allow_loosen` (3.6). An override that could set `repos.exclude` would exempt its own repository, so it is refused there (architect finding 4).
- `PRIVATE_ONLY = ("org_settings", "members", "apps", "tokens", "secrets", "variables")`: allowed in the run file and in an extended file of a private repository; refused in an extended file of a public or internal repository.
- `ORG_LEVEL = PRIVATE_ONLY + ("labels", "webhooks", "deploy_keys", "branches", "branch_protection", "profile", "git_ops")`: the run file or any extended file; never an override. (`profile` and `git_ops` are plan 90's p12 sections, the item 8 settings; they are organisation-specific and go into the organisation's private file.)
- `OVERRIDABLE = ("repo_settings", "security", "actions", "rulesets", "agent", "release", "workflow_lint", "config_dirs", "workflows", "workflow_params")`: the run file, a base (except the per-repository keys) and an override.
- `PER_REPO_ONLY = ("rulesets.default_branch.required_status_checks", "workflow_params", "config_dirs.known", "workflows[].params")`: allowed in an override and in the run file (the old single-repository use); refused in a base.
- A test asserts that these tables classify every top-level property of the schema (extra names such as `profile` are allowed), so a new key cannot slip through unclassified.
- `null` is refused anywhere in a base or an override, so an override cannot delete a section.

### 3.4 `extends`: grammar, fetch, no cache

- `extends` is a string or a list of one to four strings; the starter holds an empty list. Each entry is `<owner>/<repo>/<path>@<40-hex commit>`, the grammar and pin rule of plan 90 section 3.2 (a tag or branch is rejected; the tag stays as a trailing YAML comment). Two entries naming the same `<owner>/<repo>/<path>` are an error. **Rejected:** a string only (the owner's answer needs two files).
- **Fetch:** `GET /repos/{owner}/{repo}/contents/{path}?ref=<sha>` through the run's client, so a private file is readable with the owner's token and the audit needs no checkout; `GET /repos/{owner}/{repo}` gives `private`, `visibility` and `default_branch`; `GET /repos/{owner}/{repo}/compare/{default_branch}...{sha}` must answer `behind` or `identical` (the pin is an ancestor of the default branch), so a commit on an unreviewed branch of the base repository is refused. **Rejected:** plan 90's anonymous git fetch (cannot read the private file, needs a checkout).
- **No disk cache** (a departure from plan 90, which caches under the git directory): the audit is online by nature, a commit-addressed fetch costs three calls per file and a private file should not rest on a disk outside a repository. The run memoises each file once.
- **Reuse of plan 90 (`src/tld/profile/base.py`):** `BaseRef` and `parse_extends(value, label=...)` for the grammar, and `check_base_shape(text, label)` for size 65536 bytes, UTF-8 without BOM, no YAML anchors or aliases, a mapping on top, depth 8, `secret_scan.scan_text` after removing every `secret-scan:allow` mark, and refusal of any mapping key for which `secret_like_name` is true. If plan 90 landed without the `label` keyword or without the split of `check_base_shape` out of `check_base_text`, phase p3 makes those two compatible edits in `base.py` (defaults keep the profile texts); it never copies the code.
- Every extended file and every override goes through `check_base_shape` (an override comes from a repository an agent can edit, and anchors are an expansion vector).
- Errors (printed with the prefix `policy: `; `<i>` the index; `<label>` is `<owner>/<repo>/<path>@<sha7>`):
  - `'extends[<i>]': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got '<value>')`
  - `'extends[<i>]': '@<ref>' is not a commit SHA; pin the file by its full 40-hex commit (a tag can move): run tld ops repo-admin latest-pin <owner>/<repo>/<path>`
  - `'extends': <owner>/<repo>/<path> is listed twice`
  - `'extends[<i>]': cannot read <label> (HTTP <status>: <message>); a private file needs a token that can read it (GH_TOKEN, GITHUB_TOKEN or gh auth login)`
  - `'extends[<i>]': <sha7> is not on the default branch of <owner>/<repo>; pin a commit that was merged there`
  - `base <label>: sets 'extends'; an extended file cannot extend another`
  - the plan 90 token text with the label `base <label>:`: `base <label>: refused: line <n> looks like <kind> (pattern: <name>); the value is not shown. A base never holds a credential.`
- `tld ops repo-admin latest-pin <owner>/<repo>/<path>` prints `{"sha": "<40-hex>", "tag": "<tag>"}`: tags through the API, newest by numeric components (`^v?\d+(\.\d+)*$`, at most 20 tried), the first whose commit has the file; otherwise the default branch head with `"tag": null`; it exits 1 with `latest-pin: <path> does not exist in <owner>/<repo>` when no commit has the file.

### 3.5 Merge, workflows and the resolved view

- `deep_merge(base, over)`: mappings merge, lists and scalars of `over` replace. `merge_layers(layers)` returns the merged dict and a map from dotted leaf key to the layer label that set it.
- **Workflows.** The base lists the templates without parameters: `workflows: [{template: release}, {template: land}]`. A repository sets parameters without restating the list through the new override key `workflow_params: {release: {tag_prefix, version_style, check_script, create_release}}`; `apply_override` copies them into the entries of the effective `workflows` list by template. A repository whose release workflow is its own writes `workflows: [{template: land}]` (lists replace). An override's `workflows` entries may hold only `template`, `params` and `remove`; `path`, `dest` and `repos` are refused there and in a base because the file comes from a repository and `path` cannot be resolved remotely; a base entry may hold only `template`. **Rejected:** merging `workflows` by template (it is unclear whether a one-entry override drops `land`).
- **Resolved view.** `validate-policy POLICY --resolved` prints the merged policy as YAML (keys that start with `_` left out); `--explain` prints one line per leaf, `<dotted key> = <json>  # <source>`, sorted, with the sources `run <path>`, `base <label>`, `override <owner>/<repo>:<path>` and `derived (<what>)`; `--org-policy FILE` with an override file prints the effective policy of that repository over that organisation policy. The OK line stays `policy: OK (<path>)` for a run file and ends `, repository override` or `, base` for the other kinds.

### 3.6 Safety

1. **Irreversible switches.** `IRREVERSIBLE = (secrets.delete_unused, variables.delete_unused, labels.delete_unused, labels.delete_unlisted, webhooks.delete (non-empty), deploy_keys.delete_unused, branches.delete_merged, tokens.fine_grained.max_unused_days, tokens.fine_grained.revoke_expired)`. A base that sets one to a value that turns it on is refused: `base <label>: '<key>' turns on an irreversible change; set it only in the policy file you run`. `revoke_expired` defaults to true, so `clamp_irreversible(merged, run_doc)` sets `tokens.fine_grained.revoke_expired` to `false` when the run file has no `tokens.fine_grained` and a base supplied one. The sections of these keys are organisation-level, so an override cannot set them either. `apply_findings`, `--yes` and `--allow-delete` do not change.
2. **Guarded settings** (`GUARDED`): must stay true: `security.*` (five keys), `rulesets.tags`, `workflow_lint.require_permissions`, `workflow_lint.forbid_pull_request_target`; must stay false: `rulesets.default_branch.admin_bypass`, `actions.can_approve_pull_request_reviews`; ordered (stricter last): `actions.default_workflow_permissions` (write, read), `workflow_lint.pin_actions` (third_party, all), `agent.branch_policy` (protected_branches, default_branch); must equal the organisation's value: `repo_settings.allow_merge_commit`, `allow_squash_merge`, `allow_rebase_merge`; lists that may not shrink: `config_dirs.forbid`, `config_dirs.require`. `loosened(org, eff)` compares only keys the organisation policy sets. `clamp_guarded(org, eff, allowed)` puts the organisation's value back (a shrunk list gets its dropped entries back) and returns the `Loosening` records; the `policy` check warns `<repo>: the override sets <key> to <value>, looser than the organisation's <value>; the organisation value applies`. The run file may allow it: `repos.allow_loosen: {"<repo name glob>": ["<guarded key>", ...]}`. Dropping a template from `workflows` is information only, not guarded.
3. **Public base.** An extended file in a public or internal repository may not set a `PRIVATE_ONLY` section: `base <label>: '<section>' is organisation-private and <owner>/<repo> is public; keep org_settings, members, apps, tokens, secrets and variables in a file of a private repository`. `validate-policy --kind base --public` applies the same rule to a local file before it is committed.
4. **Class errors** (`<where>` is `<owner>/<repo>:<path>` for an override read from a repository, else the file path): `<where>: '<key>' is organisation-level; only the organisation's policy and the files it extends may set it`; `base <label>: '<key>' is per repository; set it in each repository's override file`; `base <label>: 'workflows[<i>].params' is per repository; use workflow_params in each repository's override file`; `base <label>: 'workflows[<i>].<key>': a base may set only template`; `<where>: 'workflows[<i>]': a repository override may set only template, params and remove`; `<where>: '<key>': null is not allowed`; `'repos.override_path': must be a path below the repository root (no absolute path, no '..')`; `'repos.allow_loosen': '<key>' is not a guarded key`.
5. An override with problems is an `error` finding of the `policy` check; that repository is then audited with the organisation policy alone.

### 3.7 The per-repository audit

`Ctx` gains `inherited` (the run policy carries `_inherited`, set by the resolver), `override(repo)` (memoised: reads `repos.override_path` from `snapshot(repo)` at `snap.commit`, runs `check_base_shape`, the class errors and `validate_policy(kind="override")`, converts a legacy file) and `pol(repo)` (memoised under `("pol", full_name)`: `apply_override` then `clamp_guarded`). New check `policy` (`check_policy`, registered last in `CHECKS`, documented in the checks table of `docs/guides/admin.md`): override problems (`error`), loosenings (`warn`, subject `loosen:<key>`), a legacy file (`fix`, subject `override:convert`, a `files` action that replaces the file with the minimal override), a `workflow_params` template that is not in the effective list (`warn`), and, from p7, the detected proposals (`fix`, subject `override:propose`).

**Absent is not empty** (architect findings 1 and 3). In inherited mode:
- `rulesets.default_branch.required_status_checks` absent: `ruleset_bodies(cfg, live_checks=None)` takes the live ruleset's status-check contexts and keeps them; only an explicit `[]` removes the rule. A missing `tld-main` is created without a check rule. Without `extends` the behaviour is exactly today's.
- The release template entry with neither `workflow_params.release` nor its own `params` is not installed or rewritten: an `info` finding (subject `workflow:<dest>:standdown`) says so; the `policy` check proposes the parameters.
- No `release` section in the repository's resolved profile: the release template stands down with the same `info` finding (no value to compare).

`apply_files(client, repo, changes, default_branch, commit, tree, today, notes=())` appends the notes under `Detected values (the owner confirms them):` as escaped bullets; `Action` gains `note: str = ""`; `apply_findings` passes the notes of a repository's file actions. Nothing else on the apply path changes.

### 3.8 Derived logins

`derive_logins(profile) -> (agent, reviewer, reasons)`: agent is `git.bot_login`; reviewer is `git.owner_login`, else the one `git.codeowners` entry when there is exactly one, it is a plain login (matches `^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$`, no `/`, not the bot). An explicit `agent.agent_login` or `release.reviewer_login` in the effective policy wins and the profile is not read. The profile is the repository's resolved profile at its default branch, read by plan 90's remote profile reader. The schema loses `required` for `agent_login` and `reviewer_login`; for a run policy without `extends`, `validate_policy` still reports the old `missing required key` text, so old files behave the same. With no profile or no value: a `warn` finding `<repo>: agent.agent_login is not set and cannot be derived (<reason>)` with the manual `set git.bot_login in the repository's profile or agent.agent_login in its override`, the role part skipped, the environment and secret part still run; for the release check `release.reviewer_login` likewise and the whole release check skipped for that repository (comparing reviewers with none would loosen it). The reviewer id lookup moves inside `one(repo)` (it is memoised per login).

The profile's `release.workflow` default (`tld-release.yml`) is already plan 90 section 3.1; this plan only reads it.

### 3.9 Detection (proposal only)

`repo_admin_detect.py`. Pure: `status_checks`, `release_params`, `tag_workflow_creates_release`, `own_release_workflow`, `detected_override`, `pr_notes`. I/O: `gather(ctx, repo)`.
- **Checks.** Samples are the newest `DETECT_PRS = 10` merged pull requests of the default branch (`GET /repos/{fn}/pulls?state=closed&base=<branch>&sort=updated&direction=desc&per_page=50`, keep those with `merged_at`). Per sample: `GET /repos/{fn}/commits/{head}/check-runs?filter=all&per_page=100` and `GET /repos/{fn}/commits/{head}/status`. `status_checks(samples)` returns `(names, excluded)`: fewer than `DETECT_MIN_PRS = 3` samples gives no names and the reason `too few merged pull requests (<n>)`; a name is kept only when it concluded `success` on every sample. Excluded, first matching reason: `flaky: success and failure on the same commit in #<n>`; `failed on #<n>`; `skipped on #<n>` (also `neutral`, `cancelled`, `stale`); `pending on #<n>`; `seen on <k> of <n> pull requests (path filter or new)`. Failure and flakiness do not depend on whether the API returns re-runs: a check that failed on any sampled head is excluded, because a merged pull request with a red check means the check is not reliable or was bypassed.
- **Release parameters.** `release_params(tags, manifests, tag_workflow)` returns `(params, notes)`: `tag_prefix` is the most common prefix of version-like tags (`^(\D*?)(\d+\.\d+\.\d+)(.*)$`; a tie goes to the prefix that sorts first; no such tag gives no params and the note `no version-like tags`); `version_style` is `semver` when a suffix matches `^-[0-9A-Za-z.-]+$`, `pep440` when a suffix matches `^(a|b|rc)\d+$`, else `pep440` when `pyproject.toml` is in `manifests`, else `semver`; `create_release` is `"false"` when `tag_workflow` is true; `check_script` is never guessed. `tag_workflow_creates_release(texts)` is true when a workflow text matches `(?ms)^\s*push:\s*\n(?:[ \t]+.*\n)*?[ \t]+tags:` and contains `gh release create`, `action-gh-release` or `create-release`. Tags: `GET /repos/{fn}/tags?per_page=100`; manifests: the top-level blobs `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod` of the snapshot; workflows: `ctx.automation_files`.
- **Own release workflow.** `own_release_workflow(profile_release_workflow, workflows)` returns the effective `workflows` list without the release template when the resolved profile names a release workflow other than `tld-release.yml` and the list has the release template, else `None`; with it, release parameters are not proposed.
- `detected_override(checks, params, workflows)` builds the override mapping; `propose_override(existing, detected)` keeps every key the repository already wrote; `render_override(doc)` writes a two-line comment header and `yaml.safe_dump(sort_keys=False)`. Names reach YAML only through `safe_dump` and the pull request body only through the existing `_cell` escaping.
- Detection runs only for a repository whose effective policy has `rulesets.default_branch` and no `required_status_checks`, or the release template without parameters, or that has no override file; a failed call is an `unavailable` finding.

### 3.10 Reproduction and the delta

Fixtures in `tests/fixtures/admin-policy/` (a test may name the two organisations): `shared-base.yaml` (the content of 3.11), `org-a.yaml` and `org-b.yaml` (run files with `org` and `extends` placeholders), `override-a.yaml` and `override-b.yaml`, and `legacy-a.yaml` and `legacy-b.yaml` (copies of today's two files; `a` is this repository's, `b` the second). The reproduction test builds the effective policy of each repository and compares it with its legacy file after removing `org`, `repos` and the two derived logins; the only differences allowed are the listed delta, because the base manages more than the old file `a` (this repository's) did: `repo_settings.allow_merge_commit`, `allow_squash_merge`, `allow_rebase_merge`, `config_dirs.forbid` and `workflow_lint`; for `b` (the second repository's) there is none. A second test runs every check on one fake organisation twice, once with the legacy policy and once with the inherited one, and compares the set of `(check, scope, subject, severity)`, ignoring the `policy` check, on a fake state that already matches the base-only sections. The repository's own `.tld/admin-policy.yaml` is not converted by a phase: the first audit proposes the conversion (manual step ma2), so the owner keeps a runnable policy until the base exists.

### 3.11 Starters and base content

`src/tld/templates/admin-policy.yaml` gains `extends: []` and `workflow_params: {}` (the starter test needs every property). New `src/tld/templates/admin-policy-base.yaml` is the shared base, from the two real policies:

```yaml
repo_settings: {allow_auto_merge: true, delete_branch_on_merge: true, allow_update_branch: true, allow_merge_commit: true, allow_squash_merge: false, allow_rebase_merge: false}
security: {vulnerability_alerts: true, automated_security_fixes: true, secret_scanning: true, secret_push_protection: true, private_vulnerability_reporting: true}
actions: {default_workflow_permissions: read, can_approve_pull_request_reviews: false}
rulesets: {default_branch: {admin_bypass: true}, tags: true}
agent: {branch_policy: default_branch}
release: {environment: tld-release}
workflow_lint: {pin_actions: third_party, require_permissions: true, forbid_pull_request_target: true}
config_dirs: {forbid: [".archon", ".agents"]}
workflows: [{template: release}, {template: land}]
```

(`admin_bypass: true` is the single-owner choice the ask names; it applies to every repository of both organisations, and a repository tightens it by setting `false`.) New `src/tld/templates/admin-policy-org.yaml` is the organisation-level file: the six private sections as commented examples, `profile` and `git_ops` (plan 90) as commented examples, no irreversible switch. Where files live: the organisation policy `tld/admin-policy.yaml` and the private file `tld/admin-policy-org.yaml` in `<org>/git-ops` (a private repository; the policy is run from a checkout with `--policy`); the shared base in `tkcs-lab/.github` at `tld/admin-policy-base.yaml`.

### 3.12 Item 8 and plan 90

Item 8 (profile pin, guarded overrides, git-ops central repository) is plan 90's p12 (`repo_admin_profile.py`) and p13 (`repo_admin_gitops.py`), written but not implemented. **Chosen:** this plan depends on plan 90 being merged and only integrates: `profile-merge-style` reads `ctx.pol(repo)` (p6), the git-ops allowlist names `ctx.repos`, which now defaults to every repository, and `profile` and `git_ops` are organisation-level sections of the organisation's private file. **Rejected:** a copy here (about 500 duplicated lines, two definitions of the `profile` and `git_ops` schema sections in the same JSON block, duplicate check names). Cost: nothing from p3 on can start before plan 90's pull request merges (manual step mb1).

Names this plan needs from plan 90, read from the landed code by the phases (a phase stops with `status=blocked` if one is missing and cannot be added as stated):
1. `src/tld/profile/base.py`: `BaseRef` (owner, repo, path, sha) and `parse_extends`. p3 adds the optional `label` keyword and the `check_base_shape(text, label)` split when absent (compatible edits).
2. `src/tld/ops/repo_admin_profile.py`: a memoised reader of a repository's resolved profile at its default branch; plan 90 p12 does not name it, so p7 uses the function that p12 landed or, when none returns the resolved dict, adds `repo_profile(ctx, repo) -> dict | None` that calls the code p12 already uses.
3. The schema sections `profile` and `git_ops` of plan 90 p12 (classified in 3.3 whether or not they exist).

Plan 90 also touches `evals/baselines/default.json` for `playbooks/repo-admin.md`, which is in no command hash; that is plan 90's to settle. Plan 90's pins accept any 40-hex commit; the reachability check here is stricter, and plan 90 may adopt it.

### 3.13 Spec change, architecture, tests

`openspec/changes/admin-policy-inheritance/` (validated with `tld ops spec validate --change admin-policy-inheritance`) holds six `ADDED` requirements for `release-and-repo-ops` and no `MODIFIED` block, so plan 90's own delta to the same capability cannot make this one stale. No architecture change: the new modules sit in the existing Ops part and add no part, port or dependency, so no `sysml_change`. Every new test that proves a scenario is named `test_<scenario>` in lower case with other characters as one underscore, and acceptance names it as a pytest node id. No version bump here: the release skill bumps the three version lines; the changelog line goes under `## [Unreleased]`.

### 3.14 Rejected alternatives

A sub-`Ctx` per repository; a string-only `extends`; anonymous git fetch and a disk cache; `workflows` merged by template; override files allowed to set `repos`; reporting a loosening but applying it; copying plan 90's item 8 checks; converting this repository's own policy file inside a phase; a profile key for the organisation policy's path (the run file is given with `--policy`).

## 4. Manual steps

mb1 is needed before any phase; ma1 and ma2 happen after the last phase merges and before the feature pull request merges, because they need the new commands (about 55 minutes in all).

### Before implementation

**mb1 - Merge plan 90 (about 5 minutes once its pull request is ready).**

1. Open [issue #90](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/90) and follow its plan `https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/org-base-profile/docs/plans/90/plan.md`: run implement for it and merge its feature pull request.
2. Check on `main`: `ls src/tld/profile/base.py src/tld/ops/repo_admin_profile.py src/tld/ops/repo_admin_gitops.py` lists all three.

Done when all three files exist on `main`. Implement merges `origin/main` into this plan's feature branch when it starts.

### After implementation

**ma1 - Create the files in GitHub (about 25 minutes per organisation).**

1. Open `https://github.com/tkcs-lab/.github`. If it does not exist: `https://github.com/organizations/tkcs-lab/repositories/new`, name `.github`, **Public**, tick "Add a README", Create. Check `https://github.com/privacyfence/.github` is public (it is today).
2. Open `https://github.com/organizations/tkcs-lab/repositories/new` and `https://github.com/organizations/privacyfence/repositories/new` and create `git-ops` in each if it does not exist, **Private**. (Plan 90's manual step ma2 needs the same repositories.)
3. In a checkout of this repository on the feature branch, copy `src/tld/templates/admin-policy-base.yaml` to `tld/admin-policy-base.yaml` in a clone of `tkcs-lab/.github`. Run `tld ops repo-admin validate-policy --kind base --public tld/admin-policy-base.yaml`; expect `policy: OK (tld/admin-policy-base.yaml, base)`.
4. Open a pull request in `tkcs-lab/.github` with that file, get it approved by the code owners and merge it (never push to the default branch). Tag the merge commit: `git tag v1 <sha> && git push origin v1`.
5. In each organisation's `git-ops` clone create `tld/admin-policy-org.yaml` from `src/tld/templates/admin-policy-org.yaml`: uncomment only the organisation-level sections you want managed, and the `profile` and `git_ops` sections for that organisation (plan 90's guide says the keys). Validate it with `tld ops repo-admin validate-policy --kind base tld/admin-policy-org.yaml` (no `--public`: the repository is private), merge it through a pull request and tag it `v1`.
6. Print both pins: `tld ops repo-admin latest-pin tkcs-lab/.github/tld/admin-policy-base.yaml` and `tld ops repo-admin latest-pin <org>/git-ops/tld/admin-policy-org.yaml`; each prints `{"sha": ..., "tag": "v1"}` (needs `gh auth login` as the owner).
7. In each `git-ops` clone create `tld/admin-policy.yaml` with `org: <org>`, `extends` listing the base pin first and the organisation file second, each written `<owner>/<repo>/<path>@<sha>  # v1`, and `repos: {exclude: [...]}` for the exceptions. Put every irreversible switch you want in this file only. Run `tld ops repo-admin validate-policy tld/admin-policy.yaml --resolved` and read the merged policy; `--explain` shows where each value comes from.

Report back: the two pins per organisation and the `validate-policy` result.

**ma2 - Run the first audit with an owner token (about 30 minutes).**

1. In a clone of `<org>/git-ops` on your own machine run `gh auth login` as the owner (a web session cannot run the audit).
2. `tld ops repo-admin whoami --org <org>` must print `"can_administer": true`.
3. `tld ops repo-admin audit --policy tld/admin-policy.yaml --out <org>-audit.md`. Expect `policy` findings: a conversion of each repository's whole `.tld/admin-policy.yaml` into a minimal override, or a proposed new override where the file is absent, plus plan 90's pin and git-ops findings.
4. `tld ops repo-admin apply --policy tld/admin-policy.yaml --only <id> ...` is a dry run; add `--yes` to open the pull requests. Never add `--allow-delete` for these.
5. Open each pull request, read the proposed `required_status_checks` and the list of excluded checks with their reasons in its body, correct them, and merge it yourself (the script merges nothing).
6. The audit cannot create the `GIT_OPS_TOKEN` secret or the `git-ops` environment; it lists them as open items: create them as plan 90's guide says.
7. Run the audit again and report one pass or fail line per repository.

Report back: pass or fail per repository, and any `policy` finding you did not understand.

## 5. Risks and open questions

1. **Plan 90 changes or lands differently.** A worker finds `parse_extends`, `BaseRef`, the remote profile reader or the schema sections `profile` and `git_ops` missing or renamed. Symptom: `ImportError` or `AttributeError` in p3, p4 or p7. Stop with `status=blocked` and name what is missing; do not copy plan 90's code.
2. **`compare` semantics.** The reachability check assumes `compare/<default>...<sha>` answers `behind` or `identical` for an ancestor. If the first real run refuses a valid pin, the status word differs: stop and report the answer.
3. **A ruleset that loses its checks.** Symptom: a `rulesets` fix whose body has no `required_status_checks` for a repository whose live rule has them. The keep-live rule of 3.7 is missing or reads the wrong ruleset.
4. **A tuned release workflow rewritten.** Symptom: `workflow .github/workflows/tld-release.yml differs from its template` for a repository without `workflow_params.release`. The stand-down of 3.7 is missing.
5. **Import cycle** `partially initialized module` between `repo_admin`, `repo_admin_profile`, `repo_admin_extends` and the two pure modules: the pure modules import nothing from `repo_admin`; `repo_admin_extends` imports `ApiError` inside a function.
6. **API budget.** Detection is about 22 calls per repository; a 429 in a large organisation means the first audit runs with `--repo` batches; the client already waits out one rate limit.
7. **Mutants.** `tests/core/test_mutants_file.py` fails when a mutant's `old` text no longer occurs once. p3 may touch `src/tld/profile/base.py`, which plan 90 mutants cover; p9 adds the new ones.
8. **The reproduction test cannot be made equal** without a difference beyond the listed delta: the key classes are wrong; stop and report the difference.
9. **No project words** (`tests/core/test_no_project_words.py`): organisation and repository names live in `tests/` and `docs/`, never in `src/`, `playbooks/` or `adapters/`; the word `pytest` stays out of `src/`.
10. **Open questions answered by default.** Item 13 of the architect's report: a repository with no `release` section in its profile has its release template stand down with an `info` finding. The shared base sets `admin_bypass: true` for every repository of both organisations, as the ask says. `config_dirs.require` is overridable (the ask is silent). Change 3.3 before implementing if you disagree.
11. **Flaky detection.** The rule does not rely on `filter=all` returning re-runs; it also excludes any check that failed on a merged pull request's head. No research request was needed.

## Implementation manifest

```yaml
plan_slug: admin-policy-inheritance
feature_branch: feature/admin-policy-inheritance
tracking_issue: 93
spec_change: admin-policy-inheritance
max_parallel: 3
manual_before:
  - id: mb1-plan-90-merged
    title: Merge plan 90 (the org base profile) to main
    why: p3 reuses plan 90's pin grammar and shape check, p7 its remote profile reader and its pin and git-ops checks; without them p3 and p7 stop blocked.
    done_when: src/tld/profile/base.py, src/tld/ops/repo_admin_profile.py and src/tld/ops/repo_admin_gitops.py exist on main.
manual_after:
  - id: ma1-create-files
    title: Create the shared base, the private organisation files and each organisation's policy, tag them and print the pins
    why: A phase cannot create files in another organisation's repositories; the audit needs the pinned files.
  - id: ma2-first-audit
    title: Run the first audit with an owner token and review the pull requests it proposes
    why: The audit needs an organisation owner's token, which a cloud session never has.
verify_after_merge:
  - .venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_policy.py tests/core/test_repo_admin_detect.py -q
  - .venv/bin/python cli/tld ops repo-admin validate-policy src/tld/templates/admin-policy.yaml
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - "`tld plan deviations check --file docs/plans/93/deviations.md --plan docs/plans/93/plan.md --all` exits 0"
  - "the changelog has entries under ## [Unreleased] and no version heading"
  - "`tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
  - "`tld ops spec validate --profile .tld/toolkit.yaml` exits 0 and `openspec/changes/admin-policy-inheritance` does not exist"
  - "`python3 evals/run.py check-baseline` exits 0 and `python3 evals/run.py run --agent stub --repeats 1 --require-pass` exits 0"
phases:
  - id: p1-policy-model
    title: The pure policy model (key classes, merge, guards, derived logins, legacy conversion)
    depends_on: []
    complexity: M
    touches:
      - src/tld/ops/repo_admin_policy.py
      - tests/core/test_repo_admin_policy.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.1 to 3.6, 3.8 and 3.9), src/tld/ops/repo_admin.py (lines 57-70 and 262-320), src/tld/schema/admin-policy.schema.json.
      1. Create src/tld/ops/repo_admin_policy.py. It imports only copy, dataclasses, fnmatch, json, re and yaml, and never imports tld.ops.repo_admin (the module is pure so repo_admin can import it).
      2. Constants, exactly the tables of 3.3 and 3.6: RUN_ONLY, PRIVATE_ONLY, ORG_LEVEL, OVERRIDABLE, PER_REPO_ONLY (dotted names), IRREVERSIBLE (dotted names), and GUARDED with the five groups of 3.6 item 2 (TRUE_KEYS, FALSE_KEYS, ORDERED as a dict from dotted key to a list ordered loosest first, EQUAL_KEYS, LIST_KEYS) plus GUARDED_KEYS, the sorted tuple of all their dotted names.
      3. kind_of(doc) returns "run" when "org" is in doc, else "override".
      4. key_errors(doc, kind, where, public=None) -> list[str] for kind "override" or "base". `where` is the prefix of every message ("base <label>" for a base, "<owner>/<repo>:<path>" for an override). `public` is "<owner>/<repo>" when the base file's repository is public or internal, else None. Messages are exactly the class errors of 3.6 item 4, item 1 (irreversible) and item 3 (public base), and for a base that has "extends": "<where>: sets 'extends'; an extended file cannot extend another". Rules: an override may hold only the OVERRIDABLE sections, and every other top-level key gets the organisation-level message; a base may not hold org, repos (message "<where>: '<key>' is set only in the policy file you run"); a base may not hold a PER_REPO_ONLY key (the 'is per repository' messages); an override's workflows entries hold only template, params, remove; a base's workflows entries hold only template; a None value anywhere gives the null message; in a base an IRREVERSIBLE key whose value turns it on (True for the delete_unused and delete_merged switches and revoke_expired, a non-empty list for webhooks.delete, any number for max_unused_days) gives the irreversible message; with `public` set, a PRIVATE_ONLY section gives the public-base message. It never raises and never looks at values beyond these rules (the schema check does that).
      5. deep_merge(base, over) -> dict (new objects, the inputs are not changed; mappings merge, everything else in `over` replaces). merge_layers(layers: list[tuple[str, dict]]) -> tuple[dict, dict[str, str]] merges in order and returns the dotted-leaf-to-label map (lists and scalars are leaves; the label is the layer that set the final value).
      6. clamp_irreversible(merged, run_doc) -> dict: when run_doc has no tokens.fine_grained and merged has tokens.fine_grained, return a copy with revoke_expired set to False when the key is absent; otherwise return merged unchanged.
      7. apply_override(org, override) -> dict as 3.5 says: deep_merge(org, override without workflow_params); workflow_params = deep_merge(org's, override's); when not empty store it under "workflow_params" and copy each template's params into the matching entries of "workflows" (entry params first, then workflow_params, later wins).
      8. Loosening is a frozen dataclass (key, org_value, value). loosened(org, eff) -> list[Loosening] and clamp_guarded(org, eff, allowed: set[str]) -> tuple[dict, list[Loosening]] exactly as 3.6 item 2 (compare only keys the organisation sets; an absent key in eff is not a loosening; a shrunk list gets the dropped entries back after the kept ones; keys in `allowed` are reported nowhere and not clamped). allowed_for(run_policy, repo_name) -> set[str] reads repos.allow_loosen globs with fnmatch.fnmatchcase.
      9. derive_logins(profile) -> tuple[str | None, str | None, list[str]] as 3.8; profile may be None (reason "no profile"); reasons are the short strings "no git.bot_login", "no git.owner_login and not exactly one git.codeowners entry", "git.codeowners entry is not a plain login", "no profile". drop_derived(doc, agent, reviewer) -> dict removes agent.agent_login and release.reviewer_login from a copy when they equal the derived values and drops a section that became empty.
      10. legacy_to_override(legacy, org) -> tuple[dict, list[str]]: drop the RUN_ONLY keys and the ORG_LEVEL sections (one note per dropped section: "dropped organisation-level section '<name>'"), then remove every leaf equal to the organisation's (minimal(): mappings recurse and vanish when empty; lists and scalars equal to the organisation's go; workflows is compared as a whole list).
      11. propose_override(existing, detected) -> dict is deep_merge(detected, existing or {}); render_override(doc) -> str is the two header lines "# Repository override of the organisation's repo-admin policy (docs/guides/admin.md)." and "# Only what differs from the organisation policy belongs here." followed by yaml.safe_dump(doc, sort_keys=False). explain_lines(merged, sources) -> list[str] gives "<dotted key> = <json, sort_keys, compact separators>  # <source>" sorted by key.
      12. Tests in tests/core/test_repo_admin_policy.py, one per rule above, with these names: test_key_errors_override_org_level, test_key_errors_override_workflow_entries, test_key_errors_base_per_repo_keys, test_key_errors_base_irreversible, test_key_errors_base_public_private_sections, test_key_errors_null, test_key_errors_base_extends, test_deep_merge_lists_replace, test_merge_layers_sources, test_clamp_irreversible, test_apply_override_workflow_params, test_apply_override_workflows_replace, test_loosened_each_group, test_clamp_guarded_restores_and_allows, test_allowed_for_globs, test_derive_logins, test_drop_derived, test_legacy_to_override_minimal, test_propose_override_keeps_existing, test_render_override_header, test_explain_lines, test_classes_cover_the_schema (every top-level property of the schema is in exactly one of RUN_ONLY, ORG_LEVEL or OVERRIDABLE, the three are disjoint).
      13. Stop with status=blocked if tests/core/test_no_project_words.py fails on the new file (a forbidden word); fix the word, never the test.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_policy.py -q exits 0 and runs at least 21 tests"
      - ".venv/bin/python -m pytest tests/core/test_no_project_words.py tests/core/test_repo_admin.py -q exits 0"
      - "grep -c 'tld.ops.repo_admin' src/tld/ops/repo_admin_policy.py prints 0 for the import (the module never imports repo_admin)"
  - id: p2-detect-pure
    title: The pure detection functions
    depends_on: []
    complexity: M
    touches:
      - src/tld/ops/repo_admin_detect.py
      - tests/core/test_repo_admin_detect.py
    brief: |
      Read first: docs/plans/93/plan.md (section 3.9), src/tld/ops/repo_admin.py (lines 1181-1186 for the escaping style).
      1. Create src/tld/ops/repo_admin_detect.py with DETECT_PRS = 10 and DETECT_MIN_PRS = 3, frozen dataclasses Run(name, conclusion) and Sample(number, runs) (conclusion is a string or None for a run that has not completed), and no import of tld.ops.repo_admin (gather comes in p7).
      2. status_checks(samples) -> tuple[list[str], dict[str, str]] exactly as 3.9: fewer than DETECT_MIN_PRS samples returns ([], {"": "too few merged pull requests (<n>)"}); otherwise the names kept (sorted) and, for every other name seen, the first matching reason in the order flaky, failed (failure, timed_out, startup_failure, action_required), skipped (skipped, neutral, cancelled, stale), pending (conclusion None), seen on <k> of <n> pull requests (path filter or new). A name with success and failure runs on the same sample is flaky with that sample's number.
      3. tag_workflow_creates_release(texts: list[str]) -> bool with the regular expression of 3.9 and the three release markers.
      4. release_params(tags, manifests, tag_workflow) -> tuple[dict[str, str], list[str]] exactly as 3.9 (version-like tag regular expression `^(\D*?)(\d+\.\d+\.\d+)(.*)$`; most common prefix, ties to the prefix that sorts first; style rules in the order semver by hyphen suffix, pep440 by a|b|rc suffix, pep440 by pyproject.toml, else semver; create_release "false" only when tag_workflow; never check_script; no version-like tag returns ({}, ["no version-like tags"])).
      5. own_release_workflow(profile_release_workflow, workflows) -> list | None and detected_override(checks, params, workflows) -> dict: checks None or [] adds no rulesets key, otherwise {"rulesets": {"default_branch": {"required_status_checks": checks}}}; params non-empty adds {"workflow_params": {"release": params}}; workflows not None adds {"workflows": workflows}.
      6. pr_notes(checks, excluded, params, notes) -> list[str]: one line "required_status_checks: <names comma separated>" (or "required_status_checks: none proposed"), one line "excluded: <name> (<reason>)" per excluded name (the empty name gives "excluded: (all) (<reason>)"), one line "release parameters: <key>=<value> ..." when params, then each note.
      7. Tests in tests/core/test_repo_admin_detect.py named: test_checks_from_merged_pull_requests, test_too_few_pull_requests, test_release_parameters, test_own_release_workflow, test_flaky_failed_skipped_and_partial_checks_are_excluded, test_version_style_rules, test_tag_prefix_tie, test_tag_workflow_creates_release, test_detected_override_shapes, test_pr_notes.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_detect.py::test_checks_from_merged_pull_requests tests/core/test_repo_admin_detect.py::test_too_few_pull_requests tests/core/test_repo_admin_detect.py::test_release_parameters tests/core/test_repo_admin_detect.py::test_own_release_workflow tests/core/test_repo_admin_detect.py::test_flaky_failed_skipped_and_partial_checks_are_excluded tests/core/test_repo_admin_detect.py::test_version_style_rules tests/core/test_repo_admin_detect.py::test_tag_prefix_tie tests/core/test_repo_admin_detect.py::test_tag_workflow_creates_release tests/core/test_repo_admin_detect.py::test_detected_override_shapes tests/core/test_repo_admin_detect.py::test_pr_notes -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_no_project_words.py -q exits 0"
  - id: p3-extends
    title: Resolve extends through the API (fetch, checks, merge, latest pin)
    depends_on: [p1-policy-model]
    complexity: M
    touches:
      - src/tld/ops/repo_admin_extends.py
      - src/tld/profile/base.py
      - tests/core/test_repo_admin_extends.py
      - tests/core/test_profile_base.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.4, 3.5, 3.6 and 3.12), src/tld/profile/base.py (plan 90 p2), src/tld/ops/repo_admin_policy.py, src/tld/guard/secret_scan.py (lines 81-135), tests/core/test_profile_base.py.
      1. Stop with status=blocked when src/tld/profile/base.py or BaseRef or parse_extends does not exist (plan 90 is not merged).
      2. In src/tld/profile/base.py make two compatible edits only when they are missing: parse_extends(value, label="toolkit.yaml: 'tld.extends'") puts `label` in front of its two error texts instead of the fixed prefix, and check_base_shape(text, label) -> tuple[dict | None, list[str]] holds the size, UTF-8, BOM, anchor, mapping, depth, scan_text and secret_like_name checks that check_base_text already runs, with check_base_text calling it and then its own profile key rules. Extend tests/core/test_profile_base.py with test_parse_extends_label and test_check_base_shape_alone. If tests/core/test_mutants_file.py then fails because a mutant's old text moved, update only that mutant's old and new text in tests/mutation/mutants.yaml.
      3. Create src/tld/ops/repo_admin_extends.py. Imports ApiError from tld.ops.repo_admin inside the functions that catch it (never at module level). Dataclass Layer(label, doc, public) and Resolved(policy, sources, errors, labels).
      4. parse_list(value) -> tuple[list[BaseRef], list[str]]: a string becomes a one-item list; at most four entries; each through parse_extends(entry, label=f"'extends[{i}]'"); duplicates of owner/repo/path (compared lower case) give "'extends': <owner>/<repo>/<path> is listed twice".
      5. fetch_layer(client, ref, index) -> tuple[Layer | None, list[str]]: GET /repos/<owner>/<repo> (private, visibility, default_branch), GET /repos/<owner>/<repo>/compare/<default_branch>...<sha> whose status must be behind or identical, then client.get_text of the contents path with ref=<sha>; ApiError becomes the "cannot read" error of 3.4 with the status and message; a bad compare status gives the "is not on the default branch" error; then check_base_shape(text, "base <label>") with the base label; yaml.safe_load; key_errors(doc, "base", "base <label>", public=<owner>/<repo> when private is false or visibility is public or internal, else None). A visibility of private gives public None.
      6. resolve(client, run_doc) -> Resolved: errors from parse_list and every layer are collected (no early stop); on any error policy is None. Otherwise layers are the bases in order then the run document without "extends" (labels `run`), merge_layers, clamp_irreversible(merged, run_doc), and the policy gets "_inherited": True, "_extends": the list of labels, "_sources": the source map. Entries of the run document are not changed.
      7. latest_pin(client, source) -> tuple[str, str | None] exactly as 3.4 (tags by paginate on /repos/<o>/<r>/tags, version sort by numeric components of names matching ^v?\d+(\.\d+)*$, at most 20 tried by a contents GET with ref=<tag commit sha>, else the default branch head from GET /repos/<o>/<r>/branches/<default> with None); raises LookupError("latest-pin: <path> does not exist in <owner>/<repo>") when no commit has the file.
      8. Tests in tests/core/test_repo_admin_extends.py with a small fake client defined in the file (get and get_text answer from a dict keyed by path, an unknown path raises ra.ApiError(404, "Not Found", "GET", path); params are ignored): test_small_policy_resolves, test_pin_is_not_a_commit, test_pin_is_not_on_the_default_branch, test_token_like_text, test_organisation_private_section_in_a_public_repository, test_irreversible_switch_in_an_inherited_file (a base with branches.delete_merged true is refused, and a base tokens section leaves revoke_expired false while a run file that sets tokens.fine_grained keeps its own value), test_chained_extends, test_two_layers_later_wins, test_duplicate_entry, test_cannot_read_a_private_file, test_latest_pin_picks_the_newest_tag_with_the_file, test_latest_pin_without_tags, test_latest_pin_missing_file.
      9. Stop with status=blocked when the real compare answer for an ancestor is not "behind" (only knowable at the first real audit: report it, do not change the rule).
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_extends.py::test_small_policy_resolves tests/core/test_repo_admin_extends.py::test_pin_is_not_a_commit tests/core/test_repo_admin_extends.py::test_pin_is_not_on_the_default_branch tests/core/test_repo_admin_extends.py::test_token_like_text tests/core/test_repo_admin_extends.py::test_organisation_private_section_in_a_public_repository tests/core/test_repo_admin_extends.py::test_irreversible_switch_in_an_inherited_file tests/core/test_repo_admin_extends.py::test_chained_extends tests/core/test_repo_admin_extends.py::test_two_layers_later_wins tests/core/test_repo_admin_extends.py::test_duplicate_entry tests/core/test_repo_admin_extends.py::test_cannot_read_a_private_file tests/core/test_repo_admin_extends.py::test_latest_pin_picks_the_newest_tag_with_the_file tests/core/test_repo_admin_extends.py::test_latest_pin_without_tags tests/core/test_repo_admin_extends.py::test_latest_pin_missing_file -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_profile_base.py tests/core/test_mutants_file.py tests/core/test_no_project_words.py -q exits 0"
  - id: p4-schema-kinds
    title: Schema, validate_policy kinds and the three starters
    depends_on: [p1-policy-model]
    complexity: M
    touches:
      - src/tld/schema/admin-policy.schema.json
      - src/tld/ops/repo_admin.py
      - src/tld/templates/admin-policy.yaml
      - src/tld/templates/admin-policy-base.yaml
      - src/tld/templates/admin-policy-org.yaml
      - docs/guides/admin.md
      - tests/core/test_repo_admin_kinds.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.2, 3.3, 3.6, 3.8 and 3.11), src/tld/ops/repo_admin.py (lines 262-320), src/tld/schema/admin-policy.schema.json, src/tld/templates/admin-policy.yaml, tests/core/test_repo_admin.py (lines 120-230), docs/guides/admin.md (the Policy reference table).
      1. Stop with status=blocked when the schema has no `profile` and `git_ops` properties (plan 90 p12 is not merged).
      2. Schema: add `extends` (an array of 0 to 4 strings, or one string; description names the pin form), `workflow_params` (object; one property `release` of type object with the same params description as workflows[].params), `repos.override_path` (string) and `repos.allow_loosen` (object whose values are arrays of strings); remove `required` from `agent` and `release`.
      3. repo_admin.py validate_policy(policy, base_dir=None, kind="run"): for kind override or base validate against a copy of the schema whose top-level `required` is []; after the schema check call repo_admin_policy.key_errors(policy, kind, where) (where is "override" or "base" when the caller gives none: add a `where=""` keyword) and return its messages first; keep the existing forbid, labels, workflows and params checks for every kind. For kind run: without `extends`, an `agent` section without agent_login and a `release` section without reviewer_login give exactly the text the schema check gave before (run the old schema check against git show HEAD:src/tld/schema/admin-policy.schema.json to read it, and assert it in a test); with `extends` they are allowed. For kind run also check `repos.override_path` (relative, no `..`, no leading `/`) with the message of 3.6 item 4, and `repos.allow_loosen` keys against repo_admin_policy.GUARDED_KEYS.
      4. Templates: src/tld/templates/admin-policy.yaml gains `extends: []` and `workflow_params: {}` with a one-line comment each (the starter test needs every property) and stays valid. Create admin-policy-base.yaml with exactly the content of 3.11 and a comment header that says the file is public, holds no organisation-level section and needs `tld ops repo-admin validate-policy --kind base --public`. Create admin-policy-org.yaml: a comment header, the six private sections as commented examples copied from the starter, and commented `profile` and `git_ops` examples copied from the starter; no irreversible switch is uncommented.
      5. docs/guides/admin.md: add a row to the Policy reference table for each new key, written as `extends`, `workflow_params`, `repos.override_path`, `repos.allow_loosen` and `workflow_params.release` (tests/core/test_repo_admin.py::test_every_policy_key_is_documented requires every property in backticks); one sentence each. Do not rewrite other sections (p10 does).
      6. Tests in tests/core/test_repo_admin_kinds.py: test_organisation_level_key_in_an_override (validate_policy kind override with labels, org, extends and repos each fails with the organisation-level message, workflows entry with path fails), test_per_repository_key_in_a_base (required_status_checks, workflow_params, config_dirs.known and a workflows params each fail for kind base), test_policy_without_extends (an old policy with agent and release sections validates exactly as before and the missing-login messages are unchanged), test_override_and_base_need_no_org, test_run_policy_still_needs_org, test_override_path_and_allow_loosen_checked, test_templates_validate (the starter as run, the base template as base with public set to a repository name, the org template as base), test_base_template_has_no_private_section.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_kinds.py::test_organisation_level_key_in_an_override tests/core/test_repo_admin_kinds.py::test_per_repository_key_in_a_base tests/core/test_repo_admin_kinds.py::test_policy_without_extends tests/core/test_repo_admin_kinds.py::test_override_and_base_need_no_org tests/core/test_repo_admin_kinds.py::test_run_policy_still_needs_org tests/core/test_repo_admin_kinds.py::test_override_path_and_allow_loosen_checked tests/core/test_repo_admin_kinds.py::test_templates_validate tests/core/test_repo_admin_kinds.py::test_base_template_has_no_private_section -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_e2e.py tests/core/test_repo_admin_rulesets.py tests/core/test_no_project_words.py -q exits 0"
      - ".venv/bin/python cli/tld ops repo-admin validate-policy src/tld/templates/admin-policy.yaml exits 0"
  - id: p5-cli-resolve
    title: validate-policy kinds and resolution, load_policy with extends, latest-pin
    depends_on: [p3-extends, p4-schema-kinds]
    complexity: M
    touches:
      - src/tld/ops/repo_admin.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_repo_admin_cli.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.4, 3.5 and 3.6), src/tld/ops/repo_admin.py (lines 320-338 and 1615-1731), src/tld/ops/repo_admin_extends.py, src/tld/cli.py (line 73), docs/reference/cli.md (line 78).
      1. load_policy(path, client=None): behaviour without `extends` is unchanged. A document with `org` and `extends`: validate (kind run), then resolve through repo_admin_extends.resolve with `client` (when None build _client()); any resolve error raises SystemExit with each message prefixed "policy: "; the returned policy is the resolved one plus `_dir`. A document without `org` raises SystemExit("repo_admin: '<path>' is a repository override file (it has no 'org'); run the audit with the organisation's policy file"). _run passes its client to load_policy; ApiError during resolve is turned into the "cannot read" message by resolve, not raised.
      2. cmd_validate gains --kind (auto, run, override, base; default auto), --public (only with --kind base, else exit 2 with "validate-policy: --public needs --kind base"), --resolved, --explain (implies --resolved), --offline and --org-policy FILE. Rules: kind auto picks run when "org" is present, else override; run with `extends` resolves unless --offline (a client with _client()); --resolved prints yaml.safe_dump of the resolved policy without keys that start with "_" ; --explain prints repo_admin_policy.explain_lines of the resolved policy's _sources, one per line; a repository override with --org-policy FILE and --resolved prints the effective policy (apply_override over the resolved organisation policy of FILE, then clamp_guarded with allowed_for of that policy); this combination needs --repo-name NAME (the repository's name, used for the allow_loosen globs), else it exits 2 with "validate-policy: --org-policy needs --repo-name"; the OK line is `policy: OK (<path>)` for run, `policy: OK (<path>, repository override)` for override, `policy: OK (<path>, base)` for base.
      2b. validate_policy(kind="run") also checks `extends` through repo_admin_extends.parse_list (import it inside the function) and returns its messages; add test_validate_policy_checks_the_extends_form to the tests below (a tag pin, a malformed entry, five entries and a duplicate each fail; a 40-hex pin passes offline).
      3. New command `latest-pin SOURCE` (argument <owner>/<repo>/<path>): prints json.dumps({"sha": sha, "tag": tag}); a LookupError prints its message on stderr and exits 1. Register it in build_parser and handlers.
      4. cmd_audit: a resolved policy has _extends; in the markdown report add the line `Extends: <label>, <label>.` after the summary line and in the JSON an "extends" list (both only when inherited).
      5. src/tld/cli.py: the description of ("ops", "repo-admin") becomes "validate-policy | whoami | audit | apply | latest-pin"; docs/reference/cli.md row at line 78 likewise, and the module docstring of repo_admin.py lists the new options.
      6. Tests in tests/core/test_repo_admin_cli.py using the fake client of p3's tests (copy the small class; do not import another test module): test_resolved_view (--explain on a small run policy prints a line per key with `# base <label>`, `# run` sources and --resolved prints no key that starts with an underscore), test_validate_kinds_and_ok_lines, test_public_flag_needs_base_kind, test_offline_does_not_fetch, test_load_policy_refuses_an_override_file, test_load_policy_without_extends_is_unchanged, test_latest_pin_command_prints_json, test_latest_pin_missing_file_exits_1, test_audit_header_names_the_extends, test_validate_policy_checks_the_extends_form.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_cli.py::test_resolved_view tests/core/test_repo_admin_cli.py::test_validate_kinds_and_ok_lines tests/core/test_repo_admin_cli.py::test_public_flag_needs_base_kind tests/core/test_repo_admin_cli.py::test_offline_does_not_fetch tests/core/test_repo_admin_cli.py::test_load_policy_refuses_an_override_file tests/core/test_repo_admin_cli.py::test_load_policy_without_extends_is_unchanged tests/core/test_repo_admin_cli.py::test_latest_pin_command_prints_json tests/core/test_repo_admin_cli.py::test_latest_pin_missing_file_exits_1 tests/core/test_repo_admin_cli.py::test_audit_header_names_the_extends tests/core/test_repo_admin_cli.py::test_validate_policy_checks_the_extends_form -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_e2e.py tests/core/test_cli_reference.py tests/core/test_contracts.py -q exits 0"
  - id: p6-per-repo
    title: The effective policy per repository, the policy check and the keep-live rules
    depends_on: [p5-cli-resolve]
    complexity: M
    touches:
      - src/tld/ops/repo_admin.py
      - src/tld/ops/repo_admin_profile.py
      - docs/guides/admin.md
      - tests/core/test_repo_admin_inherit.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.1, 3.6 and 3.7), src/tld/ops/repo_admin.py (Ctx at lines 358-476, the checks listed in 3.1, ruleset_bodies at 765, check_rulesets at 839, check_files at 1353, apply_files at 1533, apply_findings at 1569), src/tld/ops/repo_admin_policy.py, src/tld/ops/repo_admin_profile.py (plan 90 p12), tests/core/test_repo_admin.py (Fake, add_repo, world, lines 20-115).
      1. Ctx: add the property `inherited` (bool of policy.get("_inherited")); the dataclass Override(doc, path, legacy, problems, notes); `override(repo)` memoised as 3.7 says (path from repos.override_path default ".tld/admin-policy.yaml"; no file or an empty repository gives Override(None, path, False, [], []); a read failure, a check_base_shape error, a YAML error, a non-mapping, key_errors with where "<full_name>:<path>" and validate_policy(kind="override") errors are problems, and with problems doc is None; a document with "org" is legacy: validate_policy(kind="run") errors are problems, then legacy_to_override; the label for check_base_shape is "override <full_name>:<path>"); `pol(repo)` memoised under ("pol", full_name): without `inherited` return self.p; else apply_override(self.p, override.doc or {}) then clamp_guarded(self.p, eff, allowed_for(self.p, repo["name"])), keeping the Loosening list in the memo under ("loose", full_name). Import the policy module at the top of repo_admin.py.
      2. Move the 12 sites of 3.1 to pol(repo) inside one(repo), including the guards that returned early; check_release looks up the reviewer id inside one(repo) with the existing memo. check_files reads config_dirs, workflows and release.environment from pol(repo) and keeps ctx.p only inside workflow_source for `_dir`. repo_admin_profile.py: the merge-style check reads ctx.pol(repo) for repo_settings (one line).
      3. ruleset_bodies(cfg, live_checks=None): the checks are main["required_status_checks"] when that key is present, else live_checks or []. check_rulesets.one(repo) lists the rulesets first, reads the live tld-main when it exists, derives live_checks from its required_status_checks rule (a list of contexts) only when ctx.inherited and the effective default_branch has no required_status_checks key, and builds the bodies after that; without inheritance live_checks is None and the output is byte-for-byte today's.
      4. check_files: in inherited mode a workflow entry with template "release" whose effective params (entry params plus workflow_params.release) are empty is skipped with Finding("files", fn, f"workflow:{dest}:standdown", "release workflow: no release parameters for this repository yet; it is not installed or rewritten (the policy check proposes them)", "info"). The same finding text when the repository's resolved profile has no release section is added by p7, not here.
      5. Action gets `note: str = ""`; apply_files(..., today, notes=()) appends, after the summary and before the closing sentence, the line "Detected values (the owner confirms them):" and one bullet per note passed through _cell(note, 500); apply_findings passes [f.action.note for f in group if f.action.note].
      6. check_policy(ctx) registered last as "policy" in CHECKS (the --check choices follow CHECKS): per repository of ctx.repos when ctx.inherited, else []: an Override with problems gives Finding("policy", fn, "override:invalid", "<path>: <problem>", "error") per problem; each Loosening gives Finding("policy", fn, f"loosen:{key}", "the override sets <key> to <value>, looser than the organisation's <org value>; the organisation value applies", "warn"); a legacy override gives Finding("policy", fn, "override:convert", "<path> is a whole policy; with inheritance it holds only the repository's differences", "fix", Action("files", repo=fn, changes=[{"op": "put", "path": path, "content": render_override(doc), "mode": "100644"}], note="; ".join(notes))) where doc is the converted override; a workflow_params template that is not in the effective workflows gives a warn finding subject f"workflow_params:{template}".
      7. docs/guides/admin.md: one row `| `policy` |` in the checks table (what it looks at, what it can change) so test_every_check_is_documented passes.
      8. Tests in tests/core/test_repo_admin_inherit.py with world() and add_repo() copied as small helpers (import them from test_repo_admin only if conftest already allows it; otherwise copy): test_override_merged, test_no_override_file, test_organisation_level_key_in_an_override, test_whole_legacy_file, test_only_the_checks (an override with only required_status_checks on a policy that sets repo_settings, security and actions: every check of that repository runs on the inherited values plus those checks), test_loosening_held, test_loosening_allowed_by_the_run_file, test_deletion_needs_the_flag (apply_findings with yes=True and allow_delete=False on an inherited policy with a label finding: nothing destructive is sent), test_absent_value_stands_down (a live tld-main with checks keeps them when the key is absent and loses them for an explicit empty list; a release template without parameters is not rendered; the same policy without inheritance behaves as before), test_pol_is_the_policy_without_extends (pol returns ctx.p itself and no contents route is read), test_override_problems_are_errors_and_the_org_policy_applies, test_apply_notes_reach_the_pull_request_body.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_inherit.py::test_override_merged tests/core/test_repo_admin_inherit.py::test_no_override_file tests/core/test_repo_admin_inherit.py::test_organisation_level_key_in_an_override tests/core/test_repo_admin_inherit.py::test_whole_legacy_file tests/core/test_repo_admin_inherit.py::test_only_the_checks tests/core/test_repo_admin_inherit.py::test_loosening_held tests/core/test_repo_admin_inherit.py::test_loosening_allowed_by_the_run_file tests/core/test_repo_admin_inherit.py::test_deletion_needs_the_flag tests/core/test_repo_admin_inherit.py::test_absent_value_stands_down tests/core/test_repo_admin_inherit.py::test_pol_is_the_policy_without_extends tests/core/test_repo_admin_inherit.py::test_override_problems_are_errors_and_the_org_policy_applies tests/core/test_repo_admin_inherit.py::test_apply_notes_reach_the_pull_request_body -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_e2e.py tests/core/test_repo_admin_rulesets.py tests/core/test_repo_admin_profile.py tests/core/test_repo_admin_gitops.py -q exits 0 (every existing test passes unchanged)"
  - id: p7-derive-detect
    title: Derived logins and detected proposals in the audit
    depends_on: [p2-detect-pure, p6-per-repo]
    complexity: M
    touches:
      - src/tld/ops/repo_admin.py
      - src/tld/ops/repo_admin_detect.py
      - src/tld/ops/repo_admin_profile.py
      - tests/core/test_repo_admin_derive.py
      - tests/core/test_repo_admin_propose.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.8, 3.9 and 3.12), src/tld/ops/repo_admin.py (check_agent at 964, check_release at 997, check_policy from p6), src/tld/ops/repo_admin_detect.py, src/tld/ops/repo_admin_profile.py (plan 90 p12), tests/core/test_repo_admin_inherit.py.
      1. Stop with status=blocked when repo_admin_profile.py has no function that returns a repository's resolved profile and none can be added as 3.12 says; in repo_admin_profile.py use the function p12 landed, else add repo_profile(ctx, repo) -> dict | None that calls the code p12's checks already use to resolve the repository's profile at its default branch and memoises it under ("profile", full_name); a missing or unreadable profile returns None.
      2. check_agent and check_release (3.8): effective login = the explicit value from pol(repo), else derive_logins(repo_profile(ctx, repo)); the profile is read only when the explicit value is missing. No login: the warn finding and the parts that still run as 3.8 says (agent: environment and secret part runs; release: the whole check skipped for that repository). A repository whose resolved profile has no `release` section gets, for the release template entry in check_files, the info finding of p6 step 4 with the text "release workflow: the repository's profile has no release section; it is not installed or rewritten".
      3. repo_admin_detect.gather(ctx, repo) -> Gathered(samples, tags, manifests, tag_workflow, profile_release_workflow) with the API calls of 3.9; it imports ApiError inside the function and lets ApiError propagate.
      4. check_policy: when inherited, for each repository whose effective policy has rulesets.default_branch without required_status_checks, or the release template without workflow_params.release and without params, or whose override file is absent: call gather; checks, excluded = status_checks(samples); params, notes from release_params unless own_release_workflow returns a list; build detected_override, propose_override(existing override doc or None, detected), and emit Finding("policy", fn, "override:propose", "<path> proposed from the repository's merged pull requests, tags and manifest", "fix", Action("files", repo=fn, changes=[put], note="; ".join(pr_notes(...)))) only when the proposed document differs from the existing one; for a legacy file the conversion finding of p6 also passes through drop_derived with the derived logins and keeps its note; a failed call becomes an unavailable finding through failure().
      5. Tests: tests/core/test_repo_admin_derive.py: test_logins_derived, test_explicit_login_wins (no route for the profile is read), test_login_not_derivable (agent: warn, environment part still checked; release: warn and no release findings), test_release_template_stands_down_without_a_release_section. tests/core/test_repo_admin_propose.py: test_proposal_for_a_repository_without_an_override (a fake organisation with 3 merged pull requests, check runs and tags: one fix finding whose content holds the detected checks and whose note lists the excluded checks), test_proposal_keeps_what_the_repository_wrote, test_proposal_for_an_own_release_workflow (the content has workflows without the release template and no workflow_params), test_no_proposal_when_nothing_is_missing, test_detection_failure_is_an_unavailable_finding.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_derive.py::test_logins_derived tests/core/test_repo_admin_derive.py::test_explicit_login_wins tests/core/test_repo_admin_derive.py::test_login_not_derivable tests/core/test_repo_admin_derive.py::test_release_template_stands_down_without_a_release_section tests/core/test_repo_admin_propose.py::test_proposal_for_a_repository_without_an_override tests/core/test_repo_admin_propose.py::test_proposal_keeps_what_the_repository_wrote tests/core/test_repo_admin_propose.py::test_proposal_for_an_own_release_workflow tests/core/test_repo_admin_propose.py::test_no_proposal_when_nothing_is_missing tests/core/test_repo_admin_propose.py::test_detection_failure_is_an_unavailable_finding -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_e2e.py tests/core/test_repo_admin_inherit.py tests/core/test_repo_admin_profile.py tests/core/test_repo_admin_gitops.py tests/core/test_no_project_words.py -q exits 0"
  - id: p8-reproduce
    title: Both reference policies reproduce as base plus overrides
    depends_on: [p7-derive-detect]
    complexity: M
    touches:
      - tests/fixtures/admin-policy/shared-base.yaml
      - tests/fixtures/admin-policy/org-a.yaml
      - tests/fixtures/admin-policy/org-b.yaml
      - tests/fixtures/admin-policy/override-a.yaml
      - tests/fixtures/admin-policy/override-b.yaml
      - tests/fixtures/admin-policy/legacy-a.yaml
      - tests/fixtures/admin-policy/legacy-b.yaml
      - tests/core/test_repo_admin_reproduce.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.10 and 3.11), .tld/admin-policy.yaml, tests/core/test_repo_admin.py (Fake, world), tests/core/test_repo_admin_inherit.py.
      1. Fixtures: legacy-a.yaml is a copy of .tld/admin-policy.yaml; legacy-b.yaml is the second reference policy written out in full from this description (fields: org, repos.include, repo_settings (six keys), security (five), actions (two), rulesets.default_branch (ten checks named test, "Test (Python 3.11, core suite)", "Test (Python 3.12, core suite)", "Test (Python 3.14, core suite)", static-analysis, org-mode-smoke, "Sync client (Python 3.11)", "Sync client (Python 3.13)", website-build, n8n-node; admin_bypass true), rulesets.tags true, agent (agent_login and branch_policy default_branch), release (reviewer_login, environment tld-release), config_dirs (forbid [".archon", ".agents"], known [.claude-plugin]), workflow_lint (three keys), workflows (release with params tag_prefix v, version_style pep440, create_release "false", check_script scripts/release_check.py; and land)); use the organisations acme-a and acme-b and the logins bot-a, owner-a and owner-b in every fixture. shared-base.yaml is a copy of src/tld/templates/admin-policy-base.yaml. org-a.yaml and org-b.yaml are run files with org and an extends list of two placeholders that the test replaces by pins; override-a.yaml holds required_status_checks (two names), config_dirs.known and workflows [{template: land}]; override-b.yaml holds the ten checks, config_dirs.known and workflow_params.release.
      2. tests/core/test_repo_admin_reproduce.py: test_effective_policy_reproduces_each_legacy_file (build a fake client whose contents, repository and compare routes serve the base and override files, resolve each run file, create a Ctx over a fake organisation, take ctx.pol(repo), remove org, repos and the two derived logins from the legacy file, and assert that the leaf-by-leaf difference between the effective policy and the legacy file is exactly the DELTA constant written at the top of the test file: for a the three merge-method keys, config_dirs.forbid and workflow_lint; for b nothing), test_same_findings_as_before (one fake organisation per repository whose live state differs from the policy in sections both policies manage; run_checks with the legacy policy and with the inherited one; assert the sets of (check, scope, subject, severity) are equal ignoring the policy check), test_small_policy_resolves_and_validates (the run file with only org and extends passes validate-policy through the command line with the fake client), test_override_with_only_the_checks_audits_the_repository_fully (override only required_status_checks: the repo_settings, security, actions, rulesets, agent, release and workflow findings of the repository are the same as with the whole file), test_base_with_a_token_like_string_is_refused, test_org_level_key_in_an_override_is_rejected.
      3. Stop with status=blocked when the two policies cannot be made equal without a difference beyond the DELTA constant and report the difference (the key classes need a change).
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_reproduce.py -q exits 0 and runs 6 tests"
      - ".venv/bin/python -m pytest tests/core/test_no_project_words.py -q exits 0"
  - id: p9-mutants
    title: Mutants for the new pure modules
    depends_on: [p7-derive-detect]
    complexity: S
    touches:
      - tests/mutation/mutants.yaml
      - tests/core/test_mutants_file.py
    brief: |
      Read first: tests/mutation/mutants.yaml (the format, lines 1-90), tests/core/test_mutants_file.py, src/tld/ops/repo_admin_policy.py, src/tld/ops/repo_admin_detect.py.
      1. In tests/core/test_mutants_file.py add "src/tld/ops/repo_admin_policy.py" and "src/tld/ops/repo_admin_detect.py" to MODULES.
      2. In tests/mutation/mutants.yaml add under `tests:` the two files mapped to tests/core/test_repo_admin_policy.py and tests/core/test_repo_admin_detect.py, and under `mutants:` these nine, each with an `old` text that occurs exactly once in the file as it is now (read the code, copy one expression) and a `new` text that flips it: AI1 kind_of returns "override" for a document with org; AI2 the org-level message check in key_errors is skipped for the first key of an override (condition replaced by False); AI3 clamp_irreversible never sets revoke_expired; AI4 loosened treats an ordered key as loosened in the stricter direction; AI5 key_errors does not refuse a private section when public is set; AI6 allowed_for matches no glob; AX1 status_checks keeps a name that failed on one sample; AX2 status_checks keeps a name missing from some samples; AX3 status_checks keeps a skipped name.
      3. Run `.venv/bin/python tests/mutation/run_mutants.py --only AI1 AI2 AI3 AI4 AI5 AI6 AX1 AX2 AX3`: every mutant must be killed. A survivor means a test is missing: add the test to the file named for that module (tests/core/test_repo_admin_policy.py or tests/core/test_repo_admin_detect.py is not in this phase's touches: report the survivor with status=blocked instead and name the test needed).
    acceptance:
      - ".venv/bin/python tests/mutation/run_mutants.py --only AI1 AI2 AI3 AI4 AI5 AI6 AX1 AX2 AX3 exits 0"
      - ".venv/bin/python -m pytest tests/core/test_mutants_file.py -q exits 0"
  - id: p10-playbook-docs-evals
    title: The playbook, the admin guide and the new eval task
    depends_on: [p7-derive-detect]
    complexity: M
    touches:
      - playbooks/repo-admin.md
      - docs/guides/admin.md
      - evals/fixtures/commands.py
      - evals/tasks/repo-admin-override-file/task.yaml
      - evals/stubs/repo-admin-override-file.json
      - tests/core/test_evals_tasks.py
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.1 to 3.9), playbooks/repo-admin.md, docs/guides/admin.md, evals/tasks/land-needs-bot-login/task.yaml, evals/stubs/land-needs-bot-login.json, evals/fixtures/commands.py, docs/architecture/evals.md (the section on tasks and stubs).
      1. playbooks/repo-admin.md: add the optional input "the path of the organisation's policy file (default `admin.policy`)"; in "Before anything" step 1 add: when `tld ops repo-admin validate-policy <file>` prints a line ending `repository override` the file is this repository's override, so stop with exactly `repo-admin: <file> is this repository's override file; run /tld:repo-admin <path of the organisation's policy file>` and write no command after it; step 2 runs validate-policy on the file given (it resolves `extends` and needs the token; offline: add `--offline`). In the flow, add after step 1 (Audit) that `policy` findings are proposals: report in words the detected status checks and the excluded ones with their reasons, and ask the owner to confirm them before `apply` opens the pull request (a `confirm` question per repository), and say the owner corrects the values in the pull request. In "What it can and cannot do" add: inheritance of a pinned shared base and a private organisation file, a small override file per repository, derived logins; cannot: create the `GIT_OPS_TOKEN` secret or the git-ops environment (open items), read a private file the token cannot read. In "Never" add: edit an override file or a base to make a finding disappear unless the owner asked; apply a `policy` proposal the owner did not confirm; put a credential in a base. Every tld command named exists (tests/core/test_contracts.py).
      2. docs/guides/admin.md: rewrite the sentence at "One policy file governs one organisation" and "Use it in a project" around the four file kinds, the layers and the three files per organisation (3.2, 3.11); add a section "Inheriting the policy" with: extends and the pin, the key classes table of 3.3 as a markdown table, the guarded keys and `repos.allow_loosen`, the irreversible-switch rule, detection and its limits (a proposal, the owner confirms; what is excluded and why), derived logins, how to read the resolved view (`--resolved`, `--explain`) and `latest-pin`, and the dependency on plan 90 for the `profile` and `git_ops` sections. Keep every key row p4 added. Do not add a heading that makes a link to a missing anchor.
      3. evals: in evals/fixtures/commands.py add the case `repo-admin` to build(): the profile of tiny_app plus `admin:\n  policy: .tld/admin-policy.yaml\n`, the file .tld/admin-policy.yaml containing `repo_settings:\n  allow_auto_merge: true\n` (no org), and expected["stop_message"] = "is this repository's override file". Create evals/tasks/repo-admin-override-file/task.yaml (copy land-needs-bot-login: command /tld:repo-admin, fixture builder commands with params command: repo-admin, graders result_mentions key stop_message, forbidden_ops_absent, no_changes, model sonnet, repeats 3) and its stub evals/stubs/repo-admin-override-file.json (copy the land stub with result_text the expected message and the shell action `cat .tld/admin-policy.yaml`). In tests/core/test_evals_tasks.py add "repo-admin-override-file" to the set of shipped ids.
      4. Run `python3 evals/run.py validate`, `python3 evals/run.py run --dry-run`, `python3 evals/run.py run --agent stub --repeats 1 --require-pass` (all exit 0) and `python3 evals/run.py check-baseline` (exits 0; playbooks/repo-admin.md is in no command hash, so the baseline does not change; if it reports a stale command, run `python3 evals/run.py baseline --refresh-hashes` and say in the commit message that no playbook the command links changed in behaviour). A real run costs money and is not part of this phase.
      5. Stop with status=blocked when the stub run fails for the new task and the cause is not in the fixture or the stub you wrote.
    acceptance:
      - "python3 evals/run.py validate exits 0 and python3 evals/run.py run --agent stub --repeats 1 --require-pass exits 0"
      - "python3 evals/run.py check-baseline exits 0"
      - ".venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_evals_tasks.py tests/core/test_evals_stubs.py tests/core/test_evals_fixtures.py tests/core/test_repo_admin.py tests/core/test_no_project_words.py -q exits 0"
  - id: p11-retire
    title: Retirement - reference docs, changelog, spec archive and index rows
    depends_on: [p8-reproduce, p9-mutants, p10-playbook-docs-evals]
    complexity: M
    touches:
      - CHANGELOG.md
      - docs/README.md
      - docs/reference/profile-reference.md
      - SECURITY.md
      - openspec/**
    brief: |
      Read first: docs/plans/93/plan.md (sections 3.6, 3.12 and 3.13), docs/plans/93/deviations.md, CHANGELOG.md (the Unreleased section), docs/README.md (the row for guides/admin.md), docs/reference/profile-reference.md (the admin.policy row), SECURITY.md, openspec/changes/admin-policy-inheritance/.
      1. Reconcile openspec/changes/admin-policy-inheritance/ with the deviations file so the delta describes what was built (edit only wording of scenarios that a deviation changed).
      2. `git diff --quiet $(git merge-base HEAD origin/main) origin/main -- openspec/specs` must exit 0; otherwise stop with status=blocked (main changed the specs).
      3. `tld ops spec archive --profile .tld/toolkit.yaml admin-policy-inheritance`, then `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0 and `grep -rn "TBD" openspec/specs` must print nothing.
      4. CHANGELOG.md: under `## [Unreleased]` add one entry: the admin policy can extend a pinned shared base and a private organisation file, each repository keeps a small override file, with derived logins, detected proposals, guarded settings and `latest-pin`; policies without `extends` are unchanged. Do not open a version heading.
      5. docs/README.md: change only the row of guides/admin.md so it also says it covers inheriting the policy (shared base, organisation file, repository override files), keeping the row format; no new doc was added by this plan (the plan document is never indexed).
      6. docs/reference/profile-reference.md: in the `admin.policy` row add that, once a policy inherits, this file may be the repository's override file and the audit then runs from the organisation's policy file (give the path with /tld:repo-admin).
      7. SECURITY.md: add one short paragraph: the audit reads files pinned by commit from other repositories and each repository's override file with the owner's token; they are checked for credentials and key class, an override cannot loosen a guarded setting or turn on an irreversible change, and only the policy file that is run can.
      8. Run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0.
    acceptance:
      - ".venv/bin/python cli/tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/admin-policy-inheritance does not exist"
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - "grep -n 'extends' CHANGELOG.md prints a line whose number is smaller than the one printed by grep -n -m1 '^## \\[[0-9]' CHANGELOG.md"
```
