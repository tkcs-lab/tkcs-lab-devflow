# Contributing

## Setup

```
python3 -m venv .venv
.venv/bin/python -m pip install -r tests/requirements.txt
```

## Tests

```
.venv/bin/python -m pytest tests -q
```

`tests/core/test_no_project_words.py` fails if a file contains a project-specific word; keep the text generic.
`tests/core/test_contracts.py` checks the playbooks against the code: every `tld` call parses with the real CLI,
every runtime action is defined in `playbooks/runtime.md`, every role, checklist, stack and policy they name exists,
and no runtime tool or model name appears in the core content. `tests/adapters/claude/test_structure.py` checks the
Claude wrappers and that the `runtime` skill maps every action. A procedure change goes into the playbook, with a test
that runs the code it relies on; there are no sentence-level grep tests.

The version is in three places that must agree: `pyproject.toml`, `src/tld/__init__.py` (`__version__`, which
`tld.version` in a profile is checked against) and `.claude-plugin/plugin.json`.

## Evals

Before and after changing a playbook or command, run:

```
python3 evals/run.py validate
python3 evals/run.py run --dry-run
```

## Plugin versions

There is one plugin, `tld`, with its manifest in `.claude-plugin/plugin.json`. Its version and the package version in `pyproject.toml` must agree; `tests/adapters/claude/test_structure.py::test_plugin_versions_agree` enforces it. A plan's retirement phase bumps them together, because a Claude Project caches the plugin per version (see [docs/guides/delivery.md](docs/guides/delivery.md)).

## Adding a hook case

1. Add rows to `tests/core/test_hook_<name>.py` for the hook you changed.
2. Add entries to `evals/hook_cases.yaml` in the form `{name, tool, input, expect: deny|allow}`. Write a token-shaped string as `@@GH_TOKEN@@`, so no credential-like literal sits in the repository.
3. Run the tests and the evals above.
