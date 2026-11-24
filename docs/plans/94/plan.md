# Plan 94: a reading guide in the entry file

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** An agent opens a tld repository and finds a short numbered guide in the entry file (`AGENTS.md` here, `CLAUDE.md` elsewhere). It says which source answers which question: a brief's `Read first:` docs, the docs index, the specs, the architecture doc, the ADRs, the changelog, then a code search. It also says what not to read. The owner, docs init or a plan's last phase runs `tld ops docs-index guide --profile .tld/toolkit.yaml --write`, which writes the guide from the profile, so each repository sees only the sources it really has. `tld ops docs-index check` warns when the written guide no longer matches the profile.

**Scope:** A new module `src/tld/ops/reading_guide.py`, a new `guide` subcommand of `tld ops docs-index`, and new check rules: a stale guide is a warning; broken markers, a guide in both entry files and a bad profile path in a written guide are errors. The reading protocol in `playbooks/policies/docs.md` is rewritten to match. Docs init writes the guide, docs tidy refreshes a stale one, the ask playbook follows it, and the make-plan retirement phase writes it. This repository's `AGENTS.md` gets the guide. No profile key, no schema change, no new command or skill, and no architecture-model change: the subcommand lives inside the existing ops part. A repository without the markers sees no new message.

**Security:** The writer puts profile values into a file every session loads. It accepts only relative paths under the root with no link-breaking characters. It refuses symlinked entry files, refuses broken markers, refuses a result over 60 lines, and writes atomically.

**Review focus:** The exact guide text and its conditions (3.2), because every session pays for it. The write rules, which must never drop text (3.4). Stale as a warning rather than an error (3.5), so a plan's middle phase cannot block merges. The rollout through retirement phases and docs init, with nothing unattended inserting a first guide (3.6).

## 1. Goal

