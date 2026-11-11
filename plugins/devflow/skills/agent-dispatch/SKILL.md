---
name: agent-dispatch
description: Resolves which generic agents the project profile makes mandatory at a workflow point, dispatches them with a fixed prompt, and gates on their report lines. Load it in /make-plan, /implement, /review and /dod.
user-invocable: false
---

# Dispatching the profile's agents

The profile key `agents` decides which of the ten devflow agents are mandatory at which point, whether a
finding blocks, and how strict the security reviewer is. A required agent that did not run fails visibly.
Load the `project-profile` skill first; the `agents` defaults are applied by `scripts/agents.py`, nowhere else.

The points are `make_plan`, `implement_phase`, `implement_final`, `review` and `dod`.

## Resolve

Write the changed paths of the diff at this point, one repo-relative path per line, to a scratch file. Skip this
at `make_plan` and `review`, which have no diff. Then run `agents.py required` from the repo root:

```bash
python3 "<devflow root>/scripts/agents.py" required --profile .claude/toolkit.yaml --at <point> [--changed <file>] > required.json
```

The JSON has `required` (agent, `blocking`, `matched`), `not_applicable` (agent, `why`), `posture.security`,
`extra_context` and `disabled`. Exit 1 prints `agents.py: <message>` on stderr: show it and stop. A profile without
`agents` gives an empty `required`: nothing is mandatory and this skill has nothing more to do at that point.
Never dispatch an agent listed in `disabled`.

## Dispatch

Dispatch every item of `required` with the `Agent` tool, in parallel, one call per agent. The `subagent_type` is
the agent's name as the agent list shows it (the plugin prefix form `devflow:<name>` when that is how the list
shows it). The prompt is this text, with the fields filled in from the profile (real values, not "see the profile"):

```
You are the <agent> agent, running at <point>.
Mode: <review|edit>
Scope: <diff range or paths>
Security posture: <critical|standard|low>
Extra context:
- <each agents.extra_context line>
Must-read docs: <paths>
Stack skills: <names>
<agent-specific fields>
End with the AGENT-REPORT line described in your Report section.
```

Agent-specific fields, only for the agent that uses them: `Audit commands` (dependency-auditor), `Website build`
and `Website links` (website-maintainer), `Verify (fast)` (refactorer), `Changelog target` (tech-writer).

Index parts: the `Must-read docs` field holds the profile's must-read docs and, when the profile has `docs.index`, the paths of the docs you read through the index for this task (a worker: its `Read first:` list). Never hand an agent the index and tell it to read everything.

## Modes

| Point | Who dispatches | Mode | Failure of a required agent |
|---|---|---|---|
| `make_plan` | the planner session, with the `Agent` tool | review | a blocking finding is resolved in the plan before it is pushed; a non-blocking one goes to the plan's Risks |
| `implement_phase` | the phase's worker session (child brief rule 3b) | edit for the four edit agents, review for the others | the orchestrator sends the phase back; it is not merged |
| `implement_final` | the final review session | review | a blocking finding is a blocking finding of the review (`verdict=changes`) |
| `review` | the `/review` session, alongside the dimension subagents | review | its findings join the triage; `blocking` findings become severity `high`, `non-blocking` ones `medium` |
| `dod` | the `/dod` session | review | row `FAIL` |

`edit` mode exists only for the four edit agents (tech-writer, website-maintainer, debugger, refactorer) and is used
only inside a worker session or when the user asks one of them directly. Every other agent, and every agent at every
other point, runs in `review` mode and reports only.

**Fixing a blocking finding.** A read-only agent's blocking finding is fixed by the dispatching session (the worker
at `implement_phase`, the planner at `make_plan`) and the same agent is then dispatched again at the same point; its
new report line is the one that counts, because `agents.py verify` reads the last line per agent and point. An edit
agent fixes its own findings in `edit` mode and ends with a report line that already reflects the fixed state.

## Report

Every agent ends its answer with exactly one line, printed bare on its own line, never quoted or in backticks:

```
AGENT-REPORT <agent> at=<point|adhoc> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>
```

`verdict=findings` when `blocking + non_blocking > 0`, `pass` otherwise, `n/a` when the agent could not run (the
reason is on the lines before it). A required agent whose line says `n/a` counts as **did not run**. The findings
before the line use `<n>. blocking|non-blocking · path:line · what is wrong · the fix`.

Copy each agent's report line unchanged; never paraphrase it.

## Gate

After the agents have answered, save their full answers, report lines included, as one report file and run:

```bash
python3 "<devflow root>/scripts/agents.py" verify --required required.json --report <report file>
```

It prints one line per required agent, `OK <agent> at=<point> blocking=<n>`, `MISSING <agent> at=<point>` (no
report line, or `verdict=n/a`) or `BLOCKED <agent> at=<point> blocking=<n>` (the item is `blocking` and `n > 0`), and
ends with `agents: ok (<n> required)` or `agents: FAILED (<m> of <n> required)`. Exit 1 on any `MISSING` or `BLOCKED`.
A `MISSING` agent is dispatched again once; if it is still missing it counts as failed. What a failure does at each
point is the last column of the table in `## Modes`. A `non-blocking` entry with findings is `OK`: its findings go to
the place the table names, and they do not fail the gate.

## Not required

An agent that is neither required at this point nor in `disabled` may be dispatched on judgement, for example an
`architect` for a large plan or a `debugger` for a failing test. Use the same prompt, with `at=adhoc` in the report
line. No failure rule applies to it: its findings are advice, and `agents.py verify` does not look at it.
