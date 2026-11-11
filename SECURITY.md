# Security policy

## Scope

In scope: the guardrail hooks (`plugins/devflow/hooks/`), the secret scan, and the scripts under `plugins/devflow/scripts/`. A report is in scope if it shows a way to get a denied action through a hook, a secret past the scan, or a script doing something its documentation does not say.

The hooks are a seat belt and not a security boundary: they catch common mistakes by an agent that is trying to follow the rules, not an attacker. See [docs/architecture/hooks.md](docs/architecture/hooks.md) for what they do and do not cover.

## How to report

Use GitHub private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Please do not open a public issue for a vulnerability.

## What a report should contain

- The affected file, hook or script, and the version (the plugin version from its `plugin.json`).
- The exact input, command or tool call that triggers the problem.
- What you expected, and what happened instead.
- The impact, in your own words, and a suggested fix if you have one.