The owner asked for "a very clear and focused and context-aware instruction to claude to save tokens and effectively find answers", pointing to README, ADRs, OpenSpec, SysML and AGENTS.md ([#94](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/94)). After this change every tld repository can carry, in its always-loaded entry file, a reading guide of about a dozen lines. The guide names the first source to try for each kind of question and what to skip. tld generates it from the profile, so it lists only what the repository has and stays correct when the profile changes.

## 2. Current state

- Entry chain here: `CLAUDE.md` (2 lines) links `AGENTS.md` (38 lines). The `## Docs` section of `AGENTS.md` (`AGENTS.md:18-21`) says "Open docs/README.md first, then only the rows that match your task. Do not read other docs for context. If you add, move or delete a doc, update its row in the same change."
- The reading rules live in `playbooks/policies/docs.md:22-28` ("Reading protocol"). They cover only the index, the rows and the ADR index. They say nothing of `openspec/specs/` (12 capabilities here), `sysml/model/` and its drawn `docs/architecture.md` (`src/tld/ops/sysml.py:33`, `OUTPUTS`), the changelog, `openspec/changes/` or `sysml/changes/`, or how to look into the code.
- The entry-file shape is set in `playbooks/policies/docs.md:17-20`: a `## Docs` section with one fixed "Open … first" line. `playbooks/docs.md` init step 5 writes that shape. `playbooks/ask.md`, the `tld:ask` skill that answers plain questions, has no reading order.
- `tld ops docs-index` (`src/tld/ops/docs_index.py`, 606 lines) has `check`, `inventory` and `move`. `load_config` (`:106-124`) reads only `docs.index`, `adr_dir`, `adr_index` and `plan_dir`. `check` (`:168-252`) looks only at the root `CLAUDE.md` (`:173-185`). The CLI parser is at `:553-576`.
- Tests: `tests/core/test_docs_index.py` (54 tests, `make_repo` helper at `:22`, `run` helper, the repository checks `test_this_repository_docs_index_is_clean` and `test_claude_md_is_thin` at `:511-525`). `tests/core/test_contracts.py:95-129` parses every `tld …` call a playbook names with the real CLI.
- Spec: `openspec/specs/release-and-repo-ops/spec.md:105-124` "Requirement: Docs index check".
- Eval baselines `evals/baselines/default.json` hash every command's playbook and linked files (CONTRIBUTING.md:80-84). Changing `policies/docs.md`, `docs.md`, `ask.md` or `make-plan.md` makes `python3 evals/run.py check-baseline` fail until the hashes are refreshed.

## 3. Design

### 3.1 Where it lives

A new module `src/tld/ops/reading_guide.py` holds pure functions. `docs_index.py` wires in a `guide` subcommand and calls the module from `check`. Rejected alternatives:
- A static doc linked from the entry file: one more read in every session, and it cannot know which sources a repository has.
- A skill: a skill loads only on its trigger, and non-Claude runtimes that read `AGENTS.md` never see it.
- A template file with conditionals: it would need a small template language.
- Parsing the block out of the policy doc: that ties runtime output to a playbook's formatting.

Drift between the policy and the code is caught by a test (p2) that checks the policy names every source the renderer can emit.

### 3.2 The rendered block (exact)

The inputs come from the profile only: no filesystem, no git, no clock, no version. That keeps the block deterministic, so `check` can compare by rendering again.

- `index`: `docs.index`, or `--index`.
- `spec`: true when the profile has a mapping `spec`.
- `sysml`: true when the profile has a mapping `sysml`.
- `adr`: `docs.adr_index`, else `<docs.adr_dir without trailing />/README.md`, only when `docs.adr_dir` is set.
- `changelog`: `docs.changelog.file` when `docs.changelog` is a mapping with `file`.
- `plan_dir`: `docs.plan_dir`, default `docs/plans`, without trailing `/`.

The block is these lines, in this order, joined with `\n` and ending with a final `\n`; each line ends at its last non-space character. Every item present is numbered 1 to n in the order shown:

```
<!-- tld:reading-guide v1 -->
Take each answer from the first source below that has it, read only the part you need, then stop.

<n>. A `Read first:` line in your prompt or brief: open those docs first.
<n>. How it works or how to do something: [<index>](<index>), then only the rows that match.
<n>. Required behaviour, rules and exact messages: list `openspec/specs/`, then read only the matching `### Requirement` block of `openspec/specs/<capability>/spec.md`.        (only with spec)
<n>. Which parts exist and how they connect: [docs/architecture.md](docs/architecture.md); open `sysml/model/` only to change the model.        (only with sysml)
<n>. Why something was decided: [<adr>](<adr>), then only the ADRs whose one-line decision touches the area.        (only with adr)
<n>. What changed in a release: [<changelog>](<changelog>), only the section you need.        (only with changelog)
<n>. The code: search for the symbol, path or exact message text, then read only the lines around each hit.

Do not read every doc. Skip <skips> unless your task names them.
<!-- /tld:reading-guide -->
```

The `(only with …)` notes are not part of the output. `<skips>` is built from this list: `` `archive/` directories ``, `` the plans under `<plan_dir>/` ``, then `` `openspec/changes/` `` (only with spec), then `` `sysml/changes/` `` (only with sysml). The items are joined with `, `, except that the last two are joined with ` and `.

For this repository's profile (spec, sysml, changelog, no ADRs) the items are numbered 1 to 6, and the last line reads: Skip `archive/` directories, the plans under `docs/plans/`, `openspec/changes/` and `sysml/changes/` unless your task names them.

The architecture path is the constant `ARCHITECTURE_DOC = "docs/architecture.md"` in `reading_guide.py`. A test asserts it equals `tld.ops.sysml.OUTPUTS[1]`. Keeping a constant avoids importing the SysML package for every check.

Every path value (`index`, `adr`, `changelog`, `plan_dir`) passes `check_path(value, key)`. It raises `GuideError(f"{key}: '{value}' cannot go into the entry file")` when the value is empty, absolute, contains a `..` segment or a backslash, or contains any of the characters `\n \r [ ] ( ) < > ` and backtick.

### 3.3 Module API (`src/tld/ops/reading_guide.py`)

```python
BEGIN = "<!-- tld:reading-guide v1 -->"
END = "<!-- /tld:reading-guide -->"
BEGIN_PREFIX = "<!-- tld:reading-guide "
ARCHITECTURE_DOC = "docs/architecture.md"
MAX_ENTRY_LINES = 60

class GuideError(ValueError): ...

def guide_inputs(profile_data: dict, index: str) -> dict          # keys: index, spec, sysml, adr, changelog, plan_dir (3.2)
def check_path(value: str, key: str) -> str
def render(inputs: dict) -> str                                   # the block of 3.2
def find_entry(root: Path) -> Path                                # 3.4
def find_markers(text: str) -> tuple[int, int] | None             # 0-based line numbers of BEGIN and END
def apply(text: str, block: str) -> str                           # 3.4
def write(root: Path, inputs: dict, max_lines: int = MAX_ENTRY_LINES) -> str   # "wrote <rel>" or "unchanged <rel>"
def check_entry(root: Path, inputs: dict) -> tuple[list[str], list[str]]       # (errors, warnings) for docs-index check, 3.5
```

`find_markers` skips every line inside a fenced code block (a line whose stripped text starts with ```` ``` ```` or `~~~` toggles the fence). Outside fences:
- A line whose stripped text starts with `BEGIN_PREFIX` but is not exactly `BEGIN` raises `GuideError("reading guide marker of another version")`.
- No `BEGIN` and no `END` returns `None`.
- Exactly one `BEGIN` before exactly one `END` returns the pair.
- Anything else raises `GuideError("reading guide markers are duplicated or unbalanced")`.

### 3.4 Entry file and write rules

`find_entry(root)` returns `root/"AGENTS.md"` when `root/"CLAUDE.md"` is a file whose text matches `\]\((?:\./)?AGENTS\.md\)` and `root/"AGENTS.md"` is a file. Otherwise it returns `root/"CLAUDE.md"`.

`apply(text, block)` never drops a line outside the markers:
1. Markers found: replace the lines from `BEGIN` to `END` (inclusive) with the block's lines.
2. Otherwise, the first line outside fences that equals `## Docs` after `rstrip()`: insert directly after it an empty line and then the block's lines. When the next existing line is not empty, also insert one empty line after the block.
3. Otherwise: make the text end with `\n`, then append `\n## Docs\n\n` and the block.

`write(root, inputs)`:
- The entry file is missing: `GuideError("no CLAUDE.md in the repository root")`.
- `entry.is_symlink()`, or `entry.resolve()` not under `root.resolve()`: `GuideError(f"{rel}: is a symbolic link or outside the repository")`.
- The new text has more than `max_lines` lines: `GuideError(f"{rel}: {n} lines after the write, over {max_lines}: move detail into docs/ first")`.
- New text equals the old: return `f"unchanged {rel}"` without writing.
- Otherwise write a temporary file in the same directory and `os.replace` it onto the entry file, then return `f"wrote {rel}"`.

`rel` is the path relative to the root (`AGENTS.md` or `CLAUDE.md`).

### 3.5 CLI and check

`tld ops docs-index guide [--profile PATH] [--root DIR] [--index PATH] [--write]`. It is added to the `for name in (...)` loop of `main` (`docs_index.py:556`), so it shares `--profile`, `--root`, `--index` and `--json`; `--json` is accepted and ignored. `--write` is added to the `guide` parser only.
- Without `--write`: write the block to stdout exactly as `render` returns it (`print(block, end="")`), exit 0.
- With `--write`: print the message from `write`, exit 0.
- A `GuideError`: print `docs index guide: <message>` to stderr and exit 1.
- No `docs.index` and no `--index`: the existing exit 2 of `load_config`.

`load_config` additionally stores `cfg["guide_inputs"] = reading_guide.guide_inputs(data, <docs.index or --index as given, relative>)`. The path checks run lazily, in `render`, so `check` and `inventory` do not fail on a bad path unless the guide is in use.

`check` gains, after the CLAUDE.md block, `errors += e; warnings += w` from `check_entry(root, cfg["guide_inputs"])`. That function:
- Both `CLAUDE.md` and `AGENTS.md` exist and each has markers: error `CLAUDE.md and AGENTS.md both hold a reading guide: keep it only in <entry>`.
- `find_markers` on the entry file raises: error `<rel>: <message>`.
- Markers found and the text between them, markers included, differs from `render(inputs)` without its final newline: warning `<rel>: the reading guide is out of date (run tld ops docs-index guide --write)`. A `GuideError` from `render` is an error `<rel>: <message>`.
- No markers: nothing.
- Only the entry file is examined for broken markers; the other of the two files is read only for the two-guides error (its markers found with `find_markers`, a `GuideError` there counted as "has markers").

Stale is a warning and not an error because `check` runs after every merge, and only the retirement phase may edit the entry file. An error would block every merge between a phase that changes the profile and the retirement phase. `--strict` still turns it into an exit 1, which tidy and dod readers can choose. A missing guide is not reported, so upgrading tld adds no message to any repository.

### 3.6 Who writes it (rollout)

- The policy (`playbooks/policies/docs.md`): the entry file's `## Docs` section holds the reading guide, plus any rule lines the repository adds. The Reading protocol is rewritten to the same order as the block (p2 gives the exact text). Maintain gains a rule: a change to the profile's `docs`, `spec` or `sysml` keys runs `guide --write`.
- docs init: writes it at the end of step 10.
- docs tidy: refreshes only a stale guide (a mechanical fix). It never inserts a first one, because unattended runs must not grow every entry file.
- make-plan (index parts): the retirement phase runs `guide --write` when the plan changes those profile keys or the entry file has no guide yet. That is how existing repositories get it, inside a reviewed pull request.
- ask: answers follow the guide's order.

### 3.7 This repository's entry file (p3)

After `guide --write`, the `## Docs` section of `AGENTS.md` is: the heading, an empty line, the block, an empty line, and the single kept line `If you add, move or delete a doc, update its row in the same change.` The two old sentences "Open [docs/README.md](docs/README.md) first, then only the rows that match your task. Do not read other docs for context." are removed by hand, because the guide's items 1 and 2 and its last line say the same. That removes no rule.

### 3.8 The spec change

The change `openspec/changes/reading-guide/` (committed with this plan; `tld ops spec validate --change reading-guide` exits 0). Its capability is `release-and-repo-ops`.

ADDED "Requirement: Docs reading guide" with these scenarios:
- Only declared sources
- Same profile, same guide
- Write keeps existing text
- Refused write

MODIFIED "Requirement: Docs index check": the whole block, with these scenarios:
- Errors (now also broken markers and two guides)
- Exempt documents
- Warnings (now also a stale guide)
- No reading guide (new)
- JSON and missing index setting

The architecture model does not change: no part, port or dependency is added (the subcommand is inside the existing ops part, `sysml/model/core.sysml:23`). No `sysml_change`.

## 4. Manual steps

None before implementation.

### After implementation

1. **ma1-fresh-session-check** (about 5 minutes)
   1. Open https://claude.ai/code, start a new session with the repository `tkcs-lab/tkcs-lab-devflow` and the branch `feature/reading-guide` (the branch's entry file: https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/reading-guide/AGENTS.md).
   2. Ask: "Which requirement says what `tld ops release-check` prints when a check is still running? Do not change anything."
   3. Expected: the session opens the guide's spec source (`openspec/specs/release-and-repo-ops/spec.md`), finds "Judge whether a commit is green for a release", and does not open `docs/plans/` or every doc.
   4. Report back on the pull request: `ma1: pass` or `ma1: fail - <which files it opened>`.

## 5. Risks and open questions

- **Eval hashes.** p2 changes four playbook files. If `python3 evals/run.py check-baseline` still fails after `baseline --refresh-hashes`, stop with `status=blocked` and quote the output.
- **Eval stub.** `evals/stubs/docs-check-unindexed.json` quotes check output for a repository without a guide. The new rules print nothing there. If an eval test fails on it, stop with `status=blocked`.
- **No-project-words test.** The rendered text is under `src/`. `tests/core/test_no_project_words.py` must pass. If it flags a word of 3.2, stop with `status=blocked` instead of rewording on your own.
- **Contract parse.** `test_every_tld_call_parses_with_the_real_cli` checks the `guide` calls p2 adds against `guide --help`. It only works after p1 registers the subparser (hence `depends_on`).
- **Length.** This repository's `AGENTS.md` grows from 38 to 50 lines (51 at the moment of the write), under 60. If `guide --write` refuses with the line limit, stop with `status=blocked`.
- **Rendered text.** The exact guide wording is the riskiest decision, and ma1 is its only real check.

## Implementation manifest

```yaml
plan_slug: reading-guide
feature_branch: feature/reading-guide
tracking_issue: 94
spec_change: reading-guide
max_parallel: 1
manual_after:
  - id: ma1-fresh-session-check
    title: Ask a fresh session a spec question on the feature branch and see which files it opens
    why: only a real session shows whether the guide steers reading; no test can
verify_after_merge:
  - .venv/bin/python -m pytest -q -k docs_index
  - .venv/bin/python -m pytest -q -k contracts
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - tld plan deviations check --file docs/plans/94/deviations.md --plan docs/plans/94/plan.md --all exits 0
  - the changelog has entries under docs.changelog.section and no version heading
  - tld ops docs-index check --profile .tld/toolkit.yaml exits 0
  - tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/reading-guide does not exist
phases:
  - id: p1-guide-command
    title: Add the reading-guide module, the guide subcommand and the check rules
    depends_on: []
    complexity: M
    touches:
      - src/tld/ops/reading_guide.py
      - src/tld/ops/docs_index.py
      - tests/core/test_reading_guide.py
      - tests/core/test_docs_index.py
      - docs/reference/cli.md
    brief: |
      Read first: docs/plans/94/plan.md sections 3.2 to 3.5, docs/reference/cli.md, stacks/python.md.
      1. Create src/tld/ops/reading_guide.py with exactly the names, signatures, strings and rules of plan sections 3.2, 3.3 and 3.4 (module docstring: one paragraph saying it renders and writes the entry file's reading guide; stdlib only, plus `from pathlib import Path`). guide_inputs reads `profile_data.get("docs") or {}` and treats a non-dict profile as {}.
      2. In src/tld/ops/docs_index.py: import `from tld.ops import reading_guide`; in load_config keep the profile data and set cfg["guide_inputs"] = reading_guide.guide_inputs(data, index_as_given) where index_as_given is args.index or docs.index before it is resolved (data is {} when the profile file is missing); add "guide" to the `for name in ("check", "inventory")` loop; add `--write` (store_true, help "write the guide into the entry file") to the guide parser; in main handle `args.cmd == "guide"` as plan section 3.5 says; in check() append the result of reading_guide.check_entry(root, cfg["guide_inputs"]) after the CLAUDE.md block. Extend the module docstring: a usage line `docs_index.py guide [--profile ...] [--root .] [--index PATH] [--write]`, the new error and warning in the Errors/Warnings paragraphs, and one sentence that `guide` writes only with --write.
      3. tests/core/test_reading_guide.py (new, unit tests calling the functions):
         - test_render_for_this_shape: spec+sysml+changelog, no ADR, equals the exact text of section 3.2 with items 1-6 and the Skip line quoted there;
         - test_guide_renders_only_declared_sources: parametrized over spec, sysml, adr, changelog; each on: its row present, each off: absent;
         - test_guide_uses_the_profile_index_path: docs.index handbook/INDEX.md is in the block;
         - test_adr_index_defaults_to_readme_in_adr_dir;
         - test_block_has_both_markers: starts with BEGIN line, last line END;
         - test_render_is_deterministic: two calls are equal;
         - test_check_path_refuses: parametrized "/abs.md", "../x.md", "a\\b.md", "a)b.md", "a]b.md", "a\nb.md", "a<b.md", "";
         - test_architecture_doc_matches_sysml_outputs: ARCHITECTURE_DOC == tld.ops.sysml.OUTPUTS[1];
         - test_find_markers: none, one pair, duplicated begin, end before begin, unterminated begin, other version, a marker inside a ``` fence is ignored;
         - test_apply_replaces_between_markers (text outside kept byte for byte), test_apply_inserts_under_docs_heading (the line after the heading and a following `## Commands` section kept), test_apply_appends_docs_section (exactly one `## Docs`, ends with the block);
         - test_find_entry: AGENTS.md when CLAUDE.md links `(AGENTS.md)` or `(./AGENTS.md)`; CLAUDE.md when AGENTS.md exists but is not linked.
      4. tests/core/test_docs_index.py (CLI tests with the existing run helper and make_repo; give the helper a mode "guide" if it needs one):
         - test_guide_prints_block_and_writes_nothing; test_guide_write_targets_agents_md_when_claude_md_links_it (CLAUDE.md byte-identical); test_guide_write_targets_claude_md_otherwise (AGENTS.md unchanged);
         - test_guide_write_twice_is_byte_identical (second prints `unchanged CLAUDE.md`);
         - test_guide_write_refuses_symlink_entry (AGENTS.md a symlink to a file outside root, exit 1, outside file unchanged); test_guide_write_refuses_unterminated_marker and test_guide_write_refuses_duplicate_markers (exit 1, file unchanged); test_guide_write_refuses_over_line_limit (a 58-line CLAUDE.md, exit 1, unchanged); test_guide_write_without_claude_md_exits_one (no file created); test_guide_refuses_bad_profile_path (docs.changelog.file "../x.md", exit 1, message names docs.changelog.file);
         - test_check_after_guide_write_is_clean (exit 0, no line containing "reading guide"); test_check_without_reading_guide_prints_nothing_about_it; test_check_stale_reading_guide_is_a_warning (edit one line inside the markers: exit 0, the exact warning; exit 1 with --strict; also in --json warnings); test_check_stale_after_profile_gains_sysml (write, add `sysml: {subset: 1}` to the profile, warning); test_check_broken_markers_is_an_error (exit 1); test_check_two_guides_is_an_error (markers in both CLAUDE.md and AGENTS.md);
         - test_docs_index_guide_is_a_subcommand (`docs-index --help` output lists guide) and test_guide_help_lists_its_flags (`guide --help` lists --profile, --root, --index, --write).
         Keep every existing assertion unchanged.
      5. docs/reference/cli.md:80: change the row's command cell to `tld ops docs-index check\|inventory\|move\|guide ...` and append to its last cell `; guide prints the entry file's reading guide from the profile and writes it with --write`.
      Stop conditions: if an existing test in tests/core/test_docs_index.py fails after step 2 without a guide in its repository, the check hook reports something for a repository without markers: fix your code, never the test; if tests/core/test_no_project_words.py flags a word of section 3.2, stop with status=blocked and quote it.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_reading_guide.py -q passes
      - .venv/bin/python -m pytest tests/core/test_docs_index.py -q passes, including test_check_stale_reading_guide_is_a_warning, test_guide_write_refuses_symlink_entry and test_docs_index_guide_is_a_subcommand
      - .venv/bin/python -m pytest tests -q passes
      - "spec scenario Only declared sources: test_guide_renders_only_declared_sources passes"
      - "spec scenario Same profile, same guide: test_render_is_deterministic and test_guide_write_twice_is_byte_identical pass"
      - "spec scenario Write keeps existing text: test_apply_replaces_between_markers, test_apply_inserts_under_docs_heading and test_apply_appends_docs_section pass"
      - "spec scenario Refused write: test_guide_write_refuses_symlink_entry, test_guide_write_refuses_duplicate_markers, test_guide_write_refuses_over_line_limit, test_guide_refuses_bad_profile_path, test_guide_write_without_claude_md_exits_one and test_guide_write_refuses_unterminated_marker pass"
      - "spec scenarios Errors and Warnings: test_check_broken_markers_is_an_error, test_check_two_guides_is_an_error and test_check_stale_reading_guide_is_a_warning pass"
      - "spec scenario No reading guide: test_check_without_reading_guide_prints_nothing_about_it passes"
      - "spec scenarios Exempt documents and JSON and missing index setting: the existing tests of tests/core/test_docs_index.py pass unchanged"
      - grep -n "guide prints the entry file's reading guide" docs/reference/cli.md matches
  - id: p2-playbooks-and-policy
    title: Make the docs policy, docs, ask and make-plan playbooks use the guide
    depends_on: [p1-guide-command]
    complexity: S
    touches:
      - playbooks/policies/docs.md
      - playbooks/docs.md
      - playbooks/ask.md
      - playbooks/make-plan.md
      - docs/guides/docs-index.md
      - tests/core/test_reading_guide.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/94/plan.md sections 3.2 and 3.6, playbooks/policies/docs.md, docs/guides/docs-index.md, CONTRIBUTING.md (Baseline refresh).
      1. playbooks/policies/docs.md, Structure: replace the last bullet's text from "and a `## Docs` section:" to the end of the bullet with: "and a `## Docs` section: the reading guide that `tld ops docs-index guide --profile .tld/toolkit.yaml --write` writes from the profile, plus any rule lines the repository adds."
      2. Same file: replace the whole "## Reading protocol" list with this text, verbatim:
         "The entry file's reading guide (`tld ops docs-index guide`) is this protocol for one repository, limited to the sources its profile declares.

         1. The entry file is already loaded. A brief with a `Read first:` line names the exact docs: open those, and the index only if they are not enough.
         2. Otherwise open the index and only the rows that match the task.
         3. Behaviour, with specs: list `openspec/specs/`, then read only the matching `### Requirement` block.
         4. Structure, with an architecture model: read `docs/architecture.md`; open `sysml/model/` only to change the model.
         5. Decisions: read the ADR index, then only the ADRs whose one-line decision touches the area.
         6. Release history: only the changelog section you need.
         7. Code: search for the symbol, path or exact message text and read only the lines around each hit.
         8. Never read `archive/`, another change's plan, or another change's `openspec/changes/` or `sysml/changes/`. Never read every doc."
      3. Same file, "## Maintain": add item 4: "4. A change to the profile's `docs`, `spec` or `sysml` keys runs `tld ops docs-index guide --profile .tld/toolkit.yaml --write` in the same change (in a plan: the retirement phase); `check` warns about a stale guide." In "## Who edits the index (C3)", in the sentence that starts "Only three things edit the index or the entry file:", insert " (the retirement phase and docs init write the reading guide; tidy only refreshes it)" directly before that sentence's final period.
      4. playbooks/docs.md init step 10: append "Then run `tld ops docs-index guide --profile .tld/toolkit.yaml --write`; on exit 1 show its message, shorten the entry file and run it again, then `tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0." Step 5: replace "rewrite the entry file to the shape in the policy" with "rewrite the entry file to the shape in the policy, leaving the `## Docs` section with only its rule lines (step 10 writes the reading guide)". Tidy step 3: add a last bullet to the mechanical fixes: "an out-of-date reading guide (the check's warning): `tld ops docs-index guide --profile .tld/toolkit.yaml --write`; tidy never writes a first guide into an entry file that has none." Tidy step 4: append to the judgement items list ", a reading guide that `guide --write` refuses (with its message)".
      5. playbooks/ask.md, Rules: add as the second bullet: "- Find the answer in the order of the entry file's reading guide, or without one the Reading protocol of [policies/docs.md](policies/docs.md); open nothing the answer does not need."
      6. playbooks/make-plan.md, the paragraph starting "Index parts: the retirement phase also updates the docs index": replace "and the entry-file lines a change made untrue; it runs" with "and the entry-file lines a change made untrue; it runs `tld ops docs-index guide --profile .tld/toolkit.yaml --write` when the plan changes the profile's `docs`, `spec` or `sysml` keys or the entry file holds no reading guide yet, and it runs".
      7. docs/guides/docs-index.md: replace the whole paragraph under "## How a session reads" with: "The entry file's reading guide lists, in order, the sources this repository has: a brief's `Read first:` docs, the index and its matching rows, then specs, the architecture doc, the ADR index and the changelog where they exist, then a code search. Never read `archive/` or another change's plan, and never read every doc." and add a section "## The reading guide" after "## Keeping it current" of at most 15 lines: what it is (a generated block between `<!-- tld:reading-guide v1 -->` and `<!-- /tld:reading-guide -->`), `tld ops docs-index guide [--write]`, the entry file rule (AGENTS.md when CLAUDE.md links it), the three write cases and that no line outside the markers is dropped, the refusals (symlink, broken markers, bad profile path, over 60 lines), check (stale is a warning, broken markers an error, no guide no message), and who writes it (docs init, a plan's retirement phase, docs tidy only refreshes).
      8. tests/core/test_reading_guide.py: add test_reading_protocol_names_every_guide_source: the text of playbooks/policies/docs.md contains "`Read first:`", "openspec/specs/", "### Requirement", "docs/architecture.md", "sysml/model/", "ADR index", "changelog", "archive/", "openspec/changes/" and "sysml/changes/".
      9. Run `python3 evals/run.py baseline --refresh-hashes`, then `python3 evals/run.py check-baseline` (must exit 0). Say in the commit message: hashes refreshed only; the edits add a reading step and a guide write and change no command's decisions.
      Stop condition: if test_every_tld_call_parses_with_the_real_cli fails on a `guide` call, p1's parser does not match section 3.5: stop with status=blocked and quote the failure; do not change the call.
    acceptance:
      - .venv/bin/python -m pytest tests/core/test_contracts.py -q passes
      - .venv/bin/python -m pytest tests/core/test_reading_guide.py -q passes, including test_reading_protocol_names_every_guide_source
      - python3 evals/run.py check-baseline exits 0
      - grep -n "docs-index guide --profile .tld/toolkit.yaml --write" playbooks/docs.md playbooks/make-plan.md playbooks/policies/docs.md matches in all three files
      - grep -n "reading guide" playbooks/ask.md matches
      - .venv/bin/python -m pytest tests -q passes
  - id: p3-retire
    title: Write this repository's guide, archive the spec change, changelog
    depends_on: [p2-playbooks-and-policy]
    complexity: S
    touches:
      - AGENTS.md
      - CHANGELOG.md
      - tests/core/test_docs_index.py
      - openspec/**
    brief: |
      Read first: docs/plans/94/plan.md sections 3.7 and 3.8, docs/plans/94/deviations.md if it exists, AGENTS.md.
      1. Run `.venv/bin/python cli/tld ops docs-index guide --profile .tld/toolkit.yaml --write`; it must print `wrote AGENTS.md`. Then in AGENTS.md delete the old line "Open [docs/README.md](docs/README.md) first, then only the rows that match your task. Do not read other" (it wraps; it is the line after the block's empty line) and the words "docs for context. " at the start of the next line, so that the `## Docs` section is: heading, empty line, the block, empty line, "If you add, move or delete a doc, update its row in the same change." (plan section 3.7). Run the guide command again: it must print `unchanged AGENTS.md`.
      2. tests/core/test_docs_index.py test_claude_md_is_thin: add `assert "<!-- tld:reading-guide v1 -->" in agents`; test_this_repository_docs_index_is_clean: add `assert "reading guide" not in r.stdout`.
      3. CHANGELOG.md under "## [Unreleased]" / "### Added": add "- `tld ops docs-index guide` writes a short reading guide into the entry file from the profile (which source answers which question, what to skip); docs init writes it, a plan's last phase adds it, docs tidy refreshes it, and `tld ops docs-index check` warns when it is out of date (#94)."
      4. Spec, in this order: (1) reconcile openspec/changes/reading-guide/ with docs/plans/94/deviations.md so the deltas describe what was built; (2) `git diff --quiet $(git merge-base HEAD origin/main) origin/main -- openspec/specs` must exit 0, otherwise stop with status=blocked (main changed the specs, so the MODIFIED block may be stale); (3) `.venv/bin/python cli/tld ops spec archive --profile .tld/toolkit.yaml reading-guide`; (4) `.venv/bin/python cli/tld ops spec validate --profile .tld/toolkit.yaml` must exit 0; (5) `grep -rn "TBD" openspec/specs` must print nothing; (6) commit the moved change and the updated specs.
      5. Docs index: no doc was added, moved or deleted, so no index row changes; `.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` must exit 0.
      Stop condition: if step 1 refuses (line limit or markers), stop with status=blocked and quote the message; never shorten other AGENTS.md sections.
    acceptance:
      - grep -c "<!-- tld:reading-guide v1 -->" AGENTS.md prints 1
      - .venv/bin/python cli/tld ops docs-index guide --profile .tld/toolkit.yaml --write prints unchanged AGENTS.md
      - .venv/bin/python -m pytest tests/core/test_docs_index.py -q passes
      - .venv/bin/python cli/tld ops spec validate --profile .tld/toolkit.yaml exits 0 and openspec/changes/reading-guide does not exist
      - .venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0
      - grep -n "docs-index guide" CHANGELOG.md matches
```
