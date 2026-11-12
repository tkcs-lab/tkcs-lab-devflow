---
description: "Deep review of a repository (or part of it) for security, test coverage (unit, integration, e2e) and documentation including a website; writes a triaged review document on its own review/ branch for /tld:make-plan, and asks the owner about the open items on the status board"
argument-hint: "[empty for the whole repository | paths | #<PR> or PR URL | branch] \u2014 or: apply <review file URL>"
model: opus
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/review.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

This turn runs at the `strong` level (`opus`, the `model:` line above); start the session on that model so the wakes after the decisions ask run on it too.
