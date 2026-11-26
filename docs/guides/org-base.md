# The org base profile

One file per organisation holds what every repository of the owner should share: the code owners, the bot login, the
required roles, the guardrail settings. A repository extends it with one line and writes only what is its own. A minimal
profile is `tld.extends` plus `verify.fast` and `verify.dod`; built-in defaults fill the common values
([profile-reference.md](../reference/profile-reference.md)).

```yaml
tld:
  extends: <owner>/.github/tld/profile-base.yaml@<40-hex commit>  # v1
  version: ">=1.7,<2"
verify:
  fast: [...]
  dod: [...]
```

## The base file

It lives in the organisation's `.github` repository at `tld/profile-base.yaml` (setup probes exactly that path; a
different source is passed with `--base` or `TLD_BASE_PROFILE`). Example:

```yaml
tld: {version: ">=1.7,<2"}
git: {bot_login: example-bot, codeowners: [example-owner], branch_pattern: "<type>/<kebab-case>"}
roles:
  posture: {security: critical}
  required:
    - {role: security-reviewer, at: [implement_phase, implement_final], blocking: true}
    - {role: reflektor, at: [dod]}
hooks:
  dod_gate: {enabled: true, max_attempts: 3}
  plan_gate: {enabled: true}
  board_gate: {enabled: true}
models: {worker: standard, reviewer: strong}
runtime: {environments: [TLD]}
verify:
  dod_manual: ["A user-visible change needs a changelog line under ## [Unreleased]."]
```

**Allowed keys** (anything else is refused, with the list in the message): `tld.version`, `tld.allow_override`,
`git.bot_login`, `git.codeowners`, `git.branch_pattern`, `roles.posture`, `roles.required`, `hooks.*`, `models`,
`runtime.environments`, `verify.dod_manual`. A base never sets `verify.fast` or `verify.dod` (it must not run code in every
repository), `roles.extra_context` (prompt text), a feature section or `tld.extends` (no chaining). It is refused when it
holds token-like text (a `secret-scan:allow` mark does not hide it) or a secret-like key name, exceeds 65536 bytes or
nesting 8, or uses a YAML anchor or alias. Check a file before tagging it: `tld profile base check tld/profile-base.yaml`
prints `base: OK`.

## Pinning and bumping

The pin is a full 40-hex commit, never a tag or branch (a moved tag would change every repository without a pull
request). The commit must be a version tag's commit or an ancestor of the base repository's default branch head, so a
commit that only a pull request holds is refused. `tld profile base latest <owner>/<repo>/<path>` prints
`{"sha": ..., "tag": ...}` (the newest tagged commit that has the file, else the default branch head with `"tag": null`).
`tld profile base fetch [PROFILE]` caches the pinned base under the git directory (`tld profile base fetch --ref REF`
reads the pin of that ref's profile); it is never fetched twice, works offline afterwards and a corrupt entry is refetched.
Without the cache and without network the playbooks stop (`tld roles required` and the playbooks that load the profile; `deps_prepare` and `release_prepare` still ignore a missing
base); hooks use the cache only and, without it, drop everything the base adds (its extra protect paths included).

A bump is a pull request that changes one line: `/tld:setup update`, the audit's pin-bump pull request
(`profile-pin-old`, title `chore: bump the tld base to <tag>`) or by hand. Its `**Security:**` line of the Summary must name
`.tld/toolkit.yaml`. The new base's weaker guardrails take effect only after the merge (when the default branch's copy is
reachable; offline there is no clamp), because guarded keys are clamped
to the default branch's profile.

## Guarded keys

`tld profile validate` refuses (and the audit reports) a repository that weakens a base (the hooks clamp to the default branch's profile, not to the base's floor): `hooks.disable` (a hook the base switches on), the protect lists, the
three gates' `enabled`, `roles.posture.security` (critical above standard above low) and the roles the base requires.
`tld profile validate` names the rule broken. The base lists the keys a repository may weaken in `tld.allow_override`
(`hooks.disable.<hook>`, `hooks.protect_paths`, `hooks.protect_paths_allow`, `hooks.<gate>.enabled`,
`roles.posture.security`, `roles.required.<role>`); only a base may set it. Merging: the repository's scalars and lists
replace the base's, except `verify.dod_manual` (base rows, then the repository's, no duplicates) and `roles.required`
(by `role`: `at` and `when` are unions, `blocking` is either). `tld profile validate --resolved --explain` prints the result
and where each value came from; `--ref REF` reads the profile and the files that decide the defaults from a git ref.

## Behaviour changes on upgrade (1.7)

1. **Gates on.** `plan_gate`, `board_gate` and `dod_gate` are on for every repository with a profile and no `hooks` value;
   turn one off with `enabled: false` (`tld profile validate` refuses it, and the audit reports it, under a base without `tld.allow_override`; the hooks do not re-check the base). `verify.dod` runs at the stop of
   an editing session, from the default branch's profile.
2. **`docs.plan_dir`** is `docs/plans` when that directory exists, else `docs`.
3. **`land.max_prs` is 10** (`false` for no cap).
4. **Protect list.** The profile and ordinary workflows are no longer protected by default; a pull request that changes
   one names it under Security. A repository with its own `hooks.protect_paths` is unchanged.
5. **`git.merge_style`** is `merge-commit` unless written; a squash repository writes it.
6. **`git.branch_types`** is `[feature, fix, chore]` unless written (no longer detected).
7. **Docs paths** apply when the file exists: `docs/README.md`, `CHANGELOG.md`, `docs/adr/`, `.tld/admin-policy.yaml`,
   `scripts/build_site.py`; `false` turns each off. `tld migrate . --defaults` asks about files off these paths.
8. **Messages** for `/deps`, `/spec`, `/sysml`, a missing main branch, `/git-ops` and the audit changed; `deps`, `spec`,
   `sysml` and `release.workflow` have defaults inside their sections.

## The owner's manual steps

These need a person (another organisation's repositories, secrets, visibility):

1. **Create the base** in each org's `.github` repository: write `tld/profile-base.yaml`, run `tld profile base check`,
   merge it through a pull request the code owners approve, tag the merge commit (`git tag v1 <sha>`, push the tag) and
   run `tld profile base latest <owner>/.github/tld/profile-base.yaml` for the commit. A cloud session reads the base
   anonymously, so a private `.github` repository stops sessions with the fetch error. Making it public is the owner's
   decision and exposes **every file and the whole history**, issues, pull requests and Actions logs of that repository;
   for an organisation's `.github` repository it also publishes `profile/README.md` on the organisation page and turns its
   community-health files into defaults for every public repository. Review the history first. The alternative is a
   dedicated public repository that holds only the base file, passed with `--base` or `TLD_BASE_PROFILE`.
2. **Create the git-ops environment and secret** in each org's `git-ops` repository, following steps 1 and 2 of
   [git-ops.md](git-ops.md#set-up-once): the repository must be private with `main` protected (pull requests only) and a
   small group with write access; the token is fine-grained, with Contents read and write and Pull requests read on only
   the repositories to clean up, expiring in 90 days, and is never pasted into chat; the environment `git-ops` allows
   deployment from `main` only and holds the environment secret `GIT_OPS_TOKEN`. Do this before the audit, then run
   `/tld:repo-admin`: it adds `tld-git-ops.yml` and the allowlist through pull requests into the git-ops repository.
3. **After the release** that carries this change, run `/tld:setup update` (or merge the audit's pin-bump pull request) in
   every repository, check that the `**Security:**` line of its Summary names `.tld/toolkit.yaml`, and compare `tld profile validate
   --resolved` with `--explain`.
