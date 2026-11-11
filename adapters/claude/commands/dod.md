---
description: "Run the project's definition-of-done gate (from .tld/toolkit.yaml) and report a pass/fail table"
argument-hint: "[optional: narrows the test run, for example a test path]"
---

Follow `${CLAUDE_PLUGIN_ROOT}/playbooks/dod.md` with these arguments:

$ARGUMENTS

Load the `tld:runtime` skill first and map every runtime action the playbook names with it; the playbook's
`tld ...` commands run as `"${CLAUDE_PLUGIN_ROOT}/bin/tld" ...`. Read the playbook and the policies it links in
full before the first step.
