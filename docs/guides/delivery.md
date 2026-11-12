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
pip install git+https://github.com/tkcs-lab/tkcs-lab-devflow@v1.0.0   # a release tag; the console script tld
cli/tld --help                                                         # or, from a checkout, without installing
```

Python 3.11+ and PyYAML. [cli.md](../reference/cli.md) lists every command.

## Versions

Releases are tags `vX.Y.Z` with a GitHub release (notes from CHANGELOG.md and the merged pull requests), cut by
the owner with this repository's release workflow. The plugin version in `.claude-plugin/plugin.json` and the
package version are the same string, so a Claude Project caches one copy per release.

A Claude Project installs the marketplace's current version; there is no per-repository pin of the plugin.
What a repository pins is compatibility: `tld.version` in its profile (`">=1.0,<2"` from `/tld:setup` and
`tld migrate`). Every playbook starts with `tld profile validate`, which fails with
`'tld.version': this profile needs tld >=1.0,<2, but tld 2.0.0 is running` when the installed tld does not
satisfy it; the session stops before doing anything. Read the release notes, then raise the specifier in a pull
request. A development build (`1.1.0.dev0`) counts as the release it leads to. To run a fixed version of the
command line, install that tag (above).

Upgrade by updating the plugin in the Project; a new session picks it up.

## Not tested end to end

The Project settings UI cannot be driven from a session. Verified: `claude plugin validate .` passes for the
marketplace and its plugin, and `claude plugin marketplace add <path>` followed by
`claude plugin install tld@tkcs-lab-devflow` puts the repository in the plugin cache as described above.

## Uninstall

Disable the plugin in the Claude Project settings. In a cloud session there is nothing else: the container goes
away. `pip uninstall tld` removes the command line.
