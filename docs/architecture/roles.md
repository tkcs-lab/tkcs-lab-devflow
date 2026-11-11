# Roles

A **role** is the one review concept of tld (D5): a role card in `roles/<role>.md` (purpose, inputs, method, report,
modes, default level) plus, for most roles, a checklist in `checklists/`. The roles are the same for every project.
What differs is the profile: the `roles` block of `.tld/toolkit.yaml` says which of them are **mandatory** at which
point, whether a finding **blocks**, and how strict the security reviewer is. A required role that did not run fails
visibly. How a session runs them is [playbooks/policies/roles.md](../../playbooks/policies/roles.md); the keys are in
[profile-reference.md](../reference/profile-reference.md); `/setup` writes the block for you
([setup.md](../guides/setup.md)).

## The roster

| Role | Default level | Checklist | Modes |
|---|---|---|---|
| `architect` | strong | none (reads the must-read docs, the ADR index and the code) | review |
| `code-reviewer` | strong | `checklists/review.md` | review |
| `security-reviewer` | strong | `checklists/security.md` | review |
| `test-architect` | strong | `checklists/test.md` | review |
| `ux-reviewer` | strong | none (the stack guides' UI rules) | review |
| `dependency-auditor` | standard | none (runs the audit commands of its context) | review |
| `tech-writer` | standard | `checklists/docs.md` | review, edit |
| `website-maintainer` | standard | `checklists/docs.md` (its website part) | review, edit |
| `debugger` | standard | none | review, edit |
| `refactorer` | standard | none | review, edit |

The four edit roles change files only in `edit` mode, which `tld roles required` gives only at `implement_phase`
(C2). No role card names a project, a runtime tool or a model. The Claude adapter wraps each role as a subagent,
`adapters/claude/agents/<role>.md`: front matter (tools, and the model the `tld:runtime` skill maps the default level
to) plus one line that applies the card.

## The profile block

```yaml
roles:
  posture:
    security: critical            # critical | standard | low; missing means standard
  disable: [dependency-auditor]   # roles that are never run; missing means none
  required:
    - {role: security-reviewer, at: [implement_phase, implement_final], blocking: true}
    - {role: ux-reviewer, at: [implement_final], when: ["app/views/**"], blocking: false}
    - {role: test-architect, at: [make_plan]}
    - {role: tech-writer, at: [dod, review]}
    - {role: website-maintainer, at: [dod], when: ["site/**", "docs/**"]}
  extra_context:                  # lines handed to every role
    - "Every outbound request is logged."
```

- `required[].at` is a non-empty list of points (below). `blocking` defaults to `false`. `when` is a non-empty list
  of globs matched against the files changed at that point; the entry applies only when one of them matches.
- `website-maintainer` needs `docs.website`. Validation also rejects a role that is both required and disabled,
  `when` at points that have no diff, and a role at `review` that is no review dimension (allowed there:
  `security-reviewer`, `dependency-auditor`, `test-architect`, `tech-writer`, `website-maintainer`).
- A profile without `roles` means every role is available and none is mandatory. The defaults are applied by
  `tld roles`, not by the schema.

## Points, modes and failure rules

| Point | Who runs the roles | Mode | Failure of a required role |
|---|---|---|---|
| `make_plan` | the planner | review | a blocking finding is resolved in the plan before it is pushed; a non-blocking one goes to the plan's Risks |
| `implement_phase` | the phase's worker | edit for the edit roles, review for the others | the orchestrator sends the phase back |
| `implement_final` | the final reviewer | review | a blocking finding is a blocking finding of the review |
| `review` | the review session: the roles are its dimensions (C11) | review | their findings are the candidates, one id space (`SEC`, `DEP`, `TST`, `DOC`, `WEB`) |
| `dod` | the dod session, the orchestrator's included | review | row `FAIL` |

A role runs at most once per point, apart from a re-run after the session fixed that role's own blocking findings;
`tld roles verify` reads the last report line per role and point.

## The report line

```
AGENT-REPORT <role> at=<point|adhoc> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>
```

`verdict=findings` with at least one finding, `pass` otherwise, `n/a` when the role could not run. Findings are
`<n>. blocking|non-blocking · path:line · what is wrong · the fix`. At the **security posture** `critical` the
security reviewer starts with a `## Threat model` section and grades findings about authentication, authorization,
cryptography, secrets and data leaving the system `blocking` unless clearly unreachable; `standard` applies the
checklist as written; `low` applies only the secrets and supply-chain items and says so.

## `tld roles`

```
tld roles required --profile .tld/toolkit.yaml --at dod --changed changed.txt
tld roles verify --required required.json --report report.txt
```

`required` validates the profile and prints JSON: the roles required at the point (`role`, `blocking`, the globs
that `matched`, `mode`), the ones not applicable and why, the posture, the extra context and the disabled roles.
`verify` prints one `OK`, `MISSING` or `BLOCKED` line per required role and `roles: ok (<n> required)` or
`roles: FAILED (<m> of <n> required)`; exit 0 means no `MISSING` and no `BLOCKED`.

## Switching a role off

Add its name to `roles.disable`: it is never run, not even on judgement. To make a role optional rather than off,
remove it from `roles.required`; a playbook may still run a non-required, non-disabled role on judgement
(`at=adhoc`), and no failure rule applies to it.
