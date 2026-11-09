# claude-toolkit

A plan → implement workflow for Claude Code on the web (claude.ai/code), for any repository in any
language.

- **`/make-plan <what you want>`** (Opus) researches the repo, then writes either a self-contained
  single-session prompt (small scope) or a plan document with a YAML implementation manifest on a
  `plan/<slug>` branch (large scope), plus a step-by-step page for anything only a human can do.
- **`/implement <plan URL>`** (Sonnet) orchestrates a plan: one child cloud session per phase,
  periodic check-ins, merges into one feature branch, verification after every merge, one Opus review
  session, and one PR driven to green.
- **`/dod`** runs the project's definition of done and reports a table.
- **`/review [scope]`** (Opus) reviews the whole repository, some paths, or a PR in depth: security,
  tests at the unit, integration and e2e levels, and the documentation and website (accuracy,
  validity, completeness, clarity, readability). It verifies every finding, decides itself what to
  fix and what not, and writes a review document on a `review/<slug>` branch. What only you can
  decide goes onto an interactive page (add to the plan, create an issue, or drop); once you have
  chosen, it updates the review and creates the issues. Then run `/make-plan <review URL>`.

See [docs/review.md](docs/review.md) for the review flow.

Everything specific to your project lives in one file, `.claude/toolkit.yaml` (docs to read, branch
rules, verify commands, CI workflows a session may dispatch, stacks, models). The commands contain no
project facts and stop with a message naming the missing key.

## Use it in a project

1. Copy [`templates/toolkit.yaml`](templates/toolkit.yaml) to `.claude/toolkit.yaml` and fill it in.
   Reference: [docs/profile-reference.md](docs/profile-reference.md).
2. Add the plugins in your Claude Project's settings (marketplace `andras-tkcs/claude-toolkit`), see
   [docs/delivery.md](docs/delivery.md).
3. Start a session and run `/make-plan <what you want>`.

## What is here

| Path | |
|---|---|
| `plugins/devflow` | the four commands, the `project-profile`, `pr-steward`, `review-checklist`, `secure-code-review`, `test-review` and `docs-review` skills, `scripts/validate_manifest.py`, `scripts/validate_profile.py`, `scripts/review_decisions.py` (with its page template), `schema/profile.schema.json` |
| `plugins/stack-python`, `plugins/stack-go`, `plugins/stack-swift`, `plugins/stack-ipados` | stack skills the profile selects (`ipados` goes with `swift`) |
| `templates/toolkit.yaml` | starter profile |
| `docs/` | profile reference, delivery, design, [the review flow](docs/review.md), [how PrivacyFence migrated](docs/migrating-privacyfence.md) |
| `tests/` | `python -m pytest tests -q` (Python 3.11+, PyYAML) |

There is no server and nothing long-running: everything runs inside Claude Code sessions.

## Development

```
python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m pytest tests -q
```

The tests include a check that no project-specific word (a particular project's name, test runner
or linter) appears in the generic plugin. Stack-specific words belong in the `plugins/stack-*` skills.
