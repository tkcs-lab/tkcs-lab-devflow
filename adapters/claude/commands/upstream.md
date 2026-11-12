---
description: "Weekly unattended sync of a patch-carrying fork to the newest upstream release tag - one commit, one pull request, never merged"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/upstream.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

It runs from a scheduled task: `attended: false`, no `get_session`, alerts are a push only.
