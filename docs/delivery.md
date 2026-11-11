# Delivery: getting the toolkit into a cloud session

A cloud session (claude.ai/code) does **not** install plugins that a repo enables through its
`.claude/settings.json`. Add the plugins in the Claude Project instead.

## Claude Project plugins

1. In claude.ai, open the Claude Project the repository's sessions belong to, and its settings.
2. Add the marketplace `tkcs-lab/claude-toolkit` (GitHub repository source).
3. Enable `devflow`, plus the `stack-*` plugins (`stack-python`, `stack-go`, `stack-swift`, `stack-ipados`) for the stacks the profile lists.
4. Commit `.claude/toolkit.yaml` to the repository (see [profile-reference.md](profile-reference.md)). Plugins are
   enabled per Project, so add a profile to **every** repository in the Project, even a minimal one with at least
   `git.main_branch`: without it the guardrail hooks deny every `git push` there.
5. In a new session, `/review`, `/make-plan`, `/implement` and `/dod` are available. Claude
   Code namespaces plugin skills (`devflow:project-profile`); the commands use whichever form the skill list shows. The guardrail hooks load with the plugin and need
   `python3` 3.11+ and PyYAML in the session (without PyYAML they behave as if there were no profile); see
   [hooks.md](hooks.md#installing-and-checking) for how to confirm they are active. The other commands
   (`/board`, `/deps`, `/upstream`, `/land`) also read the profile and need PyYAML for the validators.

Upgrade by updating the plugin in the Project. There is no pin in the repository, so a plan run is
only reproducible to the extent the Project's plugin version is.

**Status: not tested end to end.** The Project settings UI cannot be driven from a session. What was
verified: `claude plugin validate` passes for the marketplace and all its plugins, and
`claude plugin marketplace add <path>` followed by `claude plugin install devflow@claude-toolkit`
puts the commands, skills and scripts in `~/.claude/plugins/cache/claude-toolkit/devflow/<version>/`,
which is where the `project-profile` skill looks for them. In a cloud session whose plugins come from the
Claude Project the scripts are under `~/.claude/plugins/synced/<id>/devflow/`.

## Uninstall

Disable the plugins in the Claude Project settings. In a cloud session there is nothing else: the container goes away.
