## Why

Every repository copies the profile template, so guardrails, roles and defaults drift between repositories, and a new repository needs many questions. One pinned org base profile plus built-in defaults makes tld behave the same everywhere with almost no questions.

## What Changes

- A profile may extend a base profile pinned by commit; the base is fetched once, cached and checked, and a repository can never weaken its guarded keys.
- Built-in defaults replace many required keys; `tld profile validate --resolved` prints the result and `--explain` prints where each value came from.
- The plan, board and definition-of-done gates are on by default; the profile file and ordinary workflows are no longer protected by default, and a pull request that changes them must name them under Security.
- Setup reads more facts from the repository and asks at most one batch; migrate asks one batch about files off their default path; the organisation audit checks the base, merge settings and the git-ops central repository.

## Capabilities

### Modified Capabilities
- `project-profile`: inheritance, defaults, guarded keys, resolved output, survey and migrate additions.
- `repository-guardrails`: default protect list, gates on by default, trusted resolved profile.
- `definition-of-done-gate`: the gate is on by default.
- `plan-run-tracking`: the pull request Summary check names changed workflow and profile files.
- `release-and-repo-ops`: audit of the base pin, merge settings and the git-ops central repository.

## Impact

Behaviour changes for existing repositories are listed in the plan and the changelog.
