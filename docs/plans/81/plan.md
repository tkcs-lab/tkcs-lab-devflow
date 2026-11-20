# Plan: SysML architecture management (model from code, architecture change with the plan, applied in the PR, drawn on docs/architecture.md)

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** A repository opts in with `sysml: {subset: 1}` in its profile. `/tld:sysml init` surveys the code, asks you to confirm a component list, writes a small model in tld's documented subset of the SysML v2 notation under `sysml/model/`, validates it, draws it and opens one pull request that adds the model, `docs/architecture.md` and `docs/architecture.svg`; `/tld:sysml check` only validates and reports. From then on `/tld:make-plan` writes an architecture change (a proposal and the changed model files) next to the plan on the feature branch, and the last phase of `/tld:implement` archives it into the model and redraws the two docs, so the one feature pull request merges code, plan, model and picture together. CI can run `tld ops sysml check` and `tld ops sysml render --check`.

**Scope:** New: profile key `sysml.subset`, command `tld ops sysml` (four fixed subcommands, pure Python, no Node, Java or network), playbook and command `sysml`, manifest key `sysml_change` with a fence on `sysml/` and the two generated docs, status-record command `sysml`, changes to make-plan and implement, one guide. The model language is tld's documented subset of the SysML v2 textual notation; the image is an SVG. Not changed: repositories without a `sysml` block behave as today; the `spec_change` rules keep their exact messages; this repository does not turn the feature on for itself and its own plan carries no architecture change. In a repository with a `sysml` block, a plan phase that touches `docs/**`, `**/*.md` or the two generated docs now fails `validate-manifest` unless the plan carries `sysml_change` (3.7).

**Security:** Model text is written by an agent from untrusted code: hard parse limits, one path module that refuses symbolic links, an SVG with names only from a fixed element allowlist, and doc text with control characters, links or secret-like text rejected.

**Review focus:** the overlay with base hashes and the archive step (3.4); path and text safety (3.2, 3.3); the fence and its "no change, no touch" rule (3.7); the claim that the subset is SysML v2 (3.1).

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

