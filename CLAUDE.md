# claude-toolkit

A plugin marketplace for Claude Code on the web: `devflow` (commands, skills, scripts, hooks, schema)
and the `stack-*` skills. The commands are project-independent; every project fact comes from
`.claude/toolkit.yaml`.

## Layout

- `plugins/devflow/` - commands, skills, scripts, hooks, schema (the product)
- `plugins/stack-*/` - stack skills the profile selects
- `templates/toolkit.yaml` - starter profile; `tests/` - pytest; `evals/` - eval harness
- `docs/` - all documentation

## Docs

Open [docs/README.md](docs/README.md) first, then only the rows that match your task. Do not read other
docs for context. If you add, move or delete a doc, update its row in the same change.

## Commands

- Tests: `python -m pytest tests -q` (Python 3.11+, PyYAML); `/dod` runs the full gate.
- Contributor rules: [CONTRIBUTING.md](CONTRIBUTING.md)
- Docs index: `python3 plugins/devflow/scripts/docs_index.py check --index docs/README.md`

## Rules

- No project-specific words in `plugins/`, `templates/` or `.claude-plugin/` (`tests/test_no_project_words.py`).
- A behaviour a command file promises is covered by a test that greps the string or runs the script.
- Keep this file under 60 lines: detail belongs in `docs/`.
