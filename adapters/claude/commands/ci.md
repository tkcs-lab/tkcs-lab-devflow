---
description: "Unattended CI watch: find workflows failing on the default branch (scheduled runs too), diagnose, fix what the repo can fix, report the rest, never merge"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/ci.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/launcher/tld" ...`. Read the playbook and the policies it links in
full before the first step.

It runs from a scheduled task: `attended: false`, no `get_session`, alerts are a push only.