The subset is written to be a syntactic subset of the SysML v2 textual notation, **but nobody has run it through a SysML tool**: the keyword list, the form `dependency from A to B;` and `connect a.p to b.q;`, and the name-resolution rule below come from the planner's knowledge of the notation, not from the specification text (the open web was closed). So the guide, the module docstring and the `--help` of `tld ops sysml` say "a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; tld does not check it against one", the subset is deliberately narrower than the language (it rejects every word that is a SysML keyword on the planner's list, a wider list than needed), and the manual step ma2 runs the valid fixture corpus through a real SysML v2 tool. If ma2 fails, the report names the construct and a follow-up plan fixes the subset (the profile's `subset` number exists for that).

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

Comments: `// ...` to the end of a line may stand anywhere and is skipped; a block comment `/* ... */` (not nested) is allowed only directly after `doc` (anywhere else: `block comment only allowed after doc`). The first word of a statement must be one of the container's: file `package`; package `package`, `part`, `port`, `dependency`, `doc`; part def `doc`, `port`, `part`, `connect`; any other word is `unsupported element '<word>'` (imports, attributes, quoted names, states, requirements and all the rest are outside the subset). After the first word the parser expects these tokens in order, and a wrong one is `unexpected '<token>' (expected <what>)` with `<token>` its text or `end of file`: `package`: a name, `'{'`; `part` or `port` in a package: `'def'` (so `part x : T;` in a package is `unexpected 'x' (expected 'def')`); `part def N`: `'{'`; `port def N`: `';' or '{'`; `part` or `port` usage in a part def: a name, `':'`, a name, `';'`; `connect`: a name, `'.'`, a name, `'to'`, a name, `'.'`, a name, `';'`; `dependency`: `'from'`, a name, `'to'`, a name, `';'`; `doc`: `a /* */ comment`; a body still open at the end: `'}'`. A punctuation token where a statement must start gives `unexpected '<token>' (expected a statement or '}')` in a body and `unexpected '<token>' (expected 'package')` at the top; a word that is not `package` at the top is `unsupported element '<word>'`; in a `port def` body anything but `doc` is `unexpected '<word>' (expected 'doc' or '}')`.

Reserved words (a name equal to one is an error; the list is deliberately wider than the SysML keyword list): `about accept action actor alias all allocate allocation analysis and as assert assign assume at attribute bind binding by calc case comment concern connect connection constant constraint decide def dependency derived do doc else end entry enum event exhibit exit expose false filter first flow for fork frame from hastype if import in include individual inout interface istype item join language library loop merge message meta metadata new not null objective occurrence of or ordered out package parallel part perform port private protected public readonly redefines ref references render rendering rep require requirement return satisfy send snapshot specializes stakeholder standard state subject subsets succession then timeslice to transition true until use variant variation verification verify via view viewpoint while xor`.

Qualified names and scopes: an element's `qname` is its owners' names joined by `::` (`Pkg::Sub::Name`). A reference `A::B::C` is resolved by taking its first segment and looking for a member of each enclosing namespace, innermost first, finishing with the top-level packages (`<scope>::A`, then each owner's scope, then plain `A`); the remaining segments are looked up as members one by one. A nested package therefore sees the members of its owners, and a sibling package's members need qualification. `connect a.p to b.q;` inside part def `D`: `a` and `b` must be part usages that are direct members of `D`, `p` a port usage of the part def that `a`'s type names, `q` of `b`'s.

The checks, in this order (the two limit findings first, the element limit before the relation limit, only the first one returned, with the file `sysml/model` and line 0), each a `Finding(file, line, message)` printed as `<file>:<line>: <message>` with these exact messages (`<x>` filled in):

| Where | Message |
|---|---|
| files | `<path> is longer than 100000 bytes`; `more than 50 model files`; `the model is larger than 1000000 bytes` (`<path>` is the repository-relative path `sysml/model/<relpath>`; these raise `ModelError`, exit 2) |
| characters | `unexpected character '<c>'`, `<c>` being the character itself for printable ASCII and `U+XXXX` (upper-case hex, at least four digits) for anything else, for: any character of Unicode category Cc (except tab, newline and carriage return), Cf, Cs, Co, Cn, Zl or Zp anywhere in the file, comments and doc text included (so bidi controls, zero-width characters and a byte order mark are refused everywhere); any other character outside printable ASCII, tab, newline and carriage return in code (outside comments and doc text; non-ASCII letters are allowed in comments and docs); and any printable ASCII character that starts no token (``' " @ # $ % ^ & * ( ) + - = [ ] | \ < > ? ! ~ ` , /`` and a digit at the start of a word; `//` and `/*` are comment starts, so a lone `/` is this case); `unterminated comment`; `block comment only allowed after doc` |
| syntax | `unexpected '<token>' (expected <what>)`, token `end of file` at the end; `unsupported element '<word>'`; `name '<name>' is reserved`; `name '<name>' is longer than 64 characters`; `nesting deeper than 6` (depth counted before descending: package and part def levels); `duplicate doc` |
| doc text | `doc is longer than 1000 characters`; `doc contains a link or a secret-like text` (matches `(?i)[a-z][a-z0-9+.-]*://`, `(?i)\bwww\.`, `(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]`, `-----BEGIN`, `\b(AKIA|ghp_|gho_|ghs_|sk-)[A-Za-z0-9_-]{8,}`) |
| model | `duplicate name '<qname>'`; `unknown name '<ref>'`; `'<ref>' is a <kind>; a <expected-kind> is needed` (a part's type must be a part def, a port's a port def, dependency ends part defs); `part def '<qname>' needs a doc`; `connect: '<a>' is not a part of '<qname>'`; `connect: '<a>' has no port '<p>'`; `too many elements (limit 300)` (packages, part defs, port defs, parts and ports); `too many relations (limit 600)` (connects and dependencies) |

A file with a syntax or character finding gives only that one finding (the character scan runs over the whole file first, so a character finding wins over a syntax finding; otherwise parsing stops at the first syntax finding); the model checks run only when no file has one, and a limit finding (`too many ...`) is then the only finding returned. Findings are sorted by file, line, message. A doc's text is the comment body without `/*`, `*/` and the optional leading `*` of each line, whitespace runs collapsed to one space, trimmed; the 1000-character limit and the link and secret check run on that normalised text.

### 3.3 Files and paths (`src/tld/sysml/files.py`)

The only module that touches the filesystem for the model and its outputs; the wrapper never opens a path itself.

- The model lives in `sysml/model/**.sysml`. A model relpath (below `sysml/model/`) must `re.fullmatch` `[a-z0-9_-]+(/[a-z0-9_-]+)*\.sysml`, else the error `invalid file '<x>': use a path like core/api.sysml`.
- `load_tree(root, base) -> dict[str, str]` walks `base` below `root`, sorted by relpath, reads UTF-8 (a decoding error is `ModelError("<path> is not valid UTF-8")`), enforces the three file limits of 3.2, and refuses a symbolic link or any non-regular file or directory; a file whose relpath does not match the model relpath rule is `ModelError("invalid file '<x>': use a path like core/api.sysml")`, never skipped.
- Every read and write checks each path component from `root` down with `os.lstat`: a symbolic link is `ModelError("path '<repo-relative path>' is a symbolic link")`, anything else that is not a directory (or a regular file at the end) `... is not a regular file or directory`. Writes create parent directories one level at a time under the same check and open the file with `os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW`, mode 0o644. A destination directory that already exists where one must be new is `ModelError("path '<p>' already exists")`. An existing write target with more than one hard link (`st_nlink != 1`) is `ModelError("path '<p>' has more than one hard link")`. `check_writable(root, rel_path)` runs every check `write_text` makes before it opens the file (the component walk, a non-regular existing target, the hard-link rule) without writing anything; the wrapper calls it for every path an archive will write, delete or move before it writes the first.
- Resource limits: 100000 bytes a file, 50 files, 1000000 bytes in all.

### 3.4 The overlay: a change is whole files with base hashes (`src/tld/sysml/change.py`, `diff.py`)

A change lives in `sysml/changes/<id>/`:

- `proposal.md`: the headings `## Why`, `## What Changes` and `## Impact`, each with text that is not empty and not the word `TODO`.
- `model/<relpath>.sysml`: the **whole new content** of a model file (replacing the file of the same relpath), or a new file.
- `base.json`: `{"schema": 1, "files": {"<relpath>": "<sha256 hex of the model file the change replaces>"}, "removed": {"<relpath>": "<sha256 hex of the file the change deletes>"}}`. An overlay file that is not under `files` is a new file.

Rationale: a whole-file overlay is the simplest thing the parser can validate, but alone it would let a later archive silently revert a merged edit of another plan. The base hash turns that into a loud stop, and `check --change` prints a semantic diff (3.6) so the reviewer sees what changes instead of a new file.

Findings of `check --change <id>` (`<c>` is `sysml/changes/<id>`): problems of `base.json` are at `<c>/base.json` line 1; problems of the proposal at `<c>/proposal.md` (a missing section at line 1, an empty or TODO section at the heading's line); a missing `proposal.md` gives one `missing section '<heading>'` per heading at line 1. Messages: `change '<id>' changes nothing` (no overlay file and `removed` empty; at base.json); `missing section '<heading>'`; `section '<heading>' is empty or still TODO`; `base.json is missing or invalid` (not JSON, not an object, `schema` other than 1, `files` or `removed` not objects, a key that is not a model relpath, a value that is not 64 lower-case hex digits); `<relpath> is in the change but exists in the model; list it with new-change --file` (an overlay file not under `files` whose model file exists); `<relpath> is listed in base.json but missing from the change` (a `files` entry only; a `removed` entry has no overlay file); `<relpath> cannot be both replaced and removed`; for a `files` entry whose model file is absent now or hashes differently, `<relpath> changed since the change was written; delete <c>/model/<relpath> and its entry in base.json, run new-change --file <relpath> and apply your edit again`; for a `removed` entry, `<relpath> changed since the change was written; delete its entry in base.json and run new-change --remove <relpath> again` (an absent file counts as changed). When `base.json` is missing or invalid, that finding and the proposal findings are the only ones and the composed model is not built. An overlay file whose name is not a model relpath, or a symbolic link anywhere under `<c>`, is a `ModelError` (exit 2), never a finding. The composed model (the current files, replaced and added by the overlay, minus the removed) is then built and checked as in 3.2; its findings carry the file name prefixed `sysml/changes/<id>/model/` for overlay files and `sysml/model/` for the rest.

`diff(old: Model, new: Model) -> list[Change]` compares element by `qname`: `added`, `removed`, or `changed` when `(kind, type_ref, doc)` differs (an owner move, or a changed end of a connect or dependency, is a different `qname`: one `removed` and one `added`), sorted by `(qname, op)`; printed `<op> <kind> <qname>`.

`archive <id>` computes everything in memory first (the check above, with zero findings required; the composed files; the two outputs of 3.5), calls `check_writable` for every path it will write, delete or move, and only then writes: replaced and new model files, deletes the removed ones, moves `sysml/changes/<id>` to `sysml/changes/archive/<yyyy-mm-dd>-<id>` (UTC date, injected clock `_today()`), writes the outputs. The destination must not exist. The id `archive` is reserved.

### 3.5 Drawing and the generated docs (`layout.py`, `svg.py`, `markdown.py`)

Outputs, written only by `render` and `archive`: `docs/architecture.svg` and `docs/architecture.md`, each with the stamp `<!-- generated by tld ops sysml render, layout 1; do not edit -->` (the SVG as its first line, the markdown after the summary). Byte stability is a requirement: integer coordinates only, `font-family="monospace"` at 12px with 7 pixels a character, sorted iteration (never a set), `\n`, UTF-8, no clock.

**Layout 1.** The elements drawn are part defs, grouped in frames by their owning package (a package that owns no part def has no frame; frames in the order of the first part def's declaration). Constants: `BOX_W=224`, `HEAD_H=28`, `LINE_H=16`, `PAD=8`, `GAP_X=48`, `GAP_Y=40`, `COLS=3`, `FRAME_PAD=16`, `FRAME_HEAD=28`, `MARGIN=24`, `CHAR_W=7`. `fit(text)` returns the text, or its first 27 characters plus `...` when it is longer than 30. Detail view when the model has at most 60 part defs and at most 150 aggregated edges, otherwise the package view.

- Detail geometry: frame `x = MARGIN`, `w = 2*FRAME_PAD + COLS*BOX_W + (COLS-1)*GAP_X` (800), first frame `y = MARGIN`, each next frame `y` the previous frame's `y + h + GAP_Y`; frame `h = FRAME_HEAD + (sum of its row heights) + (rows-1)*GAP_Y + FRAME_PAD`. A part def box has the header `fit(name)`, then one line `> <port> : <type>` (through `fit`; `<type>` is the `type_ref` as written) per port in declaration order, at most 6, then `+<n> more` when there are more; `h = HEAD_H + LINE_H*lines + PAD`. Boxes fill a frame row by row, `COLS` to a row: box `x = frame.x + FRAME_PAD + col*(BOX_W+GAP_X)` (40, 312, 584 in the first frame), `y = frame.y + FRAME_HEAD + (sum of the heights of the rows above) + row*GAP_Y`, a row's height the tallest box in it. Canvas `width = 800 + 2*MARGIN` (848), `height = 2*MARGIN + (sum of the frame heights) + (frames-1)*GAP_Y` (48 for a model with no part def). Text positions: a frame title (`fit(qname)`) at `(frame.x + PAD, frame.y + 18)`, a box header at `(box.x + PAD, box.y + 19)`, line `i` (from 0) at `(box.x + PAD, box.y + HEAD_H + LINE_H*i + 12)`.
- Package view geometry: no frames; one box per package that owns a part def, header `fit(qname)`, one line `<n> part defs`, `h = HEAD_H + LINE_H + PAD` (52), boxes on one grid of `COLS` columns with `x = MARGIN + FRAME_PAD + col*(BOX_W+GAP_X)` and `y = MARGIN + row*(52 + GAP_Y)`; canvas width 848, `height = 2*MARGIN + rows*52 + (rows-1)*GAP_Y`; edges aggregated per pair of packages (an edge between two part defs of one package is dropped), same kinds and drawing as below.
- Edges, aggregated by `(kind, source, target)` with a count (a connect is unordered: its pair is sorted), none between a box and itself: `dependency` (dashed, arrowhead at the target), `connect` (solid, from a `connect` statement, drawn between the part defs the two parts are typed by), `composition` (solid, diamond at the owning part def, from a part usage). A count above 1 is the label `x<n>` at the midpoint (`text-anchor="middle"`). A line runs from the centre of the source box to the centre of the target box, cut where it leaves each rectangle; floats are rounded with `round()` to integers; with `u` the unit vector from the source centre to the target centre and `n = (-u.y, u.x)`: the arrowhead at the target is the polygon `(tip, base+5n, base-5n)` with `tip` the cut point on the target box and `base = tip - 10u`; the diamond at the owner is `(tip, tip+5u+5n, tip+10u, tip+5u-5n)` with `tip` the cut point on the source box; every point is rounded with `round()`; the label sits at `(round((x1+x2)/2), round((y1+y2)/2) - 4)`.
- Colours: background `#ffffff`, frame stroke `#8b949e`, box fill `#f6f8fa`, stroke and text `#1f2328`.

**The SVG** uses only the elements `svg g rect line polygon text title` and the attributes `xmlns width height viewBox role aria-label x y x1 y1 x2 y2 points fill stroke stroke-width stroke-dasharray font-family font-size text-anchor`; no `href`, `style`, `script` or `foreignObject`. Text content is XML-escaped; it holds names, types and counts only, never doc text. `<title>` is `Architecture model` and `aria-label` is `Architecture diagram: <n> part defs in <m> packages` (`<m>` counts the packages that own a part def).

**The markdown** is: `# Architecture`; a blank line; a summary of at most 2 lines (`<n> part defs in <m> packages, <k> dependencies and <c> connections, generated from sysml/model/. Change it with a plan, never by hand.` and, in the package view only, `The diagram shows packages only; the tables list every part def.`); the stamp; `![Architecture](architecture.svg)`; then per package (every package, in declaration order, a nested one after its owner) a heading `## <qname>`, its doc (when there is one), and a table `| Part def | Ports | Description |` with one row per part def (name and `port : Type` pairs in backticks; the description is the doc); then `## Relations` with a table `| From | Kind | To |` with one row per distinct `(kind, from, to)` of the layout's edges before aggregation (composition included; From and To are part def qnames, a connect row is the sorted pair), sorted by `(kind, from, to)`. In the summary `<k>` counts dependency statements and `<c>` connect statements. Doc text is written with whitespace runs collapsed and every one of these 15 characters preceded by a backslash: `` \ ` * _ [ ] ( ) < > # ! | ~ & ``.

`render --check` compares both files with what `render` would write and exits 1 with, per file, `<path> is missing: run tld ops sysml render`, `<path> was rendered by layout <n>, this tld renders layout 1: run tld ops sysml render` (stamp number differs) or `<path> is out of date: run tld ops sysml render`.

### 3.6 The wrapper `tld ops sysml`

Module `src/tld/ops/sysml.py`, registered as `("ops", "sysml"): ("tld.ops.sysml", (), "new-change | check | render | archive: the architecture model")`. Four fixed subcommands; `--profile FILE` (default `<root>/.tld/toolkit.yaml`) and `--root DIR` (default `.`) on each, through a shared parent parser as `src/tld/ops/spec.py` does. Exit 0 ok, 1 findings or drift, 2 cannot run (each with the exact stderr line).

Checks before anything runs, exit 2: `ID` and the `--change` value must fullmatch `[a-z0-9]+(-[a-z0-9]+)*` (`tld ops sysml: invalid id '<id>': use lower-case words joined by hyphens`) and not be `archive` (`tld ops sysml: 'archive' is reserved`); each `--file` / `--remove` value a model relpath (3.3); the profile exists (`tld ops sysml: profile not found: <path>`); the `sysml` block exists with `subset` (`toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`) equal to the integer 1 (`tld ops sysml: sysml.subset must be 1 (got <repr>)`; a bool fails).

| Subcommand | Does |
|---|---|
| `new-change ID [--file R]... [--remove R]...` | needs model files (`tld ops sysml: no model files under sysml/model (run the sysml command's init first)`, exit 2); creates `sysml/changes/<ID>/proposal.md` when absent with the skeleton `# <ID>`, then the three headings each followed by a blank line, `TODO` and a blank line; for each `--file` copies the model file to `sysml/changes/<ID>/model/<R>` unless that exists and records its sha256 under `files` unless recorded; for each `--remove` records the hash under `removed` (a model file that does not exist: `tld ops sysml: model file <R> does not exist`; both replaced and removed: `tld ops sysml: <R> cannot be both replaced and removed`). Safe to repeat: it only adds. Prints `created sysml/changes/<ID>` or `updated sysml/changes/<ID>`. |
| `check [--change ID] [--json]` | builds and checks the model (or, with `--change`, the composed model and the change, 3.4; a missing change is `tld ops sysml: change '<id>' does not exist`, exit 2) and prints findings one per line, then with `--change` the semantic diff one `<op> <kind> <qname>` line each, then `sysml: ok (<n> elements)` when there are no findings, `<n>` being the number counted against the element limit (packages, part defs, port defs, parts and ports). `check`, `render` and `archive` with no model file exit 2 with the `no model files under sysml/model (run the sysml command's init first)` line of `new-change`. `--json` prints one object `{"ok": bool, "findings": [{"file","line","message"}], "changes": [{"op","kind","qname"}]}`. |
| `render [--check]` | builds and checks the model (findings: printed, exit 1, nothing written), then writes the two outputs and prints `wrote docs/architecture.svg` and `wrote docs/architecture.md`, or with `--check` compares them (3.5) and prints `sysml: docs up to date` when both match. |
| `archive ID` | 3.4; prints `archived sysml/changes/<ID> to sysml/changes/archive/<yyyy-mm-dd>-<ID>`. A destination that exists is `tld ops sysml: path '<p>' already exists` (exit 2); any finding (a `changed since` one included) exit 1 with nothing written. |

Test seams: `_today() -> datetime.date`. Everything else is pure functions and `tmp_path`.

### 3.7 Profile key, record command, guards, manifest fence

- `sysml` is an optional top-level profile block, `additionalProperties: false`, one required key `subset`, `{"type": "integer", "enum": [1]}`. A new grammar is a new number, decided by the owner in the protected profile.
- `sysml` joins `tld.board.record.COMMANDS` and the status-record schema `command` enum, `board_gate.RECORD_COMMANDS` with `RECORD_MODES["sysml"] = ("init",)`, and `plan_gate.OPENING`, together with the playbook, the command file and an eval task (tests require all of them for a record command).
- Manifest: optional `sysml_change: <id>` (`[a-z0-9]+(-[a-z0-9]+)*`, not `archive`; else `sysml_change must be lower-case words joined by hyphens`). The spec fence code becomes one table-driven loop with two entries, keeping every `spec_change` message byte for byte. For `sysml_change` the fenced paths are `sysml/**`, `docs/architecture.md` and `docs/architecture.svg`, and the messages are: `sysml_change needs the profile's sysml block` (a profile was given without the block); `phase '<id>': touches sysml/ or the architecture docs but only the last phase may when sysml_change is set`; `last phase '<id>' must touch sysml/ when sysml_change is set` (touching any one of the three paths satisfies it); `last phase '<id>' must depend on every other phase when sysml_change is set (missing: <ids>)`; warning `sysml_change differs from plan_slug`. **No change, no touch:** with a profile that has a `sysml` block and no `sysml_change`, every phase whose `touches` overlaps a fenced path is the error `phase '<id>': touches sysml/ or the architecture docs but the manifest has no sysml_change; narrow the touches or set sysml_change`. (The spec fence keeps its present behaviour without that rule.) With no profile given the rule is skipped.

### 3.8 The playbooks

**`sysml` (init, check)** is shaped like `playbooks/spec.md`. Input `check` (default) or `init`; anything else prints `Usage: sysml [check | init]`. `check`: `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml`, a findings table, verdict: passes when both exit 0; no record. `init` (attended, record `command: sysml`, items `survey`, `confirm`, `draft`, `validate`, `pr`; `tld dod exempt`; before branching runs `git status --porcelain` and, when it prints anything, stops with `The working tree has changes; commit or stash them first. Nothing was changed.`; branch `chore/sysml-init-<yyyymmdd>` from `origin/<main>`):

1. **Survey**: stop with `The architecture model already exists (sysml/model holds files); plans update it. Nothing was changed.` when `sysml/model` holds a file; stop with `docs/architecture.md or docs/architecture.svg exists and was not generated by tld; move it first. Nothing was changed.` when either output exists without the stamp. Otherwise `run_helper` sweeps (level `standard`) find the components (deployable units, libraries, services, top-level modules), their ports (public interfaces: commands, endpoints, file formats) and which component calls which, and propose at most 4 packages and 12 part defs, each with one evidence path and one sentence, and the dependency pairs with one evidence path each.
2. **Confirm**: one `ask_human` `text` question of at most 1900 characters (one line per part def `<package>/<Name>: <at most 8 words> (<evidence path>)`, then the `from -> to` pairs), reply `ok` or the corrected list; names must fullmatch `[A-Za-z_][A-Za-z0-9_]*` and not be reserved, at most 12 part defs; a second bad reply stops with `The component list is not valid. Nothing was changed.`
3. **Draft**: one file `sysml/model/<package in lower case, hyphens for other characters>.sysml` per package, written by hand in the subset, every part def with a doc of one or two sentences describing what it is for (no literal credentials, hostnames, URLs or e-mail addresses), ports only for interfaces another component uses, dependencies only from evidence.
4. **Validate and draw**: `tld ops sysml check --profile .tld/toolkit.yaml` must exit 0 (fix and repeat), then `tld ops sysml render --profile .tld/toolkit.yaml`, then `tld ops sysml render --check --profile .tld/toolkit.yaml` exits 0. With `docs.index` in the profile add the row `- [architecture.md](<path of docs/architecture.md relative to the index file's directory>) - the architecture model and its diagram, generated from sysml/model; read when you change how the parts of the system relate.` and run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0.
5. **Deliver**: stage only `sysml/`, `docs/architecture.md`, `docs/architecture.svg` and the docs index file when a row was added; `git diff --cached --name-only` must list nothing else; commit, push, `github.pr_create` titled `chore: add the SysML architecture model` with `## What this adds`, `## Evidence`, `## Gaps` and `## Not verified`; `github.pr_subscribe` when offered; `needs_you` reason `Review PR #<n>`.

Never: merge, approve or enable auto-merge; edit a generated doc by hand; hand-write a doc image; pass an argument other than through the four subcommands.

**make-plan, "Architecture parts"** apply only with the profile's `sysml` block. Setup bullet; section 0 step 2 reads `sysml/model/**/*.sysml` and `docs/architecture.md` and stops with `run the sysml command's init first` when `sysml/model` has no file; in the Design section a subsection `### The architecture change (architecture parts)`: decide whether components, ports, composition or dependencies change (if not: no change, no `sysml_change`, say so in Scope; a revision that drops its change runs `git rm -r sysml/changes/<plan slug>/`); else `tld ops sysml new-change --profile .tld/toolkit.yaml <plan slug> --file <relpath>...` (every model file to change; `--remove` for a deleted one), edit the copied files so they are the whole new files, add new files under `sysml/changes/<plan slug>/model/`, fill `proposal.md`, run `tld ops sysml check --profile .tld/toolkit.yaml --change <plan slug>` (exit 0 before the push) and paste its diff lines into the Design section; every part def and port the change adds or removes is named by an acceptance item of the phase that builds it; manifest `sysml_change: <plan slug>`. The retirement phase lists `sysml/**`, `docs/architecture.md` and `docs/architecture.svg` in `touches`, no other phase does, and its brief holds in order: reconcile `sysml/changes/<id>/` with the deviations file so the change describes what was built; `tld ops sysml archive --profile .tld/toolkit.yaml <id>` (a `changed since` finding stops with `status=blocked`: another plan changed a file this change replaces, the report names it); `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml` exit 0; commit. A conflict in `docs/architecture.*` after a merge of `origin/<main>` is resolved by running `tld ops sysml render --profile .tld/toolkit.yaml`, never by hand. The merge of `origin/<main>` into the feature branch is implement's (after the last phase); another plan's change to a model file this change replaced then conflicts and stops as `status=blocked`, and a clean merge is followed by `check` and `render --check`. `final_checks` gets: `tld ops sysml check --profile .tld/toolkit.yaml and tld ops sysml render --check --profile .tld/toolkit.yaml exit 0 and sysml/changes/<sysml_change> does not exist`. The small-scope prompt gets the same as a paragraph `Architecture change (architecture parts):` and the review helper checks that replaced files are whole, every new or removed part def and port has an acceptance item and the pasted diff matches.

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

1. Run this check before the pull request is merged, with the plugin from the feature branch: clone https://github.com/tkcs-lab/tkcs-lab-devflow, `git checkout feature/sysml-architecture`, and start Claude Code with `claude --plugin-dir <that clone>` (the plugin is sourced from the repository root; the planner did not verify the flag, and when your Claude Code has none, run this check after the merge with the updated plugin as the README's Install section says). Take a scratch repository that has a `.tld/toolkit.yaml` and some code, add the two lines `sysml:` and `  subset: 1` to the profile (the profile is protected: let the session propose it, or edit it yourself) and push it to the default branch.
2. Start a Claude Code session on it and run `/tld:sysml init`. Expect a question listing part defs and dependencies; reply `ok` or correct it.
3. Expect a pull request titled `chore: add the SysML architecture model`. Open `docs/architecture.md` in its files view: the diagram shows boxes in package frames with arrows, the tables list every part def, and no path outside `sysml/`, `docs/architecture.md`, `docs/architecture.svg` and the docs index changed.
4. Run `/tld:sysml check`; expect no findings.
5. Report back: pass or fail, whether the picture is readable, and the first error line if it failed.

**ma2-sysml-tool-parse** (about 15 minutes). Nothing in the tests runs a SysML tool, so this is the only check that the subset is SysML v2.

1. Take the files in https://github.com/tkcs-lab/tkcs-lab-devflow/tree/feature/sysml-architecture/tests/fixtures/sysml/valid (they exist once phase p3 has merged).
2. Open them in any SysML v2 tool you have, for example the tools of the pilot implementation (https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation; the planner did not open this page) or a VS Code SysML v2 extension. The specification is at https://www.omg.org/spec/SysML/2.0 (not opened either).
3. Expect every file to load with no syntax error. A semantic complaint about a missing standard library import is not a failure.
4. Report back: pass or fail, and for a failure the file, the line and the tool's message; a failure becomes a follow-up plan that fixes the subset.

## 6. Risks and open questions

- The SysML claim is unverified (3.1). If ma2 fails the subset needs a fix; nothing breaks for users in the meantime because tld checks its own subset, but the files may not open in other tools. Open research questions for the owner who wants them settled earlier: the exact reserved-word list of the notation, whether `dependency from A to B;` and `connect a.p to b.q;` are valid as written, how a nested package resolves names without `import`, and whether a `/* */` comment elsewhere than after `doc` is a comment element in real tools (the subset therefore allows block comments only after `doc` and `//` elsewhere).
- The layout is a grid with straight lines: a model of 300 elements falls back to the package view (3.5), and crossings in the detail view are accepted. A worker that finds the picture of a generated 60-part-def model cut off or an edge missing stops with `status=blocked`.
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
    why: the tests use temp directories, so only a real run shows whether the survey, the diagram and the pull request are good; run it before the pull request merges, with the plugin from the feature branch
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
      Pattern: commit 7428256 of PR #73. Stop condition: if the validator accepts `subset: true` after your schema change, stop with status=blocked and quote src/tld/profile/validate.py:61-80.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_profile.py -q passes, including the new sysml tests
      - .venv/bin/python -m pytest tests -q passes
      - grep -n "sysml.subset" docs/reference/profile-reference.md matches
  - id: p2-sysml-files
    title: Add the shared types and the safe file layer
    depends_on: []
    complexity: M
    touches:
      - src/tld/sysml/__init__.py
      - src/tld/sysml/types.py
      - src/tld/sysml/files.py
      - tests/core/test_sysml_files.py
    brief: |
      Read first: src/tld/ops/docs_index.py (module conventions), plan sections 3.2 (limits, reserved words) and 3.3.
      1. Create the package src/tld/sysml/ with `__init__.py` (a docstring only: "tld's SysML subset: parse, check, change, draw (docs/guides/sysml.md)").
      2. src/tld/sysml/types.py: `@dataclass(frozen=True) class Finding: file: str; line: int; message: str` with `__str__` returning `f"{file}:{line}: {message}"`; `class ModelError(Exception)` (the message is the stderr line without the `tld ops sysml: ` prefix); `@dataclass(frozen=True) class Element` with fields `kind: str` ("package", "part def", "port def", "part", "port", "connect", "dependency"), `name: str` (empty for connect and dependency), `qname: str`, `owner: str` ("" at the top), `type_ref: str | None`, `ends: tuple[str, ...]` (a connect `(a, p, b, q)`, a dependency `(from_ref, to_ref)`, else `()`), `doc: str`, `file: str`, `line: int`; the constant `RESERVED` (a frozenset of exactly the words listed in plan section 3.2) and the limits `MAX_FILE_BYTES=100000`, `MAX_FILES=50`, `MAX_TOTAL_BYTES=1000000`, `MAX_NAME=64`, `MAX_DEPTH=6`, `MAX_DOC=1000`, `MAX_ELEMENTS=300`, `MAX_RELATIONS=600`.
      3. src/tld/sysml/files.py exactly as plan section 3.3: `MODEL_DIR = "sysml/model"`, `RELPATH_RE`, `check_relpath(rel) -> str` (returns it or raises ModelError `invalid file '<x>': use a path like core/api.sysml`), `load_tree(root: Path, base: str = MODEL_DIR) -> dict[str, str]`, `read_text(root, rel_path) -> str | None` (None when absent), `write_text(root, rel_path, text) -> None`, `check_writable(root, rel_path) -> None`, `remove_file(root, rel_path)`, `move_dir(root, src, dst)` (dst must not exist: `path '<dst>' already exists`; every component of both paths checked), `sha256_text(text) -> str`. One private helper `_check_components(root, rel_path)` does the lstat walk and every public function calls it; `write_text` additionally opens with the flags `os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW` (this exact expression, once in the file) and maps an `OSError` with errno ELOOP to `ModelError("path '<p>' is a symbolic link")`. Walk with `os.scandir` and `os.lstat`; never `Path.resolve` or `os.path.realpath`.
      4. Tests tests/core/test_sysml_files.py (tmp_path): a symlinked `sysml`, `sysml/model`, a model file and a model subdirectory each give `path '<p>' is a symbolic link` from `load_tree`, `write_text` and `read_text`; a symlinked `docs` directory and a symlinked `docs/architecture.svg` are refused by `write_text` and by `check_writable`; a dangling symlink at the target is refused; `test_write_text_open_refuses_final_symlink_even_if_component_check_is_skipped` (monkeypatch `files._check_components` to a no-op, put a symlink at the target, assert ModelError and that the link's target file is unchanged); `test_write_text_refuses_hard_linked_target` and `test_check_writable_refuses_hard_linked_target` (a second hard link to an outside file; ModelError `path '<p>' has more than one hard link`; the outside content is unchanged); a FIFO is refused; relpaths `A.sysml`, `a/../b.sysml`, `/a.sysml`, `a.txt`, `a\n.sysml`, `a b.sysml` are invalid and `core/api_2.sysml` is valid; `load_tree` raises `invalid file` for a stray `A.sysml` and `a b.sysml` in the tree; a file of 100001 bytes, 51 files and a total over 1000000 bytes give the three limit messages; a non-UTF-8 file gives `<path> is not valid UTF-8`; files come back sorted; `test_remove_file_refuses_symlinked_parent_and_symlinked_target` (the link target survives); `test_move_dir_refuses_symlink_in_src_or_dst_components` (`sysml/changes` and `sysml/changes/archive` each a link, nothing moved) and `move_dir` onto an existing path; `check_writable` writes nothing.
      Stop condition: if the Python in this environment is older than 3.11, stop with status=blocked.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_files.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - grep -c "os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW" src/tld/sysml/files.py prints 1
  - id: p2b-sysml-parse
    title: Add the subset parser
    depends_on: [p2-sysml-files]
    complexity: M
    touches:
      - src/tld/sysml/parse.py
      - tests/core/test_sysml_parse.py
    brief: |
      Read first: src/tld/sysml/types.py, plan section 3.2 (the grammar, the comment rule, the expected-token list, the finding table).
      1. src/tld/sysml/parse.py: `parse_file(text: str, file: str) -> tuple[list[Element], list[Finding]]` implementing the grammar, the character rule (every case of the `characters` row, `<c>` as printable ASCII or `U+XXXX`), the comment rule (`//` anywhere; a block comment only directly after `doc`, else `block comment only allowed after doc`; an open one is `unterminated comment`), the first-word and expected-token rules (`unsupported element '<word>'`, `unexpected '<token>' (expected <what>)` with the exact `<what>` of 3.2), `name '<name>' is reserved` (a name in `RESERVED`), `name '<name>' is longer than 64 characters`, `nesting deeper than 6` (depth counted before descending: package and part def levels), `duplicate doc`, and the doc-text rows (`doc is longer than 1000 characters`, `doc contains a link or a secret-like text` with the five regular expressions of 3.2 compiled once). Parsing stops at the first finding of a file and returns that one finding with no elements. A doc's text is normalised as 3.2 says. Qualified names: `qname` joins the owners' names with `::`; a connect is `<owner qname>::connect(<a>.<p>-<b>.<q>)` and a dependency `<owner qname>::dependency(<from_ref>-><to_ref>)` with the references as written, and the second, third ... identical statement of one owner gets the suffix `#2`, `#3`.
      2. Tests tests/core/test_sysml_parse.py: one test per grammar form and per message of the characters, syntax and doc-text rows, each with a literal expected `Finding` including the line: every reserved word as a name (loop over `RESERVED`); a 65-character name; nesting of 7 levels; `doc /* open`; a block comment before a statement (`block comment only allowed after doc`); a NUL, U+202E (in code, in a `//` comment and in a doc), U+200B in a doc, U+2028 in a doc (`unexpected character 'U+2028'`), a CRLF file whose error is on its third line (reported as line 3), a byte order mark, U+00E9 in code (`U+00E9`) and U+00E9 in a doc and in a `//` comment (allowed); the printable ASCII non-token characters each (`'quoted name'` gives `unexpected character '''`); `part x : T;` at package level (`unexpected 'x' (expected 'def')`); `connect a.p to b.q;` in a package and `dependency from A to B;` in a part def (`unsupported element`); `import X::*;` and `attribute` (`unsupported element`); a missing `;`, `{`, `}` at end of file, `to`, `from`; doc twice; doc of 1001 characters; `test_doc_secret_or_link_rejected` parametrized over `http://x`, `HTTP://x`, `www.x`, `WWW.x`, `password: x`, `passwd=x`, `secret : x`, `token=x`, `API-KEY: x`, `api_key=x`, `-----BEGIN`, `ghp_abcdefgh1`, `gho_abcdefgh`, `ghs_abcdefgh`, `AKIA12345678`, `sk-abcdefgh`; `test_doc_benign_text_passes` for `the token bucket`, `skeleton`, `a www b`, `e.g. this`; the happy path: doc normalisation (`/* \n * a\n *   b */` gives `a b`), `qname`s, the connect and dependency qnames and the `#2` suffix of an identical repeat, `//` comments skipped, `port def P;` and `port def P { doc /* x */ }`.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_parse.py -q passes
      - .venv/bin/python -m pytest tests -q passes
  - id: p3-sysml-model-check
    title: Resolve names and check the model, with the fixture corpus
    depends_on: [p2b-sysml-parse]
    complexity: M
    touches:
      - src/tld/sysml/model.py
      - tests/core/test_sysml_model.py
      - tests/fixtures/sysml/valid/**
      - tests/fixtures/sysml/invalid/**
    brief: |
      Read first: src/tld/sysml/types.py, src/tld/sysml/parse.py, plan section 3.2 (qualified names, the model rows).
      1. src/tld/sysml/model.py: `@dataclass class Model: elements: tuple[Element, ...]; index: dict[str, Element]; types: dict[str, str]` (qname of a part or port usage to the qname of its resolved type def) `; targets: dict[str, tuple[str, ...]]` (a dependency's qname to `(from qname, to qname)`, a connect's to `(type qname of a, type qname of b)`); `build(files: dict[str, str], names: dict[str, str] | None = None) -> tuple[Model, list[Finding]]`: parse every file in sorted relpath order (the file name in findings is `names[relpath]` when given, else `sysml/model/<relpath>`), and when no file has a syntax or character finding run the model checks of plan section 3.2 in the table's order: the element and relation limits first (a limit finding is the only finding returned), then duplicate names, name resolution (`resolve(ref, scope)` exactly as the plan describes: first segment looked up as a member of each enclosing namespace innermost first, then at the top; the rest member by member; a result of the wrong kind gives the `'<ref>' is a <kind>; a <expected-kind> is needed` message with the kinds `package`, `part def`, `port def`, `part`, `port`), the doc rule for part defs, and the connect rules. Findings sorted by `(file, line, message)`. A model with findings still returns the elements it built.
      2. Fixture corpus. tests/fixtures/sysml/valid/ holds five files, each loadable alone with no finding, using only `//` comments, and each with its own distinct top-level package (`Minimal`, `Ports`, `Connect`, `CrossPackage`, `Composition`) so that all five also build together: `minimal.sysml` (one package, one part def with a doc), `ports.sysml` (port def, ports, a part def used twice), `connect.sysml` (two parts in one part def connected through their ports), `cross_package.sysml` (a dependency and a part type referenced by a qualified name across two packages, plus a nested package that uses its owner's part def unqualified), `composition.sysml` (part usages). tests/fixtures/sysml/invalid/ holds seven files, each starting with the line `// expect: <line>: <message>` naming its one expected finding (`line` counting the expect line as line 1): `duplicate_name`, `unknown_name`, `wrong_kind_part_type`, `wrong_kind_port_type`, `wrong_kind_dependency`, `no_doc`, `connect_not_part`; and three more written as tests instead of files: `connect_no_port`, `sibling_unqualified` (a reference to a sibling package's member without qualification gives `unknown name`), `too_many_elements`.
      3. Tests tests/core/test_sysml_model.py: `test_fixture_corpus_counts` (5 valid files, 7 invalid files); every valid fixture builds with no findings alone and `test_valid_fixtures_build_together`; the limit findings are the literal `Finding("sysml/model", 0, ...)`; `build` with `names` uses the given file names; every invalid fixture gives exactly its expectation; the `index`, `types` and `targets` of `connect.sysml` and `cross_package.sysml` as literal expected dicts; 300 elements pass (one package and 299 part defs, generated text) and 301 fail with `too many elements (limit 300)` as the only finding; 600 relations pass and 601 fail (two part defs and generated `dependency from A to B;` lines) with `too many relations (limit 600)` as the only finding; two files defining the same qname give one `duplicate name` finding on the second; a syntax error in one file hides the model checks of the others; findings are sorted; resolution order (an inner package's name wins over an outer one's).
      Stop condition: if a valid fixture does not parse with p2b's parser, fix the fixture to the grammar, not the parser, and say so in the report; stop with status=blocked only if the grammar of plan section 3.2 cannot express the fixture.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_model.py -q passes, including test_fixture_corpus_counts
      - .venv/bin/python -m pytest tests -q passes
  - id: p4-sysml-change
    title: Add the architecture change overlay, its semantic diff and archive plan
    depends_on: [p3-sysml-model-check]
    complexity: M
    touches:
      - src/tld/sysml/diff.py
      - src/tld/sysml/change.py
      - tests/core/test_sysml_change.py
    brief: |
      Read first: src/tld/sysml/files.py, src/tld/sysml/model.py, plan sections 3.4 and 3.6 (the new-change and archive rows).
      1. src/tld/sysml/diff.py: `@dataclass(frozen=True) class Change: op: str; kind: str; qname: str` with `__str__` `f"{op} {kind} {qname}"`, and `diff(old: Model, new: Model) -> list[Change]` exactly as plan section 3.4.
      2. src/tld/sysml/change.py: constants `CHANGES_DIR = "sysml/changes"`, `HEADINGS = ("## Why", "## What Changes", "## Impact")`, `skeleton(id) -> str`; `@dataclass(frozen=True) class ChangeFiles: proposal: str | None; base: dict | None; overlay: dict[str, str]` (`base` None when base.json is absent or invalid) and `@dataclass(frozen=True) class ArchivePlan: composed: dict[str, str]; write: tuple[str, ...]; delete: tuple[str, ...]; dest: str`; `valid_id(id) -> str` (fullmatch, and not `archive`, raising ModelError with the two messages of plan section 3.6; the only place the reserved id is checked); `new_change(root, id, files, removes) -> str` ("created"/"updated"), copying and hashing as the table of 3.6 says through files.py only (a copy that already exists is detected with `os.lstat`, a symlink there is a ModelError); `load_change(root, id) -> ChangeFiles` (every file read through files.py; an absent change folder is `ModelError("change '<id>' does not exist")`; an overlay name that is not a model relpath is a ModelError); `check_change(root, id, base_files) -> tuple[dict[str, str], Model | None, list[Finding]]` returns the composed files, the composed model (None when base.json is missing or invalid, see 3.4) and all findings: the change-level ones of plan section 3.4 (messages, files and lines exact; a section is empty when its body, stripped, is empty or equals `TODO`) followed by the findings of `model.build(composed, names)` with `names` mapping overlay relpaths to `sysml/changes/<id>/model/<relpath>` and the rest to `sysml/model/<relpath>`; `compose(base_files, overlay, removed) -> dict[str, str]`; `archive_plan(root, id, today, composed, base_files) -> ArchivePlan` computed in memory from files `check_change` already found clean (the wrapper runs `check_change` first and exits 1 on any finding, then calls this): `write` is every relpath whose composed text is new or differs, `delete` the removed ones, `dest` the destination; ModelError(`path '<dst>' already exists`) when `sysml/changes/archive/<today.isoformat()>-<id>` exists.
      3. Tests tests/core/test_sysml_change.py (tmp_path repository with a model of two files): `test_valid_id` for `archive`, `A`, `a--b`, `-a`, `a_b`, `` and a good id; new-change creates the skeleton (literal expected text), copies a file and records its sha256, is repeatable and only adds (a second `--file` call keeps an edited copy untouched), records a removal, refuses a file that is not in the model, refuses replace plus remove of one file; `test_new_change_refuses_a_preexisting_symlink_copy` (ModelError `path '<p>' is a symbolic link`, the link's outside target unchanged, base.json not written); `test_new_change_refuses_symlinked_changes_dir` (`sysml/changes` points outside; nothing written there); check_change: each message of plan section 3.4 once with its file and line (missing and TODO sections, a missing proposal.md, `changes nothing`, `is in the change but exists in the model`, `is listed in base.json but missing from the change`); `test_replaced_base_changed_gives_changed_since`, `test_removed_base_changed_gives_changed_since`, `test_replaced_base_deleted_from_model_gives_changed_since`, `test_base_json_replace_and_remove_same_file` (each the literal Finding with the file `sysml/changes/<id>/base.json`); `test_removed_base_deleted_from_model_gives_changed_since` (the literal `delete its entry in base.json and run new-change --remove` finding); `test_base_json_rejects_bad_keys_and_shapes` parametrized over the sections `files` and `removed` and the keys `../x.sysml`, `/abs.sysml`, `A.sysml`, `a/../b.sysml`, `x.txt`, a hash that is not 64 lower-case hex, `schema: 2`, `schema` missing, the section given as a list, base.json not JSON and base.json missing (each gives exactly `[Finding("sysml/changes/<id>/base.json", 1, "base.json is missing or invalid")]` and a tree snapshot shows nothing written); `test_overlay_file_with_invalid_name_is_refused` (`model/Evil.sysml`, `model/notes.txt`: ModelError `invalid file`); `test_check_change_refuses_any_symlink_under_change` parametrized over a symlinked overlay file, `base.json`, `proposal.md`, the `model` directory and the change directory itself (each a ModelError, a canary outside unchanged); the composed model of a replace, an add and a remove is built, returned, and its findings carry the right prefix (`sysml/changes/<id>/model/` for overlay files); with an invalid base.json only base.json and proposal findings come back and the model is None; `diff` for a literal pair of models gives added, removed and changed (a doc edit and a type edit; an owner move and an `ends` edit of a dependency and of a connect each give one removed plus one added) and an empty list for equal models, and the exact ordered list for a pair with an add, a remove and a change interleaved by qname; `archive_plan` computes the destination from the injected date and refuses an existing destination; a test snapshots the tree before and after `check_change` and `archive_plan` and asserts nothing was written.
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
      1. src/tld/sysml/layout.py: the constants of 3.5 as module constants (`LAYOUT_VERSION = 1`, `BOX_W`, `HEAD_H`, `LINE_H`, `PAD`, `GAP_X`, `GAP_Y`, `COLS`, `FRAME_PAD`, `FRAME_HEAD`, `MARGIN`, `CHAR_W`, `MAX_DETAIL_BOXES = 60`, `MAX_DETAIL_EDGES = 150`); frozen dataclasses `Text(x, y, value)`, `Box(x, y, w, h, texts)` (the header first, then the lines), `Frame(x, y, w, h, title)`, `Edge(kind, x1, y1, x2, y2, label, head)` (`label` is `""` or `x<n>`, `head` the polygon points as a tuple of integers, empty for a connect), `Layout(view, width, height, frames, boxes, edges, counts)` with `counts = (part defs, packages, dependencies, connections)`; `fit(text)`; `layout(model: Model) -> Layout` exactly as plan section 3.5: the detail geometry, the package view geometry, port lines `> name : type`, edges aggregated and sorted by `(kind, source qname, target qname)` with `dependency`, `connect`, `composition` computed from `model.targets` and part usages (a part usage's owner part def to the usage's type def), self edges dropped, a connect pair sorted, the line cut with float arithmetic and `round()`, arrowhead and diamond polygons as 3.5 says.
      2. Tests tests/core/test_sysml_layout.py: build models from text through `tld.sysml.model.build`. Literal values derived by hand from the formulas of 3.5, not from the code's output: canvas width 848; first frame `x` 24, `y` 24, `w` 800; box x values 40, 312, 584; the first box `y` 24+28=52; a box with 3 ports has `h` 28+16*3+8=84, with 0 ports 36, with 8 ports (6 lines plus `+2 more`) 28+16*7+8=148; the second row's `y`; frame `h` for one row of one box with 3 ports `28+84+0+16`; canvas height for one frame `48+h`; a literal expected `Layout` for the `connect.sysml` and `composition.sysml` fixtures; `fit` on 30 and 31 characters; edge aggregation (`x2`), connect symmetry, no self edges, a dependency edge's end point lies on the target rectangle's border; `test_package_view_boxes_and_aggregated_edges` (61 part defs in 2 packages with cross-package dependencies: exactly two boxes with their literal titles, lines, `x`, `y` and `h` 52, and one aggregated edge labelled `x<n>` with the literal `n`); the package view also at 60 part defs with 151 aggregated edges, and `test_detail_view_at_exactly_60_part_defs_and_150_edges` (`view == "detail"`); determinism: the same model laid out twice, and a model built from files given in another dict order, give equal layouts; an empty model gives width 848 and height 48.
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
      - tests/fixtures/sysml/golden/**
    brief: |
      Read first: src/tld/sysml/layout.py, plan section 3.5 (the SVG and the markdown paragraphs).
      1. src/tld/sysml/svg.py: `STAMP = "<!-- generated by tld ops sysml render, layout 1; do not edit -->"`, `ELEMENTS` and `ATTRIBUTES` frozensets (the allowlists of 3.5 written out), `esc(text)` (`&`, `<`, `>`, `"` to entities), `to_svg(lay: Layout) -> str`: the stamp line, then the `<svg>` root with `xmlns="http://www.w3.org/2000/svg"`, width, height, viewBox, `role="img"`, the `aria-label` and a `<title>`, a white `rect` background, frames (`rect` plus `text`), edges before boxes (`line`, dashed `stroke-dasharray="6 4"` for dependencies, the `polygon` from `Edge.head`, the label `text`), boxes (`rect` and the `text`s of `Box.texts`, `font-family="monospace" font-size="12"`), the colours of 3.5, one element per line, `\n` ending, integers only.
      2. src/tld/sysml/markdown.py: `to_markdown(model: Model, lay: Layout) -> str` exactly as plan section 3.5 (title, summary lines with the counts, stamp, the image line, a section per package that owns anything with its doc, the part def table, the Relations table), `md_escape(text)` collapsing whitespace and backslash-escaping the 15 characters listed there, ending with one `\n`.
      3. Both modules export `layout_number(text) -> int | None` (reads the number from the stamp line of an existing output, None when there is no stamp) for the wrapper's drift message.
      4. Tests tests/core/test_sysml_render.py: the SVG of the `connect.sysml` fixture parses with `xml.etree.ElementTree`; every element tag is in ELEMENTS and every attribute name in ATTRIBUTES (also on a generated 61-part-def model, the package view) in the test named `test_svg_uses_only_allowlisted_elements_and_attributes`; no `href`, `style`, `script` or `foreignObject` string occurs; a model whose names are `A_1` renders names escaped and the SVG contains no doc text at all (a doc containing `<script>&"`); golden output: `to_svg` and `to_markdown` of `connect.sysml` equal the checked-in files tests/fixtures/sysml/golden/connect.svg and connect.md (write them from the first run, then check by hand that their coordinates match the formulas of 3.5 and the hand-derived values of p5's tests, and commit them in this phase); `test_golden_changes_with_layout_constant` monkeypatches `layout.GAP_X` and asserts the output differs; `test_golden_svg_matches_hand_derived_layout` (parse golden/connect.svg and assert every box `rect`'s x, y, width and height equal the hand-derived literal values of p5's connect test, repeated literally); `test_md_escape_escapes_all_15_characters` with the Python literal `"| [x](y) * _ # ! ~ & < > \\ `"` (every one of the 15 gets a backslash, no raw `|` stays inside a table cell); `test_doc_with_link_syntax_is_rendered_inert` pinning what `javascript:alert(1)`, `user@example.com` and `[a](b)` become (the 15 characters escaped, no raw `(`, `)`, `[`, `]`); the summary has at most 2 lines and the package-view line appears only in the package view; the stamp is on the first line of the SVG and after the summary in the markdown; `layout_number` of both stamps is 1 and of text without a stamp None; two renders in one process are byte-equal (the cross-process check is p7's).
      Stop condition: if the golden SVG is not valid XML or an element outside the allowlist is needed for a polygon or a label, stop with status=blocked and say which.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_sysml_render.py -q passes
      - .venv/bin/python -m pytest tests -q passes
      - .venv/bin/python -m pytest tests/core/test_sysml_render.py::test_svg_uses_only_allowlisted_elements_and_attributes -q passes
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
      Read first: src/tld/ops/spec.py (the model for this module), docs/reference/cli.md, tests/core/test_mutants_file.py, tests/mutation/mutants.yaml, plan section 3.6. Pattern: commit 823d951 of PR #73.
      1. Create src/tld/ops/sysml.py in the shape of src/tld/ops/spec.py: module docstring with the usage lines, `main(argv=None) -> int`, a shared parent parser with `--profile` and `--root` passed as `parents=[common]` to the four subparsers (new-change with `id`, repeatable `--file` and `--remove`; check with `--change` and `--json`; render with `--check`; archive with `id`), `if __name__ == "__main__": sys.exit(main())`. Usage errors exit 2 (argparse). No other subcommand and no pass-through argument.
      2. Implement plan section 3.6 exactly: the checks in the order listed with their stderr lines and exit 2 (ids through `change.valid_id` only, relpaths through `files.check_relpath`, profile, block, subset as the integer 1 and not a bool); then each subcommand as its table row says, using only the functions of tld.sysml.files, model, change, diff, layout, svg and markdown (the wrapper opens no path itself; `check --change` and `archive` call `change.check_change` first, `archive` then `change.archive_plan`; the module docstring and the `--help` description say "a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; tld does not check it against one"): the output lines of the table, the `--json` object, `render` writing `docs/architecture.svg` and `docs/architecture.md` (the `OUTPUTS` constant) only through `files.write_text`, `render --check` with its three messages (using `svg.layout_number` and `markdown.layout_number`; both files are checked and every problem printed), `archive` computing everything in memory, calling `files.check_writable` for every path it will write, delete or move (the model files, the change folder move, the two outputs), and only then writing in the order: composed model files, deletions, the moved change folder, the two outputs; a `ModelError` or an `OSError` anywhere prints `tld ops sysml: <message>` and exits 2; the injectable `_today()` seam (`datetime.datetime.now(datetime.timezone.utc).date()`).
      3. Register in src/tld/cli.py COMMANDS: `("ops", "sysml"): ("tld.ops.sysml", (), "new-change | check | render | archive: the architecture model")`. Add the row to docs/reference/cli.md in the ops block in the format of the `ops spec` row: `tld ops sysml new-change\|check\|render\|archive [--profile FILE] [--root DIR]`, module `tld.ops.sysml`.
      4. Tests tests/core/test_ops_sysml.py (tmp_path repositories with a profile and the p3 valid fixtures copied into `sysml/model/`): each subcommand's happy path with the literal expected stdout of the table; every exit-2 check with its exact line (`archive` reserved, bad ids, bad relpath, no profile, no `sysml` block, `subset: 2`, `subset: true`, no model files for `check`, `render`, `new-change` and `archive`, `change '<id>' does not exist` for `check --change`, `model file <R> does not exist` and `<R> cannot be both replaced and removed` for `new-change`); `check` findings exit 1 and the `--json` shape; `check --change` prints the diff lines; `render` writes both files and `render --check` is 0, then 1 with `is out of date` after an edit, with `is missing` after a delete and with `was rendered by layout 7, this tld renders layout 1` for a file whose stamp says 7; `render` with a model finding writes nothing; `test_render_bytes_identical_across_hash_seeds` (a subprocess `cli/tld ops sysml render --root R --profile P` with `PYTHONHASHSEED` 0, 1 and 12345, on the five valid fixtures and again on a generated model of 61 part defs in 2 packages with cross-package dependencies: both outputs byte-equal across the three runs and equal to the outputs of the in-process run; and with `_today` patched to two dates in-process the render output does not change); a symlinked `docs` directory makes `render` exit 2 and write nothing (a canary file outside the tree is untouched); the full cycle: new-change, edit the copy, fill the proposal, `check --change` 0, `archive` (patched `_today` to 2026-01-02), then `sysml/changes/<id>` is gone, `sysml/changes/archive/2026-01-02-<id>` exists, the model has the new content, `render --check` is 0; `test_archive_with_symlinked_docs_writes_nothing` (valid change, `docs` replaced by a symlink to an outside directory: exit 2 with `tld ops sysml: path 'docs' is a symbolic link`, `sysml/model` and `sysml/changes/<id>` byte-identical to a snapshot, the outside directory empty); `test_archive_with_symlinked_changes_archive_writes_nothing` (the same for `sysml/changes/archive` as a link); `test_archive_with_hard_linked_output_writes_nothing` (`docs/architecture.md` hard-linked to an outside file: exit 2, `sysml/model` and `sysml/changes/<id>` byte-identical to a snapshot, the outside file unchanged, no `sysml/changes/archive/` created); `test_archive_oserror_on_output_exits_2` (monkeypatch `files.write_text` to raise PermissionError for `docs/architecture.svg` only: exit 2 and the line `tld ops sysml: <message>`); `test_archive_refuses_bad_base_json_keys_and_leaves_canary` (a base.json with the key `../../README.md` under `removed`: exit 1, a canary file outside `sysml/` byte-identical); archive exits 1 and writes nothing for a changed base file, a changed `removed` base file and a base file deleted by another plan; archive exits 2 with `path 'sysml/changes/archive/2026-01-02-<id>' already exists` when the destination exists; two plans changing one file: the second archive is refused; unknown subcommands and extra arguments exit 2 with nothing run (`feedback`, `init`, `archive x --force`). One subprocess test runs `cli/tld ops sysml check --root R --profile P` and asserts the exit code and the `sysml: ok` line, which proves the registration.
      5. Mutation: add `src/tld/ops/sysml.py`, `src/tld/sysml/files.py` and `src/tld/sysml/change.py` to `MODULES` in tests/core/test_mutants_file.py and four mutants to tests/mutation/mutants.yaml in the file's format, with the ids `sysml-no-nofollow` (remove `os.O_NOFOLLOW` from the write flags in files.py; killed by the final-symlink test of p2), `sysml-archive-id-not-reserved` (make `change.valid_id` accept `archive`; killed by test_valid_id), `sysml-base-hash-not-checked` (delete the base-hash comparison of `check_change`; killed by the changed-since tests) and `sysml-render-check-compares-nothing` (make the `--check` branch of `render` skip the comparison; killed by the out-of-date test); each pointed at the test files of its module. Stop with status=blocked if `MODULES` is not defined in that test file.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_ops_sysml.py tests/core/test_mutants_file.py -q passes
      - .venv/bin/python tests/mutation/run_mutants.py --only sysml-no-nofollow sysml-archive-id-not-reserved sysml-base-hash-not-checked sysml-render-check-compares-nothing exits 0
      - .venv/bin/python -m pytest tests/core/test_sysml_files.py tests/core/test_sysml_parse.py tests/core/test_sysml_model.py tests/core/test_sysml_change.py tests/core/test_sysml_layout.py tests/core/test_sysml_render.py tests/core/test_ops_sysml.py -q --cov=tld.sysml --cov=tld.ops.sysml --cov-branch --cov-report=term-missing --cov-fail-under=90 passes
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
      Read first: src/tld/plan/manifest.py (lines 20-100, 255-280 and 360-380), tests/core/test_validate_manifest.py (the spec_change tests, lines 411-514), tests/mutation/mutants.yaml, plan section 3.7. Pattern: commit 01036df of PR #73.
      1. Add "sysml_change" to TOP_KEYS after "spec_change".
      2. Replace the spec-only code in validate() (the id check block and the fence block) by one table-driven loop over `FENCES = {"spec_change": {"block": "spec", "paths": ("openspec/**",), ...}, "sysml_change": {"block": "sysml", "paths": ("sysml/**", "docs/architecture.md", "docs/architecture.svg"), ...}}` where each entry also carries its message templates. Every message of `spec_change` stays byte for byte as it is now; the `sysml_change` messages are those of plan section 3.7. The id rule for `sysml_change` additionally rejects `archive` with the same id error; `spec_change: archive` stays accepted. A phase "touches the fence" when `paths_overlap(entry, p)` holds for any fenced path p; "the last phase must touch" is satisfied by one of the paths.
      3. The no-change-no-touch rule of 3.7 for `sysml` only: with a profile that has a `sysml` mapping and no `sysml_change` key, add the error `phase '<id>': touches sysml/ or the architecture docs but the manifest has no sysml_change; narrow the touches or set sysml_change` for every phase that touches the fence (the last phase included); skipped when no profile is given.
      4. docs/reference/profile-reference.md, section "The manifest": add one sentence after the `spec_change` one: `sysml_change` (optional) names the architecture change the plan carries; the profile needs a `sysml` block and only the last phase may touch `sysml/`, `docs/architecture.md` and `docs/architecture.svg`; with a `sysml` block and no `sysml_change` no phase may touch them.
      5. Tests in tests/core/test_validate_manifest.py next to the spec tests, with `SYSML_PROFILE = {"sysml": {"subset": 1}}` (no `spec` key): the happy path with it (`vm.validate(m, SYSML_PROFILE) == ([], [])`); `{"spec": {"version": "2.1.0"}}` alone gives `sysml_change needs the profile's sysml block`; the middle-phase fence test parametrized over `[SYSML_PROFILE, None]` and `"sysml_change needs the profile's sysml block" not in errors(m, vm, None)`; ids `"abc\n"`, `"-x"`, `"../x"`, `"A"`, `"a--b"`, `""`, `"archive"`, `7`, `["x"]`; the missing block error, also for `sysml: null`; the fence for a middle phase with each of `sysml/model/core.sysml`, `sysml/changes/x/model/a.sysml`, `sysml/`, `sysml/**`, `docs/architecture.md`, `docs/architecture.svg`, `docs/**`, `**/*.md` (exact error each) and no error for `src/**` and `docs/README.md`; the last phase touching only `docs/architecture.svg` passes; the last phase touching none gives the last-phase error; the dependency rule; the differing-slug warning; `test_no_change_no_touch` parametrized over the same entries as the fence (exact message, with a profile; no error without a profile; no error for a profile without a `sysml` block); `test_spec_profile_without_spec_change_lets_a_middle_phase_touch_openspec` (`errors(m, vm, SPEC_PROFILE)` mentions no `openspec`); `test_spec_change_archive_is_still_accepted`; both `spec_change` and `sysml_change` set with a last phase touching both fences passes; `sysml_change` added to the known-key test with a plan that keeps `errors(m, vm) == []`; one CLI test through `--profile`.
      6. tests/mutation/mutants.yaml: three mutants in the file's format with the ids `sysml-fence-last-phase-not-excluded` (let the fence loop also flag the last phase for sysml), `sysml-fence-block-check-skipped` (replace `"block": "sysml"` by `"block": "spec"` in FENCES) and `sysml-no-change-no-touch-dropped` (delete the no-change-no-touch branch), each pointed at tests/core/test_validate_manifest.py.
      Stop condition: if any existing spec_change test fails after your refactor, undo the refactor of that message and keep it byte for byte; stop with status=blocked if `paths_overlap` does not flag `docs/architecture.md` against `docs/**`.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_validate_manifest.py tests/core/test_mutants_file.py -q passes
      - .venv/bin/python tests/mutation/run_mutants.py --only sysml-fence-last-phase-not-excluded sysml-fence-block-check-skipped sysml-no-change-no-touch-dropped exits 0
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
      Read first: src/tld/board/record.py (line 42), tests/core/test_status_record.py (grep for `spec`), plan section 3.7. Pattern: commit 587ad82 of PR #73.
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
      Read first: playbooks/spec.md (the model for this playbook), adapters/claude/commands/spec.md, plan section 3.8 (the `sysml` paragraph), the eval task `spec-needs-version` (evals/tasks, evals/stubs, evals/fixtures/commands.py). Pattern: commit 8c66427 of PR #73.
      1. Create playbooks/sysml.md from plan section 3.8 in the shape of playbooks/spec.md: title, one-paragraph purpose, the line `Usage: sysml [check | init]`, `Input: check (default) or init`, the rules line linking policies/untrusted-text.md, policies/status-board.md, policies/research.md and runtime.md, Setup (profile as policies/profile.md says; stop with `toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`; `tld dod exempt` for init), `## check`, `## init` with the steps headed `### 1. Survey`, `### 2. Confirm`, `### 3. Draft`, `### 4. Validate and draw`, `### 5. Deliver` and the status record (kind command, command sysml, `attended: true`, document id from `tld board record-id --repo <owner>/<repo> --command sysml --session <this session's id>`, items survey, confirm, draft, validate, pr), `## Never`. Every `tld ops sysml` call uses `--profile .tld/toolkit.yaml` and only flags the subcommand's --help lists. Before branching the playbook runs `git status --porcelain` and, when it prints anything, stops with `The working tree has changes; commit or stash them first. Nothing was changed.`. The playbook text must contain, literally, the two commands `git checkout -b chore/sysml-init-<yyyymmdd> origin/<main>` and `git push -u origin chore/sysml-init-<yyyymmdd>` (tests/adapters/claude/test_hooks_compat.py requires every COMPAT phrase to occur in it). State in `## init` the subset in one short list (the grammar forms of plan section 3.2 in plain words) so a session can write the model without the plan.
      2. The playbook must not contain `/tld:`, runtime tool or model names, or the words ruff, pytest, connector, mypy (tests/core/test_contracts.py RUNTIME_WORDS, tests/conftest.py FORBIDDEN). Refer to the command as `sysml`.
      3. Create adapters/claude/commands/sysml.md as a copy of adapters/claude/commands/spec.md with: description "Build a SysML architecture model for existing code (init: one pull request, never merged) or validate it (check); needs the profile's sysml block", argument-hint "[check | init]", `model: opus`, the playbook path `${CLAUDE_PLUGIN_ROOT}/playbooks/sysml.md`. Under 1500 bytes.
      4. src/tld/guard/board_gate.py: add "sysml" to RECORD_COMMANDS and `"sysml": ("init",)` to RECORD_MODES. src/tld/guard/plan_gate.py: add "sysml" to OPENING.
      5. tests/core/test_contracts.py: add "sysml" to COMMANDS (line 25) and RESEARCH_PLAYBOOKS (line 313). tests/adapters/claude/test_structure.py: add "sysml" to the tuple at line 65. tests/core/test_board_record_wording.py: add "sysml" to WRITERS (line 8). tests/adapters/claude/test_hooks_compat.py: add `COMPAT["sysml"]` with the two rows `("git checkout -b chore/sysml-init-20260101 origin/main", "git checkout -b chore/sysml-init-<yyyymmdd> origin/<main>")` and `("git push -u origin chore/sysml-init-20260101", "git push -u origin chore/sysml-init-<yyyymmdd>")`, add `sysml/model/core.sysml`, `docs/architecture.md` and `docs/architecture.svg` to test_files_the_commands_write_are_allowed (line 221), and `"<sysml_change>": "foo"` to PLACEHOLDERS (line 170). tests/adapters/claude/test_hooks_config.py: add `("sysml", True)` to the dod-exempt parametrize (line 211).
      6. Guard tests: tests/core/test_hook_board_gate.py: copy the spec tests for sysml (`/tld:sysml` and `/tld:sysml check` open no state and do not block; `/tld:sysml init` does); tests/core/test_hook_plan_gate.py: copy the `/tld:spec init` opening test for `/tld:sysml init`; tests/adapters/claude/test_hook_board_gate_adapter.py: copy the `/tld:spec init` real-script case for `/tld:sysml init`.
      7. Eval task: copy `spec-needs-version` as `sysml-needs-subset`: a profile without a `sysml` block, command `/tld:sysml init`, expected stop message `toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`; add the `sysml` branch to `build` in evals/fixtures/commands.py (and a `- `sysml`: ...` line to its docstring list at line 6) and "sysml" to the parametrize at tests/core/test_evals_fixtures.py:81 (and the `if command == "spec"` assertion that the profile has no block, for sysml too).
      8. tests/core/test_sysml_playbook.py: the playbook contains the line `Usage: sysml [check | init]`, contains `attended: true`, contains the five step headings of item 1, and the command file names the playbook path; `test_sysml_playbook_names_the_stop_message_of_its_eval` (model: the spec one in tests/core/test_spec_playbook.py) reads the `stop_message` of the `command == "sysml"` branch of evals/fixtures/commands.py, asserts it occurs in playbooks/sysml.md and equals the stderr of `tld.ops.sysml.main` for a profile without a `sysml` block; the playbook contains each stop message of plan section 3.8 verbatim; `test_sysml_init_stops_on_a_dirty_tree_before_it_branches` (copy of the spec one in tests/core/test_spec_playbook.py).
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
      Read first: playbooks/make-plan.md (the spec parts, lines 27-31, 88-95, 133-142, 219-300 and 365-372), playbooks/implement.md (sections 4, 5 and 6), plan section 3.8. Pattern: commit fd5a4ef of PR #73.
      1. playbooks/make-plan.md, Setup step 1: add a bullet with this text: "Architecture parts" (the architecture change, sysml_change, the architecture steps of the review) apply only with the profile's sysml block; without it leave them out and never mention the architecture model.
      2. Section 0 step 2: with the sysml block add: read the files `sysml/model/**/*.sysml` and `docs/architecture.md`; when `sysml/model` holds no file, stop and tell the owner to run the sysml command's init first.
      3. After the subsection `### The spec change (spec parts)` add `### The architecture change (architecture parts)` with plan section 3.8's make-plan paragraph in imperative numbered form (decide, `new-change` with `--file` and `--remove`, edit whole files, add new files, proposal, `tld ops sysml check --profile .tld/toolkit.yaml --change <plan slug>` before the push and paste its diff lines into the Design section, acceptance for every new or removed part def and port, manifest key); say that the files are committed to the feature branch with the plan.
      4. The manifest block in section 2: add the line `sysml_change: <plan slug>   # optional; architecture parts only; the architecture change this plan carries` after the `spec_change` line, add the extra `final_checks` line `<`tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml` exit 0 and `sysml/changes/<sysml_change>` does not exist>   # architecture parts only`, and after the paragraph that starts `Spec parts: with `spec_change`` add `Architecture parts:` with the ordered rules of plan section 3.8 for the retirement phase (reconcile; archive, a `changed since` finding is `status=blocked`; check and render --check; commit; a conflict in `docs/architecture.*` is resolved with render) and the `touches` rule, plus the sentence that in a repository with a sysml block a plan phase touching `docs/**` or `**/*.md` must narrow its `touches` or carry `sysml_change`.
      5. Small scope section: after the `Spec change (spec parts):` paragraph add a paragraph headed `Architecture change (architecture parts):` with the files in full as text, the steps new-change, edit, check, implement, archive, commit, and the two acceptance items (check and render --check exit 0; `sysml/changes/<sysml_change>` does not exist, it moved to `sysml/changes/archive/`).
      6. Section 4: extend the helper's list with: (architecture parts) a replaced file that is not whole, a new or removed part def or port that no acceptance item names, a pasted diff that does not match `check --change`.
      7. playbooks/implement.md Merge step 2: after the spec sentence add: with `sysml_change` in the manifest, a diff that touches `sysml/`, `docs/architecture.md` or `docs/architecture.svg` in any phase but the last is sent back, with the same revision and fix exception; with the profile's `sysml` block and no `sysml_change`, any diff that touches them is sent back. Where implement merges `origin/<main>` into the feature branch after the last phase (the sentence near line 336), add: with `sysml_change`, then run `tld ops sysml check --profile .tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml`; a conflict in `docs/architecture.md` or `docs/architecture.svg` is resolved by `tld ops sysml render --profile .tld/toolkit.yaml`, a conflict in a file under `sysml/` or a failing check stops the run with a blocking finding. Section 5 final reviewer brief: after the spec sentence add the architecture sentence of plan section 3.8 (the files under `sysml/changes/<sysml_change>/` were authored by the plan; run check and render --check; the folder must be gone; every part def and port of the archived change named by an acceptance item or a test; failing any is blocking).
      8. Both files stay free of `/tld:`, runtime tool names and the forbidden words (p10's brief item 2). Do not renumber sections.
      9. tests/core/test_sysml_calls.py (model: tests/core/test_spec_calls.py): `test_every_tld_ops_sysml_span_runs_through_the_wrapper`: extract each `tld ops sysml ...` span from playbooks/sysml.md, playbooks/make-plan.md and playbooks/implement.md, fill placeholders with valid ids and relpaths, run `tld.ops.sysml.main` in a fresh temp repository per span (a profile, a valid model, the rendered outputs, and for the change spans a complete change with a filled proposal and correct hashes), assert the exit code is exactly 0 for every span, and that no span uses a subcommand or flag outside the four subcommands; assert the set of subcommands found per file so an empty extraction fails: playbooks/sysml.md has `{check, render}`, playbooks/make-plan.md has `{new-change, check, archive, render}`, playbooks/implement.md has `{check, render}`; `test_implement_sends_back_sysml_touches_and_final_review_checks_the_archive` and `test_make_plan_manifest_block_has_sysml_change_and_final_check` (substring assertions on the sentences and lines of items 4 and 7).
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
      Read first: docs/architecture/design.md (the Playbooks paragraph), docs/architecture/hooks.md (the plan-gate and board-gate lists), plan section 3. Pattern: commit 32303e4 of PR #73.
      1. docs/architecture/design.md, the Playbooks paragraph: add `sysml` to the list of playbooks and one sentence after the OpenSpec one: the architecture model is tld's own pure-Python subset of the SysML v2 notation, drawn as an SVG, and the plan's architecture change is archived by the retirement phase. Do not link the guide (it is added in p13).
      2. docs/architecture/hooks.md: add `sysml` to the plan-gate list of commands that open a session and in the board-gate sentence change "`spec` only in its `init` mode" to "`spec` and `sysml` only in their `init` mode".
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
      Read first: README.md (the Commands table), docs/guides/spec.md (the shape of this guide), docs/README.md, CHANGELOG.md (the `## [Unreleased]` section), plan sections 3 and 5. Pattern: commit ea87bc8 of PR #73.
      1. Create docs/guides/sysml.md: `# Architecture with SysML`, a summary of at most 3 lines, then: what it is and the opt-in (`sysml.subset: 1` with a profile snippet); the honesty sentence of plan section 3.1 ("a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; tld does not check it against one"); the subset reference (the grammar forms in a table or a short code block, the reserved words rule, qualified names and scopes, the limits, the exact finding messages' meanings in one table); `/tld:sysml init` and `check`; how make-plan writes the architecture change (the overlay: proposal, whole files, base hashes, `check --change` diff) and how implement's last phase archives it and redraws; the fence and the no-change-no-touch rule; the two generated docs and the stamp, `render --check` and the layout number, with a two-line CI snippet (`tld ops sysml check` and `tld ops sysml render --check`); that the check protects the model against the docs, never against the code; the safety notes (symbolic links refused, SVG shows names only, doc text rules); that a board host older than this release refuses `command: sysml` records; that a plan phase touching `docs/**` or `**/*.md` in a repository with a `sysml` block must narrow its `touches` or carry `sysml_change`; that a `changed since the change was written` finding at archive means another plan changed the file, with the remedy of the message; the manual checks ma1 and ma2 of plan section 5. Under 150 lines.
      2. docs/README.md: in `## Guides` add after the `guides/spec.md` row: `- [guides/sysml.md](guides/sysml.md) - architecture with SysML: the profile's sysml block, /sysml init and check, the architecture change a plan carries and its archive, the subset and the generated docs/architecture.md; read when setting up the architecture model or changing the sysml commands.`
      3. README.md: add a row to the Commands table after `/tld:spec`: `/tld:sysml [check \| init]` | builds a SysML architecture model for existing code (one pull request, never merged) and draws it on docs/architecture.md, or validates it; with a `sysml` profile block make-plan also writes the architecture change and implement archives it ([guide](docs/guides/sysml.md)).
      4. CHANGELOG.md: under `## [Unreleased]`, in its `### Added` subsection, add one line in the file's existing style: `/tld:sysml builds an architecture model in tld's SysML v2 subset for existing code and draws it as docs/architecture.svg on docs/architecture.md; with a sysml profile block /tld:make-plan writes the architecture change and /tld:implement archives it in the last phase; tld ops sysml check and render --check guard it in CI (#81).` No version heading.
      5. This repository's profile has no `sysml` block and this plan has no `sysml_change`, so no `sysml/` folder and no `docs/architecture.md` are created here; do not create them.
      6. Run `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, then `python3 evals/run.py check-baseline`.
    acceptance:
      - sed -n '/^## \[Unreleased\]/,/^## \[/p' CHANGELOG.md | grep -n "#81" matches
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - python3 evals/run.py check-baseline exits 0
      - .venv/bin/python -m pytest tests -q passes
```
