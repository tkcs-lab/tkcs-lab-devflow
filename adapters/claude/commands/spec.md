---
description: "Build OpenSpec specs for existing code (init: one pull request, never merged) or validate them (check); needs the profile's spec block"
argument-hint: "[check | init]"
model: opus
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/spec.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

This turn runs at the `strong` level (`opus`, the `model:` line above); start the session on that model so later turns run on it too.
