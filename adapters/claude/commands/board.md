---
description: "Check the tld status board connection, or prune the stale records from it"
argument-hint: "[empty to check the board | prune]"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/board.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.
