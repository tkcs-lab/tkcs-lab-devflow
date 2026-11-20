# Plan: SysML architecture management (model from code, architecture change with the plan, applied in the PR, drawn on docs/architecture.md)

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** A repository opts in with `sysml: {subset: 1}` in its profile. `/tld:sysml init` surveys the code, asks you to confirm a component list, writes a small SysML v2 model under `sysml/model/`, validates it, draws it and opens one pull request that adds the model, `docs/architecture.md` and `docs/architecture.svg`; `/tld:sysml check` only validates and reports. From then on `/tld:make-plan` writes an architecture change (a proposal and the changed model files) next to the plan on the feature branch, and the last phase of `/tld:implement` archives it into the model and redraws the two docs, so the one feature pull request merges code, plan, model and picture together. CI can run `tld ops sysml check` and `tld ops sysml render --check`.

**Scope:** New: profile key `sysml.subset`, command `tld ops sysml` (four fixed subcommands, pure Python, no Node, Java or network), playbook and command `sysml`, manifest key `sysml_change` with a fence on `sysml/` and the two generated docs, status-record command `sysml`, changes to make-plan and implement, one guide. The model language is tld's documented subset of the SysML v2 textual notation; the image is an SVG. Not changed: repositories without a `sysml` block behave as today; the `spec_change` rules keep their exact messages; this repository does not turn the feature on for itself and its own plan carries no architecture change.

**Security:** Model text is written by an agent from untrusted code. It is parsed with hard limits, every path goes through one module that refuses symbolic links, the SVG shows names only from a fixed element allowlist, and doc text with control characters, links or secret-like text is rejected before it reaches markdown.

**Review focus:** the overlay with base hashes and the archive step (3.4); path and text safety (3.3, 3.5); the fence and its "no change, no touch" rule (3.7); the layout's byte stability and its package-level fallback (3.5); the claim that the subset is SysML v2 (3.1).

## 1. Goal

