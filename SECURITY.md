# Security policy

## Threat model

tld lets coding agents plan, implement and review changes in a repository. It defends the repository against two
kinds of agent: one that makes mistakes, and one that has been manipulated (by text in an issue, a file, a web
page or a tool result). Two layers, with different jobs:

- **GitHub is the control.** The rulesets `tld-main` (pull request with one approval, required checks, no force
  push, no deletion) and `tld-tags` (no tag except by the owner), an agent account with the `write` role (no
  admin, no bypass of the rulesets), and the environments `tld-agent` and `tld-release`, which keep `TLD_AGENT_TOKEN` and
  `TLD_RELEASE_TOKEN` on the default branch and behind the owner's approval. `tld ops repo-admin` audits and
  applies them ([docs/guides/admin.md](docs/guides/admin.md)). A manipulated agent cannot talk its way past them. With `admin_bypass: true` the owner (admin role, never the agent) may merge a pull request through `tld-main` in `pull_request` mode, required checks included, so the owner waits for green CI.
  Precisely: the `write` role *can* press merge on a pull request into the main branch, but only once `tld-main` is
  satisfied — an approval by the owner (the agent cannot approve its own pull request), the required checks green,
  stale approvals dismissed by a new push and the last push approved by someone other than its author. So the agent
  cannot get its own unreviewed change onto the main branch; what it can do is merge a pull request the owner has
  already approved, which the `no-merge` hook denies as a seatbelt.
- **The hooks are a seatbelt.** The Claude Code hooks (`adapters/claude/hooks/`, policies in `src/tld/guard/`)
  deny merges, pushes to the main branch, force pushes, tags, writes of credential-like text and edits of protected
  paths before the tool call runs, and tell the agent what to do instead. They read a command, they do not run it:
  `python -c`, a script file or a Makefile target is out of their reach by design
  ([docs/architecture/hooks.md](docs/architecture/hooks.md#what-the-hooks-do-not-protect)). The protect lists and
  `hooks.disable` come from the profile on the remote's default branch (the branch the remote reports, fetched and
  pinned by commit SHA and origin URL), so a branch, a local ref or a repointed origin cannot switch a hook off.
- **Untrusted text is data.** Only the owner and collaborators can give an instruction or answer an ask
  ([playbooks/policies/untrusted-text.md](playbooks/policies/untrusted-text.md)). An ask is answered only by the
  owner, logged in on the board; the session token cannot answer one ([docs/guides/board-server.md](docs/guides/board-server.md)).

Not in scope of the design: sessions without the plugin, a person at a terminal, a compromised owner account, and
the security of the runtime itself.

## The curl installer

`install.sh` (the curl line in [docs/guides/delivery.md](docs/guides/delivery.md)) downloads the release wheel
and checks it against `SHA256SUMS`. That file comes from the same release over the same TLS connection, so the check
shows integrity (a corrupt or truncated download), not authenticity (a tampered release). `install.sh` itself is
unverified, as with every `curl | sh`, and neither it nor `compose.yaml` is signed. PyYAML is installed from PyPI
without a hash. The release workflow's isolated build installs the setuptools of `[build-system]` in pyproject.toml (a
lower bound only) without hashes, and `pip install build` pulls unpinned dependencies, so a compromise there reaches
users through a correctly checksummed wheel. Releases should be made immutable (the owner
enables this once before the first release, see CONTRIBUTING.md), so assets cannot be replaced after publishing,
and the compose file pins the board image by digest because a ghcr tag can be overwritten. The digest pin protects
against a moved tag, not against a tampered release; the image is not signed.

The release workflow has two jobs. `build` has no environment: it checks the commit is green, runs the third-party
build code (pip, setuptools, the docker actions, QEMU, whose binfmt image is pinned by digest), pushes the board image
by digest without a tag, holds `packages: write` and `checks: read`, and never references `TLD_RELEASE_TOKEN`.
`publish` is behind the environment `tld-release`, the one approval of a run, and holds `TLD_RELEASE_TOKEN`, which can
create tags; it runs `gh`, docker and the shell, with no third-party build code on that runner. It checks the
downloaded `dist/` against `SHA256SUMS`, which catches a corrupt transfer but not a compromised `build` job, since that
job wrote the sums, adds the image tags with the workflow token (`packages: write`) and only then makes the tag and the
release. An unapproved run moves no tag, but `build` runs without approval.

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
