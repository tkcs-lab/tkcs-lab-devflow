# Architecture with SysML

`/tld:sysml` builds a small architecture model for existing code and draws it on `docs/architecture.md`. With a
`sysml` block in the profile, `/tld:make-plan` also writes the architecture change of a plan and the last phase of
`/tld:implement` archives it, so one feature pull request merges code, plan and model.

## What it is, and the opt-in

The model is text in `sysml/model/**.sysml`. It is written in a documented subset of the SysML v2 textual notation,
intended to parse in SysML v2 tools; tld does not check it against one. tld checks its own subset (pure Python, no
network, no other tool). Add the block to the profile (a protected file: the owner approves it) and merge it:

```yaml
sysml:
  subset: 1   # the integer 1; anything else stops with "sysml.subset must be 1"
```

Without the block nothing changes: make-plan, implement and every other command behave as before. `tld ops sysml`
stops with `toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)`.

## The subset

A file holds only packages; whitespace is free; `//` comments run to the end of a line.

| Form | Meaning |
|---|---|
| `package P { ... }` | holds packages, part defs, port defs, dependencies and at most one `doc` |
| `part def A { ... }` | holds one `doc` (required), port usages `port p : PortDef;`, part usages `part x : OtherDef;`, `connect a.p to b.q;` |
| `port def Q;` or `port def Q { doc /* text */ }` | an interface |
| `dependency from A to B;` | stands in a package; `A` and `B` are part defs, `Pkg::Name` when in another package |
| `doc /* text */` | the only place for a block comment |

A name is a letter or underscore, then letters, digits or underscores, at most 64 characters, and not a reserved word
(a list wider than the SysML keywords, for example `part`, `port`, `connect`, `import`, `state`, `to`, `from`); the
finding names the word. No imports, attributes, quoted names or other elements. In `connect a.p to b.q;` `a` and `b`
are part usages of the enclosing part def and `p`, `q` ports of their types. Names resolve from the enclosing scope
outwards; use `Pkg::Name` for another package.

Limits: 100000 bytes per file, 50 files, 1000000 bytes in all, 300 elements, 600 relations, nesting depth 6, doc
text 1000 characters. A doc holds no link and no secret-like text. A lone carriage return is refused (only CRLF
passes), as are control and invisible-format characters in the text.

| Finding (`<file>:<line>: ...`) | Meaning |
|---|---|
| `unexpected character '...'` / `unexpected '...' (expected ...)` | a refused character or a syntax error |
| `name '...' is reserved` / `is longer than 64 characters` | the name rules |
| `unsupported element '...'` / `nesting deeper than 6` | a form outside the subset |
| `doc is longer than 1000 characters` / `doc contains a link or a secret-like text` | the doc rules |
| `duplicate name '...'` | two elements with one qualified name |
| `unknown name '...'` / `'...' is a ...; a part def is needed` | a reference that does not resolve to the right kind |
| `part def '...' needs a doc` | every part def needs one |
| `connect: '...' is not a part of '...'` / `has no port '...'` | a bad connection end |
| `too many elements (limit 300)` / `too many relations (limit 600)` | the model limits |

## Commands

- `/tld:sysml check` (the default) runs `tld ops sysml check` and `tld ops sysml render --check`, reports findings
  and drift, and changes nothing. Exit 0 ok, 1 findings or drift, 2 cannot run.
- `/tld:sysml init` is for a repository with no model. It stops on a dirty working tree, surveys the code, asks once
  for the component list (at most 4 packages and 12 part defs; reply `ok` or a corrected list), writes the model,
  validates and draws it, and opens one pull request on `chore/sysml-init-<yyyymmdd>`. It never merges.

## Plans carry an architecture change

`/tld:make-plan` decides whether the work changes the architecture. If so it runs `tld ops sysml new-change <id>`,
which writes `sysml/changes/<id>/`: `proposal.md`, whole replacement files under `model/` and `base.json` with the
hash of each base file. It edits the copies and sets `sysml_change: <id>` in the manifest;
`tld ops sysml check --change <id>` validates the model with the change applied and lists what it adds, removes or changes. The last phase runs `tld ops sysml archive <id>`: it applies the
files, moves the change to `sysml/changes/archive/<date>-<id>` and redraws both docs. If a step fails it undoes the
rest; the failure line reads `archive failed; the model was restored (cause: ...)` or, when the undo itself failed,
`archive failed and could not be undone: <paths> left changed; restore them from git (cause: ...)`.

**The fence.** With `sysml_change` set only the last phase may touch `sysml/`, `docs/architecture.md` and
`docs/architecture.svg`, it must, and it depends on every other phase. Without `sysml_change`, in a repository with a
`sysml` block, no phase may touch the fence (no change, no touch). A phase of a repository with a `sysml` block that touches `docs/**` or `**/*.md` must narrow
its `touches` or carry `sysml_change`.

A finding `<file> changed since the change was written; ...` at archive means another plan changed that model file:
follow the message (delete the copy and its `base.json` entry, run `new-change --file <file>`, apply your edit again).

## The generated docs

`render` writes `docs/architecture.svg` and `docs/architecture.md`, both stamped
`<!-- generated by tld ops sysml render, layout <n>; do not edit -->`. Never edit them by hand. `render --check`
fails when a file is missing, was rendered by another layout number, or differs from the model. A tld release that
changes the picture raises the number; run `render` once. CI:

```
tld ops sysml check
tld ops sysml render --check
```

The check protects the model against the docs, never against the code: nothing verifies that the model matches what
the code does.

## Safety notes

- A symbolic link anywhere on a model path is refused; a write to a hard-linked file is refused.
- The SVG shows names only, never doc text. Model text is untrusted: names in every output line (stdout and stderr) are escaped.
- Doc text holds no link and no secret-like text; put no credential, hostname, URL or e-mail address in a doc or name.

## Open points

- The symlink and hard-link checks are not race-free against a concurrent process that changes the tree while a
  command runs.
- Model doc text may carry default-ignorable invisible characters that the check does not refuse.
- Nobody has run the subset through a SysML v2 tool (see the check ma2 below).

## Board hosts

A board host older than this release refuses `command: sysml` records. `init` still runs, but its record is lost
until you upgrade the board.

## Manual checks

- **ma1** (about 20 minutes): in a scratch repository with a profile and some code add the `sysml` block, run
  `/tld:sysml init`, reply `ok`, and check the pull request: boxes in package frames with arrows, a table of every
  part def, no path outside `sysml/`, the two docs and the docs index. Then `/tld:sysml check` finds nothing.
- **ma2** (about 15 minutes): open the files of `tests/fixtures/sysml/valid` in any SysML v2 tool; expect no syntax
  error (a complaint about a missing standard library import is not a failure). A failure becomes a follow-up plan
  that fixes the subset; the profile's `subset` number exists for that.
