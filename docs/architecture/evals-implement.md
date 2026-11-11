# Evals of `/implement`: design

Part of [evals.md](evals.md).

Built: `implement-invalid-manifest`, the stop before any branch or worker when the manifest does not validate. It
needs no cloud tool, so it runs locally and in stub mode. Not built: the orchestration below.

`/implement` reads a plan manifest and starts **one child session per phase** with `create_session`
(the cloud session tooling), waits for each child's `PHASE-REPORT` via `send_message` and `list_events`,
merges each phase branch into the feature branch with `--no-ff` and a `Plan-Phase: <slug>/<id>` trailer,
runs the fast checks after each merge, reverts the merge (`git revert -m 1`) when they go red, runs a
final review session, and opens one pull request with a Scope section.

**Can a headless local runner drive it?** Not the real thing. `create_session`, `send_message`,
`list_events`, `archive_session` and the GitHub MCP tools exist only inside the cloud environment, and
a local `claude -p` has none of them. Local `claude -p` can spawn *subagents*, but that is a different
mechanism with a different failure profile (shared checkout, no branch per child), so a result would
not describe production. The real command needs the cloud environment: a repository on GitHub, a
bot identity, and child sessions that cost real money. That is a separate harness, not an adapter.

**What a stubbed-children variant can verify.** Replace the cloud tools with a local fake: an MCP
server (`--mcp-config`, tools named as the command expects) whose `create_session` creates a branch
from the fixture's feature branch, applies a *canned patch* for that phase (the "worker"), commits with
the trailer, and answers `list_events` with a canned `PHASE-REPORT`. The model under test is then only
the orchestrator, and these are checkable by code on the final git state:

- **merge order**: the feature branch's merge commits follow a topological order of `depends_on`, with
  `--no-ff` merges whose second parent is the phase branch;
- **`Plan-Phase` trailers**: every merge commit and every phase tip has one, and a resumed run
  (fixture starts with some phases merged) does not redo them;
- **revert on red**: a canned phase that breaks `verify.fast` is merged, then reverted with
  `git revert -m 1`, the phase is re-run, the history shows both; scope drift is recorded;
- **the PR body**: assembled from a local stand-in for `create_pull_request`, graded for the Scope
  section, `Closes #n` lines, the manual-after checklist, no secrets;
- **no forbidden operations** (reuse `forbidden_ops_absent`: no force-push, tag or merge to main).

It cannot verify that real workers produce good phases, that cloud session limits and timeouts behave,
or the status-board writes against a real board.

**Starting state plus expected scope.** The task format already allows it: `fixture` (a repository
that holds a plan, a feature branch and the canned patches) and `expected: {touches: [...], merge_order:
[...]}`. The future fixture source is **replay of real scope-drift cases** from the runtime
monitoring records (`docs/architecture/scope-drift.md`): each recorded phase has a base, a manifest `touches`, and
the paths it actually changed, which is exactly the starting state, the canned patch and the expected
scope. Replays should be anonymised into the same synthetic form (paths and sizes kept, content
generated) before they enter `evals/fixtures/`.

**Recommendation.** Build the stubbed-children variant as slice 2 and nothing more. Do not build a
cloud-driven harness until the stubbed variant shows the orchestrator's merge logic is stable; the cloud
version duplicates the cost of a real `/implement` run (an orchestrator, one Sonnet child per phase, a
review session) for every repeat.

Cost estimate (unmeasured; scaled from the one measured slice-1 run): orchestrator-only runs on Sonnet are roughly $1 to $3 each (about 20 to 40 turns of
git and merge handling plus the final review prompt), so 3 repeats of 3 tasks (ordered merge, revert
on red, resume) is about $10 to $25 per full pass. A cloud-driven run of a 3-phase plan is
roughly 4 to 6 sessions at $2 to $8 each, so $10 to $40 per repeat and $30 to $120 per task at 3
repeats: affordable once as a release check, not as a routine. These are estimates from the
slice-1 per-run costs, to be replaced by measured figures.
