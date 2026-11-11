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

## Evals

Before and after changing a command, run:

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
