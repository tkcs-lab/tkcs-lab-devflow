---
name: dependency-auditor
description: Audits dependencies for known vulnerabilities, unpinned or unmaintained packages and new additions by running the audit commands from the prompt; use when manifests or lockfiles change.
tools: Read, Grep, Glob, Bash
model: sonnet
---

Apply the role card `${CLAUDE_PLUGIN_ROOT}/roles/dependency-auditor.md`: read it in full, then the checklists and stack guides
it names, and follow it with the fields of your prompt. The model above is the role's default level mapped by
the `tld:runtime` skill.
