# Delivery: getting the toolkit into a cloud session

A cloud session (claude.ai/code) does **not** install plugins that a repo enables through its
`.claude/settings.json`. Add the plugins in the Claude Project instead.

## Claude Project plugins

1. In claude.ai, open the Claude Project the repository's sessions belong to, and its settings.
2. Add the marketplace `tkcs-lab/tkcs-lab-devflow` (GitHub repository source).
3. Enable `tld`. The stack skills (`stack-python`, `stack-go`, `stack-swift`, `stack-ipados`) ship inside it; the profile's `stacks` selects them.
4. Commit `.tld/toolkit.yaml` to the repository (see [profile-reference.md](../reference/profile-reference.md)). Plugins are
   enabled per Project, so add a profile to **every** repository in the Project, even a minimal one with at least
   `git.main_branch`: without it the guardrail hooks deny every `git push` there.
5. In a new session, `/review`, `/make-plan`, `/implement` and `/dod` are available. Claude
   Code namespaces plugin skills (`tld:project-profile`); the commands use whichever form the skill list shows. The guardrail hooks load with the plugin and need
   `python3` 3.11+ and PyYAML in the session (without PyYAML they behave as if there were no profile); see
   [hooks.md](../architecture/hooks.md#installing-and-checking) for how to confirm they are active. The other commands
   (`/board`, `/deps`, `/upstream`, `/land`) also read the profile and need PyYAML for the validators.

Upgrade by updating the plugin in the Project. There is no pin in the repository, so a plan run is
only reproducible to the extent the Project's plugin version is.

**Status: not tested end to end.** The Project settings UI cannot be driven from a session. What was
verified: `claude plugin validate` passes for the marketplace and its plugin, and
`claude plugin marketplace add <path>` followed by `claude plugin install tld@tkcs-lab-devflow`
puts the plugin (the whole repository: the plugin is sourced from its root) in
`~/.claude/plugins/cache/tkcs-lab-devflow/tld/<version>/`. In a cloud session whose plugins come from the
Claude Project it is under `~/.claude/plugins/synced/<id>/tld/`. Either way Claude Code sets
`CLAUDE_PLUGIN_ROOT` to that directory, and the commands call `"${CLAUDE_PLUGIN_ROOT}/bin/tld"`.

## Uninstall

Disable the plugins in the Claude Project settings. In a cloud session there is nothing else: the container goes away.
