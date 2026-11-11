---
name: stack-ipados
description: iPadOS app conventions for devflow plans and phases, on top of stack-swift — a repository layout that keeps most code testable in the Linux container, iPad-specific behaviour every UI phase must handle (resizable windows, multiple scenes, keyboard, pointer, Pencil, drag and drop), and tests on an iPad simulator dispatched to a macOS runner. Loaded when the profile lists the ipados stack (list swift too).
user-invocable: false
---

# Stack: iPadOS

This skill adds to `stack-swift`; it does not replace it. List both in the profile
(`stacks: [swift, ipados]`) and follow `stack-swift` for what the container can and cannot build,
for dispatching to the macOS runner, and for the Swift code and test conventions. The project's
own docs and the style of the surrounding code win over both.

## Repository layout

For a new repository, or a phase that sets one up, plan this shape:

```
Package.swift                 # local SwiftPM package: everything that does not import UIKit/SwiftUI
Sources/<App>Core/            # models, persistence protocols, parsing, networking behind a protocol
Sources/<App>Features/        # view models / state (Observation), no SwiftUI import
Tests/<App>CoreTests/         # swift test, runs in the container
Tests/<App>FeaturesTests/
App/<App>.xcodeproj           # thin app target: SwiftUI views, scenes, App entry, assets, Info.plist
App/<App>/                    # a synchronized folder (Xcode 16+): new files need no .pbxproj edit
App/<App>UITests/             # XCUITest, iPad simulator, macOS runner only
.github/workflows/ipad-tests.yml
```

- The app target depends on the local package. The more logic sits in the package, the more of
  each phase the worker can verify itself with `swift test`.
- Use synchronized folders (Xcode 16 "folder" rather than "group") for the app and UI-test targets,
  so a worker adding a Swift file does not touch `project.pbxproj`. Creating the project itself
  needs Xcode, so the first `.xcodeproj` is a `manual_before` step for the user (or a project
  generator such as XcodeGen, whose `project.yml` is plain text, if the user prefers; then the
  workflow runs the generator before `xcodebuild`).
- Persistence, networking, clocks and file access sit behind protocols in `<App>Core` with an
  in-memory fake, so view models are tested without the device.
- No `#if canImport(UIKit)` sprinkled through the core to make it compile on Linux; if something
  needs UIKit it belongs in the app target.

## iPad behaviour every UI phase handles

A phase that adds or changes a screen names, in its brief and acceptance, which of these apply:

1. **Any window size.** iPadOS windows resize freely (Stage Manager, Split View, the windowed mode
   of iPadOS 26), so a layout must work from compact width to a full 13-inch screen, both
   orientations. Lay out by size class and available space (`ViewThatFits`, `GeometryReader`
   sparingly), never by device model or screen bounds. Do not plan `UIRequiresFullScreen`.
2. **Navigation.** `NavigationSplitView` for list-detail, collapsing to a stack in compact width;
   selection state lives in the view model so it survives the collapse.
3. **Multiple windows.** If the app supports several scenes (`WindowGroup`, `openWindow`), state is
   per scene (`@SceneStorage`, scene-scoped models), and shared data is safe to change from two
   windows at once.
4. **Keyboard.** Main actions have `.keyboardShortcut` and appear in the menu bar via `.commands`;
   focus moves with Tab (`@FocusState`, `.focusable`); text fields submit with Return.
5. **Pointer.** Hover effects on custom controls (`.hoverEffect`), context menus (`.contextMenu`) for
   secondary actions, which also serve long press on touch.
6. **Apple Pencil**, when the feature involves drawing or handwriting: PencilKit (`PKCanvasView` in a
   representable), `UIPencilInteraction` for double-tap / squeeze; never assume a Pencil is present.
7. **Drag and drop** between the app's views and with other apps: `Transferable` types with
   `.draggable` / `.dropDestination`.
8. **Accessibility.** Dynamic Type up to the accessibility sizes without truncating actions,
   VoiceOver labels on icon-only buttons, sufficient contrast in light and dark mode.

## Tests

- **In the container** (`swift test`): everything in the package: models, view models, persistence
  against the fake, and the state transitions behind navigation (selection, collapse, deep links).
- **On the macOS runner**, by dispatching the workflow: the app target builds for an iPad
  simulator, unit tests that need UIKit, and XCUITests for the main flows. Keep UI tests few and
  about flows, not pixel positions; use `accessibilityIdentifier`s, not visible text.
- To cover window sizes, the UI-test workflow can run the same tests on an iPad and, if the app
  is universal, an iPhone destination; snapshot tests, if the project uses them, render each view
  in compact and regular width.

## Rules for the planner (on top of `stack-swift`)

1. The first phase of a new app sets up the layout above and the workflow below, and its
   `manual_before` covers what only the user can do: create the Xcode project with its bundle
   identifier and team, and merge the workflow to the default branch so it can be dispatched.
2. Split each feature into a package phase (model and view model, `swift test` acceptance) and a
   UI phase (views, `workflow ipad-tests.yml is green on the phase branch` acceptance). The UI phase
   `depends_on` the package phase; parallel UI phases rarely overlap if each owns its views' folder.
3. `verify_after_merge` carries `swift test` for the touched package targets and
   `dispatch ipad-tests.yml on feature/<slug>` once the plan has app-target changes.
4. Signing, App Store Connect, TestFlight, entitlements needing a provisioning profile, and
   on-device testing (Pencil hardware, external display, performance) are `manual_before` or
   `dod_manual` items, never phase work.

## A starter workflow (for the user to add)

```yaml
name: ipad-tests
on:
  workflow_dispatch:
  pull_request:
jobs:
  package:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - run: swift test
  app:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - name: Pick an iPad simulator
        id: sim
        run: |
          udid=$(xcrun simctl list devices available -j |
            jq -r '[.devices | to_entries[] | select(.key | contains("iOS")) | .value[] | select(.name | startswith("iPad"))][0].udid')
          echo "udid=$udid" >> "$GITHUB_OUTPUT"
      - run: >
          xcodebuild test -project App/<App>.xcodeproj -scheme <App>
          -destination "id=${{ steps.sim.outputs.udid }}"
          CODE_SIGNING_ALLOWED=NO
```

The simulator is chosen by query, not by a device name, so the workflow survives runner image
updates. Its file name goes into `ci.dispatchable`, for example
`{workflow: ipad-tests.yml, use_when: "Build the iPad app and run its UI and UIKit tests on an iPad simulator (macOS runner)"}`.
