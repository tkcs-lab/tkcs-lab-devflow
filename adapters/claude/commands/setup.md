---
description: "Survey this repository and create or update .tld/toolkit.yaml, delivered as one pull request that is never merged"
argument-hint: "[optional: create | update] [--accept-proposals]"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/setup.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/bin/tld" ...`. Read the playbook and the policies it links in
full before the first step.
