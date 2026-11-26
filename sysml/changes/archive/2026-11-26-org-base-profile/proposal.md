# org-base-profile

## Why

Every repository copies the profile template, so the same guardrails, roles and defaults drift. One pinned org base profile plus built-in defaults makes tld the same in every repository.

## What Changes

- A new part, `ProfileBase`, fetches, caches and checks the pinned base profile.
- `Profile` now resolves the repository's keys, the base and the defaults in one place.
- `Guard` and `Plan` read the resolved profile instead of the raw file, so each depends on `Profile`.

## Impact

Core only. No adapter or board component changes.
