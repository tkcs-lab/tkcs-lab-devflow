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

`tests/test_no_project_words.py` fails if a file contains a project-specific word; keep the text generic.

## Evals

Before and after changing a command, run:

```
python3 evals/run.py validate
python3 evals/run.py run --dry-run
```

## Plugin versions

The five `plugins/*/.claude-plugin/plugin.json` files must carry the same version; `tests/test_structure.py::test_plugin_versions_agree` enforces it. A plan's retirement phase bumps them together, because a Claude Project caches each plugin per version (see [docs/delivery.md](docs/delivery.md)).

## Adding a hook case

1. Add rows to `tests/test_hook_<name>.py` for the hook you changed.
2. Add entries to `evals/hook_cases.yaml` in the form `{name, tool, input, expect: deny|allow}`. Write a token-shaped string as `@@GH_TOKEN@@`, so no credential-like literal sits in the repository.
3. Run the tests and the evals above.
