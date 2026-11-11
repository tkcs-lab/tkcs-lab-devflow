---
name: test-review
description: Checklist for reviewing a repository's tests at three levels (unit, integration, e2e) — what exists, what CI runs, what is covered, and whether the tests can actually fail; load when reviewing test coverage, in particular in /review.
user-invocable: false
---

# Test review

Judge the tests against the code they are meant to protect, not against a coverage number alone. A
project's own testing policy (in its must-read docs) adds to this list and wins where it is
stricter. The stack skills say how the stack runs and measures tests.

## Levels

Classify every suite and every test file by what it exercises, whatever its directory is called:

- **Unit**: one module, class or function in isolation; I/O, clock and network faked; milliseconds.
- **Integration**: several real components together, or one component against real local
  infrastructure (a database in the container, the filesystem, a subprocess, an in-process HTTP
  server, a real parser on real fixtures).
- **End-to-end (e2e)**: the system as a user runs it, through its public interface: the built CLI,
  the running service over HTTP, the UI in a browser, the installed package, the deployed
  environment.

## Checks

1. **Inventory per level**: suites, test counts, how each is run, and which CI workflow runs it on
   which trigger. A suite that no workflow runs, or runs only by hand, is a finding.
2. **Run them** as the project documents. Record failures, skips and run time. A failing or
   erroring test on the main branch is a finding of its own.
3. **Coverage**: use the project's own coverage report when the gate produces one; name the files
   and branches below the project's floor, or, without a floor, the security-relevant and core
   files with low coverage. Without a report, map behaviours to tests (next item) and say the
   numbers are estimated.
4. **Behaviour map**: list the behaviours that matter (each entry point, each trust boundary and
   its checks, error and retry paths, parsers and validators, configuration loading, migrations,
   concurrency, anything a past bug or incident touched) and, for each, the test that would fail
   if it broke, or "none".
5. **Level gaps**: behaviour only reachable through integration (a real database query, a
   subprocess, file permissions) tested only with mocks; user journeys with no e2e test at all. A
   gap at a level the project already has a harness for is a fix; introducing a harness the
   project does not have is a user decision.
6. **Can the test fail?**: assertions that check nothing (`assert True`, only "no exception"),
   assertions on the mock instead of the result, snapshot tests nobody reads, tests that pass with
   the code under test deleted, over-mocking that replaces the logic under test.
7. **Disabled and weakened tests**: skips, expected-failures, commented-out tests and lowered
   thresholds without a reason and a tracking link.
8. **Flakiness by construction**: sleeps and wall-clock timing, order dependence, shared global
   state, real network in unit tests, randomness without a seed, time zones and locale.
9. **Test data**: fixtures with real credentials, personal data or production identifiers;
   fixtures that drifted from the real format they stand in for.
10. **Docs for tests**: the documented way to run each suite works as written.

## Output

One finding per gap, in the format the calling command asks for. A "missing test" finding names
the behaviour, the file and function it lives in, the level the test belongs at, the test file to
extend, and the assertion that would prove it. End with coverage per level (measured or estimated)
and what you could not run.
