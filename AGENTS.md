# tkcs-lab-devflow

`tld`: a project-independent plan, implement and review workflow for coding agents on GitHub. The core is a
Python package with one CLI plus neutral playbooks; the Claude Code plugin `tld` is a thin adapter over it. Every
project fact comes from the project profile `.tld/toolkit.yaml`.

## Layout

- `src/tld/` - the core package (profile, plan, roles, dod, guard, board, ops, schema, templates)
- `launcher/tld` - the CLI launcher (`tld <group> <command>`, `tld migrate`; see [docs/reference/cli.md](docs/reference/cli.md))
- `playbooks/` (with `runtime.md`, `policies/`), `roles/`, `checklists/`, `stacks/` - the neutral procedures and content
- `adapters/claude/` - thin commands and agents, the `runtime` skill (runtime map, levels), hook entries, `mcp.json`
- `.claude-plugin/` - the marketplace and the one plugin `tld`, sourced from the repository root
- `tests/core/`, `tests/adapters/claude/` - pytest; `evals/` - eval harness; `deploy/` - board image
- `.github/workflows/` - CI (`test.yml`), the weekly mutation check, this repository's `release.yml`
- `.tld/toolkit.yaml` - this repository's own profile; `docs/` - all documentation; `CHANGELOG.md` - per release

## Docs

Open [docs/README.md](docs/README.md) first, then only the rows that match your task. Do not read other
docs for context. If you add, move or delete a doc, update its row in the same change.

## Commands

- Tests: `python -m pytest tests -q` (Python 3.11+, PyYAML); `/dod` runs the full gate.
- Profile: `launcher/tld profile validate .tld/toolkit.yaml`
- Docs index: `launcher/tld ops docs-index check --index docs/README.md`
- Evals after a playbook change: `python3 evals/run.py check-baseline`
- Contributor rules, coverage, mutation check, releasing: [CONTRIBUTING.md](CONTRIBUTING.md)

## Rules

- No project-specific words in `src/`, `launcher/`, `adapters/`, `.claude-plugin/` or the core content (`tests/core/test_no_project_words.py`).
- No runtime tool or model name in `playbooks/`, `roles/`, `checklists/`, `stacks/`; those live in the adapter.
- Every `tld` call, runtime action, role, checklist and policy a playbook names must exist (`tests/core/test_contracts.py`).
- A new command needs a playbook, a thin wrapper in `adapters/claude/commands/` and its rows in the contract tests.
- One version in `pyproject.toml`, `plugin.json` and `tld.__version__`; a user-visible change gets a CHANGELOG line.
- Keep this file and CLAUDE.md under 60 lines: detail belongs in `docs/`.