Add architecture management to tld ([#81](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/81)) on top of the OpenSpec integration of [PR #73](https://github.com/tkcs-lab/tkcs-lab-devflow/pull/73): an architecture model in SysML v2 built together with a `sysml init` command, an architecture change created with each plan and applied by the feature pull request (like the spec change), and the architecture drawn as an image shown on `docs/architecture.md`.

## 2. Current state

- Baseline: this plan is written on the head of PR #73 (`feature/openspec-integration`, not merged when this was written). It adds `spec_change` (`src/tld/plan/manifest.py:264-275` and the fence at `:366-376`), the wrapper `src/tld/ops/spec.py`, `playbooks/spec.md`, the spec parts of `playbooks/make-plan.md` and `playbooks/implement.md`, and the registrations a record-writing command needs: `src/tld/board/record.py:42`, `src/tld/schema/status-record.schema.json:213`, `src/tld/guard/board_gate.py:28-29`, `src/tld/guard/plan_gate.py:20`, `src/tld/cli.py:71`, the contract tests (`tests/core/test_contracts.py:25,279,313`, `tests/adapters/claude/test_structure.py:65`, `tests/core/test_board_record_wording.py:8`, `tests/adapters/claude/test_hooks_compat.py:76,170,221`, `tests/adapters/claude/test_hooks_config.py:211`), an eval task (`evals/tasks/spec-needs-version`, `evals/fixtures/commands.py:57`, `tests/core/test_evals_fixtures.py:81`) and the eval baseline `evals/baselines/default.json`.
- The profile validator enforces `type` (a bool is not an integer), `enum`, `pattern` and `minimum` (`src/tld/profile/validate.py:61-80`). The only runtime dependency is PyYAML (`pyproject.toml`), and the package needs Python 3.11 or newer.
- There is no architecture layer: a repository's structure is described only by prose docs.
- Generated docs are not a pattern yet. `tld ops docs-index check` requires a row for every doc and warns above 400 lines (`playbooks/policies/docs.md`).

## 3. Design

### 3.1 Facts and the honesty rule (research, 2026-11-20)

Read from the package registries, nothing was installed or run (the session policy refused it):

- PyPI `sysml` 0.2.0, published 2026-11-09, https://pypi.org/project/sysml/: the Open-MBEE SDK; reads `.sysml` files through a native binding library carried in platform wheels (Linux x86-64 glibc 2.28+, macOS, Windows), SDK Apache-2.0, bundled standard library EPL-2.0; its standard library JSON is downloaded from GitHub on first use. Its first release is six weeks old.
- PyPI `syside` 0.11.0, https://pypi.org/project/syside/: proprietary, needs a license key (`SYSIDE_LICENSE_KEY`), Python 3.12+.
- The npm registry has no SysML parser package (queried by name); the OMG pilot implementation needs a JVM.
- Owner decision (board, 2026-11-20): tld's own subset, pure Python, no external tool.

The subset is written to be a syntactic subset of the SysML v2 textual notation, **but nobody has run it through a SysML tool**: the keyword list, the form `dependency from A to B;` and `connect a.p to b.q;`, and the name-resolution rule below come from the planner's knowledge of the notation, not from the specification text (the open web was closed). So every statement tld prints and documents says "a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; tld does not check it against one", the subset is deliberately narrower than the language (it rejects every word that is a SysML keyword on the planner's list, a wider list than needed), and the manual step ma2 runs the valid fixture corpus through a real SysML v2 tool. If ma2 fails, the report names the construct and a follow-up plan fixes the subset (the profile's `subset` number exists for that).

### 3.2 The subset, `subset: 1`

Grammar (statements end with `;` or a `{}` body; whitespace and comments are free):

```
file      = { package }                                   -- only packages at the top
package   = "package" NAME "{" { pkgitem } "}"
pkgitem   = package | partdef | portdef | dependency | doc
partdef   = "part" "def" NAME "{" { pditem } "}"
pditem    = doc | port | part | connect
portdef   = "port" "def" NAME ( ";" | "{" [ doc ] "}" )
port      = "port" NAME ":" QNAME ";"                     -- only inside a part def
part      = "part" NAME ":" QNAME ";"                     -- only inside a part def (composition)
connect   = "connect" NAME "." NAME "to" NAME "." NAME ";"  -- only inside a part def
dependency= "dependency" "from" QNAME "to" QNAME ";"      -- only inside a package
doc       = "doc" BLOCKCOMMENT                            -- at most one per container
NAME      = [A-Za-z_][A-Za-z0-9_]*, at most 64 characters, not a reserved word
QNAME     = NAME { "::" NAME }
```

Comments `// ...` and `/* ... */` (not nested) are skipped everywhere except directly after `doc`. Any other statement start is `unsupported element '<word>'` (imports, attributes, quoted names, states, requirements and all the rest are outside the subset).

Reserved words (a name equal to one is an error; the list is deliberately wider than the SysML keyword list): `about accept action actor alias all allocate allocation analysis and as assert assign assume at attribute bind binding by calc case comment concern connect connection constant constraint decide def dependency derived do doc else end entry enum event exhibit exit expose false filter first flow for fork frame from hastype if import in include individual inout interface istype item join language library loop merge message meta metadata new not null objective occurrence of or ordered out package parallel part perform port private protected public readonly redefines ref references render rendering rep require requirement return satisfy send snapshot specializes stakeholder standard state subject subsets succession then timeslice to transition true until use variant variation verification verify via view viewpoint while xor`.

Qualified names and scopes: an element's `qname` is its owners' names joined by `::` (`Pkg::Sub::Name`). A reference `A::B::C` is resolved by taking its first segment and looking for a member of each enclosing namespace, innermost first, finishing with the top-level packages (`<scope>::A`, then each owner's scope, then plain `A`); the remaining segments are looked up as members one by one. A nested package therefore sees the members of its owners, and a sibling package's members need qualification. `connect a.p to b.q;` inside part def `D`: `a` and `b` must be part usages that are direct members of `D`, `p` a port usage of the part def that `a`'s type names, `q` of `b`'s.

The checks, in this order, each a `Finding(file, line, message)` printed as `<file>:<line>: <message>` with these exact messages (`<x>` filled in):

| Where | Message |
|---|---|
| files | `<path> is longer than 100000 bytes`; `more than 50 model files`; `the model is larger than 1000000 bytes` (these raise `ModelError`, exit 2) |
| characters | `unexpected character '<c>'` (anything outside printable ASCII, tab, newline and comments; a NUL or bidi control included); `unterminated comment` |
| syntax | `unexpected '<token>' (expected <what>)`, token `end of file` at the end; `unsupported element '<word>'`; `name '<name>' is reserved`; `name '<name>' is longer than 64 characters`; `nesting deeper than 6` (depth counted before descending: package and part def levels); `duplicate doc` |
| doc text | `doc is longer than 1000 characters`; `doc contains a character that is not allowed` (a control character other than newline and tab, U+202A-U+202E, U+2066-U+2069); `doc contains a link or a secret-like text` (matches `(?i)[a-z][a-z0-9+.-]*://`, `(?i)\bwww\.`, `(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]`, `-----BEGIN`, `\b(AKIA|ghp_|gho_|ghs_|sk-)[A-Za-z0-9_-]{8,}`) |
| model | `duplicate name '<qname>'`; `unknown name '<ref>'`; `'<ref>' is a <kind>; a <expected-kind> is needed` (a part's type must be a part def, a port's a port def, dependency ends part defs); `part def '<qname>' needs a doc`; `connect: '<a>' is not a part of '<qname>'`; `connect: '<a>' has no port '<p>'`; `too many elements (limit 300)` (packages, part defs, port defs, parts and ports); `too many relations (limit 600)` (connects and dependencies) |

A file with a syntax or character finding gives only those findings of that file (parsing stops at the first one); the model checks run only when no file has one. Findings are sorted by file, line, message. A doc's text is the comment body without `/*`, `*/` and the optional leading `*` of each line, whitespace runs collapsed to one space, trimmed.

### 3.3 Files and paths (`src/tld/sysml/files.py`)

The only module that touches the filesystem for the model and its outputs; the wrapper never opens a path itself.

- The model lives in `sysml/model/**.sysml`. A model relpath (below `sysml/model/`) must `re.fullmatch` `[a-z0-9_-]+(/[a-z0-9_-]+)*\.sysml`, else the error `invalid file '<x>': use a path like core/api.sysml`.
- `load_tree(root, base) -> dict[str, str]` walks `base` below `root`, sorted by relpath, reads UTF-8 (a decoding error is `ModelError("<path> is not valid UTF-8")`), enforces the three file limits of 3.2, and refuses a symbolic link or any non-regular file or directory.
- Every read and write checks each path component from `root` down with `os.lstat`: a symbolic link is `ModelError("path '<repo-relative path>' is a symbolic link")`, anything else that is not a directory (or a regular file at the end) `... is not a regular file or directory`. Writes create parent directories one level at a time under the same check and open the file with `os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW`, mode 0o644. A destination directory that already exists where one must be new is `ModelError("path '<p>' already exists")`.
- Resource limits: 100000 bytes a file, 50 files, 1000000 bytes in all.

### 3.4 The overlay: a change is whole files with base hashes (`src/tld/sysml/change.py`, `diff.py`)

A change lives in `sysml/changes/<id>/`:

- `proposal.md`: the headings `## Why`, `## What Changes` and `## Impact`, each with text that is not empty and not the word `TODO`.
- `model/<relpath>.sysml`: the **whole new content** of a model file (replacing the file of the same relpath), or a new file.
- `base.json`: `{"schema": 1, "files": {"<relpath>": "<sha256 hex of the model file the change replaces>"}, "removed": {"<relpath>": "<sha256 hex of the file the change deletes>"}}`. An overlay file that is not under `files` is a new file.

Rationale: a whole-file overlay is the simplest thing the parser can validate, but alone it would let a later archive silently revert a merged edit of another plan. The base hash turns that into a loud stop, and `check --change` prints a semantic diff (3.6) so the reviewer sees what changes instead of a new file.

Rules (`check --change <id>` reports each as a finding with the file `sysml/changes/<id>/<name>` and these messages): `change '<id>' changes nothing` (no overlay file and nothing removed); `missing section '<heading>'` (line 1) and `section '<heading>' is empty or still TODO` (the heading's line); `base.json is missing or invalid`; `<relpath> is in the change but exists in the model; list it with new-change --file`; `<relpath> changed since the change was written; redo the overlay` (current hash differs from `files` or `removed`); `<relpath> is listed in base.json but missing from the change`; `<relpath> cannot be both replaced and removed`. The composed model (the current files, replaced and added by the overlay, minus the removed) is then built and checked as in 3.2; its findings carry the relpath's file name prefixed `sysml/changes/<id>/model/` for overlay files and `sysml/model/` for the rest.

`diff(old: Model, new: Model) -> list[Change]` compares element by `qname`: `added`, `removed`, or `changed` when `(kind, owner, type_ref, ends, doc)` differs, sorted by `(qname, op)`; printed `<op> <kind> <qname>`.

`archive <id>` computes everything in memory first (the check above, with zero findings required; the composed files; the two outputs of 3.5), then writes: replaced and new model files, deletes the removed ones, moves `sysml/changes/<id>` to `sysml/changes/archive/<yyyy-mm-dd>-<id>` (UTC date, injected clock `_today()`), writes the outputs. The destination must not exist. The id `archive` is reserved.

### 3.5 Drawing and the generated docs (`layout.py`, `svg.py`, `markdown.py`)

Outputs, written only by `render` and `archive`: `docs/architecture.svg` and `docs/architecture.md`, each with the stamp `<!-- generated by tld ops sysml render, layout 1; do not edit -->` (the SVG as its first line, the markdown after the summary). Byte stability is a requirement: integer coordinates only, `font-family="monospace"` at 12px with 7 pixels a character, sorted iteration (never a set), `\n`, UTF-8, no clock.

**Layout 1.** The elements drawn are part defs, grouped in frames by their owning package (a package that owns no part def has no frame; frames in the order of the first part def's declaration). Constants: `BOX_W=224`, `HEAD_H=28`, `LINE_H=16`, `PAD=8`, `GAP_X=48`, `GAP_Y=40`, `COLS=3`, `FRAME_PAD=16`, `FRAME_HEAD=28`, `MARGIN=24`; frame width `2*FRAME_PAD + COLS*BOX_W + (COLS-1)*GAP_X` (800); canvas `width = 800 + 2*MARGIN`. Detail view when the model has at most 60 part defs and at most 150 aggregated edges; otherwise the **package view**: one box per frame (header the package qname, one line `<n> part defs`), edges aggregated per pair of packages.

- A part def box: header the name; then one line `> <port> : <type>` per port in declaration order, at most 6 lines, then `+<n> more` when there are more; text longer than 30 characters is cut to 27 plus `...` (full names are in the tables). Height `HEAD_H + LINE_H*lines + PAD`. Boxes fill a frame row by row, `COLS` to a row, a row's height the tallest box; frame height `FRAME_HEAD + rows + (rows-1)*GAP_Y + FRAME_PAD`; frames stack with `GAP_Y` between them.
- Edges, aggregated by `(kind, source, target)` with a count (a connect is unordered: its pair is sorted), none between a box and itself: `dependency` (dashed, arrowhead at the target), `connect` (solid, from a `connect` statement, drawn between the part defs the two parts are typed by), `composition` (solid, diamond at the owning part def, from a part usage). A count above 1 is the label `x<n>` at the midpoint. A line runs from the centre of the source box to the centre of the target box, cut where it leaves each rectangle; floats are rounded with `round()` to integers; arrowhead and diamond are `polygon`s of length 10 and half-width 5 along the line.
- Colours: background `#ffffff`, frame stroke `#8b949e`, box fill `#f6f8fa`, stroke and text `#1f2328`.

**The SVG** uses only the elements `svg g rect line polygon text title` and the attributes `xmlns width height viewBox role aria-label x y x1 y1 x2 y2 points fill stroke stroke-width stroke-dasharray font-family font-size text-anchor`; no `href`, `style`, `script` or `foreignObject`. Text content is XML-escaped; it holds names, types and counts only, never doc text. `<title>` is `Architecture model` and `aria-label` is `Architecture diagram: <n> part defs in <m> packages`.

**The markdown** is: `# Architecture`; a blank line; a summary of at most 2 lines (`<n> part defs in <m> packages, <k> dependencies and <c> connections, generated from sysml/model/. Change it with a plan, never by hand.` and, in the package view only, `The diagram shows packages only; the tables list every part def.`); the stamp; `![Architecture](architecture.svg)`; then per package that owns anything a heading `## <qname>`, its doc (when there is one), and a table `| Part def | Ports | Description |` with one row per part def (name and `port : Type` pairs in backticks; the description is the doc); then `## Relations` with a table `| From | Kind | To |` sorted by `(kind, from, to)`. Doc text is written with whitespace runs collapsed and every one of `` \ ` * _ [ ] ( ) < > # ! | ~ & `` preceded by a backslash.

`render --check` compares both files with what `render` would write and exits 1 with, per file, `<path> is missing: run tld ops sysml render`, `<path> was rendered by layout <n>, this tld renders layout 1: run tld ops sysml render` (stamp number differs) or `<path> is out of date: run tld ops sysml render`.

### 3.6 The wrapper `tld ops sysml`

Module `src/tld/ops/sysml.py`, registered as `("ops", "sysml"): ("tld.ops.sysml", (), "new-change | check | render | archive: the architecture model")`. Four fixed subcommands; `--profile FILE` (default `<root>/.tld/toolkit.yaml`) and `--root DIR` (default `.`) on each, through a shared parent parser as `src/tld/ops/spec.py` does. Exit 0 ok, 1 findings or drift, 2 cannot run (each with the exact stderr line).

Checks before anything runs, exit 2: `ID` and the `--change` value must fullmatch `[a-z0-9]+(-[a-z0-9]+)*` (`tld ops sysml: invalid id '<id>': use lower-case words joined by hyphens`) and not be `archive` (`tld ops sysml: 'archive' is reserved`); each `--file` / `--remove` value a model relpath (3.3); the profile exists (`tld ops sysml: profile not found: <path>`); the `sysml` block exists with `subset` (`toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`) equal to the integer 1 (`tld ops sysml: sysml.subset must be 1 (got <repr>)`; a bool fails).

| Subcommand | Does |
|---|---|
| `new-change ID [--file R]... [--remove R]...` | needs model files (`tld ops sysml: no model files under sysml/model (run the sysml command's init first)`, exit 2); creates `sysml/changes/<ID>/proposal.md` when absent with the skeleton `# <ID>`, then the three headings each followed by a blank line, `TODO` and a blank line; for each `--file` copies the model file to `sysml/changes/<ID>/model/<R>` unless that exists and records its sha256 under `files` unless recorded; for each `--remove` records the hash under `removed` (a model file that does not exist: `tld ops sysml: model file <R> does not exist`; both replaced and removed: `tld ops sysml: <R> cannot be both replaced and removed`). Safe to repeat: it only adds. Prints `created sysml/changes/<ID>` or `updated sysml/changes/<ID>`. |
| `check [--change ID] [--json]` | builds and checks the model (or, with `--change`, the composed model and the change, 3.4; a missing change is `tld ops sysml: change '<id>' does not exist`, exit 2) and prints findings one per line, then with `--change` the semantic diff one `<op> <kind> <qname>` line each, then `sysml: ok (<n> elements)` when there are no findings. `--json` prints one object `{"ok": bool, "findings": [{"file","line","message"}], "changes": [{"op","kind","qname"}]}`. |
| `render [--check]` | builds and checks the model (findings: printed, exit 1, nothing written), then writes or, with `--check`, compares the two outputs (3.5). |
| `archive ID` | 3.4. |

Test seams: `_today() -> datetime.date`. Everything else is pure functions and `tmp_path`.

### 3.7 Profile key, record command, guards, manifest fence

- `sysml` is an optional top-level profile block, `additionalProperties: false`, one required key `subset`, `{"type": "integer", "enum": [1]}`. A new grammar is a new number, decided by the owner in the protected profile.
- `sysml` joins `tld.board.record.COMMANDS` and the status-record schema `command` enum, `board_gate.RECORD_COMMANDS` with `RECORD_MODES["sysml"] = ("init",)`, and `plan_gate.OPENING`, together with the playbook, the command file and an eval task (tests require all of them for a record command).
- Manifest: optional `sysml_change: <id>` (`[a-z0-9]+(-[a-z0-9]+)*`, not `archive`; else `sysml_change must be lower-case words joined by hyphens`). The spec fence code becomes one table-driven loop with two entries, keeping every `spec_change` message byte for byte. For `sysml_change` the fenced paths are `sysml/**`, `docs/architecture.md` and `docs/architecture.svg`, and the messages are: `sysml_change needs the profile's sysml block` (a profile was given without the block); `phase '<id>': touches sysml/ or the architecture docs but only the last phase may when sysml_change is set`; `last phase '<id>' must touch sysml/ when sysml_change is set` (touching any one of the three paths satisfies it); `last phase '<id>' must depend on every other phase when sysml_change is set (missing: <ids>)`; warning `sysml_change differs from plan_slug`. **No change, no touch:** with a profile that has a `sysml` block and no `sysml_change`, every phase whose `touches` overlaps a fenced path is the error `phase '<id>': touches sysml/ or the architecture docs but the manifest has no sysml_change; narrow the touches or set sysml_change`. (The spec fence keeps its present behaviour without that rule.) With no profile given the rule is skipped.

### 3.8 The playbooks

**`sysml` (init, check)** is shaped like `playbooks/spec.md`. Input `check` (default) or `init`; anything else prints `Usage: sysml [check | init]`. `check`: `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml`, a findings table, verdict: passes when both exit 0; no record. `init` (attended, record `command: sysml`, items `survey`, `confirm`, `draft`, `validate`, `pr`; `tld dod exempt`; stops on a dirty tree before branching; branch `chore/sysml-init-<yyyymmdd>` from `origin/<main>`):

1. **Survey**: stop with `The architecture model already exists (sysml/model holds files); plans update it. Nothing was changed.` when `sysml/model` holds a file; stop with `docs/architecture.md or docs/architecture.svg exists and was not generated by tld; move it first. Nothing was changed.` when either output exists without the stamp. Otherwise `run_helper` sweeps (level `standard`) find the components (deployable units, libraries, services, top-level modules), their ports (public interfaces: commands, endpoints, file formats) and which component calls which, and propose at most 4 packages and 12 part defs, each with one evidence path and one sentence, and the dependency pairs with one evidence path each.
2. **Confirm**: one `ask_human` `text` question of at most 1900 characters (one line per part def `<package>/<Name>: <at most 8 words> (<evidence path>)`, then the `from -> to` pairs), reply `ok` or the corrected list; names must fullmatch `[A-Za-z_][A-Za-z0-9_]*` and not be reserved, at most 12 part defs; a second bad reply stops with `The component list is not valid. Nothing was changed.`
3. **Draft**: one file `sysml/model/<package in lower case, hyphens for other characters>.sysml` per package, written by hand in the subset, every part def with a doc of one or two sentences describing what it is for (no literal credentials, hostnames, URLs or e-mail addresses), ports only for interfaces another component uses, dependencies only from evidence.
4. **Validate and draw**: `tld ops sysml check --profile .tld/toolkit.yaml` must exit 0 (fix and repeat), then `tld ops sysml render --profile .tld/toolkit.yaml`, then `tld ops sysml render --check --profile .tld/toolkit.yaml` exits 0. With `docs.index` in the profile add the row `- [architecture.md](<path of docs/architecture.md relative to the index file's directory>) - the architecture model and its diagram, generated from sysml/model; read when you change how the parts of the system relate.` and run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0.
5. **Deliver**: stage only `sysml/`, `docs/architecture.md`, `docs/architecture.svg` and the docs index file when a row was added; `git diff --cached --name-only` must list nothing else; commit, push, `github.pr_create` titled `chore: add the SysML architecture model` with `## What this adds`, `## Evidence`, `## Gaps` and `## Not verified`; `github.pr_subscribe` when offered; `needs_you` reason `Review PR #<n>`.

Never: merge, approve or enable auto-merge; edit a generated doc by hand; hand-write a doc image; pass an argument other than through the four subcommands.

**make-plan, "Architecture parts"** apply only with the profile's `sysml` block. Setup bullet; section 0 step 2 reads `sysml/model/**/*.sysml` and `docs/architecture.md` and stops with `run the sysml command's init first` when `sysml/model` has no file; in the Design section a subsection `### The architecture change (architecture parts)`: decide whether components, ports, composition or dependencies change (if not: no change, no `sysml_change`, say so in Scope; a revision that drops its change runs `git rm -r sysml/changes/<plan slug>/`); else `tld ops sysml new-change --profile .tld/toolkit.yaml <plan slug> --file <relpath>...` (every model file to change; `--remove` for a deleted one), edit the copied files so they are the whole new files, add new files under `sysml/changes/<plan slug>/model/`, fill `proposal.md`, run `tld ops sysml check --profile .tld/toolkit.yaml --change <plan slug>` (exit 0 before the push) and paste its diff lines into the Design section; every part def and port the change adds or removes is named by an acceptance item of the phase that builds it; manifest `sysml_change: <plan slug>`. The retirement phase lists `sysml/**`, `docs/architecture.md` and `docs/architecture.svg` in `touches`, no other phase does, and its brief holds in order: reconcile `sysml/changes/<id>/` with the deviations file so the change describes what was built (redo the overlay with `new-change` for new files); `git diff --quiet $(git merge-base HEAD origin/<main>) origin/<main> -- sysml/model` must exit 0 else stop with `status=blocked`; `tld ops sysml archive --profile .tld/toolkit.yaml <id>` (a hash mismatch stops with `status=blocked`: another plan changed the model); `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml` exit 0; commit. A conflict in `docs/architecture.*` after a merge of `origin/<main>` is resolved by running `tld ops sysml render --profile .tld/toolkit.yaml`, never by hand. `final_checks` gets: `tld ops sysml check --profile .tld/toolkit.yaml and tld ops sysml render --check --profile .tld/toolkit.yaml exit 0 and sysml/changes/<id> does not exist`. The small-scope prompt gets the same as a paragraph `Architecture change (architecture parts):` and the review helper checks that replaced files are whole, every new or removed part def and port has an acceptance item and the pasted diff matches.

**implement** sends back a merge that touches `sysml/`, `docs/architecture.md` or `docs/architecture.svg` in any phase but the last when the manifest has `sysml_change` (with the same revision and fix exception as for `openspec/`), and in a repository whose profile has a `sysml` block and a manifest without `sysml_change` sends back any merge that touches them. The final reviewer brief: the files under `sysml/changes/<sysml_change>/` were authored by the plan and are not deviations; run `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml`; `sysml/changes/<sysml_change>` must be gone; every part def and port of the archived change under `sysml/changes/archive/` must be named by an acceptance item or a test; failing any is a blocking finding.

### 3.9 Rejected

- An external tool for parsing and checking: `sysml` 0.2.0 (native library, six weeks old, first run downloads from GitHub), `syside` (proprietary), the pilot implementation (JVM). The owner chose the pure-Python subset; the price is the honesty rule of 3.1.
- An element-level delta format (merges per element but needs non-SysML syntax and a printer that loses comments and layout); editing `sysml/model/` directly on the feature branch (real git diffs, but it contradicts the owner's change-and-archive decision and leaves the docs stale between phases).
- A layered (Sugiyama-style) layout: fewer crossings but more code and harder byte stability; the grid with a package-view fallback is enough for subset 1.
- PNG: needs a rasteriser dependency; SVG renders in GitHub markdown.
- A pass-through of free arguments or an `init` subcommand in the wrapper: `init` writes ordinary model files and the wrapper checks them.
- Decisions that would be ADRs (this repository has no `docs.adr_dir`): own subset instead of an external parser; whole-file overlay with base hashes; grid layout with layout stamp; one table-driven fence.

## 4. ADRs

None (the profile has no `docs.adr_dir`).

## 5. Manual steps

### Before implementation

**mb1-merge-pr-73** (about 5 minutes). The feature pull request goes to the main branch, and this branch contains the commits of PR #73; unless #73 is merged first, the feature pull request would show all of its 33 commits. Several phases edit files that #73 changed (`playbooks/make-plan.md`, `src/tld/plan/manifest.py`, the guards, the eval baseline).

1. Open https://github.com/tkcs-lab/tkcs-lab-devflow/pull/73 and read its description; do the check `ma1-real-openspec-run` of that pull request when you want to, it does not block this plan.
2. Merge it with the merge-commit button (the repository's merge style is `merge-commit`).
3. Reload the page and expect the state `Merged`. Done when `https://github.com/tkcs-lab/tkcs-lab-devflow/pull/73` shows `Merged`.

### After implementation

**ma1-real-sysml-run** (about 20 minutes). The tests use model text and temp directories, so one real run in a repository shows whether the survey, the picture and the pull request are good.

1. After this feature is merged and the `tld` plugin is updated in your Claude Project (install steps in the repository's [README](https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/sysml-architecture/README.md)), take a scratch repository that has a `.tld/toolkit.yaml` and some code. Add the two lines `sysml:` and `  subset: 1` to the profile (the profile is protected: let the session propose it, or edit it yourself) and push it to the default branch.
2. Start a Claude Code session on it and run `/tld:sysml init`. Expect a question listing part defs and dependencies; reply `ok` or correct it.
3. Expect a pull request titled `chore: add the SysML architecture model`. Open `docs/architecture.md` in its files view: the diagram shows boxes in package frames with arrows, the tables list every part def, and no path outside `sysml/`, `docs/architecture.md`, `docs/architecture.svg` and the docs index changed.
4. Run `/tld:sysml check`; expect no findings.
5. Report back: pass or fail, whether the picture is readable, and the first error line if it failed.

**ma2-sysml-tool-parse** (about 15 minutes). Nothing in the tests runs a SysML tool, so this is the only check that the subset is SysML v2.

1. Take the files `tests/fixtures/sysml/valid/*.sysml` of this repository's main branch.
2. Open them in any SysML v2 tool you have, for example the tools of the pilot implementation (https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation; the planner did not open this page) or a VS Code SysML v2 extension. The specification is at https://www.omg.org/spec/SysML/2.0 (not opened either).
3. Expect every file to load with no syntax error. A semantic complaint about a missing standard library import is not a failure.
4. Report back: pass or fail, and for a failure the file, the line and the tool's message; a failure becomes a follow-up plan that fixes the subset.

## 6. Risks and open questions

- The SysML claim is unverified (3.1). If ma2 fails the subset needs a fix; nothing breaks for users in the meantime because tld checks its own subset, but the files may not open in other tools. Open research questions for the owner who wants them settled earlier: the exact reserved-word list of the notation, whether `dependency from A to B;` and `connect a.p to b.q;` are valid as written, and how a nested package resolves names without `import`.
- The layout is a grid with straight lines: a model of 300 elements falls back to the package view (3.5), and crossings in the detail view are accepted. A worker that finds the picture of the 60-part-def fixture cut off or an edge missing stops with `status=blocked`.
- A tld upgrade that changes the layout number makes every consumer's `render --check` fail until they run `render`; the changelog line says so and the stamp names both numbers.
- The check protects the model against the docs, never the model against the code: a part def that no longer exists in the code stays in the model until a plan removes it. The guide says so; the final review compares the archived change with the diff.
- A conflict in `docs/architecture.*` after merging `origin/<main>` is resolved by `render`; a git-clean merge of two plans' model edits can still leave a dangling reference, which `check` in `final_checks` catches.
- PR #73 has a gap outside this plan: its retirement check compares the merge base with `origin/<main>`, which misses a stale MODIFIED block once the branch has merged main. The sysml archive does not depend on it (base hashes); raise it on #73 separately.
- A phase that finds the baseline files different from this plan's line references (PR #73 was amended) re-reads the code and stops with `status=blocked` when a registration point it needs is missing.

## Implementation manifest

```yaml
plan_slug: sysml-architecture
feature_branch: feature/sysml-architecture
tracking_issue: 81
max_parallel: 2
manual_before:
  - id: mb1-merge-pr-73
    title: Merge pull request 73 (OpenSpec integration) into main
    why: the feature pull request goes to main and this branch contains the commits of PR 73; phases edit files it changed
    done_when: the page of pull request 73 shows Merged
manual_after:
  - id: ma1-real-sysml-run
    title: Run /tld:sysml init in a scratch repository and look at the picture
    why: the tests use temp directories, so only a real run shows whether the survey, the diagram and the pull request are good
  - id: ma2-sysml-tool-parse
    title: Open the valid fixture models in a real SysML v2 tool
    why: no test runs a SysML tool, so only this shows that the subset is SysML v2
verify_after_merge:
  - .venv/bin/python cli/tld profile validate .tld/toolkit.yaml
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - tld plan deviations check --file docs/plans/81/deviations.md --plan docs/plans/81/plan.md --all exits 0
  - the changelog has entries under docs.changelog.section and no version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
phases:
  - id: p1-profile-sysml-key
    title: Add the optional sysml profile block
    depends_on: []
    complexity: S
    touches:
      - src/tld/schema/profile.schema.json
      - src/tld/templates/toolkit.yaml
      - docs/reference/profile-reference.md
      - tests/core/test_validate_profile.py
    brief: |
      Read first: docs/reference/profile-reference.md, plan section 3.7.
      1. In src/tld/schema/profile.schema.json add a top-level property `sysml` next to `spec` (copy its shape): {"type":"object","additionalProperties":false,"required":["subset"],"properties":{"subset":{"type":"integer","enum":[1],"description":"The tld SysML subset the architecture model is written in. Present means the repository uses an architecture model: /sysml works and /make-plan writes an architecture change."}},"description":"Optional. Repository uses a SysML architecture model."}. Do not add it to the top-level `required` list and give it no default.
      2. In src/tld/templates/toolkit.yaml add, after the commented `# spec:` block, a commented block `# sysml:                 # optional: absent = the repository has no architecture model` and `#   subset: 1             # the tld SysML subset; present = the repository uses an architecture model`, in the style of its neighbours.
      3. In docs/reference/profile-reference.md add table rows after the `spec.version` row: `sysml` (no) "Section for the architecture commands and the architecture change /make-plan writes. Absent means the repository has no architecture model" and `sysml.subset` (**yes** in `sysml`) "Integer, only 1 today: the version of the tld SysML subset (see docs/guides/sysml.md, plain text, no Markdown link: the guide is added in p13). A new grammar is a new number". The keys must appear as `` `sysml `` and `` `sysml.subset ``.
      4. Tests in tests/core/test_validate_profile.py, in the style of the spec tests: `sysml: {subset: 1}` validates; `sysml: {}` fails with `missing required key 'sysml.subset'`; `subset: 2`, `subset: "1"`, `subset: 1.0` and `subset: true` each fail (the bool case is the one that matters: assert the error is reported); the unknown key `sysml.dir` fails; a profile without `sysml` validates and the `--resolved` output has no `sysml` key; `test_starter_template_sysml_block_validates_when_uncommented` (slice the `# sysml:` block of the template, strip `# `, merge it into the loaded template, assert no errors and that `# sysml:` is in the text).
      Stop condition: if the validator accepts `subset: true` after your schema change, stop with status=blocked and quote src/tld/profile/validate.py:61-80.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_profile.py -q passes, including the new sysml tests
      - .venv/bin/python -m pytest tests -q passes
      - grep -n "sysml.subset" docs/reference/profile-reference.md matches
  - id: p2-sysml-files-parse
    title: Add the safe file layer and the subset parser
    depends_on: []
    complexity: M
    touches:
      - src/tld/sysml/__init__.py
      - src/tld/sysml/types.py
      - src/tld/sysml/files.py
      - src/tld/sysml/parse.py
      - tests/core/test_sysml_files.py
      - tests/core/test_sysml_parse.py
    brief: |
      Read first: src/tld/ops/docs_index.py (module conventions), plan sections 3.2 and 3.3.
      1. Create the package src/tld/sysml/ with `__init__.py` (a docstring only: "tld's SysML subset: parse, check, change, draw (docs/guides/sysml.md)").
      2. src/tld/sysml/types.py: `@dataclass(frozen=True) class Finding: file: str; line: int; message: str` with `__str__` returning `f"{file}:{line}: {message}"`; `class ModelError(Exception)` (message is the stderr line without prefix); `@dataclass(frozen=True) class Element` with fields `kind: str` ("package", "part def", "port def", "part", "port", "connect", "dependency"), `name: str` (empty for connect and dependency), `qname: str` (a connect is `<owner qname>::connect#<n>` and a dependency `<owner qname>::dependency#<n>`, n counting from 1 per owner and kind in declaration order), `owner: str` ("" at the top), `type_ref: str | None`, `ends: tuple[str, ...]` (a connect `(a, p, b, q)`, a dependency `(from_ref, to_ref)`, else `()`), `doc: str`, `file: str`, `line: int`; the constants `RESERVED` (a frozenset of exactly the words listed in plan section 3.2) and the limits `MAX_FILE_BYTES=100000`, `MAX_FILES=50`, `MAX_TOTAL_BYTES=1000000`, `MAX_NAME=64`, `MAX_DEPTH=6`, `MAX_DOC=1000`, `MAX_ELEMENTS=300`, `MAX_RELATIONS=600`.
      3. src/tld/sysml/files.py exactly as plan section 3.3: `MODEL_DIR = "sysml/model"`, `RELPATH_RE`, `check_relpath(rel) -> str` (returns it or raises ModelError with the message `invalid file '<x>': use a path like core/api.sysml`), `load_tree(root: Path, base: str = MODEL_DIR) -> dict[str, str]`, `read_text(root, rel_path) -> str | None` (None when absent), `write_text(root, rel_path, text) -> None`, `remove_file(root, rel_path)`, `move_dir(root, src, dst)` (dst must not exist: `path '<dst>' already exists`; every component of both paths checked as in 3.3), `sha256_text(text) -> str`. Walk with `os.scandir` and `os.lstat`; never `Path.resolve` or `os.path.realpath`.
      4. src/tld/sysml/parse.py: `parse_file(text: str, file: str) -> tuple[list[Element], list[Finding]]` implementing the grammar, the character rule, the reserved-word and length rules, the depth rule (checked before descending), `duplicate doc` and the doc-text rules of plan section 3.2 with its exact messages; a tokenizer function `tokens(text)` yielding (kind, value, line); parsing stops at the first syntax or character finding of a file and returns that one finding plus no elements. `connect`, `part` and `port` outside a part def, and `dependency` outside a package, give `unexpected '<word>' (expected <what>)` with the grammar's allowed starts for that container.
      5. Tests tests/core/test_sysml_files.py (tmp_path): a symlinked `sysml`, `sysml/model`, a model file and a model subdirectory each give `path '<p>' is a symbolic link` from `load_tree`, `write_text` and `read_text`; a symlinked `docs` directory and a symlinked `docs/architecture.svg` are refused by `write_text`; `write_text` through a dangling symlink at the target is refused; a FIFO or other non-regular file; relpaths `A.sysml`, `a/../b.sysml`, `/a.sysml`, `a.txt`, `a\n.sysml`, `a b.sysml` are invalid and `core/api_2.sysml` valid; file size 100001 bytes, 51 files and a total over 1000000 bytes give the three limit messages; a non-UTF-8 file; `move_dir` onto an existing path; files come back sorted. Tests/core/test_sysml_parse.py: one test per grammar form and per message of the syntax, character and doc-text rows (a literal expected `Finding` each, including the line number): every reserved word as a name (loop over `RESERVED`), a 65-character name, nesting of 7 levels, `/* open`, a NUL, U+202E and U+00E9 outside a comment, `part x : T;` at package level, `connect` in a package, `dependency` in a part def, `import X::*;`, `attribute`, `'quoted name'`, doc twice, doc of 1001 characters, doc with `http://x`, `www.x`, `password: x`, `-----BEGIN`, `ghp_abcdefgh1`, a doc with a control character, and the happy path: the doc text normalisation (`/* \n * a\n *   b */` gives `a b`), `qname` and `connect#1`, `connect#2`, `dependency#1` numbering, comments skipped, `port def P;` and `port def P { doc /* x */ }`.
      Stop condition: if the Python in this environment is older than 3.11, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_files.py tests/core/test_sysml_parse.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - grep -c "O_NOFOLLOW" src/tld/sysml/files.py prints at least 1
  - id: p3-sysml-model-check
    title: Resolve names and check the model, with the fixture corpus
    depends_on: [p2-sysml-files-parse]
    complexity: M
    touches:
      - src/tld/sysml/model.py
      - tests/core/test_sysml_model.py
      - tests/fixtures/sysml/**
    brief: |
      Read first: src/tld/sysml/types.py, src/tld/sysml/parse.py, plan section 3.2 (qualified names, the model rows).
      1. src/tld/sysml/model.py: `@dataclass class Model: elements: tuple[Element, ...]; index: dict[str, Element]; types: dict[str, str]` (qname of a part or port usage to the qname of its resolved type def) `; targets: dict[str, tuple[str, ...]]` (a dependency's qname to `(from qname, to qname)`, a connect's to `(type qname of a, type qname of b)`); `build(files: dict[str, str]) -> tuple[Model, list[Finding]]`: parse every file in sorted relpath order (file name in findings `sysml/model/<relpath>`), and when no file has a syntax or character finding run the model checks of plan section 3.2 in the table's order: element and relation limits, duplicate names, name resolution (`resolve(ref, scope)` exactly as the plan describes: first segment looked up as a member of each enclosing namespace innermost first, then at the top; the rest member by member; a result of the wrong kind gives the `'<ref>' is a <kind>; a <expected-kind> is needed` message with the kinds `package`, `part def`, `port def`, `part`, `port`), the doc rule for part defs, and the connect rules. Findings sorted by `(file, line, message)`. A model with findings still returns the elements it built.
      2. Fixture corpus: tests/fixtures/sysml/valid/ holds five files, each loadable alone with no finding: `minimal.sysml` (one package, one part def with a doc), `ports.sysml` (port def, ports, a part def used twice), `connect.sysml` (two parts in one part def connected through their ports), `cross_package.sysml` (a dependency and a part type referenced by a qualified name across two packages, plus a nested package that uses its owner's part def unqualified), `composition.sysml` (part usages). tests/fixtures/sysml/invalid/ holds one file per model-row message, each starting with the line `// expect: <line>: <message>` naming its one expected finding (`line` counting the expect line as line 1): `duplicate_name`, `unknown_name`, `wrong_kind`, `no_doc`, `connect_not_part`, `connect_no_port`, `sibling_unqualified` (a reference to a sibling package's member without qualification gives `unknown name`), and `too_many_elements` is built in the test instead (301 generated part defs) rather than as a file.
      3. Tests tests/core/test_sysml_model.py: every valid fixture builds with no findings; every invalid fixture gives exactly its expectation; the `qname` index, `types` and `targets` of `connect.sysml` and `cross_package.sysml` as literal expected dicts; 300 elements pass and 301 fail (generated text, `too many elements (limit 300)`); 600 relations pass and 601 fail; two files defining the same qname give one `duplicate name` finding on the second; a syntax error in one file hides the model checks of the others; findings are sorted; resolution order (an inner package's name wins over an outer one's).
      Stop condition: if a valid fixture does not parse with p2's parser, fix the fixture to the grammar, not the parser, and say so in the report; stop with status=blocked only if the grammar of plan section 3.2 cannot express the fixture.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_model.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - ls tests/fixtures/sysml/valid tests/fixtures/sysml/invalid lists 5 and 7 files
  - id: p4-sysml-change
    title: Add the architecture change overlay, its semantic diff and archive
    depends_on: [p3-sysml-model-check]
    complexity: M
    touches:
      - src/tld/sysml/diff.py
      - src/tld/sysml/change.py
      - tests/core/test_sysml_change.py
    brief: |
      Read first: src/tld/sysml/files.py, src/tld/sysml/model.py, plan sections 3.4 and 3.6 (new-change and archive rows).
      1. src/tld/sysml/diff.py: `@dataclass(frozen=True) class Change: op: str; kind: str; qname: str` with `__str__` `f"{op} {kind} {qname}"`, and `diff(old: Model, new: Model) -> list[Change]` exactly as plan section 3.4.
      2. src/tld/sysml/change.py: constants `CHANGES_DIR = "sysml/changes"`, `HEADINGS = ("## Why", "## What Changes", "## Impact")`, `SKELETON(id)`; `valid_id(id)` (fullmatch plus not `archive`, raising ModelError with the two messages of plan section 3.6); `new_change(root, id, files, removes) -> str` ("created"/"updated"), copying and hashing as the table of 3.6 says through files.py only; `load_change(root, id) -> Change data` (proposal text, `base` dict, `overlay: dict[relpath, text]`); `check_change(root, id, base_files) -> tuple[dict[str, str], list[Finding]]` returns the composed files and the change-level findings of plan section 3.4 (messages exact; the proposal section check treats a section as empty when its body, stripped, is empty or equals `TODO`); `compose(base_files, overlay, removed) -> dict[str, str]`; `archive(root, id, today) -> list[tuple]` is not here: the wrapper (p7) orders the writes with these pieces, so this module offers `archive_plan(root, id, today) -> ArchivePlan` holding the composed files, the relpaths to write, the relpaths to delete and the destination `sysml/changes/archive/<today.isoformat()>-<id>`, computed in memory and raising ModelError(`path '<dst>' already exists`) when the destination exists.
      3. Tests tests/core/test_sysml_change.py (tmp_path repository with a model of two files): new-change creates the skeleton (literal expected text), copies a file and records its sha256, is repeatable and only adds (a second `--file` call keeps an edited copy untouched), records a removal, refuses a file that is not in the model, refuses replace plus remove of one file, refuses ids `archive`, `A`, `a--b`, `-a`, `a_b`; check_change: each message of plan section 3.4 once (missing and TODO sections with their lines, `changes nothing`, a base hash that changed, a new overlay file that exists in the model, an entry in base.json whose overlay file is missing, base.json missing and not JSON); the composed model of a replace, an add and a remove is built and its findings carry the right prefix (`sysml/changes/<id>/model/` for overlay files); `diff` gives added, removed and changed (a doc edit, a type edit, a moved owner) for a literal pair of models and an empty list for equal models; `archive_plan` computes the destination from the injected date and refuses an existing destination. A test asserts none of the functions writes to the repository (a read-only check: snapshot the tree before and after `check_change` and `archive_plan`).
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_change.py -q passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p5-sysml-layout
    title: Add the deterministic layout of layout 1
    depends_on: [p3-sysml-model-check]
    complexity: M
    touches:
      - src/tld/sysml/layout.py
      - tests/core/test_sysml_layout.py
    brief: |
      Read first: src/tld/sysml/model.py, plan section 3.5.
      1. src/tld/sysml/layout.py: constants of 3.5 as module constants (`LAYOUT_VERSION = 1`, `BOX_W`, `HEAD_H`, `LINE_H`, `PAD`, `GAP_X`, `GAP_Y`, `COLS`, `FRAME_PAD`, `FRAME_HEAD`, `MARGIN`, `CHAR_W = 7`, `MAX_DETAIL_BOXES = 60`, `MAX_DETAIL_EDGES = 150`); frozen dataclasses `Box(x, y, w, h, title, lines)`, `Frame(x, y, w, h, title)`, `Edge(kind, x1, y1, x2, y2, label)` (a label is `""` or `x<n>`), `Layout(view, width, height, frames, boxes, edges, counts)` with `counts = (part defs, packages, dependencies, connections)`; `layout(model: Model) -> Layout` exactly as plan section 3.5: frames in order of the first part def's declaration, boxes row-major, port lines `> name : type` cut with `fit(text)` (longer than 30 characters becomes the first 27 plus `...`), at most 6 port lines then `+<n> more`; edges aggregated and sorted by `(kind, source qname, target qname)` with `dependency`, `connect`, `composition` computed from `model.targets` and part usages (a part usage's owner part def to the usage's type def), self edges dropped, a connect pair sorted; the line cut with float arithmetic and `round()`; the package view when there are more than 60 part defs or more than 150 aggregated detail edges (a model with no part def gives an empty detail layout of width 848 and height 48).
      2. Tests tests/core/test_sysml_layout.py: build models from text through `tld.sysml.model.build`; a literal expected `Layout` (coordinates written out) for the `connect.sysml` and `composition.sysml` fixtures; exactly 3 boxes per row and the second row's `y`; box heights with 0, 3 and 8 ports (`+2 more`); `fit` on 30 and 31 characters; the frame width 800 and canvas width 848; edge aggregation (`x2`), connect symmetry, self edges absent, a dependency edge ends on the target's border (assert the end point lies on the rectangle's edge); the package view at 61 generated part defs, and at 60 part defs with 151 aggregated edges; determinism: laying the same model out twice, and a model built from files given in another dict order, gives equal layouts; no empty-model crash.
      Stop condition: if a fixture of p3 does not exist, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_layout.py -q passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p6-sysml-svg-markdown
    title: Write the SVG and the docs/architecture.md text
    depends_on: [p5-sysml-layout]
    complexity: M
    touches:
      - src/tld/sysml/svg.py
      - src/tld/sysml/markdown.py
      - tests/core/test_sysml_render.py
    brief: |
      Read first: src/tld/sysml/layout.py, plan section 3.5 (the SVG and the markdown paragraphs).
      1. src/tld/sysml/svg.py: `STAMP = "<!-- generated by tld ops sysml render, layout 1; do not edit -->"`, `ELEMENTS` and `ATTRIBUTES` frozensets (the allowlists of 3.5 written out), `esc(text)` (`&`, `<`, `>`, `"` to entities), `to_svg(lay: Layout) -> str`: the stamp line, then the `<svg>` root with `xmlns="http://www.w3.org/2000/svg"`, width, height, viewBox, `role="img"`, the `aria-label` and a `<title>`, a white `rect` background, frames (`rect` plus `text`), edges before boxes (`line`, a dashed `stroke-dasharray="6 4"` for dependencies, `polygon` arrowhead or diamond, label `text` at the midpoint), boxes (`rect`, header `text`, line `text`s, `font-family="monospace" font-size="12"`), the colours of 3.5, one element per line, `\n` ending, integers only.
      2. src/tld/sysml/markdown.py: `to_markdown(model: Model, lay: Layout) -> str` exactly as plan section 3.5 (title, summary lines with the counts, stamp, the image line, a section per package that owns anything with its doc, the part def table, the Relations table), `md_escape(text)` collapsing whitespace and backslash-escaping the 16 characters listed there, ending with one `\n`.
      3. Both modules also export `layout_number(text) -> int | None` (reads the number from the stamp line of an existing output, None when there is no stamp) for p7's drift message.
      4. Tests tests/core/test_sysml_render.py: the SVG of the `connect.sysml` fixture parses with `xml.etree.ElementTree`; every element tag is in ELEMENTS and every attribute name in ATTRIBUTES (assert on a 61-part-def model too, the package view); no `href`, `style`, `script` or `foreignObject` string occurs; a model whose names are `A_1` and a doc containing `<script>&"` renders names escaped and the SVG contains no doc text at all; golden output: `to_svg` and `to_markdown` of `connect.sysml` equal checked-in files tests/fixtures/sysml/golden/connect.svg and connect.md (write them from the first run, review them by eye, and commit them in this phase; a golden test must fail when a coordinate changes: add the test `test_golden_changes_with_layout_constant` that monkeypatches `layout.GAP_X` and asserts inequality); the markdown for a doc with `| [x](y) * _ # ! ~ & < > \ \``` has all 16 characters escaped and no raw `|` inside a cell; the summary has at most 2 lines and the package-view line appears only in the package view; the stamp is on the first line of the SVG and after the summary in the markdown; `layout_number` of both stamps is 1 and of text without a stamp None; output is identical across two runs.
      Stop condition: if the golden SVG is not valid XML or an element outside the allowlist is needed for a polygon or a label, stop with status=blocked and say which.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_render.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - grep -c "script" tests/fixtures/sysml/golden/connect.svg prints 0
  - id: p7-ops-sysml-cli
    title: Add tld ops sysml, the four-subcommand wrapper
    depends_on: [p4-sysml-change, p6-sysml-svg-markdown]
    complexity: M
    touches:
      - src/tld/ops/sysml.py
      - src/tld/cli.py
      - docs/reference/cli.md
      - tests/core/test_ops_sysml.py
      - tests/core/test_mutants_file.py
      - tests/mutation/mutants.yaml
    brief: |
      Read first: src/tld/ops/spec.py (the model for this module), docs/reference/cli.md, tests/core/test_mutants_file.py, tests/mutation/mutants.yaml, plan section 3.6.
      1. Create src/tld/ops/sysml.py in the shape of src/tld/ops/spec.py: module docstring with the usage lines, `main(argv=None) -> int`, a shared parent parser with `--profile` and `--root` passed as `parents=[common]` to the four subparsers (new-change with `id`, repeatable `--file` and `--remove`; check with `--change` and `--json`; render with `--check`; archive with `id`), `if __name__ == "__main__": sys.exit(main())`. Usage errors exit 2 (argparse). No other subcommand and no pass-through argument.
      2. Implement plan section 3.6 exactly: the checks in the order listed with their stderr lines and exit 2 (ids, relpaths, profile, block, subset as the integer 1 and not a bool); then each subcommand as its table row says, using only the functions of tld.sysml.files, model, change, diff, layout, svg and markdown (the wrapper opens no path itself); `check`'s output order (findings, the diff lines, then `sysml: ok (<n> elements)`), the `--json` object, `render` writing the two outputs `docs/architecture.svg` and `docs/architecture.md` (`OUTPUTS` constant) only through `files.write_text`, `render --check` with its three messages (using `svg.layout_number` and `markdown.layout_number`; both files are checked and every problem printed), `archive` writing in the order: composed model files, deletions, the moved change folder, the two outputs, after computing all of it in memory first; a `ModelError` anywhere prints `tld ops sysml: <message>` and exits 2; the injectable `_today()` seam (`datetime.datetime.now(datetime.timezone.utc).date()`).
      3. Register in src/tld/cli.py COMMANDS: `("ops", "sysml"): ("tld.ops.sysml", (), "new-change | check | render | archive: the architecture model")`. Add the row to docs/reference/cli.md in the ops block in the format of the `ops spec` row: `tld ops sysml new-change\|check\|render\|archive [--profile FILE] [--root DIR]`, module `tld.ops.sysml`.
      4. Tests tests/core/test_ops_sysml.py (tmp_path repositories with a profile and the p3 fixtures copied into `sysml/model/`): each subcommand's happy path with literal expected stdout; every exit-2 check with its exact line (`archive` reserved, bad ids, bad relpath, no profile, no `sysml` block, `subset: 2`, `subset: true`, no model files); `check` findings exit 1 and `--json` shape; `check --change` prints the diff lines; `render` writes both files and `render --check` is 0, then 1 with `is out of date` after an edit, with `is missing` after a delete and with `was rendered by layout 7, this tld renders layout 1` for a file whose stamp says 7; `render` with a model finding writes nothing; a symlinked `docs` directory makes `render` exit 2 and write nothing outside the tree (assert a canary file outside the tree is untouched); a symlinked `sysml/changes/archive`; the full cycle: new-change, edit the copy, fill the proposal, `check --change` 0, `archive` (patched `_today`), then `sysml/changes/<id>` is gone, `sysml/changes/archive/2026-01-02-<id>` exists, the model has the new content, `render --check` is 0; archive stops with exit 1 and writes nothing when another edit changed a base file after new-change (the `changed since` message) and when the destination exists; two plans changing one file: the second archive is refused; unknown subcommands and extra arguments exit 2 with nothing run (`feedback`, `init`, `archive x --force`). One subprocess test runs `cli/tld ops sysml check --root R --profile P` and asserts the exit code and the `sysml: ok` line, which proves the registration.
      5. Mutation: add `src/tld/ops/sysml.py`, `src/tld/sysml/files.py` and `src/tld/sysml/change.py` to `MODULES` in tests/core/test_mutants_file.py and four mutants to tests/mutation/mutants.yaml in the file's format, each pointed at the test files of those modules (tests/core/test_ops_sysml.py, test_sysml_files.py, test_sysml_change.py): remove `os.O_NOFOLLOW` from the write flags in files.py; turn the reserved-id check for `archive` into a no-op; delete the base-hash comparison of `check_change` (the line that raises the `changed since the change was written` finding); make `render --check` compare nothing. Stop with status=blocked if `MODULES` is not defined in that test file.
      Stop condition: if the contracts or the tests of the CLI listing (tests/core/test_contracts.py) fail because the playbook for `ops sysml` does not exist yet, that is p10: report it and say which test, do not add a playbook here.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_ops_sysml.py tests/core/test_mutants_file.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - .venv/bin/python cli/tld ops sysml --help exits 0 and lists new-change, check, render and archive
  - id: p8-manifest-sysml-change
    title: Add the sysml_change manifest key and make the fence table-driven
    depends_on: [p1-profile-sysml-key, p7-ops-sysml-cli]
    complexity: S
    touches:
      - src/tld/plan/manifest.py
      - tests/core/test_validate_manifest.py
      - tests/mutation/mutants.yaml
      - docs/reference/profile-reference.md
    brief: |
      Read first: src/tld/plan/manifest.py (lines 20-100, 255-280 and 360-380), tests/core/test_validate_manifest.py (the spec_change tests), tests/mutation/mutants.yaml, plan section 3.7.
      1. Add "sysml_change" to TOP_KEYS after "spec_change".
      2. Replace the spec-only code in validate() (the id check block and the fence block) by one table-driven loop over `FENCES = {"spec_change": {"block": "spec", "paths": ("openspec/**",), ...}, "sysml_change": {"block": "sysml", "paths": ("sysml/**", "docs/architecture.md", "docs/architecture.svg"), ...}}` where each entry also carries its message templates. Every message of `spec_change` stays byte for byte as it is now (the existing tests are the proof: do not edit them); the `sysml_change` messages are those of plan section 3.7. The id rule for `sysml_change` additionally rejects `archive` with the same id error. A phase "touches the fence" when `paths_overlap(entry, p)` holds for any fenced path p; "the last phase must touch" is satisfied by one of the paths.
      3. The no-change-no-touch rule of 3.7 for `sysml` only: with a profile that has a `sysml` mapping and no `sysml_change` key, add the error `phase '<id>': touches sysml/ or the architecture docs but the manifest has no sysml_change; narrow the touches or set sysml_change` for every phase that touches the fence; skipped when no profile is given.
      4. docs/reference/profile-reference.md, section "The manifest": add one sentence after the `spec_change` one: `sysml_change` (optional) names the architecture change the plan carries; the profile needs a `sysml` block and only the last phase may touch `sysml/`, `docs/architecture.md` and `docs/architecture.svg`; with a `sysml` block and no `sysml_change` no phase may touch them.
      5. Tests in tests/core/test_validate_manifest.py next to the spec tests: the happy path with a sysml profile; ids `"abc\n"`, `"-x"`, `"../x"`, `"A"`, `"a--b"`, `""`, `"archive"`, `7`, `["x"]`; the missing block error; the fence for a middle phase with each of `sysml/model/core.sysml`, `sysml/changes/x/model/a.sysml`, `sysml/`, `sysml/**`, `docs/architecture.md`, `docs/architecture.svg`, `docs/**`, `**/*.md` (exact error each) and no error for `src/**` and `docs/README.md`; the last phase touching only `docs/architecture.svg` passes; the last phase touching none gives the last-phase error; the dependency rule; the differing-slug warning; the no-change-no-touch error with and without a profile and its absence for a profile with no `sysml` block; both `spec_change` and `sysml_change` set with a last phase touching both fences passes; `sysml_change` added to the known-key test with a plan that keeps `errors(m, vm) == []`; one CLI test through `--profile`.
      6. tests/mutation/mutants.yaml: two mutants in the file's format, one dropping the last-phase exclusion for sysml and one skipping the sysml block check, each pointed at tests/core/test_validate_manifest.py.
      Stop condition: if any existing spec_change test fails after your refactor, undo the refactor of that message and keep it byte for byte; stop with status=blocked if `paths_overlap` does not flag `docs/architecture.md` against `docs/**`.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_manifest.py tests/core/test_mutants_file.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - grep -n "sysml_change" src/tld/plan/manifest.py matches in TOP_KEYS and validate
  - id: p9-sysml-record
    title: Register sysml as a status-record command
    depends_on: []
    complexity: S
    touches:
      - src/tld/board/record.py
      - src/tld/schema/status-record.schema.json
      - tests/core/test_status_record.py
      - tests/core/test_contracts.py
    brief: |
      Read first: src/tld/board/record.py (line 42), tests/core/test_status_record.py (the spec cases added by commit "p4-spec-record": grep for `spec`), plan section 3.7.
      1. src/tld/board/record.py: add "sysml" to COMMANDS after "spec".
      2. src/tld/schema/status-record.schema.json: add "sysml" to the `command` enum (line 213 area) and to the sentence listing commands in the description, in COMMANDS order (test_command_enum_matches_commands checks it).
      3. tests/core/test_contracts.py: add "sysml" to the `expected` set of test_record_commands_cover_the_playbooks (line 279). Do not touch COMMANDS (line 25) or RESEARCH_PLAYBOOKS (line 313): phase p10.
      4. tests/core/test_status_record.py: add "sysml" to every parametrize list that holds "spec"; add `test_record_id_for_sysml` copying the spec one (`tld board record-id --repo o/r --command sysml --session session_01abc` prints `r--sysml--ion01abc` and `parse_doc_id` accepts it).
      Stop condition: if a test outside these files fails because `sysml` is not yet a command file or a playbook, stop with status=blocked and name the test (that test is p10's).
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_status_record.py tests/core/test_contracts.py -q passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p10-sysml-command
    title: Write the sysml playbook and command wrapper and register them
    depends_on: [p7-ops-sysml-cli, p9-sysml-record]
    complexity: M
    touches:
      - playbooks/sysml.md
      - adapters/claude/commands/sysml.md
      - src/tld/guard/board_gate.py
      - src/tld/guard/plan_gate.py
      - evals/fixtures/commands.py
      - evals/tasks/sysml-needs-subset/task.yaml
      - evals/stubs/sysml-needs-subset.json
      - evals/baselines/default.json
      - tests/core/test_contracts.py
      - tests/core/test_sysml_playbook.py
      - tests/core/test_evals_fixtures.py
      - tests/core/test_board_record_wording.py
      - tests/core/test_hook_board_gate.py
      - tests/core/test_hook_plan_gate.py
      - tests/adapters/claude/test_structure.py
      - tests/adapters/claude/test_hooks_compat.py
      - tests/adapters/claude/test_hooks_config.py
      - tests/adapters/claude/test_hook_board_gate_adapter.py
    brief: |
      Read first: playbooks/spec.md (the model for this playbook), adapters/claude/commands/spec.md, plan section 3.8 (the `sysml` paragraph), the eval task `spec-needs-version` (evals/tasks, evals/stubs, evals/fixtures/commands.py).
      1. Create playbooks/sysml.md from plan section 3.8 in the shape of playbooks/spec.md: title, one-paragraph purpose, the line `Usage: sysml [check | init]`, `Input: check (default) or init`, the rules line linking policies/untrusted-text.md, policies/status-board.md, policies/research.md and runtime.md, Setup (profile as policies/profile.md says; stop with `toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`; `tld dod exempt` for init), `## check`, `## init` with the steps headed `### 1. Survey`, `### 2. Confirm`, `### 3. Draft`, `### 4. Validate and draw`, `### 5. Deliver` and the status record (kind command, command sysml, `attended: true`, document id from `tld board record-id --repo <owner>/<repo> --command sysml --session <this session's id>`, items survey, confirm, draft, validate, pr), `## Never`. Every `tld ops sysml` call uses `--profile .tld/toolkit.yaml` and only flags the subcommand's --help lists. State in `## init` the subset in one short list (the grammar forms of plan section 3.2 in plain words) so a session can write the model without the plan.
      2. The playbook must not contain `/tld:`, runtime tool or model names, or the words ruff, pytest, connector, mypy (tests/core/test_contracts.py RUNTIME_WORDS, tests/conftest.py FORBIDDEN). Refer to the command as `sysml`.
      3. Create adapters/claude/commands/sysml.md as a copy of adapters/claude/commands/spec.md with: description "Build a SysML architecture model for existing code (init: one pull request, never merged) or validate it (check); needs the profile's sysml block", argument-hint "[check | init]", `model: opus`, the playbook path `${CLAUDE_PLUGIN_ROOT}/playbooks/sysml.md`. Under 1500 bytes.
      4. src/tld/guard/board_gate.py: add "sysml" to RECORD_COMMANDS and `"sysml": ("init",)` to RECORD_MODES. src/tld/guard/plan_gate.py: add "sysml" to OPENING.
      5. tests/core/test_contracts.py: add "sysml" to COMMANDS (line 25) and RESEARCH_PLAYBOOKS (line 313). tests/adapters/claude/test_structure.py: add "sysml" to the tuple at line 65. tests/core/test_board_record_wording.py: add "sysml" to WRITERS (line 8). tests/adapters/claude/test_hooks_compat.py: add `COMPAT["sysml"]` with the two rows `("git checkout -b chore/sysml-init-20260101 origin/main", "git checkout -b chore/sysml-init-<yyyymmdd> origin/<main>")` and `("git push -u origin chore/sysml-init-20260101", "git push -u origin chore/sysml-init-<yyyymmdd>")`, add `sysml/model/core.sysml`, `docs/architecture.md` and `docs/architecture.svg` to test_files_the_commands_write_are_allowed (line 221), and `"<sysml_change>": "foo"` to PLACEHOLDERS (line 170). tests/adapters/claude/test_hooks_config.py: add `("sysml", True)` to the dod-exempt parametrize (line 211).
      6. Guard tests: tests/core/test_hook_board_gate.py: copy the spec tests for sysml (`/tld:sysml` and `/tld:sysml check` open no state and do not block; `/tld:sysml init` does); tests/core/test_hook_plan_gate.py: copy the `/tld:spec init` opening test for `/tld:sysml init`; tests/adapters/claude/test_hook_board_gate_adapter.py: copy the `/tld:spec init` real-script case for `/tld:sysml init`.
      7. Eval task: copy `spec-needs-version` as `sysml-needs-subset`: a profile without a `sysml` block, command `/tld:sysml init`, expected stop message `toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`; add the `sysml` branch to `build` in evals/fixtures/commands.py and "sysml" to the parametrize at tests/core/test_evals_fixtures.py:81 (and the `if command == "spec"` assertion that the profile has no block, for sysml too).
      8. tests/core/test_sysml_playbook.py: the playbook contains the line `Usage: sysml [check | init]`, contains `attended: true`, contains the five step headings of item 1, and the command file names the playbook path; `test_sysml_playbook_names_the_stop_message_of_its_eval` (model: the spec one in tests/core/test_spec_playbook.py) reads the `stop_message` of the `command == "sysml"` branch of evals/fixtures/commands.py, asserts it occurs in playbooks/sysml.md and equals the stderr of `tld.ops.sysml.main` for a profile without a `sysml` block; the playbook contains each stop message of plan section 3.8 verbatim.
      9. Refresh the eval baseline last: `python3 evals/run.py baseline --refresh-hashes` and commit evals/baselines/default.json.
      Stop condition: if a test in tests/core/test_contracts.py fails for a reason this brief does not cover, read the assertion and fix the playbook text, not the test; stop with status=blocked only if the test itself contradicts this brief.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_sysml_playbook.py tests/core/test_board_record_wording.py tests/core/test_evals_stubs.py tests/core/test_evals_baseline.py tests/adapters/claude -q passes
      - .venv/bin/python -m pytest tests -q passes
      - python3 evals/run.py check-baseline exits 0
  - id: p11-plan-playbooks
    title: Make make-plan write the architecture change and implement archive it
    depends_on: [p8-manifest-sysml-change, p10-sysml-command]
    complexity: M
    touches:
      - playbooks/make-plan.md
      - playbooks/implement.md
      - evals/baselines/default.json
      - tests/core/test_sysml_calls.py
    brief: |
      Read first: playbooks/make-plan.md (the spec parts, lines 27-31, 88-95, 133-142, 219-300 and 365-372), playbooks/implement.md (sections 4, 5 and 6), plan section 3.8.
      1. playbooks/make-plan.md, Setup step 1: add a bullet: `"Architecture parts" (the architecture change, `sysml_change`, the architecture steps of the review) apply only with the profile's `sysml` block; without it leave them out and never mention the architecture model.`
      2. Section 0 step 2: with the sysml block add: read the files `sysml/model/**/*.sysml` and `docs/architecture.md`; when `sysml/model` holds no file, stop and tell the owner to run the sysml command's init first.
      3. After the subsection `### The spec change (spec parts)` add `### The architecture change (architecture parts)` with plan section 3.8's make-plan paragraph in imperative numbered form (decide, `new-change` with `--file` and `--remove`, edit whole files, add new files, proposal, `tld ops sysml check --profile .tld/toolkit.yaml --change <plan slug>` before the push and paste its diff lines into the Design section, acceptance for every new or removed part def and port, manifest key); say that the files are committed to the feature branch with the plan.
      4. The manifest block in section 2: add the line `sysml_change: <plan slug>   # optional; architecture parts only; the architecture change this plan carries` after the `spec_change` line, add the extra `final_checks` line `<`tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml` exit 0 and `sysml/changes/<sysml_change>` does not exist>   # architecture parts only`, and after the paragraph that starts `Spec parts: with `spec_change`` add `Architecture parts:` with the ordered rules of plan section 3.8 for the retirement phase (reconcile; the `git diff --quiet ... -- sysml/model` check with `status=blocked`; archive, a hash mismatch is `status=blocked`; check and render --check; commit; a conflict in `docs/architecture.*` is resolved with render) and the `touches` rule.
      5. Small scope section: after the `Spec change (spec parts):` paragraph add a paragraph headed `Architecture change (architecture parts):` with the files in full as text, the steps new-change, edit, check, implement, archive, commit, and the two acceptance items (check and render --check exit 0; `sysml/changes/<slug>` does not exist, it moved to `sysml/changes/archive/`).
      6. Section 4: extend the helper's list with: (architecture parts) a replaced file that is not whole, a new or removed part def or port that no acceptance item names, a pasted diff that does not match `check --change`.
      7. playbooks/implement.md Merge step 2: after the spec sentence add: with `sysml_change` in the manifest, a diff that touches `sysml/`, `docs/architecture.md` or `docs/architecture.svg` in any phase but the last is sent back, with the same revision and fix exception; with the profile's `sysml` block and no `sysml_change`, any diff that touches them is sent back. Section 5 final reviewer brief: after the spec sentence add the architecture sentence of plan section 3.8 (the files under `sysml/changes/<sysml_change>/` were authored by the plan; run check and render --check; the folder must be gone; every part def and port of the archived change named by an acceptance item or a test; failing any is blocking).
      8. Both files stay free of `/tld:`, runtime tool names and the forbidden words (p10's brief item 2). Do not renumber sections.
      9. tests/core/test_sysml_calls.py (model: tests/core/test_spec_calls.py): `test_every_tld_ops_sysml_span_runs_through_the_wrapper`: extract each `tld ops sysml ...` span from playbooks/sysml.md, playbooks/make-plan.md and playbooks/implement.md, fill placeholders with valid ids and relpaths, run `tld.ops.sysml.main` in a temp repository with a profile, a model and a prepared change, assert it does not exit 2 (exit 0 or 1 are findings of the temp data) and that no span uses a subcommand or flag outside the four subcommands; assert the set of subcommands found per file so an empty extraction fails: playbooks/sysml.md has `{check, render}`, playbooks/make-plan.md has `{new-change, check, archive, render}`, playbooks/implement.md has `{check, render}`.
      10. Refresh the eval baseline last: `python3 evals/run.py baseline --refresh-hashes`; commit evals/baselines/default.json.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_calls.py tests/core/test_contracts.py tests/core/test_no_project_words.py tests/adapters/claude/test_hooks_compat.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - python3 evals/run.py check-baseline exits 0
  - id: p12-docs-lists
    title: Update the command lists in the architecture docs, setup, status-board policy and plugin manifests
    depends_on: [p11-plan-playbooks]
    complexity: S
    touches:
      - docs/architecture/design.md
      - docs/architecture/hooks.md
      - playbooks/setup.md
      - playbooks/policies/status-board.md
      - .claude-plugin/plugin.json
      - .claude-plugin/marketplace.json
      - evals/baselines/default.json
    brief: |
      Read first: docs/architecture/design.md (the Playbooks paragraph), docs/architecture/hooks.md (the plan-gate and board-gate lists), the diff of phase p7-docs-lists of PR #73 (`git log --oneline -- playbooks/policies/status-board.md` shows its commit) as the pattern to copy, plan section 3.
      1. docs/architecture/design.md, the Playbooks paragraph: add `sysml` to the list of playbooks and one sentence after the OpenSpec one: the architecture model is tld's own pure-Python subset of the SysML v2 notation, drawn as an SVG, and the plan's architecture change is archived by the retirement phase. Do not link the guide (it is added in p13).
      2. docs/architecture/hooks.md: add `sysml` to the plan-gate list of commands that open a session and to the board-gate list of commands that write a record, naming only `sysml init`, next to `spec`.
      3. playbooks/setup.md: add `sysml` to the list of blocks that setup never writes, next to `spec`.
      4. playbooks/policies/status-board.md: add `sysml` next to `spec` in every list of commands: the sentence listing the playbooks that write a record, the `kind` row and the `command` row; nothing else.
      5. .claude-plugin/plugin.json and .claude-plugin/marketplace.json: add `/sysml` to the command list of each description string, next to `/spec` (nothing else; versions stay equal).
      6. Refresh the eval baseline last: `python3 evals/run.py baseline --refresh-hashes`; commit evals/baselines/default.json.
    acceptance:
      - .venv/bin/python -m pytest tests -q passes
      - grep -c "/sysml" .claude-plugin/plugin.json and grep -c "/sysml" .claude-plugin/marketplace.json each print at least 1
      - python3 evals/run.py check-baseline exits 0
  - id: p13-retire
    title: Retire the plan - the sysml guide, its index row, the README row and the changelog line
    depends_on: [p12-docs-lists]
    complexity: S
    touches:
      - docs/guides/sysml.md
      - docs/README.md
      - README.md
      - CHANGELOG.md
    brief: |
      Read first: README.md (the Commands table), docs/guides/spec.md (the shape of this guide), docs/README.md, CHANGELOG.md (the `## [Unreleased]` section), plan sections 3 and 5.
      1. Create docs/guides/sysml.md: `# Architecture with SysML`, a summary of at most 3 lines, then: what it is and the opt-in (`sysml.subset: 1` with a profile snippet); the honesty sentence of plan section 3.1 ("a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; tld does not check it against one"); the subset reference (the grammar forms in a table or a short code block, the reserved words rule, qualified names and scopes, the limits, the exact finding messages' meanings in one table); `/tld:sysml init` and `check`; how make-plan writes the architecture change (the overlay: proposal, whole files, base hashes, `check --change` diff) and how implement's last phase archives it and redraws; the fence and the no-change-no-touch rule; the two generated docs and the stamp, `render --check` and the layout number, with a two-line CI snippet (`tld ops sysml check` and `tld ops sysml render --check`); that the check protects the model against the docs, never against the code; the safety notes (symbolic links refused, SVG shows names only, doc text rules); that a board host older than this release refuses `command: sysml` records; the manual checks ma1 and ma2 of plan section 5. Under 150 lines.
      2. docs/README.md: in `## Guides` add after the `guides/spec.md` row: `- [guides/sysml.md](guides/sysml.md) - architecture with SysML: the profile's sysml block, /sysml init and check, the architecture change a plan carries and its archive, the subset and the generated docs/architecture.md; read when setting up the architecture model or changing the sysml commands.`
      3. README.md: add a row to the Commands table after `/tld:spec`: `/tld:sysml [check \| init]` | builds a SysML architecture model for existing code (one pull request, never merged) and draws it on docs/architecture.md, or validates it; with a `sysml` profile block make-plan also writes the architecture change and implement archives it ([guide](docs/guides/sysml.md)).
      4. CHANGELOG.md: under `## [Unreleased]`, in its `### Added` subsection, add one line in the file's existing style: `/tld:sysml builds a SysML v2 architecture model for existing code and draws it as docs/architecture.svg on docs/architecture.md; with a sysml profile block /tld:make-plan writes the architecture change and /tld:implement archives it in the last phase; tld ops sysml check and render --check guard it in CI (#81).` No version heading.
      5. This repository's profile has no `sysml` block and this plan has no `sysml_change`, so no `sysml/` folder and no `docs/architecture.md` are created here; do not create them.
      6. Run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, then `python3 evals/run.py check-baseline`.
    acceptance:
      - sed -n '/^## \[Unreleased\]/,/^## \[/p' CHANGELOG.md | grep -n "#81" matches
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - python3 evals/run.py check-baseline exits 0
      - .venv/bin/python -m pytest tests -q passes
```
