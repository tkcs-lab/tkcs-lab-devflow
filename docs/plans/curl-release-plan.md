# Plan: releases installable and upgradable with curl; `launcher/` becomes `cli/`; plan-gate reads slash commands

## Goal

Tracking issue: [#15](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/15).

Today the command line is installed with `pip install git+https://...@v1.0.0` and the board server image is built
by hand from a clone. After this change a release carries everything an install needs, and one curl line installs
or upgrades each piece:

```
curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh              # the tld command
curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board  # the board (Docker)
```

Running the same line again upgrades to the latest release; To pin a version run that release's own installer, which installs its own version:
`curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download/vX.Y.Z/install.sh | sh` (the latest installer
also takes `... | TLD_VERSION=X.Y.Z sh`). The folder `launcher/` (never released: v1.0.0 shipped `bin/tld`) is renamed `cli/`,
with no compatibility shim. A third change comes from planning this: the plan-gate hook did not open a session
that was started with `/tld:make-plan` when the client delivered the command expanded (see D0), so the hook is fixed.

## Current state

- The CLI entry script is `launcher/tld` (renamed from `bin/` in commit `f48d389`, which is the template for the
  rename: 50 files). 46 tracked files name `launcher/tld` (44 are changed by p2's substitution; `AGENTS.md` is p5's; the other plan stays); other places: `src/tld/guard/integrity.py:39,42,49,59`
  (`PLUGIN_LAUNCHERS`, `is_tld_launcher`, a guard allow-path), `tests/conftest.py:14` (`BIN`),
  `tests/core/test_no_project_words.py:5` (`CHECKED`), `evals/harness/common.py:19` (`PLUGIN_PATHS`),
  `tests/mutation/mutants.yaml:403`, `tests/core/guard_cases.yaml:192`, `.tld/toolkit.yaml:37`, and
  `evals/baselines/default.json` (hashes of the command files).
- `.github/workflows/release.yml` (one job `release`, `environment: tld-release`, run by hand on `main`, dry run by
  default) checks the version, creates the tag and the GitHub release with the owner token `TLD_RELEASE_TOKEN`.
  The release has no assets. `tests/core/test_ci_workflows.py:20-26` demands top-level `permissions ==
  {contents: read}` and **no** job-level `permissions` in every workflow; `tests/core/test_repo_release.py` tests the
  release workflow's steps.
- `deploy/board/Dockerfile` builds the board server (copies a fixed list of modules); the docs tell the owner to
  `docker build` and `docker run` (`docs/guides/board-server.md`, sections Docker and Deploy it).
- `docs/guides/delivery.md` and `README.md` document `pip install git+...@v1.0.0` for the CLI.
- The repository is public; tags have one route, the release workflow; `CONTRIBUTING.md:96` and the header of `release.yml` say the workflow's own token only
  reads and the owner approves every write.
- The plan-gate (`src/tld/guard/plan_gate.py`, opt-in, enabled in `.tld/toolkit.yaml:48`) opens a session when
  `adapters/claude/hooks/claude_adapter.py:36` `INVOKED = ^\s*/(?:tld:)?([a-z][a-z-]*)(?:\s|$)` matches the start of the
  prompt. In the session that planned this change the prompt reached the hook as `<system-reminder>...</system-reminder>`
  blocks followed by `<command-message>tld:make-plan</command-message><command-name>/tld:make-plan</command-name>
  <command-args>...</command-args>`, so nothing matched, no `.git/tld/plan-gate/` record was written, and every write
  into the repository was denied. Only the observed shape is known; the real payload was not captured.

## Design

Decisions taken with the owner (ask `a-926d7a230af56fd1`, answered): the CLI is a private venv built from the release
wheel; the board image is on ghcr.io, public, linux/amd64 + linux/arm64; upgrading is re-running the same curl line.
The architect review changed the publishing route (D4).

### D0. The plan-gate opens on an expanded command

`invoked_command(prompt)` in `adapters/claude/hooks/claude_adapter.py` keeps the current rule (the prompt starts with
`/tld:<name>` or `/<name>`) and adds one more: after removing any number of leading
`<system-reminder>...</system-reminder>` blocks (and the whitespace around them), a prompt that starts with
`<command-name>/tld:<name></command-name>`, optionally preceded by `<command-message>...</command-message>`, counts as
invoking `<name>` (`/<name>` without `tld:` is accepted, like the typed form). The result still has to be in `known_commands()`. Nothing else changes: a command named later in the
text ("please /tld:make-plan") is still not an invocation, and the marker is a deliberate step, not a control
(`src/tld/guard/markers.py` docstring); a literal `</system-reminder>` inside reminder text cannot be told apart, which is
accepted for the same reason and said in `docs/architecture/hooks.md`. Rejected: switching the gate off for the repository (the owner keeps the guard),
and matching anywhere in the prompt (a pasted text could then open the gate).

### D1. Rename

`git mv launcher cli`. Every `launcher/tld` becomes `cli/tld`; `PLUGIN_LAUNCHERS` becomes `PLUGIN_CLI_PATHS` and
`is_tld_launcher` becomes `is_tld_cli` (so the guard's allow-path cannot silently miss the rename, a new test
asserts each path in `PLUGIN_CLI_PATHS`, with `${CLAUDE_PLUGIN_ROOT}` replaced by the repository root, exists).
Prose "the launcher" becomes "the CLI script". Left alone: `docs/plans/` (other transient plans). The CHANGELOG
Unreleased line becomes: the entry script moved from `bin/tld` to `cli/tld` (claude.ai refuses a plugin with a top-level
`bin/`); a session that was open during the plugin sync may need a restart; the installed `tld` command is unchanged.
Rejected: keeping a `launcher/` shim (it was never released; a shim would keep the name the owner dislikes).

### D2. Distribution: GitHub release assets, not PyPI

The PyPI name `tld` belongs to an unrelated package, so `pip install tld` would install the wrong thing; the docs
say so. A release `vX.Y.Z` carries five assets: `tld-X.Y.Z-py3-none-any.whl`, `tld-X.Y.Z.tar.gz`, `install.sh`
(stamped, D3), `compose.yaml` (stamped, D5), `SHA256SUMS` (sha256 of the other four). Pip alternative documented:
`pip install https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download/vX.Y.Z/tld-X.Y.Z-py3-none-any.whl`.

### D3. `deploy/install.sh` (POSIX sh, `set -eu`, tested under `sh`)

Usage: `install.sh [cli|board|uninstall]`, default `cli`; any other word: print `usage: install.sh [cli|board|uninstall]`
to stderr, exit 2. All messages go through `say` (stdout, prefix `tld-install: `) and `die` (stderr, same prefix,
exit 1).

Variables (the first five are the user interface; the last three are test hooks, named as such in the header comment):

| Variable | Default | Meaning |
|---|---|---|
| `TLD_VERSION` | `@TLD_VERSION@`, stamped by the release | version to install, a leading `v` is dropped |
| `TLD_PYTHON` | first of `python3.13`, `python3.12`, `python3.11`, `python3` whose `sys.version_info >= (3, 11)` | interpreter for the venv |
| `TLD_BIN_DIR` | `$HOME/.local/bin` | where the `tld` link goes |
| `TLD_BOARD_DIR` | `$HOME/tld-board` | board directory |
| `XDG_DATA_HOME` | `$HOME/.local/share` | data dir is `$XDG_DATA_HOME/tld` |
| `TLD_RELEASE_BASE` (test) | `https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download` | files are `$TLD_RELEASE_BASE/v$VERSION/<name>`; a `file://` base works |
| `TLD_PIP_ARGS` (test) | empty | extra pip arguments (unquoted, word-split on purpose) |
| `TLD_VENV_ARGS` (test) | empty | extra `venv` arguments |

Rules:

- The literal `@TLD_VERSION@` appears exactly once in the file, in `TLD_VERSION="${TLD_VERSION:-@TLD_VERSION@}"`, so the
  release's `sed` stamps only the default. A copy from a checkout is detected by `case "$TLD_VERSION" in *@*) die ... ;; esac`:
  `this copy of install.sh is not from a release: run the one from a release, or set TLD_VERSION=X.Y.Z`. The header comment
  says the file is stamped by the release workflow without writing the token.
- The version is checked with `case`, never `grep`: after dropping one leading `v`, die `invalid version: <value>` unless
  the value is non-empty, has no character outside `0-9` and `.` (a newline or `/` fails here), has no leading, trailing or
  doubled dot, and has exactly two dots (`[ "$(printf %s "$V" | tr -dc . | wc -c)" -eq 2 ]`). The version feeds `rm -rf` and
  the download URL, so nothing else may pass.
- `pick_python`: `${TLD_PYTHON:-}` if non-empty, else the first candidate of the table for which `"$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'` exits 0; none:
  die `need Python 3.11 or newer: install one or set TLD_PYTHON`.
- `fetch NAME DEST`: `curl -fsSL "$BASE/v$VERSION/NAME" -o DEST`; on failure die `cannot download NAME for v<VERSION>
  (a release before the first one with installer assets has none)`.
- `verify FILE`: read the line ending ` FILE` (name only, no path) from the downloaded `SHA256SUMS`, compute the hash
  with `sha256sum` or else `shasum -a 256` (neither: die `need sha256sum or shasum`), no such line: die `no checksum for FILE in SHA256SUMS`; mismatch: die
  `checksum mismatch for FILE: refusing to install`.
- All downloads go into a `mktemp -d` directory removed by an `EXIT` trap.
- **cli**: run `pick_python` first (before any download or `mkdir`); download `tld-$VERSION-py3-none-any.whl` and `SHA256SUMS`, verify the wheel; `mkdir -p "$BIN" "$DATA/venvs"`; `VENV=$DATA/venvs/$VERSION`;
  `rm -rf "$VENV"` (a re-run of the same version rebuilds it); `"$PY" -m venv $TLD_VENV_ARGS "$VENV"` (failure: die `could not create a virtual environment;
  on Debian or Ubuntu install python3-venv`); `"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check
  $TLD_PIP_ARGS "$WHEEL"` (failure: `rm -rf "$VENV"` and die `could not install the wheel into $VENV`); smoke test: `"$VENV/bin/tld" --version` must print exactly `tld $VERSION`, else `rm -rf "$VENV"` and die
  `tld --version printed '<output>', expected 'tld <VERSION>'`. Then the link swap: if `$BIN/tld` exists and is not a symlink, die `$BIN/tld exists and was not
  made by this installer`; remember `OLD=$(readlink "$BIN/tld" 2>/dev/null || true)`; `ln -s "$VENV/bin/tld"
  "$BIN/.tld.$$"` then `mv -f "$BIN/.tld.$$" "$BIN/tld"`; prune every directory in `$DATA/venvs` except `$VERSION`
  and the venv that `OLD` pointed into (kept for rollback). A venv is never moved (its shebangs hold its path). If
  `$BIN` is not on `PATH` print the `export PATH` line. Final message: `tld <VERSION> installed: <BIN>/tld`.
- **uninstall**: remove `$BIN/tld` only if it is a symlink whose target starts with `$DATA/venvs/`; `rm -rf "$DATA"`;
  say that a board directory is untouched and that `docker compose down` in it stops the board (the data volume stays).
- **board**: requires `docker` and `docker compose version` (else die `Docker with the compose plugin is required`).
  Download `compose.yaml` and `SHA256SUMS`, verify; die `compose.yaml is not stamped` if `grep -q 'image: *@'` matches it.
  `mkdir -p "$BOARD_DIR"`; always overwrite `$BOARD_DIR/compose.yaml` (local changes belong in
  `compose.override.yaml`, which compose merges and the installer never touches). If `L=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' tld-board 2>/dev/null)` succeeds
  (written as `if L=$(...); then`, so `set -e` does not exit when no container exists) and `$L` is empty or `<no value>`, die with the migration steps: `a container named
  tld-board made by docker run exists: run docker rm -f tld-board once; the data volume tld-board-data is reused`.
  Create `$BOARD_DIR/.env` only if absent, with `umask 077`, lines `TLD_BOARD_TOKEN=<64 hex chars from od -An -tx1 -N32
  /dev/urandom | tr -d ' \n'>`, `TLD_BOARD_OWNER_PASSPHRASE=`, `TLD_BOARD_PUBLIC_ORIGIN=`,
  `TLD_BOARD_SESSION_URL=https://claude.ai/code/`; never print the token, say where it is. `cd "$BOARD_DIR" && docker compose pull`: on failure die `could not pull the board image; if the message says denied, the package
  ghcr.io/tkcs-lab/tld-board must be made public once by the repository owner (CONTRIBUTING.md, first release)`.
  Start (`docker compose up -d` in `$BOARD_DIR`) only when `.env` has non-empty `TLD_BOARD_OWNER_PASSPHRASE` and
  `TLD_BOARD_PUBLIC_ORIGIN` (checked with `grep -E '^NAME=.+'`); otherwise say which are empty and the command to run
  after filling them, exit 0.

Trust model, stated in SECURITY.md and the docs: `SHA256SUMS` comes from the same release over the same TLS connection,
so it protects against a corrupt or truncated download, not against a tampered release; `install.sh` itself is unverified,
as with every `curl | sh`; PyYAML is installed from PyPI without a hash. The release is made immutable (a manual step)
so assets cannot be replaced after publishing, and the compose file pins the image by digest because a ghcr tag can be
overwritten.

### D4. The release workflow builds and attaches everything (architect option B)

Rejected: a separate `publish.yml` on `release: published` (needs `contents: write` / `packages: write` outside an
environment, which the write-role agent could dispatch from its own branch; leaves `releases/latest` without
`install.sh` for minutes; cannot work with immutable releases) and the same behind a new environment (keeps the
404 window). So `release.yml` keeps its single job `release` (environment `tld-release`, owner approves every run) and
gains job-level `permissions: {contents: read, packages: write}` (`GITHUB_TOKEN` never gets `contents: write`). `secrets.TLD_RELEASE_TOKEN` stays only in the steps that use it today; no new step receives it. New
steps, in this order, between "Check that the commit is green" and "Write the release notes":

1. `Set up Python`: `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5`, `python-version: "3.13"`.
2. `Build the wheel and the sdist`: `python -m pip install build==1.2.2`, `python -m build --outdir dist .`; fail with
   `::error::` unless `dist/tld-$VERSION-py3-none-any.whl` and `dist/tld-$VERSION.tar.gz` exist (`VERSION` from env).
3. `Set up QEMU`: `docker/setup-qemu-action@c7c53464625b32c7a7e944ae62b3e17d2b600130 # v3`.
4. `Set up Buildx`: `docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f # v3`.
5. `Log in to ghcr` (`if: inputs.dry_run == false`): `docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9 # v3`
   with `registry: ghcr.io`, `username: ${{ github.actor }}`, `password: ${{ github.token }}`.
6. `Build the board image` (`id: image`): `docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8 # v6`,
   `context: .`, `file: deploy/board/Dockerfile`, `platforms: linux/amd64,linux/arm64`,
   `push: ${{ inputs.dry_run == false }}`, tags `ghcr.io/${{ github.repository_owner }}/tld-board:${{ steps.version.outputs.version }}`
   and `ghcr.io/${{ github.repository_owner }}/tld-board:latest`. A dry run builds the image and pushes nothing.
7. `Collect the release assets` (env `VERSION`, `IMAGE=ghcr.io/${{ github.repository_owner }}/tld-board`,
   `DIGEST=${{ steps.image.outputs.digest }}`, `DRY_RUN=${{ inputs.dry_run }}`): when `DRY_RUN` is `false` an empty
   `DIGEST` is an `::error::`; when `true` use `sha256:dry-run`. `sed "s/@TLD_VERSION@/$VERSION/" deploy/install.sh >
   dist/install.sh`; `sed "s#@TLD_IMAGE@#$IMAGE@$DIGEST#" deploy/board/compose.yaml > dist/compose.yaml`; fail if
   `grep -l '@TLD_' dist/install.sh dist/compose.yaml` finds anything; `(cd dist && sha256sum
   "tld-$VERSION-py3-none-any.whl" "tld-$VERSION.tar.gz" install.sh compose.yaml > SHA256SUMS)`; append the asset list and the
   image reference to `$GITHUB_STEP_SUMMARY`.

The final step "Publish the tag and the release" keeps the tag creation and replaces the release creation with
`gh release create "$TAG" --verify-tag --draft --repo "$REPO" --title "$TAG" --notes-file release-notes.md dist/*` followed by
`gh release edit "$TAG" --draft=false --repo "$REPO"`, so the release is public complete or not at all. A failed
release can leave an orphan `:<version>` image; a re-run overwrites it. The existing failure message is extended: if the
release was not created, print the two commands to run by hand.

### D5. `deploy/board/compose.yaml` and the Dockerfile

`compose.yaml` (name `tld-board`): service `board`, `image: @TLD_IMAGE@`, `container_name: tld-board`, `restart:
unless-stopped`, `ports: ["127.0.0.1:8787:8787"]`, `env_file: .env`, volume `data:/data`; top-level `volumes: data: {name:
tld-board-data}` so an existing `docker run -v tld-board-data:/data` volume is reused. The Dockerfile gains `LABEL`s
`org.opencontainers.image.source="https://github.com/tkcs-lab/tkcs-lab-devflow"`, `...description`, `...licenses="Apache-2.0"`
(links the ghcr package to the repository). Base image digest pinning is left to Dependabot (Risks).

### D6. Workflow permission rule (replaces "no job permissions")

`tests/core/test_ci_workflows.py::test_actions_are_pinned_and_permissions_read_only` becomes: top-level `permissions`
stay `{contents: read}` in every workflow; a job may have its own `permissions` only if it has `environment: tld-release`
and every entry is one of `contents: read`, `packages: write`, `id-token: write`, `attestations: write`; actions stay
pinned to a 40-hex SHA.

### D7. Docs

README install section and `docs/guides/delivery.md` lead with the curl lines (CLI, board, pin, uninstall, pip-from-wheel
alternative, the PyPI warning); `docs/guides/board-server.md` gets a Compose section and its "Deploy it" steps use the
installer (the `docker build` path stays for development); `CONTRIBUTING.md` (Versions and releases) gets the one-time
steps (immutable releases, ghcr package public) and the new assets; `SECURITY.md` gets the installer trust model;
`docs/architecture/hooks.md` (section plan-gate) says the expanded-command shape opens the session; CHANGELOG gets the
Added and Fixed entries. No ADR directory exists, so no ADRs.

## ADRs

None (`docs.adr_dir` is not set).

## Manual steps

### mb0-second-user: Second GitHub user ready (about 30 minutes, only if not already done)

Before implementation. Follow the checklist in
[docs/reference/profile-reference.md](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/plan/curl-release/docs/reference/profile-reference.md#second-github-user):

1. Create the second GitHub user (own email, 2FA on) and put it on the team plan seat.
2. Invite it to the repository with Write (not Admin, not Maintain) at https://github.com/tkcs-lab/tkcs-lab-devflow/settings/access.
3. Make sure the ruleset on `main` requires a pull request, Code Owner review, one approval, stale-approval dismissal and
   approval of the latest push: https://github.com/tkcs-lab/tkcs-lab-devflow/settings/rules.
4. Add `.github/CODEOWNERS` with the single line `* @andras-tkcs` (the file does not exist yet) in a small pull request and merge it, so the Code Owner review of step 3 gates something.
5. On https://claude.ai/connect-github replace the connected account with the second login, enable the repository in that
   account's environment settings, open a session and ask for its GitHub identity.
6. Check that nobody is on the ruleset's bypass list, that force pushes and deletions of `main` are blocked, and that the Claude GitHub App is installed on the repository: https://github.com/apps/claude/installations/select_target.

Done when `identity()` in a new session returns `andras-tkcs-agent` and the main branch requires a Code Owner review.

### ma1-first-release: Release, publish and verify (about 40 minutes)

After implementation. These steps need the merged code on `main` (the release workflow runs only there), so they are
done **after the pull request is merged**; report the result as a pass/fail line on the tracking issue. `ma1` is therefore unchecked in the pull request when it merges.

1. Turn on immutable releases: https://github.com/tkcs-lab/tkcs-lab-devflow/settings (General, section Releases, "Enable
   release immutability"). Do this before the release; it applies to releases created afterwards.
2. In a pull request (a session can open it; only the merge is yours) bump `1.0.0` to `1.1.0` in `pyproject.toml`, `.claude-plugin/plugin.json` and `src/tld/__init__.py`,
   and turn the `## [Unreleased]` heading of `CHANGELOG.md` into `## [1.1.0] - <date>`; merge it.
3. Run https://github.com/tkcs-lab/tkcs-lab-devflow/actions/workflows/release.yml on `main` with `dry_run` ticked; approve the
   `tld-release` environment; read the job summary: tag `v1.1.0`, the five assets, the image reference.
4. Run it again with `dry_run` unticked and approve. Expect release `v1.1.0` with five assets and the image
   `ghcr.io/tkcs-lab/tld-board:1.1.0` (2 platforms).
5. Make the image public: https://github.com/orgs/tkcs-lab/packages/container/tld-board/settings, "Change visibility", Public
   (the organisation must allow public packages: https://github.com/organizations/tkcs-lab/settings/packages). Check with
   `docker pull ghcr.io/tkcs-lab/tld-board:1.1.0` while logged out of ghcr.
6. On a clean machine run `curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh`
   and `tld --version` (expect `tld 1.1.0`); run the line again (expect the same, no error); run it with `sh -s -- board`, fill
   `TLD_BOARD_OWNER_PASSPHRASE` and `TLD_BOARD_PUBLIC_ORIGIN` in `~/tld-board/.env`, run `docker compose up -d` there and open
   `/healthz`.
7. Report back: `ma1 pass` or `ma1 fail: <step and message>`.

The workflow cannot be dispatched from a branch (it exists only on `main`), which is why nothing here can be checked earlier;
the phases test the steps' shell and the installer offline.

## Risks and open questions

- **The plan-gate fix is built from one observed prompt shape** (D0). The real hook payload was not captured. Sign it is wrong:
  after the merge a session started with a slash command is still denied writes. The fallback is typing the slash command as
  the first characters of the message, or `hooks.disable: [plan-gate]` in the profile.
- **claude.ai may refuse `cli/` as it refused `bin/`** (sync error `marketplace_sync_bin_directory_not_allowed`). A worker
  cannot check this; `claude plugin validate .` in CI is the nearest check. Sign: a marketplace sync error after the merge.
- **`gh release create --draft` with files, then `gh release edit --draft=false`** must publish with all assets. Not testable
  offline (the test asserts the command text only); the dry run and the real run in `ma1` are the first real check.
- **The ghcr package is private on first push**; `ma1` step 5 and the installer's denied-pull message cover it.
- **Ubuntu 22.04 has Python 3.10 and Debian lacks `python3-venv`**; `TLD_PYTHON` and the error texts cover it.
- **Base image unpinned** (`python:3.13-slim`): add Dependabot docker updates in a later change; not done here because no
  digest can be resolved offline.
- **`.github/workflows/**` is not in the protect lists**; an agent-pushed branch could ask for write permissions in a workflow
  it controls. Immutable releases plus digest pinning limit the harm; protecting the path is a separate decision for the owner.
- **PyYAML is not hash-pinned** in the installed venv; stated in SECURITY.md.
- **The CLI wheel contains only `src/tld`** (no playbooks, roles or stacks), exactly like `pip install git+...` today.
- Only the release workflow builds a real wheel (it needs network for build isolation); no test may need the network.

## Implementation manifest

```yaml
plan_slug: curl-release
feature_branch: feature/curl-release
tracking_issue: 15
max_parallel: 1
manual_before:
  - id: mb0-second-user
    title: Second GitHub user ready
    why: The agent opens PRs as git.bot_login and the code owner's review is the gate
    done_when: identity() in a new session returns andras-tkcs-agent and the main branch requires a Code Owner review
manual_after:
  - id: ma1-first-release
    title: Release 1.1.0, make the image public, verify both curl installs
    why: The release workflow, ghcr and the installer on a clean machine run only on main and with real credentials; CI cannot do it
    done_when: tld --version prints tld 1.1.0 after the curl line, a second run of the line succeeds, and the board answers /healthz
verify_after_merge:
  - .venv/bin/python -m pytest tests/adapters/claude/test_hooks_prompt.py tests/core/test_repo_release.py tests/core/test_ci_workflows.py tests/core/test_board_deploy.py tests/core/test_no_project_words.py tests/core/test_contracts.py -q
  - python3 evals/run.py check-baseline
final_checks:
  - docs/plans/curl-release-plan.md is deleted and nothing links to it
  - the changelog has entries under Unreleased and no `## [1.1.0]` heading
  - "`cli/tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
phases:
  - id: p1-plan-gate-fix
    title: The plan-gate opens on an expanded slash command
    depends_on: []
    complexity: S
    touches:
      - adapters/claude/hooks/claude_adapter.py
      - tests/adapters/claude/test_hooks_prompt.py
      - docs/architecture/hooks.md
    brief: |
      Read first: docs/architecture/hooks.md (section plan-gate), tests/adapters/claude/test_hooks_prompt.py.
      Implement Design D0.
      1. In `adapters/claude/hooks/claude_adapter.py` next to `INVOKED` (line 36) add two compiled patterns: `REMINDER = re.compile(r"\A\s*<system-reminder>.*?</system-reminder>\s*", re.S)`
         and `EXPANDED = re.compile(r"\A\s*(?:<command-message>[^<]*</command-message>\s*)?<command-name>/(?:tld:)?([a-z][a-z-]*)</command-name>")`.
      2. Change `invoked_command(prompt)` (line 60): first try `INVOKED` on the prompt as today; if it does not match, strip leading `REMINDER`
         blocks in a loop (`while (m := REMINDER.match(text)): text = text[m.end():]`, stop when none matches) and try `INVOKED` and then `EXPANDED` on the rest.
         The group must still be in `known_commands()`, else return None. Update the docstring with the two accepted shapes.
      3. In `tests/adapters/claude/test_hooks_prompt.py` add a module constant `EXPANDED_PROMPT` (the observed shape, newlines included):
         `"<system-reminder>\nx\n</system-reminder>\n<system-reminder>\ny\n</system-reminder>\n<command-message>tld:make-plan</command-message>\n<command-name>/tld:make-plan</command-name>\n<command-args>a\nb</command-args>"`.
         Add these tests, one behaviour each, the unit tests after `test_invoked_command_reads_the_typed_line`, the last one after
         `test_opening_prompt_opens_then_write_is_allowed`: `test_expanded_command_with_reminders_is_invoked` (EXPANDED_PROMPT gives `"make-plan"`);
         `test_expanded_command_without_message_is_invoked` (`<command-name>/tld:make-plan</command-name>` alone, and `<command-name>/make-plan</command-name>`, both `"make-plan"`);
         `test_reminder_then_typed_slash_command_is_invoked` (`<system-reminder>x</system-reminder>/tld:make-plan a`);
         `test_command_name_later_in_the_text_is_not_invoked` (`"hello <command-name>/tld:make-plan</command-name>"` is None);
         `test_unknown_expanded_command_is_none` (`<command-name>/tld:nope</command-name>`);
         `test_command_name_inside_a_reminder_is_not_invoked` (`<system-reminder>x <command-name>/tld:make-plan</command-name></system-reminder>hello`
         and the unclosed `<system-reminder>x<command-name>/tld:make-plan</command-name>`, both None);
         `test_reminder_then_prose_is_not_invoked` (`<system-reminder>x</system-reminder>please /tld:make-plan` is None);
         `test_expanded_prompt_opens_then_write_is_allowed`, a copy of `test_opening_prompt_opens_then_write_is_allowed` (lines 87-92):
         `repo = make_repo(tmp_path / "r", "feature/demo", ON)`, `write = event("Write", repo, file_path=str(repo / "a.txt"), content="x")`,
         `assert gate(repo, write).code == 2`, `assert gate(repo, prompt_event(repo, EXPANDED_PROMPT)) == ca.Result(0)`, `assert gate(repo, write).code == 0`.
      4. In `docs/architecture/hooks.md` section plan-gate add one sentence after the sentence that says a prompt starting with a tld command opens the session: the
         prompt may also arrive expanded (`<command-name>/tld:<name></command-name>` after any leading `<system-reminder>` blocks), which opens it too;
         add that a literal `</system-reminder>` inside reminder text cannot be told apart, accepted because the marker is a deliberate step, not a control.
      5. Run `.venv/bin/python -m pytest tests/adapters/claude -q`, then `.venv/bin/python -m pytest tests -q`.
      Stop condition: if an existing test asserts that a prompt starting with `<` is not an invocation, stop with `status=blocked` and name it.
      Report `docs-changed:` lines: none.
    acceptance:
      - ".venv/bin/python -m pytest tests/adapters/claude/test_hooks_prompt.py -q passes"
      - ".venv/bin/python -m pytest tests -q passes"
      - "grep -n 'EXPANDED' adapters/claude/hooks/claude_adapter.py matches"
  - id: p2-rename-cli
    title: Rename launcher/ to cli/ everywhere
    depends_on: [p1-plan-gate-fix]
    complexity: M
    touches:
      - launcher/**
      - cli/**
      - adapters/**
      - playbooks/runtime.md
      - src/tld/guard/integrity.py
      - tests/**
      - evals/**
      - .github/workflows/test.yml
      - .tld/toolkit.yaml
      - .tld/admin-policy.yaml
      - pyproject.toml
      - README.md
      - CONTRIBUTING.md
      - CHANGELOG.md
      - docs/architecture/**
      - docs/guides/**
      - docs/reference/cli.md
      - docs/migrating-privacyfence.md
    brief: |
      Read first: docs/architecture/hooks.md, docs/reference/cli.md, CONTRIBUTING.md (Baseline refresh).
      This phase is purely mechanical (it exceeds the file count of a normal M phase on purpose; every edit is the same
      substitution). The template is commit f48d389 (the earlier rename, same file set).
      1. `git mv launcher cli`.
      2. Replace every `launcher/tld` with `cli/tld` in all tracked files except `docs/plans/**` and `AGENTS.md`
         (the entry file is edited only by the last phase): `git grep -l 'launcher/tld' -- . ':!docs/plans' ':!AGENTS.md' | xargs sed -i 's#launcher/tld#cli/tld#g'`.
      3. In `src/tld/guard/integrity.py` rename `PLUGIN_LAUNCHERS` to `PLUGIN_CLI_PATHS` and `is_tld_launcher` to `is_tld_cli`
         (lines 39, 42, 49, 59 and its docstring; the paths inside are already handled by step 2); update
         `tests/mutation/mutants.yaml:403` (`PLUGIN_LAUNCHERS` to `PLUGIN_CLI_PATHS`) and any test that imports the old names
         (`git grep -n 'PLUGIN_LAUNCHERS\|is_tld_launcher' -- . ':!docs/plans'` must find nothing afterwards).
      4. Replace the remaining quoted directory names: `tests/core/test_no_project_words.py:5` (`"launcher"` to `"cli"`),
         `evals/harness/common.py:19` (`"launcher"` to `"cli"`) and its comment line 17 ("the launcher" to "the CLI script"),
         `tests/conftest.py:14` (`"launcher"` to `"cli"`, comment "the CLI script; runs without installing the package") and
         the docstring at line 69 ("through the launcher" to "through the CLI script"), `.tld/toolkit.yaml:37`
         (`launcher/` to `cli/`), `tests/core/guard_cases.yaml:192` `docs/architecture/evals.md:106`, `README.md:93` and `docs/architecture/hooks-parsing.md:24` (prose "launcher" to "CLI script").
         Afterwards `git grep -n -i launcher -- . ':!docs/plans' ':!AGENTS.md' ':!CHANGELOG.md' ':!tests/core/test_guard_cli_paths.py'` must print nothing.
      5. `CHANGELOG.md`: replace the Unreleased `### Changed` bullet with: "The CLI entry script moved from `bin/tld` to `cli/tld`:
         claude.ai refuses to sync a plugin with a top-level `bin/` directory. A session that was open during the plugin sync may
         need a restart. Call `cli/tld` from a checkout; the installed `tld` command is unchanged." The 1.0.0 Added bullet (CHANGELOG.md:51) is history:
         step 2 made it `cli/tld`; change it back to `bin/tld`, as it was released.
      6. Add `tests/core/test_guard_cli_paths.py` (new): `test_every_plugin_cli_path_exists` (each entry of
         `tld.guard.integrity.PLUGIN_CLI_PATHS` with `${CLAUDE_PLUGIN_ROOT}` and `$CLAUDE_PLUGIN_ROOT` replaced by `str(ROOT)` is an
         existing file) and `test_is_tld_cli_accepts_the_new_path_and_rejects_the_old` (`is_tld_cli('"${CLAUDE_PLUGIN_ROOT}/cli/tld"')`
         is true, and the same call with the old path built as `"${CLAUDE_PLUGIN_ROOT}/" + "launcher" + "/tld"` is false, so this file never contains
         the old path as one string; the signature is `is_tld_cli(word, command="")`; no existing test calls it directly).
      7. Refresh the eval hashes only (the command wrappers changed only by this path): `python3 evals/run.py baseline --refresh-hashes`;
         say so in the commit message.
      8. Run `.venv/bin/python -m pytest tests -q` and `python3 evals/run.py check-baseline`.
      Stop condition: if a file under `docs/plans/` or `AGENTS.md` is the only remaining match of `git grep -n launcher/tld`, that is correct.
      If a test fails for a reason other than the name, stop with `status=blocked` and report it.
      Report `docs-changed:` lines: none expected.
    acceptance:
      - "git grep -n 'launcher/tld' -- . ':!docs/plans' ':!AGENTS.md' prints nothing"
      - "git grep -n 'PLUGIN_LAUNCHERS\\|is_tld_launcher' -- . ':!docs/plans' prints nothing"
      - "git grep -n -i launcher -- . ':!docs/plans' ':!AGENTS.md' ':!CHANGELOG.md' ':!tests/core/test_guard_cli_paths.py' prints nothing"
      - "test -x cli/tld && test ! -e launcher"
      - ".venv/bin/python -m pytest tests/core/test_guard_cli_paths.py -q passes"
      - ".venv/bin/python -m pytest tests -q passes"
      - "python3 evals/run.py check-baseline exits 0"
  - id: p3-installer
    title: The curl installer, the compose file and the image labels
    depends_on: [p2-rename-cli]
    complexity: M
    touches:
      - deploy/install.sh
      - deploy/board/compose.yaml
      - deploy/board/Dockerfile
      - tests/core/test_install_sh.py
      - tests/core/test_board_deploy.py
    brief: |
      Read first: docs/guides/board-server.md (sections Docker, Deploy it), tests/core/test_board_deploy.py, tests/conftest.py (`need_tool`, the autouse environment fixture).
      Implement Design D3 and D5 exactly; messages are quoted there.
      1. Create `deploy/install.sh` (mode 0755, `#!/bin/sh`, `set -eu`) following D3: functions `say`, `die`, `fetch`, `verify`,
         `pick_python`, `install_cli`, `uninstall_cli`, `install_board`, and a `case "${1:-cli}"` dispatcher at the end. Header comment lists
         the variables of the D3 table, marks the last three as test hooks, and says the file is stamped by the release workflow (without
         writing the token). The literal `@TLD_VERSION@` appears exactly once (D3) and no other `@TLD_` appears in the file.
         Use only POSIX sh (no arrays, no `local`, no `[[ ]]`, no `echo -e`).
      2. Create `deploy/board/compose.yaml` per D5 with the literal `@TLD_IMAGE@` as the image (its only `@TLD_`).
      3. In `deploy/board/Dockerfile` add after the `FROM` line the three `LABEL` lines of D5.
      4. In `tests/core/test_board_deploy.py`: in `test_dockerfile_basics` assert the three labels (`org.opencontainers.image.source` equals the
         repository URL); add `test_compose_file_shape` (`yaml.safe_load`): `name == "tld-board"`, `services.board.image == "@TLD_IMAGE@"`,
         `container_name == "tld-board"`, `restart == "unless-stopped"`, `ports == ["127.0.0.1:8787:8787"]`, `env_file` is `.env`,
         `volumes == ["data:/data"]`, top-level `volumes.data.name == "tld-board-data"`, and no `environment` key holds a `TLD_BOARD_TOKEN`.
      5. Create `tests/core/test_install_sh.py`, marked `@pytest.mark.slow`; it needs `sh`, `curl` and `sed` (`need_tool`). No setuptools, no network.
         Helpers:
         - `make_release(root, version, printed=None, stamp_compose=True)` writes `root/v<version>/` holding: a wheel `tld-<version>-py3-none-any.whl` written with `zipfile`
           (`tld/__init__.py` with `def main(): import sys; print("tld <printed or version>") if sys.argv[1:] == ["--version"] else None`,
           `tld-<version>.dist-info/METADATA` (`Metadata-Version: 2.1`, `Name: tld`, `Version: <version>`), `WHEEL` (`Wheel-Version: 1.0`, `Generator: test`,
           `Root-Is-Purelib: true`, `Tag: py3-none-any`), `entry_points.txt` (`[console_scripts]` and `tld = tld:main`) and a `RECORD` whose lines are
           `<path>,sha256=<urlsafe-base64 without padding>,<size>` plus `tld-<version>.dist-info/RECORD,,`); the stamped installer made by running
           `sed "s/@TLD_VERSION@/<version>/" deploy/install.sh` (the same command as the release workflow); `compose.yaml` made by
           `sed "s#@TLD_IMAGE@#registry.invalid/tld-board@sha256:abc#" deploy/board/compose.yaml`; and `SHA256SUMS` with lines exactly `f"{sha256}  {name}\n"`
           for the wheel, `install.sh` and `compose.yaml`.
         - fixture `release` (module scope) builds 9.9.7, 9.9.8 and 9.9.9 under one directory. A test that changes a release first copies it with `shutil.copytree` into `tmp_path`.
         - `run_installer(tmp_path, args, release_dir, script, **env)` (`script` is `release_dir/v<version>/install.sh` or, for the unstamped tests, `deploy/install.sh`) builds the environment from scratch (never from `os.environ`): `PATH` = a fake-tools directory
           + `/usr/bin:/bin`, and `HOME`, `XDG_DATA_HOME`, `TLD_BIN_DIR`, `TLD_BOARD_DIR`, `TMPDIR` all under `tmp_path`; `TLD_PYTHON=sys.executable` (an override of `None` drops a key, so `TLD_PYTHON=None` removes it),
           `TLD_RELEASE_BASE=file://<release_dir>`, `TLD_PIP_ARGS='--no-index --no-deps'`, `PIP_NO_INDEX=1`, `http_proxy`, `https_proxy` and `HTTPS_PROXY` =
           `http://127.0.0.1:9`; runs `sh <script>`; returns the completed process.
         - a fake `docker` script (written into the fake-tools directory) that appends its arguments to `docker.log`, exits `$FAKE_COMPOSE_EXIT` (default 0) for `compose version`, and for
           `inspect` exits with `$FAKE_INSPECT_EXIT` (default 1) printing `$FAKE_INSPECT_LABEL`; `pull` exits with `$FAKE_PULL_EXIT` (default 0).
         Tests, one behaviour each: `test_run_installer_env_is_confined` (the env's keys are exactly PATH, HOME, XDG_DATA_HOME, TLD_BIN_DIR, TLD_BOARD_DIR, TMPDIR, TLD_PYTHON, TLD_RELEASE_BASE, TLD_PIP_ARGS, PIP_NO_INDEX, http_proxy, https_proxy and HTTPS_PROXY plus the test's overrides; the five directory variables are under `tmp_path`; PATH is exactly `<fake-tools>:/usr/bin:/bin`);
         `test_cli_install_links_a_working_tld`; `test_rerun_of_the_same_version_keeps_a_working_tld` (install 9.9.9 twice: second exit 0, `tld --version`
         prints `tld 9.9.9`, `venvs/` holds exactly `{9.9.9}`); `test_second_run_replaces_the_link_and_keeps_one_previous_venv` (9.9.8 then 9.9.9, both venv dirs
         exist, the link points into 9.9.9); `test_install_prunes_all_but_current_and_previous` (9.9.7, 9.9.8, 9.9.9 in order: `venvs/` is exactly `{9.9.8, 9.9.9}`);
         `test_failed_smoke_test_removes_the_venv_and_keeps_the_old_link` (9.9.8 installed, then `make_release(tmp_path / "bad", "9.9.9", printed="0.0.0")`, which has matching checksums: exit 1, `expected 'tld 9.9.9'` in stderr and `checksum mismatch` not,
         no `venvs/9.9.9`, the link still points into 9.9.8); `test_checksum_mismatch_is_refused_and_nothing_is_linked` (copied release, wheel altered, stderr has `checksum mismatch for tld-9.9.9-py3-none-any.whl: refusing to install`, earlier 9.9.8
         link survives, no `venvs/9.9.9`); `test_missing_checksum_line_is_refused` (`no checksum for tld-9.9.9-py3-none-any.whl` in stderr); `test_unstamped_copy_refuses` (run `deploy/install.sh` itself);
         `test_unstamped_copy_with_tld_version_installs` (`deploy/install.sh` with `TLD_VERSION=9.9.9`); `test_leading_v_is_dropped` (`TLD_VERSION=v9.9.9`);
         `test_invalid_version_refused` parametrized over `1.2`, `1.2.3-rc1`, `../../x`, `9.9.9/../..`, `"9.9.9\nx"`, `" 9.9.9"`, `1..2`, `.9.9`, `9.9.`, `vv9.9.9`, `9.9.9.9`: exit 1, `invalid version:` in
         stderr, the data directory does not exist afterwards; `test_existing_regular_file_is_not_overwritten`; `test_uninstall_removes_link_and_data` (a file
         in `TLD_BOARD_DIR` survives); `test_uninstall_leaves_a_foreign_tld` parametrized over a regular file and a symlink to `/usr/bin/true` (unchanged, data dir removed);
         `test_unknown_mode_exits_2`; `test_missing_release_says_no_assets`; `test_old_python3_only_is_refused` (no `TLD_PYTHON`; fakes named `python3.13`, `python3.12`, `python3.11` and `python3` in the fake-tools directory, each exiting 1: exit 1, `need Python 3.11 or newer` in stderr, no `venvs/` directory);
         `test_venv_failure_names_python3_venv` (`TLD_PYTHON` is a script that exits 1); `test_path_hint_only_when_bin_is_not_on_path`; `test_temp_dir_is_removed`
         (`TMPDIR` is empty after a success and after a failure); `test_pip_failure_removes_the_venv` (`TLD_PIP_ARGS='--no-index --no-deps --no-such-option'`: exit 1, `could not install the wheel` in stderr, no `venvs/9.9.9`, an earlier link unchanged).
         Board tests: `test_board_creates_env_once_with_mode_0600_and_does_not_print_the_token` (the token line matches `^TLD_BOARD_TOKEN=[0-9a-f]{64}$`, the token
         is in neither stdout, stderr nor `docker.log`, a second run leaves `.env` byte-identical); parametrized `test_board_does_not_start_without_passphrase_and_origin`
         (only passphrase, only origin, neither: no `up` in the log, exit 0, the message names the empty variables); `test_board_starts_when_both_are_set` (pre-seeded
         `.env`; `pull` comes before `up -d` in the log); `test_board_refuses_a_docker_run_container` parametrized over an empty label and `<no value>` (`inspect` exits 0 printing it; `docker rm -f tld-board` in stderr); `test_board_upgrade_with_a_compose_container_proceeds`
         (`inspect` exits 0 printing `tld-board`: exit 0, `pull` in the log); `test_board_denied_pull_prints_the_visibility_hint` (and no `up` in the log);
         `test_board_keeps_compose_override_and_overwrites_compose_yaml`; `test_board_checksum_mismatch_keeps_the_old_compose_yaml`; `test_board_unstamped_compose_refuses` (`make_release(..., stamp_compose=False)`, checksums over the actual file: exit 1, `compose.yaml is not stamped` in stderr, `checksum mismatch` not, no `pull` in the log);
         `test_board_without_compose_plugin_refuses` (`FAKE_COMPOSE_EXIT=1`: `Docker with the compose plugin is required` in stderr, no `pull` in the log).
      6. Run the new tests, then `.venv/bin/python -m pytest tests/core -q`.
      Stop condition: if `python -m venv` cannot create a venv with pip in the test environment (no ensurepip), stop with `status=blocked`; do not make a test use the network.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_install_sh.py -q passes"
      - ".venv/bin/python -m pytest tests/core/test_board_deploy.py -q passes"
      - "sh -n deploy/install.sh exits 0"
      - "grep -c '@TLD_' deploy/install.sh prints 1, and grep -c '@TLD_' deploy/board/compose.yaml prints 1"
      - "test -x deploy/install.sh"
  - id: p4-release-workflow
    title: Build the assets and the image inside the release workflow
    depends_on: [p3-installer]
    complexity: M
    touches:
      - .github/workflows/release.yml
      - tests/core/test_ci_workflows.py
      - tests/core/test_repo_release.py
    brief: |
      Read first: .github/workflows/release.yml, tests/core/test_repo_release.py, tests/core/test_release_workflow.py, tests/core/test_ci_workflows.py, SECURITY.md (threat model), deploy/install.sh.
      Implement Design D4 and D6.
      1. In `.github/workflows/release.yml` add to job `release` the job-level `permissions: {contents: read, packages: write}` and the seven
         steps of D4 in the stated order and with the stated action SHAs, between "Check that the commit is green" and "Write the release notes".
         Pass every value into `run:` through `env:` (no `${{` inside any `run:`); `secrets.TLD_RELEASE_TOKEN` stays only in the steps that have it today.
         Update the header comment: what the workflow now builds and why the order is image, then tag, then draft release, then publish; and replace the sentence
         "the workflow's GITHUB_TOKEN only reads" by "the workflow's GITHUB_TOKEN reads, and writes only packages (the board image)".
      2. Replace the release creation in "Publish the tag and the release" by the draft create of D4 (with `--repo "$REPO"` and `dist/*`) and the
         `gh release edit "$TAG" --draft=false --repo "$REPO"` call; extend the failure message with the two manual commands.
      3. In `tests/core/test_ci_workflows.py` factor the rule of D6 into `permission_problems(doc) -> list[str]` and make
         `test_actions_are_pinned_and_permissions_read_only` assert it is empty for every workflow (keep the pinned-SHA assertion). Add
         `test_permission_rule_rejects` (parametrized synthetic documents, each returns a problem: job `permissions` without `environment`; `environment: other`;
         `contents: write`; `packages: write` with `issues: write`; top-level `permissions: write-all`; job `permissions: write-all` under `environment: tld-release`; top-level `{contents: read, packages: write}`; no top-level `permissions` key; none may raise) and `test_permission_rule_accepts_the_release_job` (the D4 shape returns `[]`).
      4. In `tests/core/test_repo_release.py` add, using `run_version_step`'s environment pattern (line 53: `GITHUB_STEP_SUMMARY` a temp file, `PATH=/usr/bin:/bin`):
         `test_image_is_built_before_the_tag_and_pushed_only_when_not_a_dry_run` (step order by index; build step `with.push == "${{ inputs.dry_run == false }}"`;
         login step `if == "inputs.dry_run == false"`); `test_build_step_has_platforms_tags_and_file` (`linux/amd64,linux/arm64`, both tags, `deploy/board/Dockerfile`);
         `test_new_actions_are_the_pinned_shas_of_d4`; `test_job_permissions_are_exactly_contents_read_and_packages_write`;
         `test_release_token_is_only_in_the_steps_that_use_it_today` (`secrets.TLD_RELEASE_TOKEN` appears only in "Check that the commit is green", "Write the release notes" and "Publish the tag and the release");
         `test_publish_creates_a_draft_with_every_asset_then_publishes` (the publish `run` contains `--verify-tag`, `--draft`, `--repo`, `dist/*` and `--draft=false`, and `--draft=false` comes after `release create`);
         `test_build_step_fails_without_the_wheel` (run its `run` with `VERSION=9.9.9` and a fake `python` (its directory before `/usr/bin:/bin` on PATH; it exits 0 for `-m pip install ...`) that creates nothing: non-zero and `::error::`) and `test_build_step_passes_with_both_files` (the fake `python` writes `dist/tld-9.9.9-py3-none-any.whl` and `dist/tld-9.9.9.tar.gz` for `-m build`: exit 0, no `::error::`);
         `test_collect_step_stamps_and_checksums` (run the "Collect the release assets" `run` with `bash` in a temp directory holding copies of `deploy/install.sh` and
         `deploy/board/compose.yaml`, a `dist/` with empty `tld-9.9.9-py3-none-any.whl` and `tld-9.9.9.tar.gz`, env `VERSION=9.9.9`, `IMAGE=ghcr.io/x/tld-board`, `DIGEST=sha256:abc`,
         `DRY_RUN=false`: `dist/` has the five files, neither stamped file contains `@TLD_`, `SHA256SUMS` has exactly four lines naming bare file names, `sha256sum -c SHA256SUMS` passes inside `dist/`,
         and the step's `run` starts with `set -euo pipefail`); variants: `DIGEST=` with `DRY_RUN=false` exits non-zero; `DRY_RUN=true` with an empty digest passes and the compose file contains `sha256:dry-run`;
         a `compose.yaml` holding an extra `@TLD_OTHER@` exits non-zero; and
         `test_stamped_installer_from_the_collect_step_is_not_refused` (after the collect step run `sh dist/install.sh` with an environment written inline, not imported from another test module (`PATH=/usr/bin:/bin`; `HOME`, `XDG_DATA_HOME`, `TLD_BIN_DIR`, `TMPDIR` under `tmp_path`; `TLD_PYTHON=sys.executable`) and `TLD_RELEASE_BASE=file://<empty dir>`: exit 1, `cannot download` in stderr, `not from a release` not in stderr).
      5. Run the three test files, then `.venv/bin/python -m pytest tests -q`.
      Stop condition: if `docker/build-push-action` does not output `digest` (check `steps.image.outputs.digest` against the action's README
      linked from its tag in the workflow comment), stop with `status=blocked`; do not invent another way to read the digest. If the collect-step test fails because `deploy/install.sh`
      or `compose.yaml` holds an `@TLD_` token other than the two stamped ones, stop with `status=blocked` (that is a p3 defect).
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_repo_release.py tests/core/test_ci_workflows.py -q passes"
      - ".venv/bin/python -m pytest tests -q passes"
      - "grep -c 'uses: .*@[0-9a-f]\\{40\\}' .github/workflows/release.yml reports at least 6"
  - id: p5-retire-docs
    title: Docs, changelog, entry file and plan retirement
    depends_on: [p4-release-workflow]
    complexity: M
    touches:
      - README.md
      - docs/guides/delivery.md
      - docs/guides/board-server.md
      - CONTRIBUTING.md
      - SECURITY.md
      - CHANGELOG.md
      - AGENTS.md
      - docs/README.md
      - docs/plans/curl-release-plan.md
      - tests/core/test_install_sh.py
    brief: |
      Read first: README.md (Install), docs/guides/delivery.md, docs/guides/board-server.md (Docker, Deploy it), CONTRIBUTING.md (Versions and releases), SECURITY.md, docs/guides/docs-index.md.
      Implement Design D7; the texts of the commands are in D2, D3 and the plan's goal.
      1. README.md: in "Install" replace the `pip install git+...` block by the two curl lines of the Goal, then one paragraph: pin with the release's own installer (`.../releases/download/vX.Y.Z/install.sh | sh`, the line of the Goal),
         uninstall with `sh -s -- uninstall`, the pip-from-wheel alternative, and "do not `pip install tld`: that name on PyPI is another package".
      2. docs/guides/delivery.md: rewrite "The command line", "Versions" and "Uninstall": the curl lines, what the installer does (private venv per version
         under `~/.local/share/tld/venvs`, link in `~/.local/bin`, previous venv kept for rollback), upgrade = run the line again, the release assets table of D2,
         that a release before 1.1.0 has no assets (`TLD_VERSION=1.0.0` fails with the no-assets message).
      3. docs/guides/board-server.md: add a section "Docker Compose (the installer)" before "TLS and a reverse proxy": the `| sh -s -- board` line, the files in
         `~/tld-board` (`compose.yaml` overwritten on upgrade, `.env` kept, `compose.override.yaml` yours), filling `.env`, start/upgrade/stop commands, adopting the
         volume `tld-board-data`, the old-container migration message; change "Deploy it" steps 1 and 3 to use the installer and keep the `docker build` path under
         "Docker" as the development route. No image digest or token-like value (32 or more of `[A-Za-z0-9_-]`) goes into the text: `test_doc_has_no_token_looking_value` rejects it.
      4. CONTRIBUTING.md "Versions and releases": list the five release assets, that the workflow also builds and pushes the image before the tag, the one-time
         steps (enable release immutability; make the ghcr package public after the first push) and that the dry run builds without pushing; replace the sentence "The workflow's own token only reads." (line 96) by "The workflow's own token reads, and writes only packages (the board image)."
      5. SECURITY.md: a short section "The curl installer" with the trust model of D3 (integrity not authenticity, install.sh unverified, PyYAML not hash-pinned,
         immutable releases, image pinned by digest) and the exception that the release job holds `packages: write` behind the `tld-release` environment.
      6. CHANGELOG.md under `## [Unreleased]`: append a bullet to the existing `### Added` (the curl installer for the CLI and the board, the release assets and the multi-arch image on ghcr) and one to the existing `### Fixed` (the
         plan-gate now opens when a slash command reaches the hook expanded).
      7. AGENTS.md (entry file, keep under 60 lines): line 10 becomes ``- `cli/tld` - the CLI script (`tld <group> <command>`, `tld migrate`; see [docs/reference/cli.md](docs/reference/cli.md))``; on line 14 replace ``` `deploy/` - board image``` by ``` `deploy/` - board image, compose file, installer```; every other `launcher` mention (Rules, Commands) becomes `cli` or `cli/tld`.
         Add `test_docs_name_every_installer_variable` to `tests/core/test_install_sh.py`: every `TLD_*` name `deploy/install.sh` reads appears in `docs/guides/delivery.md` or `docs/guides/board-server.md` (follow `test_doc_names_every_variable_and_tool`).
      8. docs/README.md: update the delivery.md row text to "installing the plugin, the CLI and the board with the curl installer, releases and `tld.version` pinning". No new doc, so no new row.
      9. `git rm docs/plans/curl-release-plan.md` and make sure nothing links to it.
      10. Run `cli/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, then `.venv/bin/python -m pytest tests -q`.
      Stop condition: if the docs index check reports an error on a doc this phase did not touch, stop with `status=blocked` and name it.
    acceptance:
      - "cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - "test ! -e docs/plans/curl-release-plan.md"
      - "git grep -n curl-release-plan prints nothing"
      - "grep -n 'releases/latest/download/install.sh' README.md docs/guides/delivery.md docs/guides/board-server.md reports a line in each file"
      - "grep -c 'launcher' AGENTS.md reports 0"
      - "wc -l AGENTS.md reports at most 60 lines"
      - ".venv/bin/python -m pytest tests -q passes"
```
