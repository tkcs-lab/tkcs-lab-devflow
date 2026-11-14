---
description: "Weekly unattended: read the asks the board collected since the last run, find those a better playbook, profile key, role, skill, command or doc would have avoided, and write a triaged review document for /tld:make-plan"
model: sonnet
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/questions.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

It runs from a scheduled task: `attended: false`, no `get_session`, alerts are a push only.
