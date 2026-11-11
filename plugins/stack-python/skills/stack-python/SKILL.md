---
name: stack-python
description: Python conventions for devflow plans and phases — virtualenv setup, lint and test conventions, and how to write acceptance and verify_after_merge entries for Python phases. Loaded when the profile lists the python stack.
user-invocable: false
---

# Stack: Python

Defaults. The project's own docs, `pyproject.toml` settings and the style of the surrounding code
win over this file.

## Environment

- Use a virtualenv at `.venv`, never the system `pip`: `python3 -m venv --upgrade-deps .venv`, then
  `.venv/bin/python -m pip install -e ".[dev,test]"` (use the extras the project defines; with no
  `pyproject.toml`, `-r requirements.txt`). The container's own Python can fail to build sdists;
  `--upgrade-deps` gives the venv a current pip and setuptools.
- Run tools as `.venv/bin/python -m <tool>` (or with `.venv/bin` first on `PATH`) so the project's
  pinned versions run, not a copy that happens to be installed in the container.
- Python version: whatever `requires-python` says; do not use newer syntax than the minimum.

## Conventions for workers

- Type hints on every public function; `pathlib.Path` for paths; no bare `except:`; no mutable
  default arguments; context managers for files and locks; imports at the top, sorted by the linter.
- Plain `pytest` functions and `assert`; one behaviour per test, named for the behaviour
  (`test_parse_rejects_empty_input`); fixtures over repeated setup; `tmp_path` for files; unit tests
  make no network calls (fake the boundary with `monkeypatch`); no dependence on test order, clock
  or randomness.
- Write the failing test first and see it fail for the right reason. A test written ahead of its
  implementation is `@pytest.mark.xfail(strict=True, reason="<phase id>")`, and the phase that
  implements it removes the marker in the same commit.
- Never loosen an assertion, delete a case or add a skip to get green.
- Lint with the project's linter before the last push (`ruff check .` if the project uses ruff);
  do not add a suppression the project does not already use for the same case.

## Writing `acceptance` entries

Each one is checkable by a command with an expected result. Prefer, in this order:

1. A named test: `python -m pytest tests/unit/test_x.py::TestParse::test_rejects_empty -q passes`
2. A test file: `python -m pytest tests/unit/test_x.py -q passes`
3. A grep with the expected outcome: `grep -n "CACHE_TTL = 7" src/pkg/x.py matches`
4. A coverage statement with its command: `python -m pytest tests/unit/test_x.py -q --cov=pkg.x
   --cov-branch --cov-report=term-missing reports 100%`
5. The project's lint or type check over the changed files, passing.

"Works well", "is tested" and "handles errors" are not acceptance.

## Writing `verify_after_merge` entries

These run after every merge, on top of the profile's `verify.fast`. Keep them targeted:

- The tests that cover this plan's modules, by path or `-k` expression, for example
  `python -m pytest tests/unit/test_x.py tests/unit/test_y.py -q`. Not the whole suite on every merge.
- Add an integration or contract test path only for the phase that makes it relevant.
- Each entry is a command that exits non-zero on failure; no entry that needs a credential, a
  display or another operating system (that is a `ci.dispatchable` dispatch).
- Use the interpreter the project's `verify.fast` uses (`python`, `python3` or `.venv/bin/python`),
  so all of them run in the same environment.

## Planning notes

- A new module and its test file belong in the same phase; list both in `touches`.
- Shared fixtures (`conftest.py`) are a common accidental overlap between parallel phases: give the
  phase that changes `conftest.py` a `depends_on` edge, or let one phase own it.
- Dependency changes also touch the lockfiles; regenerate them with the project's script, in one phase.
