---
description: "Check, build or tidy the docs index: a thin CLAUDE.md, one index, docs read only when a row matches (check reports, init builds and moves, tidy is the unattended weekly cleanup)"
argument-hint: "[check | init | tidy]"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/docs.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/cli/tld" ...`. Read the playbook and the policies it links in
full before the first step.

`/tld:docs tidy` runs from a scheduled task: `attended: false`, no `get_session`, alerts are a push only.
