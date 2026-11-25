# Plan 90: one org base profile, built-in defaults and a setup that asks almost nothing

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** A repository writes `tld.extends: <owner>/.github/tld/profile-base.yaml@<40-hex commit>` plus its own `verify.fast` and `verify.dod`. `tld profile validate --resolved` prints the merged profile and `--explain` says where each value came from; `tld profile base check|fetch|latest` checks, caches and pins a base. `/tld:setup` writes the profile in one pull request and asks only for commands it cannot find, plus a confirm per blocking role the repository adds. `/tld:migrate --defaults` asks one batch about files off their default path.

**Scope:** One pinned base per org, cached under the git directory. Built-in defaults replace most required keys: `land.max_prs` 10, fixed branch types, merge commits, a `plan_dir` rule, and the plan, board and DoD gates on. `false` turns a defaulted feature off. `/tld:quick` follows the same Security rule. The audit learns the base pin, merge settings, git-ops and secret scope. The tld repository's own profile and the per-repo keys of the ask stay as they are.

**Security:** A base edit changes what every agent may do, so the base takes only allow-listed keys, is pinned by commit, refused when token-like, and can never be weakened by a repository; guarded keys are also clamped to the default branch's resolved profile. The profile and ordinary workflows leave the default protect list, so each pull request that changes one must name it under Security (checked mechanically); the release, land and git-ops workflows stay protected in code. Making the tkcs-lab base repository public is a decision for the owner. `--explain` offsets the loss of "never invent a value".

**Review focus:** Guarded-key rules and the trusted clamp (3.4, p5); the protect-list change with its Security rule (3.5, p6); where the plan departs from the ask's words: SHA-only pins (3.2), rename-only migrate (3.7) and website `dir` `.` (3.1); defaults that depend on files existing (3.1, p1).

## 1. Goal

