# Specs with OpenSpec

`/tld:spec` builds [OpenSpec](https://github.com/Fission-AI/OpenSpec) specs for existing code and validates them.
With a `spec` block in the profile, `/tld:make-plan` also writes the spec change of a plan and the last phase of
`/tld:implement` archives it, so one feature pull request merges code, plan and specs.

## Opt in

Add the block to the profile (a protected file: the owner approves it) and merge it to the default branch:

```yaml
spec:
  version: "2.1.0"   # exact OpenSpec release, MAJOR.MINOR.PATCH; no range, no tag
```

Without the block nothing changes: make-plan, implement and every other command behave as before and never mention
specs. `tld ops spec` stops with `toolkit.yaml: missing required key 'spec.version' (add a spec block; see docs/guides/spec.md)`.

## Needs

- Node.js 22.20 or newer and `npm` on `PATH` wherever a spec command runs.
- Access to the public npm registry (`https://registry.npmjs.org/`) on the first run of a version. The package
  is installed once per version into `$TLD_CACHE_DIR/openspec/<version>`, default `~/.cache/tld/openspec/<version>`. A blocked registry
  fails with exit 2 and npm's message; ask for an allowed host, there is no fallback.

## The commands

- `/tld:spec check` (the default) runs the validator over all specs and changes, lists the capabilities and reports
  findings. It changes nothing and writes no record.
- `/tld:spec init` is for a repository that has no specs yet. It stops on a dirty working tree before it
  branches, then surveys the code and asks you once (a second time if the reply does not fit: names must be lower-case words joined by hyphens, at most 12) for the capability list (reply `ok` or give the corrected
  list). It writes one change that describes today's behaviour, validates it, archives it so OpenSpec itself produces
  the main specs, and opens one pull request on `chore/spec-init-<yyyymmdd>`. You merge it; the command never merges,
  approves or enables auto-merge. Gaps and behaviour no test covers are listed in the pull request.

## Plans carry a spec change

- `/tld:make-plan` reads `openspec/specs/*/spec.md` and decides whether the work changes observable behaviour. If it
  does, it writes `openspec/changes/<plan slug>/` (a proposal and one delta per capability), validates it, and sets
  `spec_change: <plan slug>` in the manifest. A refactor, tooling or docs change writes none.
  Without existing specs it stops and tells you to run `/tld:spec init` first.
- Every scenario of the change is named by an acceptance item of the phase that makes it true.
- The last phase (the retirement phase) archives the change: it reconciles the deltas with the deviations file,
  checks that the base branch did not change `openspec/specs`, runs `tld ops spec archive`, validates, and commits.
  The final check is that `tld ops spec validate` exits 0 and `openspec/changes/<id>` is gone.

## The fence on `openspec/`

With `spec_change` set, `tld plan validate-manifest` allows only the last phase to touch `openspec/`, requires it to
do so, and requires it to depend on every other phase, so the archive runs after all code has merged. `implement`
sends back a merge that touches `openspec/` in any other phase.

## Supply chain

The wrapper `tld ops spec` runs an npm package, so it is narrow:

- The version is an exact top-level pin in the protected profile.
- It installs outside the repository (keep `TLD_CACHE_DIR` outside the repository), with scripts off (`--ignore-scripts`) and the public registry. `--ignore-scripts` only stops install hooks.
- Only five fixed subcommands exist: `init`, `new-change`, `list`, `validate`, `archive`. No free-form OpenSpec
  arguments pass through.
- It runs with an allowlisted environment (no tokens from environment variables), no stdin, a 600 second timeout and
  telemetry off. `HOME` and the proxy variables pass through, so `~/.npmrc` is read. The package runs with your file
  permissions and is not sandboxed. Run it where no credential reachable by that user is one you would not hand to
  an npm package.
- Transitive dependencies are not pinned: the package ships no shrinkwrap, so they float. The pin protects against
  a changed top-level release only.

## Board hosts

A board host older than this release refuses `command: spec` records. `init` still runs, but its record is lost
until you upgrade the board.

## Bump the version

Change `spec.version` in the profile. That is a protected change: a worker reports it, you approve the diff and it
becomes one pull request. Run `/tld:spec check` afterwards; a bump installs the new version on its first run.

## Manual check ma1

The tests fake the OpenSpec CLI, so one real run is yours to do (about 15 minutes):

1. With the plugin updated and a board host on this release, take a scratch repository with a profile. Add
   `spec:` and `  version: "2.1.0"`, and push that to the default branch.
2. Run `/tld:spec init` and reply `ok` to the list.
3. Check the pull request `chore: add OpenSpec specs for existing code`: `openspec/specs/` holds one folder per
   capability, `openspec/changes/archive/` holds the baseline change, and no path outside `openspec/` changed.
4. Run `/tld:spec check`; expect no findings. Report pass or fail and the first error line.
