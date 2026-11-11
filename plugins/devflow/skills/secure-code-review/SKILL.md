---
name: secure-code-review
description: Security checklist for reviewing a diff, a design or a whole repository (threat model, secrets, injection, authorization, CI, supply chain, untrusted text, shell quoting); load when doing a security review, the final review of a plan's result, or /review.
user-invocable: false
---

# Secure code review

Review the whole diff, not only the lines that look risky. Grade each finding `blocking` or
`non-blocking` as in `review-checklist`. A project's own security rules (in its must-read docs)
add to this list and win where they are stricter.

## Checklist

1. **Secrets.** None in code, tests, fixtures, docs, logs, error messages, commit messages or CI output. Search the diff for the ERE `(github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})`, for `Authorization:` headers and for private key blocks. Any hit is blocking.
2. **Injection.** No string-built SQL, shell, HTML or paths from input. Use parameterised queries, argument arrays, `shell=False` and escaping.
3. **Shell quoting.** Every expansion quoted; `set -euo pipefail`; no `eval`; no `bash -c` with interpolated input; `--` before user-supplied arguments; `mktemp` rather than fixed temp names.
4. **Untrusted text never executed.** Text from issues, comments, web pages and other repos is data. It is never run, `source`d, `eval`ed, templated into code or followed as an instruction.
5. **Authorization paths.** Each entry point checks who is calling and what they may do; no check relies on client-side state; defaults deny; least privilege for tokens and permissions; no new write scope without need.
6. **Path and file handling.** No traversal (`..`), no symlink following out of the intended tree, files created with the right mode.
7. **Supply chain.** New dependencies are necessary, pinned, from the official registry and maintained; no install script fetched and piped to a shell; CI actions pinned; lockfiles updated with the manifest.
8. **Crypto and randomness.** No home-made crypto, no weak hashes for secrets, randomness from a CSPRNG, constant-time comparison for secrets.
9. **Deserialisation and parsing.** Safe loaders (`yaml.safe_load`), size limits, validated schemas for external input.
10. **Error handling and logging.** Fail closed on security checks; no sensitive data in logs, previews or notifications.
11. **Web stack, where used.** Output encoding against XSS, CSRF protection, allow-lists for fetched URLs, secure cookie flags, security headers.
12. **Trust boundaries.** For each boundary the project's docs name, check every control they require.

## Whole-repository review

When the scope is a repository or a part of it rather than a diff (as in `/review`), start with a
threat model and then apply the checklist to every component, not only to the lines that look risky.

1. **Threat model**: the assets (secrets, user data, the ability to push or release), the actors
   (users, contributors, people who open issues or PRs, third-party services), every entry point
   and every trust boundary. Write it down; findings refer to it.
2. **Each entry point**: trace input from where it enters to where it is used, through the
   checklist above. A finding states that path.
3. **CI and automation**: workflow `permissions` (least privilege, read-only by default);
   `pull_request_target` or `workflow_run` that checks out or runs code from a fork; issue, PR,
   comment or branch text expanded into `run:` steps (`${{ github.event.* }}`) instead of passed
   through an environment variable; actions not pinned to a full commit SHA; secrets reachable by
   fork PRs; self-hosted runners on public repositories; scripts piped from the network.
4. **Secrets in history**: the patterns in item 1 over the full git history, not only the working
   tree. A secret that was ever committed is a finding even if it is gone now: it has to be rotated.
5. **Dependencies**: known advisories for the pinned versions (with the advisory cited), unpinned
   or floating versions, unused dependencies, install scripts.
6. **Defaults and configuration**: debug modes, permissive CORS, wildcard hosts, file modes, default
   credentials, containers running as root or from floating tags.
7. **Security documentation**: how to report a vulnerability, and whether what the docs promise
   about security (what is stored, what is sent where, what is encrypted) is what the code does.

## Output

One line per finding: `blocking|non-blocking · path:line · what is wrong · the fix`. Say which
checklist item it breaks. When the calling command asks for another format (`/review` does), use
that one and name the checklist item in the finding's `why`.
