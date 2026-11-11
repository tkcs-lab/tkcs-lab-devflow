---
name: stack-go
description: Go conventions for devflow plans and phases — toolchain setup, the gofmt / vet / test / race / staticcheck / govulncheck checks, test conventions, and how to write acceptance and verify_after_merge entries for Go phases. Loaded when the profile lists the go stack.
user-invocable: false
---

# Stack: Go

Defaults. The project's own docs (AGENTS.md, CONTRIBUTING.md), its task runner (`Makefile`,
`mise.toml`, `Taskfile.yml`, `justfile`) and the style of the surrounding code win over this file.
When the project wraps a check in a task, run the task, not the bare command, so the flags match CI.

## Toolchain

- The Go version is the `go` (and `toolchain`, if present) line of `go.mod`. Check `go version`
  first. A Go 1.21+ binary downloads the toolchain `go.mod` asks for by itself (`GOTOOLCHAIN=auto`);
  if that download is blocked, install the version with the project's tool manager (`mise install`,
  `asdf install`) or say so, rather than building with an older toolchain.
- Never edit `go.mod` / `go.sum` by hand. `go get <mod>@<version>` to add or bump, `go mod tidy`
  afterwards; run with `GOFLAGS=-mod=readonly` (what CI usually does) to catch a missing tidy.
- Tools the project does not vendor run as `go run <module>/cmd/<tool>@<version> ./...` so nothing
  is installed globally; prefer the version the project's CI pins over `@latest`.
- CGO: if `go build` needs a C toolchain the container lacks, say so; do not switch drivers or set
  `CGO_ENABLED=0` unless the project already builds that way.

## The checks, cheapest first

| Check | Command | Notes |
|---|---|---|
| Format | `gofmt -l $(git ls-files '*.go')` prints nothing | `goimports` / `gofumpt` if the project uses them |
| Vet | `go vet ./...` | |
| Build | `go build ./...` | catches packages without tests |
| Test | `go test ./...` | `-count=1` to defeat the test cache when it matters |
| Race | `go test -race -count=1 ./...` | needs CGO; required when the change touches goroutines, channels, mutexes or shared state |
| Lint | `staticcheck ./...` or `golangci-lint run` | only the one the project uses, with its config |
| Vulnerabilities | `govulncheck ./...` | after a dependency change; needs network |

## Conventions for workers

- Errors: return them, wrap with `fmt.Errorf("doing x: %w", err)`, compare with `errors.Is` /
  `errors.As`, never by string. No `panic` for expected failures. Handle or explicitly discard every
  error (`_ =` with a reason); no ignored `Close` on a writer.
- `context.Context` is the first parameter of anything that does I/O or may block; never stored in
  a struct; pass it through rather than `context.Background()` deep in the call tree.
- Accept interfaces, return concrete types; define an interface where it is consumed, small.
  No package-level mutable state; no `init()` with side effects.
- Every goroutine has an owner that waits for it (`sync.WaitGroup`, `errgroup`) and a way to stop
  (context). Close channels only from the sender.
- Keep packages under `internal/` unless they are meant to be imported. Exported identifiers get a
  doc comment starting with their name.
- New dependencies only when the standard library cannot do it reasonably; say why in the commit.

## Tests

- Standard `testing` package plus whatever assertion helper the project already uses (do not add
  one). Table-driven tests with `t.Run(tc.name, ...)`; name the case for the behaviour.
- `t.Helper()` in helpers, `t.TempDir()` for files, `t.Cleanup` for teardown, `t.Setenv` for the
  environment (it rules out `t.Parallel()` in that test). `t.Parallel()` only where the package
  already does it and the test shares no state.
- HTTP: `net/http/httptest` (`httptest.NewServer`, `httptest.NewRecorder`); no real network in
  unit tests. Time: inject a clock or use `testing/synctest` (Go 1.25+) rather than `time.Sleep`.
- Golden files under `testdata/`, updated by an `-update` flag only if the project has one.
- Write the failing test first and see it fail for the right reason. A test written ahead of its
  implementation calls `t.Skip("<phase id>: not implemented yet")`, and the phase that implements
  it removes the skip in the same commit. Never loosen an assertion, delete a case or add a skip to
  get green.
- A test that needs a service (database server, object store, browser) carries a build tag or an
  env guard the project already uses, and is skipped, visibly, when the service is absent.

## Writing `acceptance` entries

Each one is checkable by a command with an expected result. Prefer, in this order:

1. A named test: `go test ./internal/store -run '^TestPut/rejects_empty_key$' -count=1 passes`
2. A package: `go test ./internal/store/... -count=1 passes` (with `-race` when the phase touches
   concurrency)
3. A grep with the expected outcome: `grep -n "const maxBody = 10 << 20" internal/server/limits.go matches`
4. Coverage with its command: `go test ./internal/store -coverprofile=c.out && go tool cover
   -func=c.out reports >= 85% for store.go` (only when the project tracks coverage)
5. `gofmt -l` empty, `go vet` and the project's linter clean over the changed packages.

"Works well", "is tested" and "handles errors" are not acceptance.

## Writing `verify_after_merge` entries

These run after every merge, on top of the profile's `verify.fast`. Keep them targeted:

- The packages this plan changes: `go test -count=1 ./internal/store/... ./internal/server/...`,
  with `-race` when the plan touches concurrency. Not `./...` on every merge if `verify.fast`
  already runs it.
- `go build ./...` when a phase changes exported signatures (callers in other packages break).
- Each entry is a command that exits non-zero on failure; no entry that needs a credential or a
  running service the container lacks (that is a `ci.dispatchable` dispatch).

## Planning notes

- A package and its `_test.go` files belong in the same phase; list both in `touches`.
- `go.mod` / `go.sum` are an overlap between any two phases that change dependencies: give one
  phase ownership of dependency changes, or a `depends_on` edge.
- Shared test helpers (`*_helpers_test.go`, `internal/testutil`) are a common accidental overlap.
- Generated code (`go generate`, embedded assets, sqlc, protobuf) is regenerated with the
  project's command in the phase that changes its source, and both go in `touches`.
- Changing an exported signature touches every caller: grep for them while planning and put the
  callers in the same phase's `touches`.
