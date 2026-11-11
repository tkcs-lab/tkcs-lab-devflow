# How PrivacyFence moved to the toolkit

> **Historical.** This page records the move of 2026-10 onto claude-toolkit (the `devflow` plugins). Those names are
> retired: the plugin is `tld`, the profile is `.tld/toolkit.yaml`, the commands are `/tld:<cmd>`. A repository on
> claude-toolkit today follows [guides/migrating-from-claude-toolkit.md](guides/migrating-from-claude-toolkit.md).
> The page stays because an ADR outside this repository links it.

`privacyfence/privacyfence` was the first project to move to devflow, and the move is done. Before it,
the project kept its own `.claude/commands/{make-plan,implement,dod}.md` and a full
`.claude/skills/steward`. Its
[ADR 0132](https://github.com/privacyfence/privacyfence/blob/main/docs/adr/0132-workflow-commands-come-from-the-devflow-toolkit-plugins.md)
(2026-10-09) records the decision. This page records what changed, so another project can follow the
same steps. That ADR links here, so keep this page.

## Delivery: Claude Project plugins

PrivacyFence uses [the plugin route of `delivery.md`](guides/delivery.md#claude-project-plugins). The
`devflow` and `stack-python` plugins are enabled in the Claude Project. The toolkit has no hook and no version
pin. ADR 0132 rejected the hook route because the
maintainer uses the toolkit in several projects: enabling the plugins once in the Project serves all
of them, while a hook would need its tag bumped in each repository. The cost is that no version is
pinned in the repository. ADR 0132 also rejected turning both routes on at once, because every
command would then appear twice.

## What changed in the PrivacyFence repository

| Path | Change |
|---|---|
| `.claude/toolkit.yaml` | **Added.** A copy is kept here as [`tests/fixtures/privacyfence-toolkit.yaml`](../tests/fixtures/privacyfence-toolkit.yaml), and CI validates it. The `verify.*` rows mirror §2.7 of `docs/coding-and-testing-guidelines.md`, and the project's `tests/unit/test_definition_of_done_drift.py` keeps the two in step. |
| `.claude/commands/{make-plan,implement,dod}.md` | **Deleted.** `dod.md`'s command list, conditional rows and manual rows became `verify.dod`, `verify.dod_conditional` and `verify.dod_manual`. |
| `.claude/skills/steward/SKILL.md` | **Trimmed** to the project half: why live connector checks run off-box, the container facts about Chromium, which PRs not to follow, red-check specifics, and branch, changelog and release conventions. The generic half (dispatch to CI instead of skipping, how to treat a red check) is now the toolkit's `pr-steward` skill. The dispatch table became `ci.dispatchable`. The profile's `project_steward` key makes every command read this file. |
| `.claude/commands/cut-release.md`, `qa-record.md` | Kept unchanged, because they are PrivacyFence-only. |
| `.claude/hooks/session-start.sh` | Kept: it is the project's environment setup (venv, Node, Chromium). Its closing `==>` line points at `ci.dispatchable` and the steward skill. |
| `.claude/settings.json` | Unchanged, because the plugin route needs no hook. |
| `CLAUDE.md` ("Commands and skills"), `docs/coding-and-testing-guidelines.md` §2.7, `docs/testing-policy.md` (`/dod` entry) | Each now says that the three commands come from the toolkit and that `/dod`'s rows are `verify` in `.claude/toolkit.yaml`. |
| `docs/adr/0132-…md` | **Added.** |

## The profile, and keeping it in step

The fixture is a verbatim copy of PrivacyFence's `.claude/toolkit.yaml`. When the project changes its
profile, copy the file over again. This repository's tests and the CI validator step will then show
whether a toolkit change breaks the project's real profile. The two real manifests
(`plan/atlassian-user-names` and `plan/plugin-framework`) are kept the same way, as
`tests/fixtures/privacyfence-*-manifest.yaml`.

To check the live file from a checkout of both repositories:

```
bin/tld profile validate ../privacyfence/.claude/toolkit.yaml --root ../privacyfence
```

This also checks that every file the profile lists exists.

## Differences from the old commands

- The wording is generic where the originals named PrivacyFence things, for example "live
  external-service credentials" instead of "live connector credentials". The rules are the same.
- Under the plugin route the commands are namespaced plugin commands, such as `devflow:dod`.
- `/implement` treats a `verify_after_merge` entry written as `dispatch <workflow>` as a CI dispatch
  against the feature branch. This is new and used by the Swift stack. PrivacyFence manifests have no
  such entries.
- Manifests are now checked by `validate_manifest.py` instead of inline Python. It also checks
  `feature_branch` against `git.branch_types`.
- Commands read the profile first. If a key is missing, they stop with a message that names it.
- `/review` (since v0.2.0) is new. The project never had it.
