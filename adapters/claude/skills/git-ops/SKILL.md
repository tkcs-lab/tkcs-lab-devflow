---
name: git-ops
description: Dispatches the central tld-git-ops workflow to delete a remote branch, because a cloud session cannot delete remote branches. Use only when the user asks for named branches to be deleted. It never creates a tag; tags are cut only by the release workflow.
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/git-ops.md`. Load the `tld:runtime` skill first and map every runtime action
the playbook names with it; its `tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/bin/tld" ...`.
