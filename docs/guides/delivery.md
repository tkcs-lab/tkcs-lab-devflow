# Delivery: getting tld into a session

tld reaches a session in two ways: the Claude Code plugin `tld` (commands, agents, the runtime skill and the
hooks, with the whole core beside them) and the Python package (the `tld` command line, for scripts, CI and
`tld migrate` from a plain checkout). Both come from this repository, `tkcs-lab/tkcs-lab-devflow`.

## Claude Project plugins

A cloud session (claude.ai/code) does **not** install plugins that a repository enables through its
`.claude/settings.json`. Add the plugin in the Claude Project instead.

1. In claude.ai, open the Claude Project the repository's sessions belong to, and its settings.
2. Add the marketplace `tkcs-lab/tkcs-lab-devflow` (GitHub repository source).
3. Enable `tld`. The playbooks, role cards, checklists and stack guides ship inside it; the profile's `stacks`
   selects the guides.
4. Commit `.tld/toolkit.yaml` to the repository ([profile-reference.md](../reference/profile-reference.md)). Plugins
   are enabled per Project, so add a profile to **every** repository in the Project, even a minimal one with at
   least `git.main_branch`: without it the guardrail hooks deny every `git push` there.
5. In a new session the commands are `/tld:<cmd>` (`/tld:setup`, `/tld:make-plan`, ...), the skills and agents
   `tld:<name>` (`tld:runtime`, `tld:code-reviewer`). The hooks load with the plugin and need `python3` 3.11+ and
   PyYAML in the session (without PyYAML they behave as if there were no profile); see
   [hooks.md](../architecture/hooks.md#installing-and-checking) for how to confirm they are active.

The plugin is the whole repository (its source is the root), so Claude Code sets `CLAUDE_PLUGIN_ROOT` to a copy
of it: `~/.claude/plugins/cache/tkcs-lab-devflow/tld/<version>/` after an install,
`~/.claude/plugins/synced/<id>/tld/` in a cloud session whose plugins come from the Project. The commands call
`"${CLAUDE_PLUGIN_ROOT}/cli/tld"`.

## The plugin in a local Claude Code

```
/plugin install tld --marketplace tkcs-lab/tkcs-lab-devflow
```

(Claude Code 2.1.275 or later; on older versions `/plugin marketplace add tkcs-lab/tkcs-lab-devflow`, then
`/plugin install tld@tkcs-lab-devflow`.)

## The command line

```
curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh              # the tld command
cli/tld --help                                                                                    # or, from a checkout, without installing
```

Python 3.11+ (PyYAML is installed with it). The installer downloads the release wheel and `SHA256SUMS`, checks the
wheel, builds a private virtual environment per version under `~/.local/share/tld/venvs`, runs `tld --version` in it
and only then points the link `~/.local/bin/tld` at it. The previous venv is kept for rollback; older ones are
removed. A file `~/.local/bin/tld` that is not a link made by the installer is never overwritten. If no interpreter
of 3.11 or newer is found, set `TLD_PYTHON`. Other variables: `TLD_VERSION`, `TLD_BIN_DIR`, `TLD_BOARD_DIR`,
`XDG_DATA_HOME`. Three more exist for the installer's own tests: `TLD_RELEASE_BASE` (where the files are downloaded from), `TLD_PIP_ARGS` and `TLD_VENV_ARGS` (extra arguments for pip and `venv`); do not set them outside tests: a `TLD_RELEASE_BASE` that is not https turns off the installer's TLS enforcement, and the checksum then proves nothing. The board is installed with `... | sh -s -- board` (see [board-server.md](board-server.md)).

Upgrade = run the same line again. Without the installer, from the wheel:
`pip install https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download/vX.Y.Z/tld-X.Y.Z-py3-none-any.whl`. Do not `pip install tld`: that name on PyPI is
another package. [cli.md](../reference/cli.md) lists every command.

## Versions

Releases are tags `vX.Y.Z` with a GitHub release (notes from CHANGELOG.md and the merged pull requests), cut by
the owner with this repository's release workflow. A release carries five assets:

| Asset | What it is |
|---|---|
| `tld-X.Y.Z-py3-none-any.whl` | the command line (the package `src/tld`) |
| `tld-X.Y.Z.tar.gz` | the source distribution |
| `install.sh` | the installer, stamped with the version |
| `compose.yaml` | the board's compose file, stamped with the image digest |
| `SHA256SUMS` | sha256 of the other four |

A release before 1.1.0 has no assets: `TLD_VERSION=1.0.0` fails with a "cannot download ... (a release before the
first one with installer assets has none)" message. To pin a version run that release's own installer
(`curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download/vX.Y.Z/install.sh | sh`); the latest installer also takes `... | TLD_VERSION=X.Y.Z sh`.
The latest installer is `https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh`.

The plugin version in `.claude-plugin/plugin.json` and the
package version are the same string, so a Claude Project caches one copy per release.

A Claude Project installs the marketplace's current version; there is no per-repository pin of the plugin.
What a repository pins is compatibility: `tld.version` in its profile (`">=1.0,<2"` from `/tld:setup` and
`tld migrate`). Every playbook starts with `tld profile validate`, which fails with
`'tld.version': this profile needs tld >=1.0,<2, but tld 2.0.0 is running` when the installed tld does not
satisfy it; the session stops before doing anything. Read the release notes, then raise the specifier in a pull
request. A development build (`1.1.0.dev0`) counts as the release it leads to. To run a fixed version of the
command line, install that release (above).

Upgrade the plugin by updating it in the Project; a new session picks it up.

## Not tested end to end

The Project settings UI cannot be driven from a session. Verified: `claude plugin validate .` passes for the
marketplace and its plugin, and `claude plugin marketplace add <path>` followed by
`claude plugin install tld@tkcs-lab-devflow` puts the repository in the plugin cache as described above.

## Uninstall

Disable the plugin in the Claude Project settings. In a cloud session there is nothing else: the container goes
away. The command line installed by the installer: `curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- uninstall`
removes the link and the venvs. A board directory is left alone; `docker compose down` in it stops the board (the
data volume stays). A command line installed with pip: `pip uninstall tld`.
