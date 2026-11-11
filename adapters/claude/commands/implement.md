---
description: "Orchestrate a plan document with an implementation manifest — one child session per phase, merged into one feature branch, one PR to the main branch"
argument-hint: "<GitHub URL of the plan file: https://github.com/<owner>/<repo>/blob/<ref>/<path>>"
model: sonnet
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/implement.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/launcher/tld" ...`. Read the playbook and the policies it links in
full before the first step.

This turn runs at the `standard` level (`sonnet`, the `model:` line above). Later turns (check-ins, wakes) run on the session's own model, so for a `standard` orchestrator throughout, start the session on Sonnet.
