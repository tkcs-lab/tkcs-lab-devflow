---
name: repo-admin
description: Audit and update a GitHub organisation and its repositories against a policy file — organisation and repository settings, installed apps, tokens, secrets, variables, labels, webhooks, deploy keys, unused config directories such as .archon, and installing or updating workflows such as the release (tag) workflow. Use for "audit the org", "clean up unused tokens, apps or labels", "remove .archon everywhere" or "add the release workflow to every repo".
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/repo-admin.md`. Load the `tld:runtime` skill first and map every runtime action
the playbook names with it; its `tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/bin/tld" ...`.
