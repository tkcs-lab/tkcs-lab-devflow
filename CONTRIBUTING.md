# Contributing

## Setup

```
python3 -m venv .venv
.venv/bin/python -m pip install -r tests/requirements.txt
```

## Tests

```
.venv/bin/python -m pytest tests -q                  # everything, as CI runs it
.venv/bin/python -m pytest tests -q -m 'not slow'    # skip the long git, server and browser tests while you iterate
```

`tests/core/test_no_project_words.py` fails if a file contains a project-specific word; keep the text generic.
`tests/core/test_contracts.py` checks the playbooks against the code: every `tld` call parses with the real CLI,
every runtime action is defined in `playbooks/runtime.md`, every role, checklist, stack and policy they name exists,
and no runtime tool or model name appears in the core content. `tests/adapters/claude/test_structure.py` checks the
Claude wrappers and that the `runtime` skill maps every action. A procedure change goes into the playbook, with a test
that runs the code it relies on; there are no sentence-level grep tests.

Test rules:

- `tests/conftest.py` removes `GIT_CONFIG_*` (count, key and value variables), `GH_*`, `CLAUDE_*` and `TLD_*` from
  every test's environment, and points git's global and system config at `/dev/null`.
- A fixture that changes state is function-scoped. `feature_repo` and `main_repo` are shared for speed and are
  read-only: a test that changes their HEAD, config, files or guard state fails at teardown; use `fresh_repo`.
- A timing assertion keeps a wide margin (seconds, not tenths) and says what bound it protects.
- Mark a test that takes seconds `@pytest.mark.slow` (markers are strict); CI still runs it.
- The browser tests (`tests/board_*_check.js`, node with Playwright and Chromium) and the `jq` tests skip when their
  tool is missing, and fail instead when `TLD_REQUIRE_BROWSER=1`, as in CI. Locally: `npm install --prefix
  /tmp/pw playwright@1.63.0`, `/tmp/pw/node_modules/.bin/playwright install chromium`, `NODE_PATH=/tmp/pw/node_modules`.

## Coverage

CI fails when the branch coverage of `src/tld` drops below the floor `fail_under` in `pyproject.toml`
(`[tool.coverage.*]`; 91.3% measured, floor 90). Subprocesses count: `patch = ["subprocess"]` makes coverage
measure every Python child the tests start (`cli/tld`, the hook scripts) through a `.pth` file and an environment
variable, so nothing else is needed. Same command locally:

```
.venv/bin/python -m pytest tests -q --cov --cov-report=term       # add --cov-report=html for htmlcov/
```

Raise the floor when coverage rises; never lower it to make a change pass.

## Mutation check

`tests/mutation/run_mutants.py` applies the hand-written mutants of `tests/mutation/mutants.yaml` one at a time to a
copy of the working tree (the guards in `src/tld/guard/`, `src/tld/profile/validate.py`,
`src/tld/plan/manifest.py`) and runs the tests listed for that file; a mutant they do not fail on survives and the
check exits 1. It runs weekly and on demand (`.github/workflows/mutation.yml`), and takes a few minutes locally:

```
.venv/bin/python tests/mutation/run_mutants.py                 # all mutants
.venv/bin/python tests/mutation/run_mutants.py --only SS6 VM1  # some
```

Hand-written mutants rather than a generator such as mutmut: they are the mutations the review found surviving, so
each one stands for a bypass or a validation gap that matters; they run in minutes where a generator makes thousands
of mutants of these modules (the hook tests run real git), and they need no changes to the layout or the imports.
When you fix a survivor, add the test that kills it. When you change the code under a mutant,
`tests/core/test_mutants_file.py` fails until its `old` text matches again; add mutants for new rules.

## Evals

Before and after changing a playbook or command, run:

```
python3 evals/run.py validate
python3 evals/run.py run --dry-run
python3 evals/run.py run --agent stub --repeats 1 --require-pass   # every task with its canned outcome (CI does this)
```

A real run calls the model and costs money (`python3 evals/run.py run --task <id> --repeats 1 --run-ceiling 1.5`);
see [docs/architecture/evals.md](docs/architecture/evals.md). A new task needs a stub (`evals/stubs/<id>.json`).

**Baseline refresh.** `evals/baselines/default.json` records a hash per command over the command file, its playbook
and every file the playbook links. A change to any of them makes `tests/core/test_evals_baseline.py` and
`python3 evals/run.py check-baseline` fail. Re-run the affected tasks and write a new baseline
(`python3 evals/run.py baseline <results.jsonl>`), or, for a change that cannot affect them, refresh the hashes only
(`python3 evals/run.py baseline --refresh-hashes`) and say why in the commit message.

## Versions and releases

There is one version, in `pyproject.toml`, `.claude-plugin/plugin.json` and `src/tld/__init__.py`; they are the same
string (`tests/core/test_repo_release.py`, `tests/adapters/claude/test_structure.py::test_plugin_versions_agree`). A
Claude Project caches the plugin per version, so a change users should get ships as a new version.

To release: in a pull request, bump the three to `X.Y.Z` and add a `## [X.Y.Z]` entry to `CHANGELOG.md` (the test
requires one for a release version). After the merge the owner runs the workflow `release`
(`.github/workflows/release.yml`) on `main`: a dry run first shows the tag `vX.Y.Z` and the notes (the changelog
entry plus the pull requests merged since the previous tag); unticking `dry_run` publishes, after the owner approves
the run in the environment `tld-release`, which holds `TLD_RELEASE_TOKEN`. The workflow's own token only reads. A
breaking change to the profile raises the major version, and the release notes say how to update `tld.version`.

## Adding a hook case

1. Add rows to `tests/core/test_hook_<name>.py` for the hook you changed.
2. Add entries to `evals/adapters/claude/hook_cases.yaml` in the form `{name, tool, input, expect: deny|allow}`. Write a token-shaped string as `@@GH_TOKEN@@`, so no credential-like literal sits in the repository.
3. Run the tests and the evals above.
