---
description: "Order the open pull requests of the bot, resolve their conflicts before review, run CI once on the combined set, and install the land workflow"
argument-hint: "[PR numbers]"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/land.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/bin/tld" ...`. Read the playbook and the policies it links in
full before the first step.
