# Security policy

## Threat model

tld lets coding agents plan, implement and review changes in a repository. It defends the repository against two
kinds of agent: one that makes mistakes, and one that has been manipulated (by text in an issue, a file, a web
page or a tool result). Two layers, with different jobs:

- **GitHub is the control.** The rulesets `tld-main` (pull request with one approval, required checks, no force
  push, no deletion) and `tld-tags` (no tag except by the owner), an agent account with the `write` role (no
  merge, no admin), and the environments `tld-agent` and `tld-release`, which keep `TLD_AGENT_TOKEN` and
  `TLD_RELEASE_TOKEN` on the default branch and behind the owner's approval. `tld ops repo-admin` audits and
  applies them ([docs/guides/admin.md](docs/guides/admin.md)). A manipulated agent cannot talk its way past them.
- **The hooks are a seatbelt.** The Claude Code hooks (`adapters/claude/hooks/`, policies in `src/tld/guard/`)
  deny merges, pushes to the main branch, force pushes, tags, writes of credential-like text and edits of protected
  paths before the tool call runs, and tell the agent what to do instead. They read a command, they do not run it:
  `python -c`, a script file or a Makefile target is out of their reach by design
  ([docs/architecture/hooks.md](docs/architecture/hooks.md#what-the-hooks-do-not-protect)). The protect lists and
  `hooks.disable` come from the profile on the remote default branch, so a branch cannot switch a hook off.
- **Untrusted text is data.** Only the owner and collaborators can give an instruction or answer an ask
  ([playbooks/policies/untrusted-text.md](playbooks/policies/untrusted-text.md)). An ask is answered only by the
  owner, logged in on the board; the session token cannot answer one ([docs/guides/board-server.md](docs/guides/board-server.md)).

Not in scope of the design: sessions without the plugin, a person at a terminal, a compromised owner account, and
the security of the runtime itself.

## What a report can be about

- A way past a GitHub-side control that tld sets up or documents (a ruleset, environment or workflow that lets an
  agent merge, tag or read a token it should not).
- A hook bypass for a form the hooks claim to handle (the guard corpus `tests/core/guard_cases.yaml` lists them);
  forms documented as out of reach are not vulnerabilities, but tell us if one is easy to close.
- A secret that gets past the secret scan in a form it claims to cover.
- The board server: authentication, the owner login, cross-site requests, an ask answered by anyone but the owner.
- A command, script or workflow template doing something its documentation does not say.

## How to report

Use GitHub private vulnerability reporting: open the repository's **Security** tab and choose **Report a
vulnerability**. Please do not open a public issue for a vulnerability.

A report should contain:

- The affected file, hook, command or workflow, and the version (`tld --version`, or `version` in
  `.claude-plugin/plugin.json`).
- The exact input, command or tool call that triggers the problem.
- What you expected, and what happened instead.
- The impact, in your own words, and a suggested fix if you have one.

Fixes are released as a new tag ([CHANGELOG.md](CHANGELOG.md)); only the newest release is supported.
