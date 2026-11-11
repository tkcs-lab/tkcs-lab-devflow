# tkcs-lab-devflow

`tld`: a project-independent plan, implement and review workflow for coding agents. The core is a
Python package with one CLI; the Claude Code plugin `tld` is a thin adapter over it. Every project
fact comes from the project profile `.tld/toolkit.yaml`.

## Layout

- `src/tld/` - the core package (profile, plan, roles, dod, guard, board, ops, schema, templates)
- `bin/tld` - the CLI launcher (`tld <group> <command>`, see [docs/reference/cli.md](docs/reference/cli.md))
- `adapters/claude/` - commands, agents, skills (with the `stack-*` skills), hook entries, `mcp.json`
- `.claude-plugin/` - the marketplace and the one plugin `tld`, sourced from the repository root
- `tests/core/`, `tests/adapters/claude/` - pytest; `evals/` - eval harness; `deploy/` - board image
- `.tld/toolkit.yaml` - this repository's own profile; `docs/` - all documentation

## Docs

Open [docs/README.md](docs/README.md) first, then only the rows that match your task. Do not read other
docs for context. If you add, move or delete a doc, update its row in the same change.

## Commands

- Tests: `python -m pytest tests -q` (Python 3.11+, PyYAML); `/dod` runs the full gate.
- Profile: `bin/tld profile validate .tld/toolkit.yaml`
- Docs index: `bin/tld ops docs-index check --index docs/README.md`
- Contributor rules: [CONTRIBUTING.md](CONTRIBUTING.md)

## Rules

- No project-specific words in `src/`, `bin/`, `adapters/` or `.claude-plugin/` (`tests/core/test_no_project_words.py`).
- A behaviour a command file promises is covered by a test that greps the string or runs the script.
- Keep this file and CLAUDE.md under 60 lines: detail belongs in `docs/`.
