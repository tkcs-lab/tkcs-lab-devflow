---
description: Run the project's definition-of-done gate (from .claude/toolkit.yaml) and report a pass/fail table
argument-hint: "[optional: narrows the test run, for example a test path]"
---

Run this repo's definition of done and report the result as a table. Run every command from the
repo root unless the entry names a `cwd`.

$ARGUMENTS

## Profile

Load the `project-profile` skill and follow its "Loading the profile" section. If it reports an
error, show the message verbatim and stop; never substitute a command of your own.
Skill names: the toolkit's skills carry a plugin prefix (`devflow:project-profile`,
`devflow:pr-steward`, `stack-python:stack-python`). Use whichever form the skill list shows. The
`agent-dispatch` skill is loaded in the Required agents step below, under the same naming. The definition
of done is the profile's `verify` section:

- `verify.dod`: the blocking gate, in order.
- `verify.dod_conditional`: rows that apply only when the diff touches matching files.
- `verify.dod_manual`: judgement rows.
- `verify.dod_doc`: when present, the project's human-readable version of all this; mention it in
  the report so the reader knows where the rows come from.

If arguments were given above, treat them as a narrower run and say so in the report. For each
`verify.dod` entry: when it has `narrow`, run that command with `{args}` replaced by the arguments
instead of its `run`; when it has `skip_when_narrowed: true`, skip it and mark the row
`n/a (partial run)` rather than reporting a result that isn't comparable.

**The blocking gate, in order.** Run each `verify.dod` entry (its `run`, in its `cwd` if it has
one). Keep going after a failure so the report is complete; the gate fails if any row fails.

**Then check the conditional rows against the actual diff** (`git diff --stat origin/<main>...HEAD`,
`<main>` being `git.main_branch`). For each `verify.dod_conditional` entry, if any changed file
matches one of its `when` globs, say whether its `do` has been satisfied. Do not silently drop a
row that applies. A row whose `do` needs something this container cannot do (a credential, another
operating system) is satisfied by dispatching the workflow in `ci.dispatchable` that the row or the
`pr-steward` skill points to, not by marking it done.

**Manual review items.** Read the diff for each `verify.dod_manual` row and report it as `ok`,
`needs attention` (with the file and line) or `n/a`, never PASS, since nothing was run.

**Required agents.** Run `python3 <devflow root>/scripts/agents.py required --profile .claude/toolkit.yaml --at dod --changed <file with the output of git diff --name-only origin/<main>...HEAD>`. Dispatch each agent in `required`, in review mode, as the `agent-dispatch` skill says. Each gives one row `agent: <name>`: `PASS` when it reported no findings; `FAIL` when the item is blocking and its report has blocking findings, or when it did not run (`required agent did not run`); `needs attention (<blocking plus non-blocking>)` in every other case with findings. After the table, one subsection per agent with its full report verbatim, ending in its AGENT-REPORT line.

**Report** one row per check: the command (or the manual item), PASS/FAIL/`n/a` (`ok`/`needs
attention`/`n/a` for a manual item), and for a failure the actual error, not a paraphrase. Do not
fix anything unless I ask; this command reports, it doesn't repair. End with a one-line verdict on
whether this branch is ready to open or update a PR; a `FAIL` agent row means the branch is not ready.
