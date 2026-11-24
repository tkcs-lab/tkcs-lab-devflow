## Why

Each repository carries its own full copy of the organisation audit policy, so the copies drift and every new repository needs a hand-written file. One shared base, an organisation's own small policy and a small override file per repository make the audit the same everywhere and leave each repository only what is its own.

## What Changes

- A policy may extend one or more files pinned by commit; the audit reads them with the owner's token, merges them in order and refuses a file that holds a credential, an irreversible switch or, in a public repository, an organisation-private section.
- The audit reads each repository's small override file, merges it with the organisation policy and audits the effective policy per repository; an organisation-level key in an override is rejected and an override that loosens a guarded setting is held back and reported.
- The agent and release reviewer logins are derived from each repository's resolved profile unless the policy states them.
- The audit proposes, as pull requests, an override file written from what the repository shows (required checks from recent merged pull requests, release parameters from tags and manifest) and converts a whole old policy file to a minimal override.
- Policies without `extends` behave as before; dry run, `--yes` and `--allow-delete` are unchanged.

## Capabilities

### Modified Capabilities
- `release-and-repo-ops`: the organisation audit gains inheritance, override files, guarded settings, derived logins and detected proposals.

## Impact

Old policy files keep working. A repository that wants inheritance replaces its full file by an override file after the owner creates the shared base. The audit needs a token that can read the files it extends.
