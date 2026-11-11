# Running roles

A **role** is a role card (`roles/<role>.md`) plus, for most roles, a checklist (`checklists/`). It is the one
review concept (D5): the profile's `roles` block says which roles are required at which point and whether a
finding blocks; `run_role` runs one. A required role that did not run fails visibly.

The points are `make_plan`, `implement_phase`, `implement_final`, `review` and `dod`. The ten roles are
architect, code-reviewer, security-reviewer, test-architect, ux-reviewer, dependency-auditor, tech-writer,
website-maintainer, debugger and refactorer. The four **edit roles** are tech-writer, website-maintainer,
debugger and refactorer.

## Resolve

Write the changed paths of the diff at this point, one repository-relative path per line, to a scratch file
(skip this at `make_plan` and `review`, which have no diff). Then, from the repository root:

```
tld roles required --profile .tld/toolkit.yaml --at <point> --changed <file>
```

(no `--changed` at `make_plan` and `review`). The JSON has `required` (each `{role, blocking, matched, mode}`),
`not_applicable`, `posture.security`, `extra_context` and `disabled`. Exit 1 prints `tld roles: <message>`:
show it and stop. A profile without `roles` gives an empty `required`. Never run a role listed in `disabled`.

## Run

Run every item of `required` with `run_role(role, mode, point, context)`, in parallel, `mode` exactly as the
JSON says. `context` is this prompt, filled in with real values:

```
You are the <role> role, running at <point>.
Mode: <review|edit>
Scope: <diff range or paths>
Security posture: <critical|standard|low>
Extra context:
- <each roles.extra_context line>
Must-read docs: <paths>
Stack guides: <stacks/<name>.md paths>
<role-specific fields>
End with the AGENT-REPORT line described in your Report section.
```

Role-specific fields, only for the role that uses them: `Audit commands` (dependency-auditor), `Website build`
and `Website links` (website-maintainer), `Verify (fast)` (refactorer), `Changelog target` (tech-writer).
With `docs.index`, `Must-read docs` holds the must-read docs plus the docs read through the index for this task
(a worker: its `Read first:` list). Never hand a role the index and tell it to read everything.

## Modes (C2)

| Point | Who runs the roles | Mode | Failure of a required role |
|---|---|---|---|
| `make_plan` | the planner | review | a blocking finding is resolved in the plan before it is pushed; a non-blocking one goes to the plan's Risks |
| `implement_phase` | the phase's worker | edit for the edit roles, review for the others | the orchestrator sends the phase back; it is not merged |
| `implement_final` | the final reviewer | review | a blocking finding is a blocking finding of the review (`verdict=changes`) |
| `review` | the review session, as its dimensions | review | its findings are the review's candidates |
| `dod` | the dod session (also the orchestrator's) | review | row `FAIL` |

`tld roles required` prints `mode: edit` only for an edit role at `implement_phase`; every other point,
the orchestrator's dod included, runs roles in review mode. A role runs **at most once per point**; the one
exception is a re-run after the dispatching session fixed that role's own blocking findings.

**Fixing a blocking finding.** A review-mode role's blocking finding is fixed by the session that ran it (the
worker at `implement_phase`, the planner at `make_plan`), and the same role is then run again at the same
point; its new report line is the one that counts, because `tld roles verify` reads the last line per role
and point. An edit role fixes its own findings and ends with a report line that already reflects the fixed
state.

## Report

Every role ends its answer with exactly one line, printed bare on its own line, never quoted:

```
AGENT-REPORT <role> at=<point|adhoc> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>
```

`verdict=findings` when `blocking + non_blocking > 0`, `pass` otherwise, `n/a` when the role could not run
(the reason on the lines before it). A required role whose line says `n/a` counts as **did not run**. Each
finding before the line is `<n>. blocking|non-blocking · path:line · what is wrong · the fix`; `blocking` is
anything the role would refuse to merge. Copy each report line unchanged; never paraphrase it.

## Gate

Save the roles' full answers, report lines included, as one report file and run:

```
tld roles verify --required <required JSON file> --report <report file>
```

It prints one line per required role, `OK <role> at=<point> blocking=<n>`, `MISSING <role> at=<point>` or
`BLOCKED <role> at=<point> blocking=<n>`, and ends with `roles: ok (<n> required)` or
`roles: FAILED (<m> of <n> required)`. Exit 1 on any `MISSING` or `BLOCKED`. A `MISSING` role is run again
once; if it is still missing it counts as failed. A `non-blocking` entry with findings is `OK`: its findings
go where the table above says.

## Not required

A role that is neither required here nor disabled may be run on judgement (an architect for a large plan, a
debugger for a failing test) with `at=adhoc`. No failure rule applies; `tld roles verify` ignores it.
