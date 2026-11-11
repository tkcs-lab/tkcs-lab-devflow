---
description: "Move a repository from claude-toolkit (devflow) to tld: show the plan, write it on a branch after you confirm, open one pull request that is never merged, then list your manual steps as an ask"
argument-hint: "[optional: --dry-run]"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/migrate.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/launcher/tld" ...`. Read the playbook and the policies it links in
full before the first step.
