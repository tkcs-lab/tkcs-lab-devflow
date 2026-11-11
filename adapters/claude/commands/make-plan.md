---
description: "Research a change, then write either a single-session prompt (small scope) or a plan document with an implementation manifest on its own plan/ branch (large scope), with step-by-step instructions for anything only a human can do"
argument-hint: "<what to build: a prompt, an issue number, a /review document URL, or a mix>"
model: opus
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/make-plan.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/bin/tld" ...`. Read the playbook and the policies it links in
full before the first step.

This turn runs at the `strong` level (`opus`, the `model:` line above); start the session on that model so later turns run on it too.
