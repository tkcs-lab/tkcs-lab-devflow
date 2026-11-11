# Agents

devflow ships ten generic agents in `plugins/devflow/agents/`. They are the same for every project. What differs
is the profile: the `agents` block of `.claude/toolkit.yaml` says which of them are **mandatory** at which point of
the workflow, whether a finding from them **blocks**, and how strict the security reviewer is. A required agent that
did not run fails visibly. Key reference: [profile-reference.md](../reference/profile-reference.md). To have the block written for
you, run `/setup` ([setup.md](../guides/setup.md)).

## The roster

| Agent | Model | Wraps the skill | Edit tools |
|---|---|---|---|
| `architect` | opus | none (reads the must-read docs, the ADR index and the code) | no |
| `code-reviewer` | opus | `review-checklist` | no |
| `security-reviewer` | opus | `secure-code-review` | no |
| `test-architect` | opus | `test-review` | no |
| `ux-reviewer` | opus | none (reads the `stack-*` skills named in the prompt) | no |
| `dependency-auditor` | sonnet | none (runs the audit commands the prompt lists) | no |
| `tech-writer` | sonnet | `docs-review` | yes |
| `website-maintainer` | sonnet | `docs-review` (its website checks) | yes |
| `debugger` | sonnet | none | yes |
| `refactorer` | sonnet | none | yes |

A read-only agent has no `Edit` and no `Write`; it has `Bash` for `git diff` and for running checks. The four edit
agents (`tech-writer`, `website-maintainer`, `debugger`, `refactorer`) can work in `edit` mode, see
[Modes](#modes). No agent file names a project.

## The profile block

```yaml
agents:
  posture:
    security: critical            # critical | standard | low; missing means standard
  disable: [dependency-auditor]   # agents that are never dispatched; missing means none
  required:
    - {agent: security-reviewer, at: [implement_phase, implement_final], blocking: true}
    - {agent: ux-reviewer, at: [implement_final], when: ["app/views/**"], blocking: false}
    - {agent: test-architect, at: [make_plan]}
    - {agent: tech-writer, at: [dod, review]}
    - {agent: website-maintainer, at: [dod], when: ["site/**", "docs/**"]}
  extra_context:                  # lines handed to every dispatched agent
    - "Every outbound request must pass the approval gate."
```

- `required[].at` is a non-empty list of points (below). `blocking` defaults to `false`. `when` is a non-empty list
  of globs matched against the files changed at that point; the entry applies only when one of them matches.
- `website-maintainer` needs `docs.website` in the profile. Validation also rejects an agent that is both required and
  disabled, `when` at points that have no diff, and an agent at `review` that has no review dimension
  (allowed there: `security-reviewer`, `dependency-auditor`, `test-architect`, `tech-writer`, `website-maintainer`).
- A profile without `agents` means every agent is available and none is mandatory. The defaults are applied by
  `scripts/agents.py`, not by the schema, so `--resolved` output of such a profile does not change.

## Points, modes and failure rules

| Point | Who dispatches | Mode | Failure of a required agent |
|---|---|---|---|
| `make_plan` | the planner session | review | a blocking finding is resolved in the plan before it is pushed; a non-blocking one goes to the plan's Risks |
| `implement_phase` | the phase's worker session | edit for the four edit agents, review for the others | the orchestrator sends the phase back; it is not merged |
| `implement_final` | the final review session | review | a blocking finding is a blocking finding of the review (`verdict=changes`) |
| `review` | the `/review` session, next to the dimension subagents | review | its findings join the triage; `blocking` findings become severity `high`, `non-blocking` ones `medium` |
| `dod` | the `/dod` session | review | row `FAIL` |

### Modes

`edit` mode exists only for the four edit agents and is used only inside a worker session or when you ask one of them
directly. Every other agent, and every agent at every other point, runs in `review` mode and reports only. A blocking
finding of a read-only agent is fixed by the dispatching session, which then dispatches the same agent again at the
same point; the new report line is the one that counts. An edit agent fixes its own findings and ends with a report
line that already reflects the fixed state.

## The report line

Every agent ends its answer with exactly one line, bare on its own line:

```
AGENT-REPORT <agent> at=<point|adhoc> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>
```

`verdict=findings` when there is at least one finding, `pass` otherwise, `n/a` when the agent could not run (the reason is
on the lines before it). Findings are written `<n>. blocking|non-blocking · path:line · what is wrong · the fix`.
At the **security posture** `critical` the security reviewer starts with a `## Threat model` section and grades findings
about authentication, authorization, cryptography, secrets and data leaving the system `blocking` unless clearly
unreachable; `standard` applies the checklist as written; `low` applies only the secrets and supply-chain items and says so.

## Mandatory and blocking

- **Mandatory** (listed under `required` for a point): the agent must run there and its report line must be present. A
  line with `verdict=n/a`, or no line, counts as *did not run* and fails the point.
- **Blocking** (`blocking: true`): the agent ran, but a line with `blocking=<n>` and `n > 0` also fails the point.
  Without it, findings are reported and triaged but do not fail anything.

## `agents.py`

Two sub-commands, used by the `agent-dispatch` skill:

```
python3 plugins/devflow/scripts/agents.py required --profile .claude/toolkit.yaml --at dod --changed changed.txt
python3 plugins/devflow/scripts/agents.py verify --required required.json --report report.txt
```

`required` validates the profile and prints JSON: the agents required at the point (with the globs that matched), the
ones not applicable (and why), the posture, the extra context and the disabled agents. `--changed` is a file with one
repo-relative path per line (`-` reads stdin); it is needed only when an entry has `when` at a point that has a diff.
`verify` reads that JSON and a report text, prints one `OK`, `MISSING` or `BLOCKED` line per required agent and a
summary `agents: ok (<n> required)` or `agents: FAILED (<m> of <n> required)`. Exit 0 means no `MISSING` and no
`BLOCKED`. When an agent has several lines for the same point, the last one counts.

## Switching an agent off

Add its name to `agents.disable`: it is never dispatched, not even on judgement. To make an agent optional rather than
off, remove it from `agents.required`; the commands may still dispatch a non-required, non-disabled agent on judgement,
and no failure rule applies to it. Not wanting a point only needs the entry's `at` shortened.
