# Cutting a release with /tld:release

`/tld:release` prepares a release in one pull request, waits for your merge and starts the release workflow after
one board yes. You approve only the publish job in GitHub, once. It never creates a tag itself.

## What you need in the profile

`.tld/toolkit.yaml` needs `docs.changelog` (the skill turns its unreleased section into a version heading) and the
section `release`:

```yaml
docs:
  changelog:
    file: CHANGELOG.md
    section: "## [Unreleased]"
release:
  workflow: release.yml          # file name in .github/workflows; takes the boolean input dry_run
  version_files:                 # every file that holds the version
    - path: pyproject.toml
      pattern: '^version = "(\d+\.\d+\.\d+)"$'   # regex, multiline, exactly one capture group: the version
```

A session may add both blocks in a pull request (the profile is no longer a protected path), but the pull request
must name `.tld/toolkit.yaml` under Security, and the release workflow itself (`release.workflow`, `tld-release.yml` by
default) stays protected in code: a person installs or changes it. `release.workflow` defaults to `tld-release.yml` when the
`release` section is written. Keys: [profile-reference.md](../reference/profile-reference.md). `tld profile validate` checks that each
pattern matches exactly once.

## The flow

1. **The version.** Run `/tld:release` (optionally `patch`, `minor`, `major` or `X.Y.Z`). The skill shows the
   unreleased entry and asks you for the version on the board.
2. **The branch.** The skill creates `chore/release-X-Y-Z`, runs `tld ops release-prepare --write` and checks
   the diff with `--check --base`. It edits nothing by hand.
3. **The pull request.** The skill opens `Release X.Y.Z` with the new entry in its body, asks for your review
   and drives CI to green. It never approves or merges.
4. **You merge** the pull request. That is your go for the release.
5. **After the merge** the skill checks the merged files again.
6. **The green check.** The skill reads the checks of the new head of `main` with the rule the workflow uses
   (`tld ops release-check`). While they run it asks nothing and waits, up to an hour. A red check stops it with
   the check's name and no question.
7. **The one yes.** Once the commit is green you answer one board question, which names the checked commit:
   `real`, `dry-run` or `stop`.
8. **The dispatch.** Right before it, the skill checks that the head of `main` is still the checked commit and
   still green; otherwise it checks and asks again. On `real` it then sets the release marker, starts the
   workflow with `dry_run=false` and clears the marker. `dry-run` starts it with `dry_run=true`.
9. **You approve the publish job** in GitHub, once. `build` runs without approval and pushes only an untagged
   image digest.
10. **The end.** The skill follows the run and reports the release URL or the failing step.

## The guard rules

The `no-git-tag` hook lets a session start the release workflow only with `dry_run=true` (exactly that value), or
with `dry_run=false` while `tld guard allow-release <workflow-file>` ran in the last 10 minutes. A `skip_checks`
that is not exactly `false`, `gh api --input`, every `curl` dispatch and any dynamic or glob word are denied even
with the marker, and a workflow under another name is guarded only once the profile names it
(`release.workflow`). The marker is a deliberate step, not a control: the controls are your merge and your
publish approval.

## When a step fails

The skill shows the failing step's error line and never re-runs. What a failed publish leaves behind and how to
finish by hand: the release paragraphs of [CONTRIBUTING.md](../../CONTRIBUTING.md). The manual way (bump the
files, run the workflow) still works.

A red check, or checks still running after the hour, end the flow with `Release <X.Y.Z> is merged and not started`;
run the workflow yourself when they are green. The skill sees only the GitHub Actions checks of the commit; the
workflow checks every check run and the legacy commit status.

## Other repositories

The template's green step now runs the rule of `tld ops release-check`. A repository with an installed copy gets it
when you run `tld ops repo-admin audit` (it reports the file as different) and `apply --yes`, which opens one pull
request per repository that you review and merge (tld never merges it).
