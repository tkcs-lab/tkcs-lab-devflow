---
description: "Unattended, every few hours: send the account's 5-hour and weekly subscription use to the board's Usage page"
model: haiku
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/usage.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

It runs from a scheduled task: `attended: false`, no `get_session`, no status record.
