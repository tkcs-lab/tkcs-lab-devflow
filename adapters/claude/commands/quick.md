---
description: "Do one small change end to end without a plan: create the tracking issue, refuse a large change, one worker, the final review, one fix round for the non-blocking findings, dod and one PR to the main branch"
argument-hint: "<what to change: a prompt, an issue number, or both>"
model: sonnet
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/quick.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

This turn runs at the `standard` level (`sonnet`, the `model:` line above). Later turns (check-ins, wakes) run on the session's own model, so for a `standard` orchestrator throughout, start the session on Sonnet.
