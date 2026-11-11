---
name: stack-swift
description: Swift conventions for devflow plans and phases — what the Linux cloud container can build (SwiftPM) and what it cannot (xcodebuild, simulators, signing), so iOS/macOS builds and tests are dispatched to a macOS GitHub Actions runner. Loaded when the profile lists the swift stack.
user-invocable: false
---

# Stack: Swift

## What runs in the container and what does not

| Works in the Linux container | Does not |
|---|---|
| `swift build`, `swift test` for a SwiftPM package that imports only Foundation, the standard library and cross-platform packages | `xcodebuild`, Xcode projects and workspaces, schemes |
| `swift package resolve`, `swift format` / `swiftlint` if installed | iOS/macOS simulators, UI tests, previews |
| Editing sources, tests, `Package.swift`, `.xcodeproj` text | Code signing, provisioning, notarisation, `xcrun`, TestFlight |
| | Anything importing UIKit, AppKit, SwiftUI, Combine, CoreData or other Apple-only frameworks (it compiles on a Mac only) |

Check whether a SwiftPM toolchain is present with `swift --version`. If it is not, nothing in the
container builds Swift at all: every build and test check below is then a CI dispatch.

## Rules for the planner

1. **Put the code that can be tested on Linux in a SwiftPM package target** (logic, models,
   parsing, networking with a fake transport). Tell the worker to test it with `swift test`
   there. Keep Apple-framework code in thin targets on top.
2. **Anything needing `xcodebuild`, a simulator or signing is verified on a macOS runner**, by a
   workflow the profile lists in `ci.dispatchable` (for example `use_when: "Build and test the iOS
   and macOS targets"`). The planner reads that list; if no macOS workflow is there, say so in the
   plan's Risks section and put the missing workflow in `manual_before` as a step for the user
   (add `.github/workflows/<name>.yml` with `workflow_dispatch` on the default branch).
3. **In `verify_after_merge`, write such checks as CI dispatches, not as shell commands.** The
   form is `dispatch <workflow-file> on <feature branch>`, for example
   `dispatch apple-tests.yml on feature/<slug>`. `/implement` dispatches it against the feature
   branch, waits for the run and treats a red run like a failed command. Local entries stay for
   what runs here: `swift build` / `swift test --filter <Target>Tests`.
4. **In a phase's `acceptance`**, name the test (`swift test --filter ParserTests/testEmptyInput
   passes`) for Linux-testable code, and for the rest `workflow <file> is green on the phase
   branch`. Do not accept "builds in Xcode".
5. A phase that changes only Apple-framework code has an acceptance of the dispatch kind only, and
   its brief must say that the worker cannot run it: the worker still writes the code and the
   tests, and dispatches the workflow against its own phase branch to confirm (the workflow must
   already be on the default branch, see the `pr-steward` skill).
6. Never plan a step that requires signing identities or provisioning profiles in the container.
   Those are `manual_before` (the user stores them as repository secrets, by name) and are used
   only by the macOS workflow.

## Rules for workers

- Code style: the project's SwiftLint / swift-format configuration if it has one; otherwise the
  Swift API Design Guidelines. Prefer value types; no force unwraps (`!`) or `try!` outside tests;
  `async/await` over completion handlers in new code unless the surrounding code is not concurrent.
- Tests: XCTest (or swift-testing if the package already uses it); one behaviour per test; fakes
  for network and clock. Write the failing test first and see it fail for the right reason.
- Keep `Package.swift` changes minimal and in one phase (parallel phases that both edit it overlap).
- Do not edit `.pbxproj` by hand beyond what the brief names; add files to SwiftPM targets
  where possible, since a hand-edited project file cannot be checked in this container.

## A starter workflow (for the user to add, if the project has none)

```yaml
name: apple-tests
on:
  workflow_dispatch:
  pull_request:
jobs:
  test:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - run: xcodebuild test -scheme <Scheme> -destination 'platform=iOS Simulator,name=iPhone 15'
```

Its file name goes into `ci.dispatchable` with a `use_when`.
