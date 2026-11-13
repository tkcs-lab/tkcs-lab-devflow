---
name: release
description: "Prepare a release: update the changelog and the version files in one pull request, wait for its merge, then start the release workflow after one board yes. Use only when the user asks for a release; it never creates a tag itself."
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/release.md`. Load the `tld:runtime` skill first and map every runtime action
the playbook names with it; its `tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`.