Make tld the same in every repository of the owner with the fewest questions, as asked in [issue #90](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/90). Today every repository copies the profile template, so guardrails and defaults drift, and setup asks several questions. After this plan a profile extends one pinned base, built-in defaults supply the common values, and a minimal profile is `tld.extends` plus `verify.fast` and `verify.dod`. The decisions come from the review page the owner commented on (27 threads); the owner's answer to this plan's ask settled two points: the base is per org (a repository extends `<its owner>/.github`), and the central repository is `<repo owner>/git-ops`.

## 2. Current state

- `src/tld/profile/validate.py` checks the raw profile against the schema, fills the schema's `default`s (only `docs.plan_dir` and `models`, line 119) and runs `semantic_checks`. `docs/reference/profile-reference.md:13` promises that commands never invent a value.
- Sixteen readers load or consume the profile and apply their own defaults: `src/tld/guard/_common.py:157` (`find_project`), `src/tld/guard/trust.py:191` (`trusted`, the profile at the remote default branch, cached ten minutes), `src/tld/roles/dispatch.py:126` (`_load_profile`), `src/tld/dod/gate.py:129` (reads `ctx.profile`), `src/tld/plan/{manifest,phases,scope}.py`, `src/tld/board/inbox.py:89` (`owner_login`), `src/tld/ops/{docs_index,spec,sysml,release_prepare}.py` and, new on main, `src/tld/ops/deps_prepare.py:28` (it calls `validate(profile, None)` on the trusted profile and reads `resolved["deps"]["lock_freshness"]` and `resolved["hooks"]["protect_paths"]`); `ops/migrate.py:462` calls `validate()` and `ops/repo_admin.py:258` calls `check()` from `validate.py`; both keep working through unchanged signatures (new parameters are trailing keywords with defaults).
- Hook defaults: protect list `src/tld/guard/_common.py:26` holds the profile and all workflows; the plan, board and DoD gates are off (`hooks.md:208,261,295`) while the starter template (`src/tld/templates/toolkit.yaml:137`) says all hooks but the DoD gate are on.
- Keys required inside a section today: `deps.cooldown_days`, `deps.time_budget_minutes`, `spec.version`, `sysml.subset`, `git_ops.repo`, `release.workflow`, `git.branch_pattern`, `git.main_branch`, `docs.must_read`, `stacks`.
- `/setup` (`playbooks/setup.md`) asks the posture and every blocking role, detects `branch_types` from branch prefixes, and reads neither CODEOWNERS, the version line, `deps.audit` nor `deps.lock_freshness`. `/migrate` stops at "Nothing to migrate" for a repository already on tld. repo-admin has merge-setting checks but nothing for the base, git-ops or secret scope (`src/tld/ops/repo_admin.py:1484`).
- There is no helper that fetches a file from another repository. The nearest are the pinned download of `src/tld/roles/reflektor.py` (pin at lines 49-59, download at 91-114, no cache) and the trusted-copy cache of `src/tld/guard/trust.py`.
- A privacyfence/.github clone works anonymously through the session's git proxy, including a fetch by 40-hex commit (checked in this session); that repository has no tag and no profile base yet. tkcs-lab/.github is not anonymously readable from a session.

## 3. Design

The architect role designed 3.1 to 3.8; each choice below names what was rejected. Names are final.

### 3.1 One resolver, defaults as a table

**Rejected:** patching each reader (fourteen chances to drift, which is today's problem). **Chosen:** one loader that every reader calls.

New modules under `src/tld/profile/`:

- `defaults.py` (pure): `STATIC` (dotted key to value), `SECTION_DEFAULTS` (applied only inside a section the repository writes), `FILE_CHECKED` (key, value, path that must exist), `OFF_SWITCHES`, `Env` (a dataclass of callables: `exists(path)`, `read(path)`, plus `origin_owner`, `main_branch`) and `apply(profile, env) -> (resolved, sources)`.
- `merge.py` (pure): `merge(base, repo) -> (merged, sources)`, `guarded_errors(floor, merged, allow, label)`, `clamp(floor, merged, branch)`, `POSTURE_RANK = {"low": 0, "standard": 1, "critical": 2}`, `OVERRIDE_RE`.
- `base.py`: `BaseRef`, `parse_extends`, `cached`, `fetch`, `check_base_text`, `latest_pin`, `main` (`tld profile base check|fetch|latest`).
- `resolve.py`: `Resolved` (profile, sources, errors, warnings, base), `load(path, *, ref, root, fetch, trusted, file_checks)`, the pure `resolve(raw, *, base, base_ref, trusted, trusted_branch, env)` (`trusted` is the default branch's already resolved profile or None) and `for_hook(raw, project, *, at_sha)` (cache only, never raises). `merge.py` and `defaults.py` import nothing from `tld.guard` at module level (the hook names are read inside a function).

The defaults are a Python table because existence checks, the detected main branch and the origin owner cannot be schema defaults. The schema keeps `default` annotations; a test asserts they equal the table.

`STATIC`: `git.branch_pattern` `<type>/<kebab-case>`; `git.branch_types` `[feature, fix, chore]`; `git.merge_style` `merge-commit`; `docs.must_read` `[]`; `stacks` `[]`; `models` (as today); `land.max_prs` 10; `git_ops.workflow` `tld-git-ops.yml`; `hooks.disable` `[]`; `hooks.protect_paths` `[.env, .env.*, *.lock, package-lock.json, go.sum]`; `hooks.protect_paths_allow` `[]`; `hooks.dod_gate` `{enabled: true, max_attempts: 3}`; `hooks.plan_gate.enabled` and `hooks.board_gate.enabled` true. A repository with no profile at all keeps gates off (the hooks do nothing without a profile today).

`SECTION_DEFAULTS` (only when the section is written; an empty section, YAML null, counts as written): `deps` `{cooldown_days: 3, time_budget_minutes: 90}`; `spec.version` `"2.1.0"`; `sysml.subset` 1; `release.workflow` `tld-release.yml` (`release.version_files` stays required).

Detected or file-checked defaults, each recorded with its source:

| Key | Applied when | Value |
|---|---|---|
| `git.main_branch` | `origin/HEAD` resolves, else the trusted copy's default branch | that branch |
| `git_ops.repo` | an origin exists | `<origin owner>/git-ops` |
| `docs.plan_dir` | always | `docs/plans` when that directory exists, else `docs` (keeps in-flight plans working) |
| `docs.index` | `docs/README.md` exists | `docs/README.md` |
| `docs.adr_dir`, `docs.adr_index` | `docs/adr` exists | `docs/adr`, `docs/adr/README.md` |
| `docs.adr_bar` | `adr_dir` was applied and `CONTRIBUTING.md` has the heading "Decisions, plans and ADRs" | `CONTRIBUTING.md#decisions-plans-and-adrs` |
| `docs.changelog` | `CHANGELOG.md` exists | file `CHANGELOG.md`, section `## [Unreleased]`, policy `unreleased` |
| `admin.policy` | `.tld/admin-policy.yaml` exists | that path (no error when absent) |
| `docs.website` | `scripts/build_site.py` exists | dir `.`, build `python3 scripts/build_site.py --out _site`, links `python3 -m pytest tests/unit/test_website_links.py -q` (**departs from the ask's `dir: website`**: `build` and `links` run from `dir` and both commands name root-relative paths; `website/` holds the sources, not the commands, so `dir: website` could never run them. Change this one value if you disagree) |

tld's own repository has no `docs/adr`, so ADRs stay off there. An explicit `admin.policy` naming a missing file stays an error.

**Turning a defaulted feature off.** An off switch is applied first and stops every default that depends on it (`admin: false` stops `admin.policy`; `docs.adr_dir: false` stops `adr_index` and `adr_bar`; `docs.changelog: false` stops the changelog default). `false` on `docs.index`, `docs.adr_dir`, `docs.changelog`, `docs.website`, `admin`, `git_ops` and `land.max_prs` (the schema allows `oneOf [<type>, {const: false}]` there). `null` is not used, because the owner made an empty `spec:` block mean "on". The resolver deletes the key, so no reader ever sees `false`. Gates are turned off with `enabled: false`, subject to 3.4.

**Provenance.** `--resolved` JSON keeps its shape (plus the whole `hooks` section) and prints one stderr note `toolkit.yaml: note: <n> values from the base <source>@<sha7>, <m> built-in defaults (--explain lists them)`. New `--explain` prints `<dotted key> = <json value>  # <source>`, sorted; sources are `repo`, `base <owner>/<repo>/<path>@<sha7>`, `default`, `default (<path> exists)`, `detected (origin/HEAD)` and `<branch> (the remote default branch; this branch's value is weaker)`. New `--ref REF` reads the profile and the files that decide the defaults from that ref. `playbooks/policies/profile.md` rule 1 becomes: every value comes from the resolved profile, a base value or a built-in default is part of it, and a key still missing from it is named and stops the run.

**Load order** (`resolve.load`): read YAML (or `git show REF:.tld/toolkit.yaml`); turn null `deps`, `spec`, `sysml` into `{}`; run `parse_extends` on `tld.extends` first, so a tag pin gets the 3.2 text and not a generic schema error (the schema only says "non-empty string"); check the raw repository profile for shape and unknown keys without the required-key rule; refuse `tld.allow_override` in a repository; get the base (cache, then fetch); `check_base_text`; `merge`; `defaults.apply`; `guarded_errors` against the **guard floor** (the base plus the built-in values of the guarded keys); then, with an origin, the **trusted profile** is resolved on its own and `clamp` takes the stricter value per guarded key; full schema check with required keys; `semantic_checks` on the result (so "bot_login must not be in codeowners" runs on the merged profile).

The two floors differ: the guard floor decides *errors* (what a repository may write against its base); the trusted profile decides *clamping* (what a branch may weaken against the default branch). The trusted profile is resolved by the same `resolve` with the default branch's own `tld.extends` read from the cache only (never fetched; an uncached base counts as absent, its `tld.allow_override` is not honoured and a warning says so) and an `Env` that reads files at the trusted commit (`git ls-tree --name-only <sha>`, `git show <sha>:<path>`), never the working tree.

### 3.2 Fetch, cache, pin

**Rejected:** HTTPS raw files (a second host to allow, no content addressing). **Chosen:** git over the session's proxy by commit.

- `tld.extends` is `<owner>/<repo>/<path>@<40-hex commit>`. **A tag or branch is rejected** (stricter than the owner's "tag or SHA"): sessions start from fresh clones, so a cache cannot keep a tag stable, and a moved tag would change the base in every repository without a pull request. Setup and the audit write `extends: <source>@<sha>  # <tag>` with the tag as a trailing comment. Error (from `parse_extends`; the schema carries no pattern): `toolkit.yaml: 'tld.extends': '@<ref>' is not a commit SHA; pin the base by its full 40-hex commit (a tag can move): run tld profile base latest <owner>/<repo>/<path>`.
- Source form (`base.SOURCE_RE`): owner `[A-Za-z0-9][A-Za-z0-9-]{0,38}`; repo `[A-Za-z0-9._-]{1,100}`, not `.`, `..` or ending `.git`; path of non-empty segments without `.`, `..` or backslash, printable, at most 256 characters, ending `.yaml` or `.yml`. Owner and repo compare lower-case. The URL is always `https://github.com/<owner>/<repo>.git`. Error: `toolkit.yaml: 'tld.extends': must be <owner>/<repo>/<path>@<40-hex commit SHA> (got '<value>')`.
- Fetch: a separate bare repository `<git common dir>/tld/base/objects.git` (`git rev-parse --git-common-dir`, so linked worktrees share one cache; never the project's own object store: a shallow fetch there would mark the user's repository shallow), `git fetch --depth=1 --no-tags --no-write-fetch-head https://github.com/<owner>/<repo>.git <sha>` with the safe options and environment of `src/tld/guard/trust.py` and a 20 s timeout, then `git show <sha>:<path>`.
- Cache: `<git common dir>/tld/base/<key>.yaml` (the exact bytes) and `<key>.json` (`source, sha, blob, size, sha256, fetched_at`), written atomically; `key` is the first 24 hex of `sha256("<owner>/<repo>/<path>@<sha>")` lower-cased. No TTL: a commit never changes, so it is never fetched twice, works offline and cannot change mid-session. A read verifies the hash; a mismatch is a miss. `.git/tld/**` is already always protected; a planted cache file is the same documented limit as `trusted.json`.
- Playbook loader (`tld profile validate`): a miss plus a failed fetch exits 1 with `toolkit.yaml: 'tld.extends': the base <source>@<sha7> is not cached and could not be fetched (<first git error line, 200 characters>); run again with network access`, and `...: <path> does not exist at <owner>/<repo>@<sha7>`. Stopping is the safe side: running without the base would run without its required roles.
- Hooks (`for_hook`): cache only, never a fetch (the trust lookup already spends up to 12 of the 15 seconds). On a miss nothing from the base applies: `hooks.disable` is the repository's own list (still checked), protect lists are the built-ins plus the repository's, gates follow the defaults (on), and the notice reads `the base <source>@<sha7> is not cached here; run tld profile validate to fetch it`. That is more protection, never less.
- `tld profile base latest SOURCE` prints `{"sha": ..., "tag": ...}`: the newest version-sorted tag whose commit has the file, else the default branch head with `"tag": null`. `tld profile base fetch [PROFILE]` fills the cache. `tld profile base check FILE` runs `check_base_text` so the owner can check the file before tagging.

### 3.3 Trust model and the base's allow-list

- Who edits the base: the owners of the base repository, through its own ruleset and CODEOWNERS (the audit checks them like any repository). A base change reaches a repository only through a pull request that changes the pin (setup, the audit's pin-bump pull request, or by hand).
- No chaining: a base that sets `tld.extends` is refused (`toolkit.yaml: base <source>@<sha7>: 'tld.extends': a base cannot extend another profile`), so there is one fetch, one pin and one trust analysis.
- `BASE_KEYS`, the owner's list in section 2 plus `tld.allow_override`: `tld.version`, `tld.allow_override`, `git.bot_login`, `git.codeowners`, `git.branch_pattern`, `roles.posture`, `roles.required`, `hooks.*`, `models`, `runtime.environments`, `verify.dod_manual`. Everything else is refused, in particular `verify.fast` and `verify.dod` (a base must never run code everywhere), `roles.extra_context` (prompt text in every role), every feature section (`spec`, `sysml`, `deps`, `release`, `admin`, `git_ops`, `upstream`, `docs.website`), `project_steward`, `ci`, `scope`. Error: `toolkit.yaml: base <source>@<sha7>: '<key>' cannot be set in a base (a base may set: <list>)`.
- Token check (`check_base_text`): `secret_scan.scan_text(text, skip_marked=False)` (the keyword-only option added on main, so a `secret-scan:allow` mark never hides a token in a base), and refuse any mapping key for which `secret_like_name(key)` is true whatever its value. Error, value never shown: `toolkit.yaml: base <source>@<sha7>: refused: line <n> looks like <kind> (pattern: <name>); the value is not shown. A base never holds a credential.`
- Size and shape: at most 65536 bytes, UTF-8 without BOM, a mapping on top, nesting at most 8, no YAML anchor or alias (found by scanning `yaml.parse` events; aliases are the expansion vector once the result is serialised). Error: `toolkit.yaml: base <source>@<sha7>: uses YAML anchors or aliases; a base must not`.
- The trusted copy pins the base too (3.4 clamp): a branch that points `extends` elsewhere, or removes it, still gets its own non-guarded values, but every guarded key is clamped to the default branch's resolved values.

### 3.4 Guarded keys

**Merge.** Mappings deep-merge; the repository's scalars and lists replace the base's (the owner's rule), with two documented exceptions, because replacement would silently drop shared rows in exactly the repositories that add their own, and would make every pin bump break repositories that restated `roles.required`:

- `verify.dod_manual`: base rows, then repository rows, without duplicates.
- `roles.required` merges by `role`: base entries first; a repository entry for a role the base lacks is added ("a repo may add roles"); a repository entry for a base role strengthens it (`at` is the union, `blocking` is base OR repository, `when` is the union, and a repository `when` on a base entry without one is ignored with `'roles.required[i].when': no effect, the base runs <role> on every diff`). Dropping a base role happens only through `roles.disable: [<role>]`, and only when the base lists `roles.required.<role>` in `tld.allow_override`; then `merge` removes the base entry from the merged `roles.required` (so the existing "required and disabled" check does not fire) and `roles.disable` keeps the role. Without the allowance the entry stays and `guarded_errors` reports it.

**`tld.allow_override`** (base only, a list from this closed set): `hooks.disable.<hook>` for each hook name, `hooks.protect_paths`, `hooks.protect_paths_allow`, `hooks.dod_gate.enabled`, `hooks.plan_gate.enabled`, `hooks.board_gate.enabled`, `roles.posture.security`, `roles.required.<role>`. A repository that sets it: `toolkit.yaml: 'tld.allow_override': only a base profile may set it`.

**Floor** = base plus the built-in values of the guarded keys. A profile without `tld.extends` has no floor, so old profiles validate unchanged. Refusals (each unless the base lists the key):

| Rule | Error |
|---|---|
| a hook added to `hooks.disable` beyond the floor | `toolkit.yaml: 'hooks.disable': '<hook>' is switched on by the base <source>@<sha7>; the repository cannot switch it off unless the base lists 'hooks.disable.<hook>' in tld.allow_override` |
| `roles.posture.security` below the floor (critical above standard above low) | `toolkit.yaml: 'roles.posture.security': '<repo>' is weaker than the base's '<base>' (critical > standard > low); allowed only when the base lists 'roles.posture.security' in tld.allow_override` |
| a base-required role in `roles.disable` | `toolkit.yaml: 'roles.disable': '<role>' is required by the base <source>@<sha7> at <points>; allowed only when the base lists 'roles.required.<role>' in tld.allow_override` |
| a floor pattern left out of `hooks.protect_paths` | `toolkit.yaml: 'hooks.protect_paths': leaves out '<pattern>', which the base <source>@<sha7> protects; list it, or have the base list 'hooks.protect_paths' in tld.allow_override` (with "tld's default list" for the base when the base does not set it) |
| a `hooks.protect_paths_allow` pattern not in the floor | `toolkit.yaml: 'hooks.protect_paths_allow': '<pattern>' widens what the base <source>@<sha7> protects; allowed only when the base lists 'hooks.protect_paths_allow' in tld.allow_override` |
| a gate's `enabled` false where the floor is true | `toolkit.yaml: 'hooks.<gate>.enabled': false switches off a gate the base turns on; allowed only when the base lists 'hooks.<gate>.enabled' in tld.allow_override` |

**Trusted clamp (closes a gap the architect found).** Today only the protect-paths hook stopped a worker editing the profile, and the guarded keys were read from the working tree. With the profile off the default list, a phase worker could drop a required role or set a gate to false and the final review would read the weakened copy. So `clamp(trusted, merged, branch)` takes the stricter of the working copy and the default branch's resolved profile for every guarded key: `hooks.disable` becomes the trusted list (a branch cannot add a disable), gates become trusted OR working copy (replacing decision 5 of `hooks.md:291`), the posture the higher rank, `hooks.protect_paths` the union, `hooks.protect_paths_allow` the intersection with the trusted list, and every trusted `roles.required` entry keeps its points and `blocking` and warns: `toolkit.yaml: warning: '<key>' is weaker here than on <branch> (the remote default branch); the <branch> value applies until this change is merged`. With no trusted copy (no origin, offline) there is no clamp and the warning is `toolkit.yaml: warning: no trusted copy of the profile (<problem>); guarded keys are taken from this working tree`; the hooks keep today's rule.

### 3.5 The protect list and the Security rule

- Default `hooks.protect_paths` loses `.tld/toolkit.yaml` and `.github/workflows/**`. Always protected in code: the `.git` internals and the adapter files (unchanged), the land and release workflows by name, and now also the profile's trusted `release.workflow` (tld's own is `release.yml` and holds the release token) and `tld-git-ops.yml`. The constants `GUARDED_WORKFLOWS` and `BUILTIN_PROTECT_ALLOW` stay importable as lists (`deps_checks.py`, `markers.py` and `manifest.py` use them); a new function `guarded_workflows(ctx)` returns the union for the hooks.
- `tld guard allow-profile` and its marker stay exactly as they are (a no-op for the default list, still honoured when a list adds the profile back); no playbook that calls it changes.
- **Workflow edits now run before anyone reads them.** A pushed branch's edited workflow runs at once with repository-level secrets; environment secrets limited to the default branch stay safe (the release, agent and git-ops tokens). So repo-admin gains the `secrets_scope` check (3.7) and `SECURITY.md` states the new exposure.
- `playbooks/policies/protected-changes.md` stops naming the profile and workflows as protected by default: "What is protected" lists the new default; the flow still handles any path a repository or base adds back. "Main's profile only" reads the main profile with `tld profile validate --ref origin/<main> --resolved` (the raw `git show` misses the base and the defaults); the "deps exception" paragraph of that policy stays (the deps playbook's combined pull request may carry a bot's action-ref bumps; `deps_prepare` hard-codes its own protected set, so the new default list changes nothing for it). `playbooks/implement.md` keeps "a protected path is blocking" against the smaller effective list, and adds a final-review rule: a diff touching `.github/workflows/**`, `.tld/toolkit.yaml` or a guarded workflow is a trust-boundary change the security reviewer checks at `implement_final`; a weakened guarded key, a new `pull_request_target`, a secret reference or new `permissions: write` is a blocking finding. `playbooks/quick.md` takes the same rule (it passes `--changed` and no longer calls a profile or workflow change non-small just because of the path); `playbooks/make-plan.md` still forbids listing a protected path in `touches`; the profile and ordinary workflows may now appear there and the brief names them for the Security line. `playbooks/policies/pr-steward.md` gains the general rule.
- **Mechanical check.** `tld plan summary-check FILE --kind pr --changed LIST` (one path per line; `implement` passes `git diff --name-only --no-renames origin/<main>...HEAD`). `SECURITY_PATHS` are the `.github/workflows/` prefix and `.tld/toolkit.yaml`. Problems: `summary: **Security:** is missing or None. but the pull request changes <path>[, <path>]` and `summary: **Security:** must name every workflow and profile file this pull request changes; not named: <path>[, <path>]`; a path counts as named when its full path or file name appears in the label's text. `--changed` with another kind exits 2.

### 3.6 Messages that change

| Where | New text |
|---|---|
| `/deps` without a `deps` section | `toolkit.yaml: /deps needs a 'deps' section (an empty 'deps:' uses cooldown_days 3 and time_budget_minutes 90)` |
| spec commands without a `spec` section | `toolkit.yaml: /spec needs a 'spec' section (an empty 'spec:' uses version 2.1.0; see docs/guides/spec.md)` |
| sysml commands without a `sysml` section | `toolkit.yaml: /sysml needs a 'sysml' section (an empty 'sysml:' uses subset 1; see docs/guides/sysml.md)` |
| no main branch | `toolkit.yaml: missing required key 'git.main_branch' (it could not be detected: no origin/HEAD and no remote default branch)` |
| `/git-ops` | the section is optional: `git_ops.repo` defaults to `<origin owner>/git-ops`; with `git_ops: false` it stops with `toolkit.yaml: /git-ops is switched off ('git_ops: false')` |
| repo-admin | no `admin.policy` file and no key: `toolkit.yaml: the admin audit is off (no .tld/admin-policy.yaml; see docs/guides/admin.md)` |

### 3.7 Setup, migrate, repo-admin

**Setup.** New `src/tld/profile/survey_repo.py` (`scan(root)`): CODEOWNERS logins (`.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS`; `@login` tokens only, `@org/team` and emails skipped, the bot never listed); the version line (`pyproject.toml` `^version = "([^"]+)"`, `package.json` `^\s*"version": "([^"]+)"`, `Cargo.toml` `^version = "([^"]+)"` in `[package]`), proposed as `release.version_files` only when exactly one file matches; `deps.audit` (pip-audit `--strict -r <runtime lockfile>` when a `requirements/*.lock.txt` or `requirements*.txt` exists, `npm audit --omit=dev --audit-level=high` with `cwd` for each directory holding a `package-lock.json`, `govulncheck ./...` for `go.mod`); `deps.lock_freshness` only when a `scripts/*lock*.sh` exists; the `docs.adr_bar` heading in `CONTRIBUTING.md`. `survey.py` keeps its `branch_prefixes` evidence but `survey_proposal.build(evidence, base=None)` no longer proposes `git.branch_types` or `git.merge_style`; with a base it leaves out everything the base sets and proposes `git.codeowners` only when the file differs. `survey.py` gains the option `--base FILE` (a cached base, read-only) and passes it to `build`; `profile/patch.py` `KEYS` gains `tld.extends`. Where setup learns the base (no organisation name in `src/`, `cli/`, `adapters/` or `playbooks/`), in order: the argument `--base <owner>/<repo>/<path>`; the variable `TLD_BASE_PROFILE` (set in the working environment's settings like `TLD_ENVIRONMENT`); the convention `<origin owner>/.github/tld/profile-base.yaml`, probed with `tld profile base latest`; otherwise a standalone profile and a line saying so. Flow: `tld profile base latest`, `tld profile base fetch`, `tld profile survey . --base <cache file>`, one ask only when something is missing (`verify.fast` and `verify.dod` as `text`, plus a `confirm` for each repository-specific `blocking: true` role; the posture is no longer asked), write `tld.extends: <source>@<sha>  # <tag>` and `tld.version: ">=1.7,<2"`, every detected value written explicitly, one pull request. A pull request that changes the profile or a workflow carries a `## Security` line.

**Migrate** (`src/tld/ops/migrate_defaults.py`, `tld migrate . --defaults [--write --answers FILE]`): finds a docs index, ADR directory or changelog off its default path (`docs/index.md`; `docs/adrs`, `docs/decisions`, `doc/adr`, `adr`; `CHANGES.md`, `HISTORY.md`; an Unreleased heading spelled `## Unreleased` or `## [unreleased]`) and asks one `choice` per find: `rename` (through `tld ops docs-index move SRC DST --apply`, which rewrites links) or `keep` (write the explicit key). Copying (the ask's "renamed or copied") is rejected: it leaves two sources of truth, so the choices are rename or keep; this is a departure from the ask's words. It also lists keys now equal to a default or the base, `protect_paths_allow` entries made moot, and preserve-behaviour writes (`branch_types` for types the existing manifests use, `plan_dir: docs/plans/` when plans exist there). It changes nothing without `--write` and the answers. `ops/migrate.py` calls it where it printed "Nothing to migrate".

**repo-admin** (`src/tld/ops/repo_admin_profile.py`, registered in `run_checks`; new policy sections in `admin-policy.schema.json`): `profile: {base: <owner>/<repo>/<path>, pin: latest-tag | <40-hex>, guarded_overrides: report | ignore}` and `git_ops: {repo, workflow, allowlist}`. Checks: `profile-no-extends` and `profile-invalid-extends` (warn, manual step: run setup in update mode), `profile-pin-old` (fix: a pull request through `apply_files` that rewrites only the `extends:` line, title `chore: bump the tld base to <tag>`), `profile-guarded-override` (info), `profile-merge-style`; the starter policy sets `allow_merge_commit: true`, `allow_squash_merge: false`, `allow_rebase_merge: false`; `git-ops-workflow` and `git-ops-allowlist` (fix: a pull request into the central repository), `git-ops-environment` and `git-ops-token` as open items reusing `_env_and_secret` with manual text; `secrets_scope` (report a repository or organisation Actions secret not held in an environment limited to the default branch). The base repository is audited like any repository.

### 3.8 The base file

The owner creates it in each org's `.github` repository at `tld/profile-base.yaml` (the plan's manual steps). Its content, from section 2 of the ask:

```yaml
tld:
  version: ">=1.7,<2"
git:
  bot_login: andras-tkcs-agent
  codeowners: [andras-tkcs]
  branch_pattern: "<type>/<kebab-case>"
roles:
  posture: {security: critical}
  required:
    - {role: security-reviewer, at: [implement_phase, implement_final], blocking: true}
    - {role: test-architect, at: [make_plan]}
    - {role: reflektor, at: [dod]}
    - {role: dependency-auditor, at: [dod], when: [pyproject.toml, "requirements*.txt", package.json, package-lock.json, go.mod, go.sum, Cargo.toml]}
hooks:
  dod_gate: {enabled: true, max_attempts: 3}
  plan_gate: {enabled: true}
  board_gate: {enabled: true}
models: {worker: standard, reviewer: strong}
runtime: {environments: [TLD]}
verify:
  dod_manual:
    - "A user-visible change needs a changelog line under ## [Unreleased]."
```

`roles.posture.security: critical` follows tld's own profile (the ask names `roles.posture` without a value); a repository may not lower it. Code-reviewer is left out, as in the ask.

### 3.9 Behaviour changes on upgrade (migration notes)

Ships as the next minor release after 1.6.0 (1.7.0), not 2.0.0: the schema change is additive and `CONTRIBUTING.md:97`'s major bump would break every `tld.version: ">=1.x,<2"` profile. A profile with `tld.extends` needs `>=1.7`; an older tld rejects the unknown key and stops cleanly. The release skill makes the version heading and bumps the three version lines.

1. **Gates on.** `plan_gate`, `board_gate` and `dod_gate` are on for every repository with a profile and no `hooks` value. A session no tld command started cannot write; an editing session runs `verify.dod` at stop. Turn one off with `enabled: false` (refused under a base without `tld.allow_override`).
2. **`docs.plan_dir`** defaults to `docs/`, except a repository with a `docs/plans` directory resolves to `docs/plans`, so in-flight plans and `tld plan check-url` keep working. `migrate --defaults` writes the explicit key.
3. **`land.max_prs` is 10** (was: no cap). Write another number, or `false` for no cap.
4. **Protect list.** The profile and ordinary workflows are no longer protected by default; a repository with its own `hooks.protect_paths` is unchanged; privacyfence's six `protect_paths_allow` workflow entries become moot (migrate lists them). Pull requests touching them must name them under Security.
5. **`git.merge_style`** is `merge-commit` unless written; a squash repository must write it. The audit enforces merge commits on GitHub where its policy says so.
6. **`git.branch_types`** is no longer detected: `[feature, fix, chore]` unless written, and `validate-manifest` always checks it; migrate writes the types that existing manifests use.
7. **Docs paths** apply when the file exists: an existing `docs/README.md` turns on index steps, `CHANGELOG.md` the changelog line and version-heading guard, `docs/adr/` the ADR steps, `.tld/admin-policy.yaml` the audit, `scripts/build_site.py` the website. Each is turned off with `false`.
8. Messages in 3.6 change; `deps`, `spec`, `sysml` and `release.workflow` default inside their sections.

### 3.10 Security analysis (what the architect weighed)

- **Trust.** The base is code-like policy for every agent. It is pinned by commit and edited only through the base repository's own ruleset; the key allow-list keeps it away from commands, prompt text and feature switches; the token check and the shape limits refuse content that could carry a secret or expand; no chaining keeps one trust path. The residual risk is the owner's own control of the `.github` repositories: whoever can merge there changes every repository after a pin bump, so the audit treats the base repository like any other and the pin bump is a reviewed pull request.
- **Fetch failure.** The playbook loader stops (never runs without the base); hooks use the cache only and fall back to the stricter built-ins. A moved or force-pushed base cannot change a pinned commit.
- **Pin bumps.** A bump is a pull request that changes one line; its Security line must name the profile; the new base's weaker guardrails take effect only after merge because of the trusted clamp.
- **Loss of "never invent a value".** `profile-reference.md` promised commands never use a value of their own. The defaults table is a short, documented list; `--explain` shows every value's source; setup writes every detected value explicitly into the repository's profile so the pull request shows what will run. This changes a principle, so the retirement phase rewrites the reference and `playbooks/policies/profile.md`.
- **Workflows editable by sessions.** Compensated by the Security rule, the widened code-protected workflow set, `secrets_scope` and an updated `SECURITY.md`.

### 3.11 The spec change and the architecture change

`openspec/changes/org-base-profile/` holds the deltas (validated with `tld ops spec validate --change org-base-profile`): `project-profile` (modified: validate, resolved output; added: extends, fetch and cache, base commands, unsafe base, base keys, merge, additive merge, guarded keys, static, section and file-checked defaults, survey facts, one-batch setup, migrate off-default paths), `repository-guardrails` (modified: protected paths, plan gate, board gate, trusted source), `definition-of-done-gate` (the opt-in gate replaced by a default-on gate), `plan-run-tracking` (summary check `--changed`) and `release-and-repo-ops` (base pin, git-ops, merge settings, secret scope audits). `sysml/changes/org-base-profile/` replaces `core.sysml`; `tld ops sysml check --change org-base-profile` prints:

```
changed part def Core::Profile
added part def Core::ProfileBase
added dependency Core::dependency(Guard->Profile)
added dependency Core::dependency(Plan->Profile)
added dependency Core::dependency(Profile->Guard)
added dependency Core::dependency(Profile->ProfileBase)
added dependency Core::dependency(ProfileBase->Guard)
```

### 3.12 Rejected alternatives

- Tag pins (3.2); a base that may chain; HTTPS raw fetch; `null` as the off switch; schema `default`s for everything; a single base location in code (the owner chose per-org); copying off-default files in migrate (two sources of truth); `dir: website` for the website default (the commands could not run); a 2.0.0 release; detecting `merge_style` and `branch_types` (the owner decided fixed defaults).

### 3.13 Test names and scenario coverage

Every new test that proves a spec scenario is named `test_<scenario name>` in lower case with every run of other characters as one underscore (for example `Repository overrides a scalar` is `test_repository_overrides_a_scalar`), and a phase's acceptance names its tests as pytest node ids (`file::test_name`), because pytest exits non-zero for a node id that does not exist. Scenarios whose behaviour this plan does not change (the unchanged guard, gate and summary scenarios) are proved by the existing test files, which each owning phase runs unchanged. Mutants added by the plan carry the pinned ids VP18 and VP19 (p3; VP13 to VP17 already exist), MG1 to MG3, RS1, RS2 and BS1 (p4), CL1 and CL2 (p5) and SC1 and SC2 (p6), and each of those phases runs `tests/mutation/run_mutants.py --only <its ids>`.

## 4. Manual steps

Everything the phases build runs offline against fixtures; nothing manual is needed before implementation. ma1 and ma2 happen after the last phase merge and before the feature pull request merges (a person is needed for another organisation's repositories, secrets and visibility); ma3 happens after that pull request merges, because a release needs `main`. About 40 minutes in all.

### After implementation

**ma1 - Create the base file in each org and tag it (about 15 minutes per org).**

1. Open the repository's web page: `https://github.com/privacyfence/.github` (public today) and `https://github.com/tkcs-lab/.github`. For tkcs-lab: **Settings, General, Danger Zone, Change visibility** at `https://github.com/tkcs-lab/.github/settings`, make it public (a session can only read it anonymously then; the base must hold no secret, and the token check enforces that), or confirm another way that cloud sessions can read it.
2. In a clone of tkcs-lab-devflow on the feature branch (it has `tld profile base check`), create `tld/profile-base.yaml` in each `.github` repository with the content of section 3.8 of this plan (`https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/org-base-profile/docs/plans/90/plan.md`).
3. Run `tld profile base check tld/profile-base.yaml`. Expect `base: OK`; fix what it prints otherwise.
4. Merge the file through a pull request that the repository's CODEOWNERS approve (never push to the default branch).
5. Tag the merge commit: `git tag v1 <sha> && git push origin v1` in each `.github` repository (the tag is a label; repositories pin the commit).
6. Run `tld profile base latest <owner>/.github/tld/profile-base.yaml` and keep the printed commit for step ma3.

Report back: the two commits.

**ma2 - Create the git-ops environment and secret (about 10 minutes per org).**

1. In each org's `git-ops` repository open **Settings, Environments** (`https://github.com/<owner>/git-ops/settings/environments`) and click **New environment**, name `git-ops`.
2. Under **Deployment branches and tags** choose **Selected branches and tags** and add `main` only.
3. Under **Environment secrets** click **Add environment secret**: name `GIT_OPS_TOKEN`, value a fine-grained token with `Contents: write` on the audited repositories only. The value goes only into that field; never into chat, a plan or an ask.
4. Run the org audit (`/tld:repo-admin`); it adds `tld-git-ops.yml` and the allowlist through pull requests into the git-ops repository, which you merge.

Report back: pass or fail for the audit's `git-ops-*` rows.

**ma3 - Release 1.7.0 and bump each repository's pin (about 15 minutes).**

1. After the feature pull request is merged, run `/tld:release` in tkcs-lab-devflow and answer the board question (the release skill makes the `## [1.7.0]` heading and the version lines).
2. In every existing repository run `/tld:setup update` (or merge the audit's pin-bump pull request); check the pull request's `## Security` line names `.tld/toolkit.yaml`.
3. Run `tld profile validate --resolved` there and compare with `--explain`.

Report back: one pass or fail line per repository.

## 5. Risks and open questions

1. **Gates on by default break hook tests** that build profiles without `hooks`. A worker sees `tld plan-gate` or `tld dod-gate` denials in `tests/core/test_hook_*.py`. Fix the fixtures with an explicit `hooks` block; never loosen an assertion.
2. **Circular imports.** `base.py` imports `tld.guard.secret_scan`, which imports `tld.guard._common` (`secret_scan.py:12`), which now needs `tld.profile.resolve`. `_common` imports it inside `make_ctx`, `resolve` imports `tld.guard.trust` inside `load` only, and `merge.py` and `defaults.py` import nothing from `tld.guard` at module level. Symptom: `ImportError: cannot import name ... (partially initialized module)`.
3. **Mutants.** Editing `validate.py`, a guard file or `summary.py` under a mutant fails `tests/core/test_mutants_file.py` until `tests/mutation/mutants.yaml` matches again. p3, p4, p5 and p6 own that file in turn; p4 also adds `src/tld/profile/{merge,resolve,base,defaults}.py` to `MODULES` and to the `tests:` map there. Mutant ids are pinned in 3.13.
4. **Baseline drift.** Any phase that edits a playbook, or a policy many playbooks link, changes command hashes (`tests/core/test_evals_baseline.py`). p6, p8, p10, p11 and p14 are chained for that reason (the command hashes cover `quick` too: protected-changes, pr-steward and profile policies reach all 17 commands; implement.md reaches implement and quick; make-plan.md reaches make-plan and quick; release, repo-admin and git-ops are skills and are not hashed); the recorded pass rates of the guardrail, make-plan and review evals come from real runs, so a phase that edits `evals/fixtures/tiny_app.py` or the make-plan, implement and quick playbooks says in its commit message why those rates are not affected; each refreshes with `python3 evals/run.py baseline --refresh-hashes` and says why in its commit message.
5. **Hook budget.** `tld ...: took longer than 15 s, so the call is denied` means `for_hook` reached the network or loaded the schema. Keep it cache-only and do not load the schema JSON on the hook path.
6. **Fetch by commit refused by the proxy.** Checked in this session for a public repository (works). If a worker sees `couldn't find remote ref` or `Server does not allow request for unadvertised object`, stop with `status=blocked`; the fallback is `git fetch --depth=50 <url> HEAD` plus `git cat-file -e <sha>`, which is a design change.
7. **Shallow fetch into the project's own repository.** `.git/shallow` appears or `git rev-parse --is-shallow-repository` prints true: use only the separate bare repository.
8. **Null switch sections.** `'spec': must be a mapping (got NoneType)` means the null normalisation was skipped.
9. **No project words.** `tests/core/test_no_project_words.py` bans words such as the test runner's name in `src/`. The owner-mandated default `docs.website.links` contains it, so p1 exempts that exact literal in `defaults.py` only. Org names live in `docs/` and tests, never in `src/`, `cli/`, `adapters/` or `playbooks/`.
10. **Different answers by mode.** File-checked defaults give different results for `--no-file-checks`, a scratch profile and the repository root. Always pass `--ref` or `--root`.
11. **tkcs-lab/.github** is not anonymously readable. If the owner keeps it private, sessions of tkcs-lab repositories cannot fetch the base and the loader stops with the fetch error; that is the safe failure. Making it public is a decision for the owner: the base must hold no secret (the token check enforces it), but the roles and guard settings become visible.
12. **`dod_gate` on by default** makes an unattended editing session run `verify.dod` at stop; a repository with a slow gate gets slower sessions. Its `max_attempts` of 3 bounds it.
13. **Evals prove wiring, not behaviour.** A stub run proves only that the canned outcome matches the task; the two new setup tasks and the migrate task have not been run against a real model (that costs money and needs network). The one-batch rule is proved by the grader unit tests and the code tests; run `python3 evals/run.py run --task setup-extends-base --repeats 1 --run-ceiling 1.5` once after the last merge if you want the real check.
14. **Scenario names kept.** The spec's plan-gate scenario "Off by default" keeps its name (OpenSpec refuses to drop a scenario from a modified requirement) while its text now describes `enabled: false`; the unchanged guard, gate and summary scenarios are proved by the existing test files that the owning phases run unchanged (3.13).
15. **Open question for the owner, answered by default:** `roles.posture.security: critical` in the base and no `code-reviewer`; change section 3.8 before ma1 if wanted.

## Implementation manifest

```yaml
plan_slug: org-base-profile
feature_branch: feature/org-base-profile
tracking_issue: 90
spec_change: org-base-profile
sysml_change: org-base-profile
max_parallel: 3
manual_before: []
manual_after:
  - id: ma1-create-base
    title: Create the base file in each org's .github repository, check it and tag it
    why: Repositories extend it by commit; a phase cannot create files in another organisation's repository.
  - id: ma2-git-ops
    title: Create the git-ops environment and the GIT_OPS_TOKEN secret in each org's git-ops repository
    why: The audit cannot create secrets or environments.
  - id: ma3-release-and-pins
    title: After the pull request merges, release 1.7.0 and bump each repository's pin
    why: Pins need a released tld and the base commit from ma1.
verify_after_merge:
  - .venv/bin/python -m pytest -q
  - .venv/bin/python cli/tld ops docs-index check
  - .venv/bin/python cli/tld profile validate
final_checks:
  - "`tld plan deviations check --file docs/plans/90/deviations.md --plan docs/plans/90/plan.md --all` exits 0"
  - "the changelog has entries under ## [Unreleased] and no new version heading above ## [1.6.0]"
  - "`tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
  - "`tld ops spec validate --profile .tld/toolkit.yaml` exits 0 and `openspec/changes/org-base-profile` does not exist"
  - "`tld ops sysml render --check --profile .tld/toolkit.yaml` and `tld ops sysml check --profile .tld/toolkit.yaml` exit 0 and `sysml/changes/org-base-profile` does not exist"
  - "`python3 evals/run.py check-baseline` exits 0"
phases:
  - id: p1-defaults-merge
    title: Defaults table and merge rules (pure modules)
    depends_on: []
    complexity: M
    touches:
      - src/tld/profile/defaults.py
      - src/tld/profile/merge.py
      - tests/core/test_profile_defaults.py
      - tests/core/test_profile_merge.py
      - tests/core/test_no_project_words.py
    brief: |
      Read first: docs/reference/profile-reference.md, docs/plans/90/plan.md (sections 3.1, 3.4 and 3.13), src/tld/guard/_common.py (lines 20-35), src/tld/profile/validate.py.
      1. Create src/tld/profile/defaults.py (stdlib only, no I/O, no import from tld.guard at module level): constants STATIC, SECTION_DEFAULTS, FILE_CHECKED, OFF_SWITCHES, SWITCH_SECTIONS = ("deps", "spec", "sysml") with exactly the values of section 3.1; a dataclass Env with fields exists (callable taking a repo-relative path and returning bool, or None), read (callable returning text or None, or None), origin_owner (str or None) and main_branch (str or None); and apply(profile: dict, env: Env) -> tuple[dict, dict[str, str]] returning the resolved dict and a map from dotted key to its source text (`repo`, `default`, `default (<path> exists)`, `detected (origin/HEAD)`, `off (false)`, `not applied (no root)`).
      2. apply rules, in order: an off switch the profile writes as false is applied first, deletes its key and every default that depends on it (admin stops admin.policy; docs.adr_dir stops adr_index and adr_bar; docs.changelog stops the changelog default); a key the profile writes wins over a default; SECTION_DEFAULTS apply only to a section present in the profile (an empty section, None, counts as present and becomes a mapping); a FILE_CHECKED value applies only when env.exists is not None and says the path exists; docs.adr_bar applies only when docs.adr_dir was applied and env.read("CONTRIBUTING.md") has a line equal to `## Decisions, plans and ADRs`; docs.plan_dir is `docs/plans` when env.exists("docs/plans") else `docs` (and `docs` when env.exists is None), without a trailing slash; git.main_branch comes from env.main_branch; git_ops.repo is `<env.origin_owner>/git-ops` only when origin_owner is set and git_ops is not false; docs.website uses dir `.`.
      3. The docs.website links default is the literal `python3 -m pytest tests/unit/test_website_links.py -q`. In tests/core/test_no_project_words.py remove exactly that string from the text of src/tld/profile/defaults.py before the scan, for that one file only, with a comment saying the owner mandated the literal.
      4. Create src/tld/profile/merge.py (pure; import tld.guard._common.HOOK_NAMES only inside a function): merge(base: dict, repo: dict, allow: list[str] = ()) -> tuple[dict, dict[str, str]] implementing section 3.4 (deep merge; scalars and lists replace; verify.dod_manual appended without duplicates; roles.required merged by role with at union, blocking OR, when union, a repository `when` on a base entry without one dropped with the warning text of 3.4, repository-only roles appended; a role the repository lists in roles.disable loses its base entry only when `roles.required.<role>` is in allow); POSTURE_RANK; OVERRIDE_RE accepting exactly hooks.disable.<hook name>, hooks.protect_paths, hooks.protect_paths_allow, hooks.dod_gate.enabled, hooks.plan_gate.enabled, hooks.board_gate.enabled, roles.posture.security and roles.required.<role>; guarded_errors(floor: dict, merged: dict, allow: list[str], label: str) -> list[str] with the six error texts of 3.4 (label is `<source>@<sha7>`, "tld's default list" when the floor has no protect_paths); clamp(trusted: dict, merged: dict, branch: str) -> tuple[dict, list[str]] with exactly the per-key rules of 3.4 and the warning text of 3.4 per changed key.
      5. Tests: tests/core/test_profile_defaults.py and tests/core/test_profile_merge.py contain every test named in this phase's acceptance (names follow 3.13; the extra names are written out). The fixture dicts are built inline.
      6. Do not edit validate.py or any existing module except tests/core/test_no_project_words.py. Stop with status=blocked if importing tld.guard._common inside a function is not enough to read HOOK_NAMES.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_profile_merge.py::test_repository_overrides_a_scalar tests/core/test_profile_merge.py::test_lists_replace tests/core/test_profile_merge.py::test_required_roles_merge_by_role tests/core/test_profile_merge.py::test_manual_rows_append tests/core/test_profile_merge.py::test_hook_disable_refused tests/core/test_profile_merge.py::test_weaker_posture_refused tests/core/test_profile_merge.py::test_required_role_dropped tests/core/test_profile_merge.py::test_protect_list_widened tests/core/test_profile_merge.py::test_gate_switched_off tests/core/test_profile_merge.py::test_allowed_by_the_base tests/core/test_profile_merge.py::test_strengthening_allowed tests/core/test_profile_merge.py::test_no_extends_refuses_nothing tests/core/test_profile_merge.py::test_protect_paths_floor_is_tlds_default_list_when_base_omits_it tests/core/test_profile_merge.py::test_repo_cannot_unset_base_blocking tests/core/test_profile_merge.py::test_repo_when_on_base_entry_without_when_is_ignored_with_warning tests/core/test_profile_merge.py::test_override_re_rejects_unknown_names tests/core/test_profile_merge.py::test_allowed_role_drop_removes_the_base_entry tests/core/test_profile_merge.py::test_clamp_does_not_add_a_branch_disable tests/core/test_profile_merge.py::test_clamp_gate_false_on_branch_stays_on tests/core/test_profile_merge.py::test_clamp_posture_takes_higher_rank tests/core/test_profile_merge.py::test_clamp_protect_paths_union tests/core/test_profile_merge.py::test_clamp_protect_paths_allow_intersection tests/core/test_profile_merge.py::test_clamp_keeps_floor_required_role_blocking_and_points tests/core/test_profile_merge.py::test_clamp_drops_roles_disable_of_a_floor_role tests/core/test_profile_merge.py::test_clamp_warning_text -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_profile_defaults.py::test_static_defaults tests/core/test_profile_defaults.py::test_git_ops_repository tests/core/test_profile_defaults.py::test_plan_directory_of_an_existing_repository tests/core/test_profile_defaults.py::test_empty_section_turns_the_feature_on tests/core/test_profile_defaults.py::test_file_checked_defaults tests/core/test_profile_defaults.py::test_website_default tests/core/test_profile_defaults.py::test_turned_off_with_false tests/core/test_profile_defaults.py::test_plan_dir_without_root tests/core/test_profile_defaults.py::test_off_switch_stops_dependent_defaults -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_no_project_words.py::test_exemption_removes_only_the_mandated_literal -q exits 0 and the whole of tests/core/test_no_project_words.py passes"
  - id: p2-base-fetch
    title: Base fetch, cache and check, with the profile base commands
    depends_on: []
    complexity: M
    touches:
      - src/tld/profile/base.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_profile_base.py
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.2, 3.3 and 3.13), src/tld/guard/trust.py, src/tld/guard/secret_scan.py (lines 82-137: secret_like_name, ALLOW_MARK, scan_text with its keyword-only skip_marked), src/tld/cli.py (lines 10-30), docs/reference/cli.md.
      1. Create src/tld/profile/base.py: BaseRef (owner, repo, path, sha), SOURCE_RE, parse_extends(value) -> BaseRef raising BaseError with the two error texts of 3.2; BASE_KEYS and check_base_text(text, label) -> tuple[dict | None, list[str]] with the checks and error texts of 3.3 (size, UTF-8 and BOM, anchors or aliases through yaml.parse events, mapping on top, depth 8, no tld.extends, allowed keys only, token check: run tld.guard.secret_scan.scan_text(text, skip_marked=False) (keyword) so a marked line is still refused, and refuse any mapping key for which secret_like_name is true; no error text ever contains the offending value).
      2. Cache and fetch as 3.2 says: cache_key, cached(git_dir, ref) -> str | None (verifies sha256), fetch(project, ref, timeout=20.0, runner=None) -> str writing the cache atomically under `git rev-parse --git-common-dir`/tld/base; runner is an injectable callable (args, env, timeout) -> (returncode, stdout, stderr) defaulting to subprocess; url_for(ref) builds `https://github.com/<owner>/<repo>.git` and is a module-level function so tests can replace it. Reuse the safe git options and environment of src/tld/guard/trust.py by importing them (private names included); never copy them.
      3. latest_pin(source, runner=None) -> tuple[str, str | None] as 3.2 says (tags matching ^v?\d+(\.\d+)*$ sorted by numeric components, so v10 is after v9; the path must exist at the tag's commit, checked by fetching it; the newest tag without the file is skipped; otherwise the default branch head and None).
      4. main(argv) with sub-commands `check FILE` (prints `base: OK` and exits 0, or the refusal lines on stderr and exit 1), `fetch [PROFILE]` (default .tld/toolkit.yaml; prints the source and sha7 when cached or fetched; prints `no base` and exits 0 when the profile has no extends) and `latest SOURCE` (prints the JSON of 3.2).
      5. Register ("profile", "base") in COMMANDS of src/tld/cli.py with module tld.profile.base and a one-line description; add its rows to docs/reference/cli.md next to the other `tld profile` rows.
      6. Tests in tests/core/test_profile_base.py with a local bare repository as the origin (build it with git in a tmp_path and replace url_for); every test named in this phase's acceptance. No network in tests.
      7. Stop with status=blocked if scan_text cannot be imported without importing a module that imports tld.profile.resolve (it does not exist yet; the import must stay clean).
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_profile_base.py::test_valid_pin tests/core/test_profile_base.py::test_not_a_commit tests/core/test_profile_base.py::test_malformed_source tests/core/test_profile_base.py::test_base_chains_refused tests/core/test_profile_base.py::test_first_fetch_is_cached tests/core/test_profile_base.py::test_offline_after_caching tests/core/test_profile_base.py::test_fetch_fails_without_a_cache tests/core/test_profile_base.py::test_corrupt_cache_entry tests/core/test_profile_base.py::test_latest_pin tests/core/test_profile_base.py::test_latest_without_tags tests/core/test_profile_base.py::test_check_a_base_file tests/core/test_profile_base.py::test_token_like_text tests/core/test_profile_base.py::test_anchors_and_size tests/core/test_profile_base.py::test_key_a_base_may_not_set tests/core/test_profile_base.py::test_fetch_leaves_the_project_repository_unshallow tests/core/test_profile_base.py::test_token_refusal_does_not_print_the_value tests/core/test_profile_base.py::test_secret_like_key_refused_whatever_value tests/core/test_profile_base.py::test_url_for_builds_github_url tests/core/test_profile_base.py::test_latest_pin_skips_newest_tag_without_file tests/core/test_profile_base.py::test_latest_pin_sorts_numerically tests/core/test_profile_base.py::test_base_check_cli_prints_ok tests/core/test_profile_base.py::test_cache_is_shared_by_linked_worktrees -q exits 0"
      - ".venv/bin/python cli/tld profile base --help exits 0 and names check, fetch and latest, and tests/core/test_contracts.py passes"
      - "grep -n 'def parse_extends' src/tld/profile/base.py and grep -n 'def fetch' src/tld/profile/base.py each print one line (the ProfileBase part of the architecture change exists)"
  - id: p3-schema-validate
    title: Schema keys for extends and off switches, raw shape check, null sections
    depends_on: []
    complexity: S
    touches:
      - src/tld/schema/profile.schema.json
      - src/tld/profile/validate.py
      - tests/core/test_validate_profile.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.1 and 3.13), src/tld/profile/validate.py, src/tld/schema/profile.schema.json, tests/mutation/mutants.yaml (VP1 to VP4 and VP6 to VP17 are the validate.py mutants; VP18 is the first free id), tests/core/test_mutants_file.py.
      1. In src/tld/schema/profile.schema.json add under `tld`: `extends` (a non-empty string; no pattern, parse_extends reports the error text) and `allow_override` (array of non-empty strings). Wrap docs.index, docs.adr_dir, docs.changelog, docs.website, admin, git_ops and land.max_prs as `oneOf` of their existing schema and `{"const": false}`; keep every existing `required` array unchanged (the strict check runs on the resolved profile).
      2. In src/tld/profile/validate.py add the trailing keyword parameter `required: bool = True` to check() and pass it through the recursion (src/tld/ops/repo_admin.py calls `check(policy, schema, schema, "", errors)` positionally and must keep working): with False the `missing required key` errors are skipped (types, enums and unknown keys are still checked), and add normalise(profile: dict) -> dict returning a copy where deps, spec and sysml set to None become {}; call normalise at the start of validate() before check().
      3. Teach validate() that a `false` off switch is absent: delete False off-switch keys right after the shape check (a temporary rule that p4 replaces), so semantic_checks never sees False where it expects a mapping.
      4. Tests in tests/core/test_validate_profile.py as named in the acceptance.
      5. Add exactly two mutants to tests/mutation/mutants.yaml with the ids VP18 (the `required` parameter: an inverted condition) and VP19 (normalise: None left as None), each with its test file under `tests:`; keep every existing mutant's `old` text matching.
      6. Stop with status=blocked if a validate.py mutant's `old` text cannot be kept with its meaning; report which one.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_validate_profile.py::test_an_empty_spec_block_validates tests/core/test_validate_profile.py::test_docs_changelog_false_validates_and_resolves_without_the_key tests/core/test_validate_profile.py::test_tld_extends_passes_the_shape_check_as_a_string tests/core/test_validate_profile.py::test_check_without_required_skips_missing_keys_but_reports_unknown_keys -q exits 0 and the whole file passes"
      - ".venv/bin/python -m pytest tests/core/test_mutants_file.py -q exits 0 and .venv/bin/python tests/mutation/run_mutants.py --only VP18 VP19 exits 0"
      - ".venv/bin/python cli/tld profile validate .tld/toolkit.yaml exits 0"
  - id: p4-resolve
    title: The resolver, validate --resolved --explain --ref, and mutants for the new modules
    depends_on: [p1-defaults-merge, p2-base-fetch, p3-schema-validate]
    complexity: M
    touches:
      - src/tld/profile/resolve.py
      - src/tld/profile/validate.py
      - docs/reference/cli.md
      - tests/core/test_profile_resolve.py
      - tests/core/test_profile_defaults.py
      - tests/core/test_validate_profile.py
      - tests/core/test_mutants_file.py
      - tests/adapters/claude/test_hooks_config.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.1 to 3.4 and 3.13), src/tld/profile/validate.py, src/tld/profile/defaults.py, src/tld/profile/merge.py, src/tld/profile/base.py, src/tld/guard/trust.py (lines 191-215), tests/adapters/claude/test_hooks_config.py (lines 129-143, the stdlib-only test, and 190-210).
      1. Create src/tld/profile/resolve.py with the dataclass Resolved (profile, sources, errors, warnings, base), the pure resolve(raw, *, base, base_ref, trusted, trusted_branch, env) -> Resolved implementing the "Load order" of 3.1 (parse_extends first, then the shape check, merge, defaults.apply, guarded_errors against the guard floor, clamp against `trusted`, the strict schema check, semantic_checks), load(path, *, ref=None, root=None, fetch=True, trusted=True, file_checks=True) -> Resolved (reads the YAML or `git show <ref>:.tld/toolkit.yaml`, builds the Env from the root or from the tree of the ref with one `git ls-tree --name-only` call, gets the base through tld.profile.base, and with trusted=True and an origin builds `trusted` by resolving the default branch's profile from tld.guard.trust.trusted(project) (imported inside load only) with its own tld.extends read from the cache only and an Env that reads files at the trusted commit), and for_hook(raw, project, *, at_sha=None) -> tuple[dict | None, str | None] (cache only, never raises, never fetches, never reads the schema file; returns the resolved dict and a notice).
      2. src/tld/profile/validate.py: keep check, semantic_checks and apply_defaults; ADD the keyword `fetch=True` to validate(profile, root_dir=None, *, fetch=True) and make it a wrapper over resolve; main() gains `--explain` (print `<dotted key> = <json value>  # <source>` sorted, as in 3.1) and `--ref REF`; `--resolved` prints the whole resolved profile (hooks included, docs.plan_dir without a trailing slash) and the stderr note of 3.1; the OK line is unchanged; the missing-main-branch error is the text of 3.6. Remove the temporary False-deletion of p3 step 3.
      3. Update docs/reference/cli.md: the `tld profile validate` row names --resolved, --explain and --ref.
      4. Tests: every test named in this phase's acceptance. The clamp integration tests build a tmp origin repository (a bare repo plus a clone): main has critical posture, a required role and gates on; the branch weakens them; the test runs `tld profile validate --resolved` in a subprocess and asserts on stdout, stderr and the exit code. tests/core/test_profile_defaults.py gets test_schema_defaults_equal_the_table. tests/adapters/claude/test_hooks_config.py: invert test_resolved_profile_is_unchanged_by_the_hooks_section into test_resolved_profile_includes_the_hooks_defaults and extend the stdlib-only test (test_scripts_are_small_stdlib_plus_pyyaml_python_311_without_network, lines 129-143; it forbids the socket and http modules and asserts each file stays under 480 lines) to src/tld/profile/{resolve,defaults,merge,base}.py, and keep each of those files under 480 lines.
      5. tests/core/test_mutants_file.py: add `src/tld/profile/merge.py`, `src/tld/profile/resolve.py`, `src/tld/profile/base.py` and `src/tld/profile/defaults.py` to MODULES. tests/mutation/mutants.yaml: add the mutants MG1, MG2, MG3 (merge.py: the posture comparison, the gate floor, the protect_paths_allow intersection), RS1, RS2 (resolve.py: the clamp call, the guarded_errors call) and BS1 (base.py: the SHA length) with their test files under `tests:`; keep the existing mutants' `old` text matching (update VP texts here only if p3 left one stale).
      6. Stop with status=blocked if tld.guard.trust must be imported at module level in resolve.py for a test; it stays inside load.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_profile_resolve.py::test_valid_minimal_profile tests/core/test_profile_resolve.py::test_missing_required_key tests/core/test_profile_resolve.py::test_unknown_key_and_wrong_type tests/core/test_profile_resolve.py::test_no_file_or_bad_yaml tests/core/test_profile_resolve.py::test_old_profile_without_extends tests/core/test_profile_resolve.py::test_explained_output tests/core/test_profile_resolve.py::test_resolved_at_a_ref tests/core/test_profile_resolve.py::test_repository_sets_allow_override tests/core/test_profile_resolve.py::test_release_version_files_stay_required tests/core/test_profile_resolve.py::test_merged_bot_as_code_owner tests/core/test_profile_resolve.py::test_resolved_output_plan_dir_default tests/core/test_profile_resolve.py::test_resolved_plan_dir_strips_trailing_slash tests/core/test_profile_resolve.py::test_validate_rejects_a_tag_pin_with_the_commit_message tests/core/test_profile_resolve.py::test_validate_rejects_a_malformed_source tests/core/test_profile_resolve.py::test_validate_rejects_an_uppercase_hex_pin tests/core/test_profile_resolve.py::test_branch_weakening_is_clamped_to_main tests/core/test_profile_resolve.py::test_branch_repointing_extends_is_clamped_to_main_base tests/core/test_profile_resolve.py::test_branch_removing_extends_is_clamped tests/core/test_profile_resolve.py::test_no_origin_warns_no_trusted_copy tests/core/test_profile_resolve.py::test_trusted_base_not_cached_ignores_allow_override tests/core/test_profile_resolve.py::test_for_hook_never_runs_git_fetch tests/core/test_profile_resolve.py::test_for_hook_does_not_read_the_schema tests/core/test_profile_resolve.py::test_for_hook_never_raises tests/core/test_profile_resolve.py::test_validate_with_unreachable_origin_warns_and_exits_0 tests/core/test_profile_resolve.py::test_missing_main_branch_message tests/core/test_profile_resolve.py::test_old_profile_without_extends_keeps_every_value -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_profile_defaults.py::test_schema_defaults_equal_the_table -q exits 0 and .venv/bin/python -m pytest tests/adapters/claude/test_hooks_config.py::test_resolved_profile_includes_the_hooks_defaults -q exits 0"
      - ".venv/bin/python -m pytest tests -q exits 0, and .venv/bin/python tests/mutation/run_mutants.py --only MG1 MG2 MG3 RS1 RS2 BS1 exits 0"
      - "grep -n 'tld.profile.base' src/tld/profile/resolve.py prints a line (the Profile to ProfileBase dependency exists)"
  - id: p5-hooks
    title: Hooks read the resolved profile; gates on; new protect defaults; trusted clamp
    depends_on: [p4-resolve]
    complexity: M
    touches:
      - src/tld/guard/_common.py
      - src/tld/guard/trust.py
      - src/tld/guard/plan_gate.py
      - src/tld/guard/board_gate.py
      - src/tld/guard/protect_paths.py
      - src/tld/dod/gate.py
      - src/tld/schema/profile.schema.json
      - src/tld/templates/toolkit.yaml
      - tests/hooks_helpers.py
      - tests/core/test_hook_plan_gate.py
      - tests/core/test_hook_board_gate.py
      - tests/core/test_hook_dod_gate.py
      - tests/core/test_hook_protect_paths.py
      - tests/core/test_hook_protect_paths_setup.py
      - tests/core/test_guard_trust.py
      - tests/core/test_guard_markers.py
      - tests/core/test_guard_mutations.py
      - tests/core/test_quick_guard.py
      - tests/adapters/claude/test_hook_board_gate_adapter.py
      - tests/adapters/claude/test_hooks_prompt.py
      - tests/core/guard_cases.yaml
      - tests/adapters/claude/test_hooks_config.py
      - evals/adapters/claude/hook_cases.yaml
      - evals/fixtures/tiny_app.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.2, 3.4, 3.5 and 3.13), docs/architecture/hooks.md (lines 182-300 and 400-440), src/tld/guard/_common.py, src/tld/guard/trust.py, src/tld/guard/protect_paths.py, src/tld/dod/gate.py (lines 125-145 and 205-230), tests/hooks_helpers.py (line 37).
      1. src/tld/guard/_common.py: DEFAULT_PROTECT_PATHS becomes [".env", ".env.*", "*.lock", "package-lock.json", "go.sum"]; make_ctx sets ctx.profile from tld.profile.resolve.for_hook(raw, project) (import it inside make_ctx) and ctx.notice from its notice; Ctx.trusted() keeps its return shape (a profile dict or None, and the available flag) but the dict is now for_hook(raw, project, at_sha=sha)[0] of the trusted copy; keep the "hooks section differs" notice comparing the raw sections; GUARDED_WORKFLOWS stays and a new function guarded_workflows(ctx) returns it plus `.github/workflows/<trusted resolved release.workflow>` plus `.github/workflows/tld-git-ops.yml`.
      2. For every guarded key a hook takes the stricter of the working copy and the trusted resolved profile, with the rules of `clamp` in 3.4 (gates: trusted OR working copy; hooks.disable: the trusted list only, as today) and shows the clamp notice.
      3. src/tld/guard/plan_gate.py, board_gate.py and src/tld/dod/gate.py read the gate from the resolved profile: enabled unless the resolved value is false; with no profile at all the gates stay off.
      4. src/tld/guard/protect_paths.py: replace every use of GUARDED_WORKFLOWS by guarded_workflows(ctx); the deny hint for the profile and ordinary workflows is removed from the default message. `tld guard allow-profile` and its marker (src/tld/guard/markers.py) are not changed.
      5. Update tests/adapters/claude/test_hooks_config.py::test_schema_defaults_equal_the_hooks_built_in_defaults (lines 159-163, which asserts the three gates default False) and test_template_documents_the_defaults_and_stays_valid (line 176, `dod_gate enabled is False`) to the new defaults, and the module docstrings of src/tld/guard/plan_gate.py, board_gate.py and src/tld/dod/gate.py that still say "Opt-in". Update the x-hook-default values in src/tld/schema/profile.schema.json and the commented hooks block in src/tld/templates/toolkit.yaml (lines 136-152) to the new defaults: gates on, the protect list of 3.1, every hook name in `disable`; replace the sentence "all hooks but dod-gate are on" by "all hooks are on by default".
      6. Tests: tests/hooks_helpers.py keeps `PROFILE` without a hooks block and adds `PROFILE_GATES_OFF` (PROFILE plus a hooks block with the three gates `enabled: false`); about 15 tests (test_quick_guard.py line 9, test_hook_plan_gate.py line 13, test_hook_board_gate.py line 13, test_hook_board_gate_adapter.py line 9, test_hooks_prompt.py line 107, test_guard_trust.py lines 13 and 15) concatenate `PROFILE + "hooks:\n  plan_gate: ..."`, so a hooks block inside PROFILE would duplicate the top-level key and PyYAML would silently keep the last one; every existing test that fails only because a gate is now on switches to PROFILE_GATES_OFF (never edit an assertion); the profile of evals/fixtures/tiny_app.py gets the gates-off hooks block appended at its end (evals/fixtures/deps_combine.py, release_gate.py and commands.py build on tiny_app.PROFILE and tests/core/test_evals_fixtures.py validates them, so check that no `hooks:` key is duplicated). Invert and rename the three existing default-off tests as in the acceptance (test_on_by_default_denies_a_plain_write, test_the_hook_is_on_by_default, test_on_by_default_blocks_a_failing_stop) and add the other named tests, each building its own profile without a hooks block. Update the expectations of tests/core/test_hook_protect_paths_setup.py, test_guard_markers.py and test_guard_mutations.py that say the profile or ordinary workflows are denied (change only those expectations). Add to tests/core/guard_cases.yaml the rows that a write (Write tool and Bash redirect) to `.git/tld/base/<key>.yaml` and `.json` is denied, and to evals/adapters/claude/hook_cases.yaml only two cases: editing `.tld/toolkit.yaml` is allowed and editing `.github/workflows/tld-git-ops.yml` is denied (write a token-shaped string as @@GH_TOKEN@@ if one is needed).
      7. tests/mutation/mutants.yaml: add the mutants CL1 (guarded_workflows drops the release workflow) and CL2 (the gate clamp uses the working copy only), each with its tests; keep every existing mutant's `old` text matching.
      8. Do not edit docs/architecture/hooks.md (p14 does). Say in the commit message why the guardrail eval pass rates are not affected (tiny_app keeps the gates off). Stop with status=blocked if a hook test needs network access, or passes only because it takes more than 15 seconds.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_hook_plan_gate.py::test_on_by_default_denies_a_plain_write tests/core/test_hook_plan_gate.py::test_switched_off_allows_all_writes tests/core/test_hook_plan_gate.py::test_no_profile_allows_everything -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_hook_board_gate.py::test_the_hook_is_on_by_default tests/core/test_hook_board_gate.py::test_switched_off_never_blocks tests/core/test_hook_board_gate.py::test_no_profile_allows_everything -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_hook_dod_gate.py::test_on_by_default_blocks_a_failing_stop tests/core/test_hook_dod_gate.py::test_switched_off_runs_nothing tests/core/test_hook_dod_gate.py::test_no_profile_allows_everything -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_hook_protect_paths.py::test_default_protected_paths_are_the_new_list tests/core/test_hook_protect_paths.py::test_edit_of_the_profile_is_allowed_by_default tests/core/test_hook_protect_paths.py::test_edit_of_an_ordinary_workflow_is_allowed_by_default tests/core/test_hook_protect_paths.py::test_release_workflow_of_the_trusted_profile_is_denied tests/core/test_hook_protect_paths.py::test_git_ops_workflow_is_denied tests/core/test_hook_protect_paths.py::test_release_workflow_guard_uses_trusted_value -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_guard_trust.py::test_gate_switched_off_on_a_branch_stays_on tests/core/test_guard_trust.py::test_base_not_cached_in_a_hook -q exits 0 and tests/core/test_quick_guard.py, tests/adapters/claude/test_hook_board_gate_adapter.py and tests/adapters/claude/test_hooks_prompt.py pass, and .venv/bin/python -m pytest tests/adapters/claude/test_hooks_config.py::test_schema_defaults_equal_the_hooks_built_in_defaults -q exits 0"
      - ".venv/bin/python -m pytest tests -q exits 0, .venv/bin/python tests/mutation/run_mutants.py --only CL1 CL2 exits 0 and python3 evals/run.py run --agent stub --repeats 1 --require-pass exits 0"
      - "grep -n 'tld.profile.resolve' src/tld/guard/_common.py prints a line (the Guard to Profile dependency exists)"
  - id: p6-summary-protect-playbooks
    title: Mechanical Security rule and the protect-flow playbooks
    depends_on: [p4-resolve, p5-hooks]
    complexity: M
    touches:
      - src/tld/plan/summary.py
      - tests/core/test_plan_summary.py
      - tests/core/test_summary_placement.py
      - tests/mutation/mutants.yaml
      - docs/reference/cli.md
      - playbooks/policies/protected-changes.md
      - playbooks/policies/pr-steward.md
      - playbooks/implement.md
      - playbooks/make-plan.md
      - playbooks/quick.md
      - tests/core/test_protected_changes.py
      - tests/core/test_implement_protected.py
      - tests/core/test_quick_playbook.py
      - tests/adapters/claude/test_hooks_compat.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.5 and 3.13), src/tld/plan/summary.py (lines 174-296: check, read, main), playbooks/policies/protected-changes.md (lines 7-21 and 85-89), playbooks/implement.md (lines 173-181, 251-263, 366-381, 444-456), playbooks/make-plan.md (lines 373-374), playbooks/quick.md (lines 59-63, 80-83, 109-122), tests/core/test_summary_placement.py (lines 100-165), tests/core/test_protected_changes.py, tests/core/test_implement_protected.py.
      1. src/tld/plan/summary.py: add the option `--changed FILE` next to `--findings` (a file with one repository-relative path per line; blank lines and carriage returns ignored; with a kind other than pr, `ap.error(...)` exits 2 like `--findings`; read it with the existing `read()` so an unreadable file prints one `summary:` line and exits 1), add `changed: list[str] | None = None` as a new trailing keyword of `check(text, kind, deviations_text=None, findings=None, changed=None)` (callers `tld/plan/handover.py` and `tests/core/test_roles_section.py` pass at most the first three), and run the Security test after `values` is built and before the `kind == "pr"` findings block so the problem order of `test_placement_label_and_word_problems_come_in_the_order_of_the_design` stays true; update the module docstring; the check of 3.5 with SECURITY_PATHS = (".github/workflows/", ".tld/toolkit.yaml") (a path counts when it starts with the prefix or equals the profile path, so `.github/workflows-old/x` does not count); a path counts as named when its full path appears in the Security label's text or its file name appears as a whole word (so `aci.yml` does not name `ci.yml`); stdlib only; the two problem texts of 3.5.
      2. playbooks/implement.md: at the pull request step (the check call at line 453, `tld plan summary-check <body file> --kind pr --deviations <deviations path> --findings <N>`), write the changed paths (`git diff --name-only --no-renames origin/<main>...HEAD`, with only placeholders that tests/adapters/claude/test_hooks_compat.py PLACEHOLDERS knows) to a scratch file and pass it as `--changed <changed list>`; add the final-review rule of 3.5 to Section 5's final-reviewer brief (lines 366-381, not to Finishing, so quick inherits it); keep "a lockfile in the diff is blocking"; add to the Summary rule that every workflow or profile file the diff changes is named under Security.
      3. playbooks/policies/protected-changes.md: rewrite "What is protected" (lines 7-15; the default list of 3.1 without the profile and workflows; keep "The deps exception" (lines 17-21) and reword "another protected path" there so it does not imply workflows are on the default list; the flow still handles any path a repository or base adds back; always outside the flow: the land, release and git-ops workflows, the repository's release workflow, `.git/**` and the adapter's paths) and "Main's profile only" (read it with `tld profile validate --ref origin/<main> --resolved`). Keep the apply-not-recommended rule for a workflow or profile diff.
      4. playbooks/make-plan.md lines 373-374: a phase never lists a protected path in `touches`; add that the profile and ordinary workflows may be listed and the brief then says the pull request names them under Security. playbooks/policies/pr-steward.md: add the general rule (a pull request that changes a workflow or the profile names it under a Security heading).
      5. playbooks/quick.md: pass `--changed <changed list>` in its one pull request check (line 121), say that a pull request changing a workflow or the profile names it under Security, and reword the size check (lines 61-63) and the protected-path lines so the profile and ordinary workflows are no longer called protected by default. tests/core/test_summary_placement.py: its parametrised call test maps placeholders in order; teach it the `<changed list>` placeholder (write an empty list file) so every playbook call still passes. Update the sentence pins in tests/core/test_protected_changes.py, tests/core/test_implement_protected.py and tests/core/test_quick_playbook.py to the new text (change the expected strings only), add `--changed` to the option test `test_cli_help_lists_the_options` (tests/core/test_plan_summary.py line 645), update the summary-check row of docs/reference/cli.md (line 33), and add the tests named in the acceptance. tests/mutation/mutants.yaml: add SC1 (the prefix check) and SC2 (the file-name match) for summary.py; keep every existing mutant's `old` text matching.
      6. Refresh the eval baseline: run `.venv/bin/python evals/run.py run --agent stub --repeats 1 --require-pass`, then `.venv/bin/python evals/run.py baseline --refresh-hashes`, and say in the commit message that the playbooks changed only in protect-flow wording and why the make-plan, review and quick pass rates are unaffected.
      7. Stop with status=blocked if tests/core/test_contracts.py fails because `--changed` or `--ref` is not in the real CLI help, or if a mutant SM1 to SM16 of summary.py stops applying and you cannot keep its `old` text.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_plan_summary.py::test_changed_workflow_or_profile_not_named tests/core/test_plan_summary.py::test_changed_missing_security_label tests/core/test_plan_summary.py::test_changed_none_security tests/core/test_plan_summary.py::test_changed_named_by_full_path tests/core/test_plan_summary.py::test_changed_named_by_file_name tests/core/test_plan_summary.py::test_changed_substring_does_not_count tests/core/test_plan_summary.py::test_changed_workflows_old_dir_is_not_a_workflow tests/core/test_plan_summary.py::test_changed_blank_and_crlf_lines tests/core/test_plan_summary.py::test_changed_unreadable_file tests/core/test_plan_summary.py::test_changed_with_kind_plan_exits_2 -q exits 0 and the whole file passes"
      - ".venv/bin/python -m pytest tests/core/test_implement_protected.py::test_implement_pr_step_passes_changed -q exits 0 and tests/core/test_protected_changes.py, tests/core/test_contracts.py and tests/core/test_evals_baseline.py pass"
      - ".venv/bin/python tests/mutation/run_mutants.py --only SC1 SC2 exits 0 and .venv/bin/python -m pytest tests/core/test_mutants_file.py -q exits 0"
      - "python3 evals/run.py check-baseline exits 0"
  - id: p7-cli-readers
    title: Plan, roles, board, docs-index, spec, sysml and release read the resolved profile
    depends_on: [p4-resolve, p5-hooks]
    complexity: M
    touches:
      - src/tld/roles/dispatch.py
      - src/tld/plan/manifest.py
      - src/tld/plan/scope.py
      - src/tld/board/inbox.py
      - src/tld/ops/docs_index.py
      - src/tld/ops/spec.py
      - src/tld/ops/sysml.py
      - src/tld/ops/release_prepare.py
      - src/tld/ops/deps_prepare.py
      - tests/core/test_ops_deps_prepare.py
      - tests/core/test_roles_dispatch.py
      - tests/core/test_validate_manifest.py
      - tests/core/test_scope_check.py
      - tests/core/test_board_inbox.py
      - tests/core/test_docs_index.py
      - tests/core/test_ops_spec.py
      - tests/core/test_ops_sysml.py
      - tests/core/test_release_prepare.py
      - tests/core/test_minimal_profile.py
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.1, 3.6 and 3.13), src/tld/profile/resolve.py, src/tld/plan/manifest.py (lines 255-280 and 440-470), src/tld/ops/spec.py (lines 85-105), src/tld/ops/sysml.py (lines 75-92), src/tld/roles/dispatch.py (lines 115-160).
      1. Each reader below loads through tld.profile.resolve.load instead of yaml.safe_load (arguments in brackets): src/tld/roles/dispatch.py _load_profile (a path: load(fetch=False); a profile on standard input: the pure resolve() with no `trusted`), src/tld/plan/manifest.py main (trusted=False, fetch=False), src/tld/plan/scope.py load_ignore (trusted=False, fetch=False), src/tld/board/inbox.py owner_login (trusted=False, fetch=False), src/tld/ops/docs_index.py load_config (the `missing required key 'docs.index'` message stays), src/tld/ops/spec.py and src/tld/ops/sysml.py (the section is read from the resolved profile; an absent section prints the 3.6 message instead of the old one), src/tld/ops/release_prepare.py _load, and src/tld/ops/deps_prepare.py (line 28 and 61-65: its `validate(profile, None)` call on the trusted profile becomes `validate(profile, None, fetch=False)` so an unattended /deps run never fetches; this is a one-line change; tests/core/test_ops_deps_prepare.py keeps passing and gains test_deps_prepare_reads_the_trusted_profile_without_fetching). src/tld/plan/phases.py check-commands stays raw (it reads only verify.after_merge_allow, which is not inherited): do not edit that file.
      2. manifest.py: its built-in constants for plan_dir and branch types are replaced by the resolved values; the signature validate(manifest, profile=None, *, plan_dir=...) keeps its defaults for callers that pass a dict.
      3. Update each existing test whose expectation changes (the old missing-key messages, the plan_dir default, branch types always checked) and add the tests named in the acceptance. tests/core/test_minimal_profile.py builds a tmp git repository whose profile has only `verify`, plus an empty `deps:`, `spec:` and `sysml:` and a cached base, and runs through the real CLI: profile validate --resolved, roles required --at dod, plan validate-manifest on a small manifest, ops docs-index check, ops sysml check, and asserts each exits 0 (this is the ask's "a minimal profile runs every command").
      4. Do not edit tests/mutation/mutants.yaml: keep the `old` text of every mutant in the files this phase edits. Stop with status=blocked if that is impossible and name the mutant. Stop with status=blocked if a reader runs without a git directory and needs the cache; it must fall back to fetch=False and the profile's own keys with no error.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_roles_dispatch.py::test_reads_required_roles_from_the_cached_base tests/core/test_roles_dispatch.py::test_a_profile_on_standard_input_is_resolved_without_a_floor tests/core/test_ops_deps_prepare.py::test_deps_prepare_reads_the_trusted_profile_without_fetching -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_validate_manifest.py::test_branch_types_default_is_checked tests/core/test_validate_manifest.py::test_plan_dir_default_resolves_trailing_slash -q exits 0 and .venv/bin/python -m pytest tests/core/test_scope_check.py::test_changelog_default_is_ignored -q exits 0 and .venv/bin/python -m pytest tests/core/test_board_inbox.py::test_owner_login_defaults_to_the_repository_owner_with_a_base -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_docs_index.py::test_docs_index_default_applies_when_the_file_exists -q exits 0 and .venv/bin/python -m pytest tests/core/test_ops_spec.py::test_absent_spec_section_message -q exits 0 and .venv/bin/python -m pytest tests/core/test_ops_sysml.py::test_absent_sysml_section_message -q exits 0 and .venv/bin/python -m pytest tests/core/test_release_prepare.py::test_release_workflow_defaults_inside_section -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_minimal_profile.py::test_a_minimal_profile_runs_every_command -q exits 0"
      - ".venv/bin/python -m pytest tests -q exits 0"
      - "grep -n 'tld.profile.resolve' src/tld/plan/manifest.py prints a line (the Plan to Profile dependency exists)"
  - id: p8-defaults-playbooks
    title: Playbooks and eval tasks for the defaults and messages
    depends_on: [p6-summary-protect-playbooks, p7-cli-readers]
    complexity: M
    touches:
      - playbooks/policies/profile.md
      - playbooks/deps.md
      - playbooks/spec.md
      - playbooks/sysml.md
      - playbooks/git-ops.md
      - playbooks/land.md
      - playbooks/release.md
      - playbooks/repo-admin.md
      - evals/fixtures/commands.py
      - evals/tasks/deps-needs-keys/task.yaml
      - evals/tasks/spec-needs-version/task.yaml
      - evals/tasks/sysml-needs-subset/task.yaml
      - evals/stubs/deps-needs-keys.json
      - evals/stubs/spec-needs-version.json
      - evals/stubs/sysml-needs-subset.json
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/90/plan.md (sections 3.1 and 3.6), playbooks/policies/profile.md, playbooks/deps.md (lines 5-12), playbooks/spec.md (lines 15-22), playbooks/sysml.md (lines 22-28), playbooks/git-ops.md (lines 12-20), playbooks/land.md (lines 10-14 and 40-46), playbooks/release.md (lines 14-20), playbooks/repo-admin.md (lines 14-20), evals/fixtures/commands.py (lines 50-70), evals/tasks/deps-needs-keys/task.yaml.
      1. playbooks/policies/profile.md: rule 1 becomes the text of 3.1 (every value comes from the resolved profile, a base value or a built-in default is part of it, a key still missing from it is named and stops the run); rule 2 applies to the resolved profile; step 2 of "Loading the profile" notes `--explain` and that the load fetches the base once; add `tld.extends` and `tld.allow_override` to the key table.
      2. playbooks/deps.md, spec.md, sysml.md, git-ops.md, repo-admin.md: replace each missing-key stop message by the text of 3.6; playbooks/land.md: `--max <land.max_prs>` is always passed (the resolved value; the option is left out only when the profile says `land.max_prs: false`); playbooks/release.md: `release.workflow` defaults to tld-release.yml, `release.version_files` still stops the run when missing.
      3. The expected stop messages of deps-needs-keys, spec-needs-version and sysml-needs-subset live in evals/fixtures/commands.py (`expected["stop_message"]`): change them there to the 3.6 texts, and change the matching task descriptions and stubs. A stub run only proves the canned text matches the expectation; the real messages are proved by the code tests of p7.
      4. Refresh the baseline as in p6 step 6.
      5. Stop with status=blocked if tests/core/test_contracts.py names a tld call these edits made unknown.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_spec_playbook.py tests/core/test_sysml_playbook.py tests/core/test_release_playbook.py tests/core/test_evals_tasks.py tests/core/test_evals_stubs.py tests/core/test_evals_fixtures.py tests/core/test_evals_baseline.py tests/core/test_land_command.py -q exits 0"
      - "grep -c \"/deps needs a 'deps' section\" evals/fixtures/commands.py prints 1"
      - "python3 evals/run.py run --agent stub --repeats 1 --require-pass exits 0 and python3 evals/run.py check-baseline exits 0"
  - id: p9-survey
    title: Survey reads CODEOWNERS, the version line, dependency commands and the ADR heading
    depends_on: [p4-resolve, p5-hooks]
    complexity: M
    touches:
      - src/tld/profile/survey_repo.py
      - src/tld/profile/survey.py
      - src/tld/profile/survey_proposal.py
      - src/tld/profile/patch.py
      - src/tld/templates/toolkit.yaml
      - tests/core/test_survey_repo.py
      - tests/core/test_profile_survey.py
      - tests/core/test_survey_proposal.py
      - tests/core/test_profile_patch.py
    brief: |
      Read first: docs/plans/90/plan.md (section 3.7, Setup, and 3.13), src/tld/profile/survey.py (lines 100-241), src/tld/profile/survey_proposal.py, src/tld/profile/patch.py (lines 40-60), src/tld/templates/toolkit.yaml.
      1. Create src/tld/profile/survey_repo.py with scan(root) -> dict (keys codeowners, version_files, deps_audit, lock_freshness, adr_bar) exactly as 3.7 describes; call it from survey.py and add its output to the survey evidence; leave branch_prefixes in the evidence; add the option `--base FILE` to src/tld/profile/survey.py (a cached base, read-only) and pass the parsed base to survey_proposal.build.
      2. survey_proposal.build(evidence, base=None): never emit git.branch_types or git.merge_style; with a base omit every key the base sets and emit git.codeowners only when the CODEOWNERS logins (bot removed) differ from the base's; emit release.version_files, deps.audit, deps.lock_freshness and docs.adr_bar from the new evidence.
      3. patch.py: KEYS gains `tld.extends`; set-block can write it as a text edit.
      4. src/tld/templates/toolkit.yaml: add a commented `tld.extends` example with a placeholder source and sha (never an uncommented value: the dod gate validates the template with --no-file-checks).
      5. Tests as named in the acceptance; update the existing survey, proposal and patch tests only where the proposal no longer has branch types or merge style.
      6. Stop with status=blocked if the base cannot be read without network access (it is read from a file the caller names).
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_survey_repo.py::test_version_line tests/core/test_survey_repo.py::test_lock_script tests/core/test_survey_repo.py::test_decisions_heading tests/core/test_survey_repo.py::test_dependency_commands tests/core/test_survey_repo.py::test_codeowners_skip_teams_emails_and_the_bot -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_survey_proposal.py::test_code_owners_differ_from_the_base tests/core/test_survey_proposal.py::test_values_the_base_sets_are_left_out tests/core/test_survey_proposal.py::test_no_branch_types_or_merge_style_is_proposed -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_profile_survey.py tests/core/test_profile_patch.py tests/core/test_setup_fixtures.py tests/core/test_contracts.py -q exits 0 and .venv/bin/python cli/tld profile validate src/tld/templates/toolkit.yaml --no-file-checks exits 0"
  - id: p10-setup-playbook-evals
    title: The setup playbook, its graders and its eval tasks
    depends_on: [p8-defaults-playbooks, p9-survey]
    complexity: M
    touches:
      - playbooks/setup.md
      - evals/harness/graders.py
      - evals/harness/actions.py
      - evals/fixtures/setup_repos.py
      - evals/tasks/setup-security-heavy/task.yaml
      - evals/tasks/setup-extends-base/task.yaml
      - evals/tasks/setup-extends-base-no-tests/task.yaml
      - evals/stubs/setup-security-heavy.json
      - evals/stubs/setup-extends-base.json
      - evals/stubs/setup-extends-base-no-tests.json
      - tests/core/test_evals_graders.py
      - tests/core/test_setup_fixtures.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/90/plan.md (section 3.7, Setup), playbooks/setup.md, evals/harness/graders.py (lines 199-300: sections_present, findings_section_valid, profile_valid at 262-277 whose `vp.validate(profile, None)` is at line 274, roles_block_equals; 24 graders exist, none named asks_at_most or profile_key_equals), evals/harness/actions.py, evals/tasks/setup-security-heavy/task.yaml, evals/fixtures/setup_repos.py.
      1. playbooks/setup.md: rewrite sections 2 to 4 per 3.7 (the order of learning the base; `tld profile base latest`, `tld profile base fetch`, `tld profile survey . --base <file>`; at most one ask, only for what the survey could not derive; the posture no longer asked; write `tld.extends: <source>@<sha>  # <tag>`, `tld.version: ">=1.7,<2"` and every detected value explicitly; a `## Security` line in the pull request when the profile or a workflow changes). Keep the rule that blocking true is never written without the owner's confirmation.
      2. evals/harness/actions.py: record each ask a run posts as an action of kind `ask` with its question ids. evals/harness/graders.py: add the grader `asks_at_most` (parameter max) and `profile_key_equals` (parameters key and, optionally, value); make `profile_valid` pass the fixture root and fetch=False to validate so a base seeded in `.git/tld/base` is found without network access.
      3. evals/fixtures/setup_repos.py: a fixture can carry a pre-seeded base in the git common dir's tld/base; add the two repositories used by the tasks below (one with a Makefile `test` target, one without any test command).
      4. Add the tasks setup-extends-base (graders profile_valid, asks_at_most max 0, profile_key_equals tld.extends) and setup-extends-base-no-tests (asks_at_most max 1 and the ask's question ids are exactly verify_fast and verify_dod), each with its stub; update setup-security-heavy and its stub to the new roles block (the base's roles are not repeated).
      5. Refresh the baseline as in p6 step 6. A stub run proves the wiring only; say in the commit message that a real-model run of the two new tasks was not made.
      6. Stop with status=blocked if the setup eval fixture cannot be seeded without network access.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_evals_graders.py::test_asks_at_most_fails_on_two_asks tests/core/test_evals_graders.py::test_profile_key_equals_fails_without_extends tests/core/test_evals_graders.py::test_profile_valid_reads_the_seeded_base_offline -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_evals_tasks.py tests/core/test_evals_stubs.py tests/core/test_setup_fixtures.py tests/core/test_evals_baseline.py -q exits 0"
      - "python3 evals/run.py run --agent stub --repeats 1 --require-pass exits 0 and python3 evals/run.py check-baseline exits 0"
  - id: p11-migrate
    title: Migrate asks one batch about files off their default path
    depends_on: [p10-setup-playbook-evals]
    complexity: M
    touches:
      - src/tld/ops/migrate_defaults.py
      - src/tld/ops/migrate.py
      - src/tld/cli.py
      - playbooks/migrate.md
      - evals/tasks/migrate-off-default-paths/task.yaml
      - evals/stubs/migrate-off-default-paths.json
      - evals/tasks/migrate-dry-run/task.yaml
      - evals/fixtures/commands.py
      - tests/core/test_migrate.py
      - tests/core/test_migrate_defaults.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/90/plan.md (section 3.7, Migrate), playbooks/migrate.md, src/tld/ops/migrate.py (lines 1-60 and 500-540), src/tld/ops/docs_index.py (the move command), evals/tasks/migrate-dry-run/task.yaml, evals/fixtures/commands.py.
      1. Create src/tld/ops/migrate_defaults.py: plan(root, raw) -> list of Change (kind, path, default_path, key) and apply(root, plan, answers) -> list of messages; it finds the off-default paths, keys equal to a default or the base, moot protect_paths_allow entries and the preserve-behaviour writes of 3.7; a rename calls the docs-index move code of src/tld/ops/docs_index.py with apply=True; a keep writes the explicit key into the profile by text edit through tld.profile.patch where it can, else says so in the output.
      2. src/tld/ops/migrate.py: where it prints "Nothing to migrate: the repository already uses tld.", call the defaults plan; add the options `--defaults` and `--answers FILE`; without --write nothing changes; `--write` without answers is refused; an unknown answer is refused; the output for no finds is `nothing is off its default path` and asks nothing. Touch src/tld/cli.py only if the existing "migrate" route does not pass the options through.
      3. playbooks/migrate.md: add a section "Files off their default path" after the plan step: run `tld migrate . --defaults`, ask one batch (one `choice` per find with the options `rename` and `keep`, the recommended first), write with `--write --answers`, deliver in the same pull request with a `## Security` line when the profile changes. Keep every existing rule.
      4. Evals: add migrate-off-default-paths (a fixture in evals/fixtures/commands.py with CHANGES.md and docs/adrs; graders result_mentions and no_changes in dry-run) with its stub; keep migrate-dry-run passing.
      5. Tests in tests/core/test_migrate_defaults.py as named in the acceptance; update tests/core/test_migrate.py only where the "Nothing to migrate" text changed.
      6. Refresh the baseline as in p6 step 6.
      7. Stop with status=blocked if the docs-index move cannot be called as a function without printing; report the function names you found.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_migrate_defaults.py::test_off_default_changelog tests/core/test_migrate_defaults.py::test_nothing_off_the_default tests/core/test_migrate_defaults.py::test_defaults_without_write_changes_nothing tests/core/test_migrate_defaults.py::test_write_without_answers_refused tests/core/test_migrate_defaults.py::test_unknown_answer_refused tests/core/test_migrate_defaults.py::test_preserve_plan_dir_written_when_plans_exist tests/core/test_migrate_defaults.py::test_branch_types_from_existing_manifests tests/core/test_migrate_defaults.py::test_moot_protect_paths_allow_listed tests/core/test_migrate_defaults.py::test_keys_equal_to_default_listed tests/core/test_migrate_defaults.py::test_rename_rewrites_a_link tests/core/test_migrate_defaults.py::test_keep_writes_the_explicit_key -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_migrate.py tests/core/test_contracts.py tests/core/test_evals_tasks.py tests/core/test_evals_stubs.py tests/core/test_evals_baseline.py -q exits 0 and .venv/bin/python cli/tld migrate --help exits 0 and names --defaults"
      - "python3 evals/run.py run --agent stub --repeats 1 --require-pass exits 0 and python3 evals/run.py check-baseline exits 0"
  - id: p12-admin-profile
    title: Org audit checks the base pin, merge commits and the policy schema
    depends_on: [p4-resolve]
    complexity: M
    touches:
      - src/tld/ops/repo_admin_profile.py
      - src/tld/ops/repo_admin.py
      - src/tld/schema/admin-policy.schema.json
      - src/tld/templates/admin-policy.yaml
      - tests/core/test_repo_admin_profile.py
    brief: |
      Read first: docs/plans/90/plan.md (section 3.7, repo-admin), docs/guides/admin.md (lines 100-256), src/tld/ops/repo_admin.py (lines 258-270, 952-1010, 1484-1568), src/tld/schema/admin-policy.schema.json (lines 80-95), src/tld/templates/admin-policy.yaml, tests/core/test_repo_admin.py (the stubbed API client).
      1. src/tld/schema/admin-policy.schema.json: add the optional sections `profile` (base, pin, guarded_overrides) and `git_ops` (repo, workflow, allowlist) with the types and enums of 3.7 (`pin` is `latest-tag` or a 40-hex commit, a tag name is rejected); src/tld/templates/admin-policy.yaml: add both as commented examples with placeholders and set the repository merge settings allow_merge_commit true, allow_squash_merge false, allow_rebase_merge false.
      2. Create src/tld/ops/repo_admin_profile.py with the checks profile-no-extends, profile-invalid-extends, profile-pin-old (a fix that rewrites only the `extends:` line, branch and pull request through apply_files as in repo_admin.py, title `chore: bump the tld base to <tag>`, the tag kept as the trailing comment), profile-guarded-override (information) and profile-merge-style; read each repository's profile at its default branch through the contents wrapper repo_admin.py already uses and resolve it offline with tld.profile.resolve (fetch=False, trusted=False; the base text comes from the policy client, not the network); register the checks in the CHECKS dict of src/tld/ops/repo_admin.py (lines 1484-1491, which run_checks iterates) with one entry and nothing else changed there.
      3. Tests in tests/core/test_repo_admin_profile.py with the stubbed API client of tests/core/test_repo_admin.py, as named in the acceptance.
      4. Stop with status=blocked if no stubbed API client exists in tests/core/test_repo_admin.py; report what the existing tests use.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_profile.py::test_repository_without_a_base tests/core/test_repo_admin_profile.py::test_out_of_date_pin tests/core/test_repo_admin_profile.py::test_override_listed tests/core/test_repo_admin_profile.py::test_merge_settings tests/core/test_repo_admin_profile.py::test_policy_with_profile_and_git_ops_sections_validates tests/core/test_repo_admin_profile.py::test_policy_pin_tag_rejected tests/core/test_repo_admin_profile.py::test_pin_bump_changes_only_the_extends_line tests/core/test_repo_admin_profile.py::test_guarded_override_resolves_remote_profile_offline -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_e2e.py tests/core/test_repo_admin_rulesets.py -q exits 0 and .venv/bin/python cli/tld ops repo-admin validate-policy src/tld/templates/admin-policy.yaml exits 0"
  - id: p13-admin-gitops-secrets
    title: Org audit checks the git-ops central repository and secret scope
    depends_on: [p11-migrate, p12-admin-profile]
    complexity: M
    touches:
      - src/tld/ops/repo_admin_gitops.py
      - src/tld/ops/repo_admin.py
      - playbooks/repo-admin.md
      - tests/core/test_repo_admin_gitops.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/90/plan.md (section 3.7, repo-admin), playbooks/repo-admin.md, src/tld/ops/repo_admin.py (lines 952-1010 and 1484-1568), src/tld/ops/repo_admin_profile.py, docs/guides/git-ops.md.
      1. Create src/tld/ops/repo_admin_gitops.py with the checks git-ops-workflow and git-ops-allowlist (fixes as pull requests into the central repository named by the policy's `git_ops.repo`, one commit through apply_files, the workflow from the `tld-git-ops.yml` template that tld already ships, the allowlist file naming every audited repository), git-ops-environment and git-ops-token (warn with manual text, reusing _env_and_secret, never created), and secrets_scope (report a repository or organisation Actions secret that is not held in an environment limited to the default branch); register it in the CHECKS dict of src/tld/ops/repo_admin.py (lines 1484-1491) with one entry and nothing else changed there.
      2. playbooks/repo-admin.md: document the sections and the open items (the owner creates the GIT_OPS_TOKEN secret and the git-ops environment; the audit reports them); the stop message when there is no policy file is the 3.6 text; a pull request that changes the profile carries a `## Security` line.
      3. Tests in tests/core/test_repo_admin_gitops.py with the stubbed API client, as named in the acceptance.
      4. Refresh the baseline as in p6 step 6. Stop with status=blocked if the git-ops workflow template is not available to the audit; report where tld ships it.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_admin_gitops.py::test_central_repository_incomplete tests/core/test_repo_admin_gitops.py::test_secret_and_environment tests/core/test_repo_admin_gitops.py::test_unscoped_secret tests/core/test_repo_admin_gitops.py::test_env_secret_limited_to_default_branch_not_reported tests/core/test_repo_admin_gitops.py::test_env_secret_without_branch_policy_reported -q exits 0"
      - ".venv/bin/python -m pytest tests/core/test_repo_admin.py tests/core/test_repo_admin_profile.py tests/core/test_contracts.py tests/core/test_evals_baseline.py -q exits 0"
      - "python3 evals/run.py check-baseline exits 0"
  - id: p14-retire
    title: Retirement - reference docs, guides, changelog, spec and architecture archive
    depends_on: [p13-admin-gitops-secrets]
    complexity: M
    touches:
      - docs/reference/profile-reference.md
      - docs/architecture/hooks.md
      - docs/architecture/design.md
      - docs/architecture/evals.md
      - docs/guides/setup.md
      - docs/guides/admin.md
      - docs/guides/git-ops.md
      - docs/guides/org-base.md
      - docs/guides/release.md
      - docs/guides/reflektor.md
      - docs/guides/maintenance.md
      - docs/guides/spec.md
      - docs/guides/sysml.md
      - docs/README.md
      - README.md
      - SECURITY.md
      - CHANGELOG.md
      - openspec/**
      - sysml/**
      - docs/architecture.md
      - docs/architecture.svg
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/90/plan.md (all of section 3), docs/plans/90/deviations.md, docs/reference/profile-reference.md, docs/architecture/hooks.md, docs/architecture/evals.md (the task table), docs/guides/setup.md, docs/README.md, SECURITY.md, CHANGELOG.md.
      1. First reconcile `openspec/changes/org-base-profile/` and `sysml/changes/org-base-profile/` with docs/plans/90/deviations.md so they describe what was built (edit a delta or the model file only where a deviation says the behaviour or a component differs).
      2. docs/reference/profile-reference.md: rewrite the rules block (lines 11-26) for the resolved profile and the defaults table of 3.1; add the keys `tld.extends`, `tld.allow_override`; change the Required column and defaults of every key 3.1 and 3.9 change (branch_pattern, branch_types, merge_style, plan_dir, the docs paths, deps, spec, sysml, land.max_prs, git_ops.repo, admin.policy, release.workflow, hooks.* and protect_paths); document `false` off switches, `--explain`, `--ref` and the base commands.
      3. docs/architecture/hooks.md: the gates are on by default (lines 42-46, 208, 261, 295, 368-390), the new default protect list and the code-protected workflow set (lines 182-195), the resolved trusted copy, the clamp and the cache-only base (lines 400-440; replace decision 5 at line 291), "What the hooks do not protect" gains the base cache. docs/architecture/design.md: the resolver and the base in the concepts list. docs/architecture/evals.md: add the task-table rows (lines 203-228) for setup-extends-base, setup-extends-base-no-tests and migrate-off-default-paths, and the grader-table rows (lines 272-293) for asks_at_most, profile_key_equals and the missing findings_section_valid. Also mention in hooks.md the `quick` command among the opening and record-writing commands (lines 266, 283, 296) and `scan_text(text, skip_marked=False)` (line 141) where the base token check is described. SECURITY.md: workflows are editable by sessions, the base trust model and `secrets_scope`.
      4. docs/guides/org-base.md (new, at most 150 lines): what the base is, its content and allowed keys, pinning (`tld profile base latest`), bumping, the guarded keys and `tld.allow_override`, the upgrade behaviour changes of 3.9 as a list, and the owner's manual steps ma1 to ma3 of the plan. Update docs/guides/setup.md, admin.md, git-ops.md, spec.md, sysml.md for the new messages and flow, and the lines the protect-list change makes untrue: docs/guides/release.md line 23 ("The profile is a protected path"), docs/guides/reflektor.md line 26 (`.tld/toolkit.yaml` "a protected path") and docs/guides/maintenance.md line 22 (a protected path other than an action version; keep the deps exception true).
      5. docs/README.md: one row for docs/guides/org-base.md; check every row the other edits made untrue. README.md: only the lines the change makes untrue.
      6. CHANGELOG.md: under `## [Unreleased]` add one line per user-visible change (base profile and `tld.extends`; defaults; gates on; protect list; setup, migrate and audit changes; `tld profile validate --explain/--ref`; `tld profile base`; `summary-check --changed`) and a `Behaviour changes on upgrade` list copied from 3.9. No new version heading (the first `## [` heading after `## [Unreleased]` stays `## [1.6.0]`), and do not change the version in pyproject.toml, plugin.json or tld/__init__.py (the release skill does).
      7. Archive: `tld ops spec archive --profile .tld/toolkit.yaml org-base-profile` after `git diff --quiet $(git merge-base HEAD origin/main) origin/main -- openspec/specs` exits 0 (otherwise stop with status=blocked: main changed the specs); `tld ops spec validate --profile .tld/toolkit.yaml` must exit 0 and `grep -rn "TBD" openspec/specs` must print nothing; `tld ops sysml archive --profile .tld/toolkit.yaml org-base-profile` (a `changed since` finding means stop with status=blocked and name the file); then `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml` must exit 0 (run `tld ops sysml render --profile .tld/toolkit.yaml` to refresh docs/architecture.md and docs/architecture.svg, never edit them by hand); commit the moved changes and the updated specs.
      8. Run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0; refresh the baseline as in p6 step 6.
    acceptance:
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - ".venv/bin/python cli/tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/org-base-profile does not exist and grep -rn TBD openspec/specs prints nothing"
      - ".venv/bin/python cli/tld ops sysml check --profile .tld/toolkit.yaml and .venv/bin/python cli/tld ops sysml render --check --profile .tld/toolkit.yaml exit 0 and sysml/changes/org-base-profile does not exist"
      - "grep -n 'org-base' docs/README.md prints the row of docs/guides/org-base.md"
      - "grep -c 'Behaviour changes on upgrade' CHANGELOG.md prints 1 and grep -n '^## \\[1.7' CHANGELOG.md prints nothing"
      - ".venv/bin/python -m pytest tests -q exits 0"
      - "python3 evals/run.py check-baseline exits 0"
```
