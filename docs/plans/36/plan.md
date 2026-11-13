# Review summaries for plans and pull requests

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Every plan starts with an unnumbered `## Summary` of at most 350 words under bold labels: `**Use it:**` (a mini user guide), `**Scope:**`, `**Security:**`, `**Performance:**` and `**Review focus:**`. Security and Performance appear only when relevant. The tracking issue repeats the same Summary right after `## Request`. The pull request body starts with the `Closes` lines, then a `## Summary` of at most 175 words that leads with `**Deviations:**` from the plan, then `**Review focus:**`. The full `## Deviations` section stays below it. Authors check a file with `tld plan summary-check FILE --kind plan|issue|pr [--deviations FILE]`. It prints `summary: <problem>` lines and exits 1, or prints `summary: OK (<n> words)`.

**Scope:** New command `tld plan summary-check` (`src/tld/plan/summary.py`, phase p1). The make-plan playbook (large and small scope) and the implement playbook (step 6.3) call it before the plan is pushed, the issue body is rewritten and the pull request is opened (p2). Docs and changelog follow (p3). Not changed: implement does not check a plan's Summary at start, because older plans have none; no profile keys, the limits are fixed; plan 33 and earlier plans are not rewritten.

**Security:** The Summary decides where a human looks, so it is a prompt-injection target. The playbooks require the author's own words (never pasted issue, comment or worker text), forbid "safe to merge" claims and hidden markup, and require the pull request's Review focus or Security label to name every deviation that touches a protected path or came from the security-reviewer. The checker reads one file of at most 1 MB, runs nothing and sanitises every echoed fragment. It cannot judge quality; the reviewer role and the human do.

**Review focus:** (1) the check rules in Design D1: placement per kind, fence and quote awareness, label order, `None.` rules; (2) the 175-word budget and its priority order in D3; (3) the reading of "starts with" in the ask as "after the Closes lines" (D3); (4) p2's placement tests, which run the playbooks' own calls.

## 1. Goal

A human reviewer must be able to judge a plan, and later its pull request, in a few minutes. Plan 33 is 7200 words. Every plan and every feature pull request gets a short, checkable summary at the top: a mini user guide, the scope, security and performance only when relevant, and what to look at. For the pull request the summary is half the size and about the deviations from the plan. Owner decisions (ask `a-23a4679477bc75b9`): limits 350 and 175 words, enforced by a command, fixed in tld, applied to small and large scope.

Tracking issue: [#36](https://github.com/tkcs-lab/tkcs-lab-devflow/issues/36).

## 2. Current state

- `playbooks/make-plan.md:155-169` lists the plan sections (Goal first); nothing asks for a summary. `:105-139` is the small scope (prompt, issue body headings at `:107-110`); `:286-291` is the helper review; `:299-305` rewrites the issue body.
- `playbooks/implement.md:385-393` (6.3) builds the pull request body: `Closes` lines, phases, checklist, review verdict, Scope, a full `## Deviations` section, Manual verification, branches. No summary.
- `src/tld/plan/deviations.py:54-58` `sections()` treats every `## ` line as a heading, fences included; `:48-51` `read_lines` catches only `OSError`; `:61` `clean` replaces only ASCII control characters. summary.py must not reuse them.
- `src/tld/cli.py:24` registers `("plan", "deviations")`; a new command is one row there.
- `tests/core/test_contracts.py:36,55,68` (`code_texts`, `TLD_CALL`, `tld_calls`) parse every `tld` call in the playbooks and check flags against `--help`, not flag values. `tests/core/test_plan_active.py:11` imports them (`from test_contracts import ...`). `tests/conftest.py:68` `tld_cmd`.
- `tests/core/test_mutants_file.py:10` `MODULES` lists the modules `tests/mutation/mutants.yaml` may mutate; `tests/core/test_no_project_words.py` forbids a set of words (among them `pytest`, `connector`, `ruff`) in `src/`, `playbooks/`, `roles/`, `checklists/`, `stacks/`, `adapters/`, `cli/`.
- `tests/core/test_evals_baseline.py::test_committed_baseline_is_current` fails when a playbook changes until the hashes are refreshed (`CONTRIBUTING.md:80-84`); `docs/` is not hashed.
- The profile has no `docs.adr_dir` and no `docs.changelog`; `AGENTS.md` still requires a changelog line for a user-visible change.

## 3. Design

Roles that ran at make_plan: architect (advice below), test-architect (tests below). Options considered:

- **A (chosen).** A separate command `tld plan summary-check` with three kinds. The thing checked is a Markdown section in three documents, two of which have no manifest or deviations file.
- B, rejected: extend `validate-manifest` with `--summary` and add a deviations subcommand. `implement` runs `validate-manifest` at start, so old plans would be one flag from failing; the issue body and a small-scope pull request have no manifest; the rules would be split across modules.
- C, rejected: playbook text only. The owner chose enforcement by a command.
- Also rejected: profile keys for the limits (owner: fixed); a line limit (the owner measures words); a `--require` flag for Security under the critical posture (the owner wants Security only when relevant).

### D1. The check (`src/tld/plan/summary.py`)

`tld plan summary-check FILE --kind plan|issue|pr [--deviations FILE]`. `--deviations` is accepted only with `--kind pr` (otherwise exit 2). Exit 0 prints `summary: OK (<n> words)`. Exit 1 prints one line per problem, `summary: <problem>`, in this order, and never stops at the first. Exit 2 is an argparse error. Public names: `KINDS = ("plan", "issue", "pr")`, `MAX_WORDS = {"plan": 350, "issue": 350, "pr": 175}`, `ORDER`, `REQUIRED`, `NONE_OK = ("Deviations", "Security", "Performance")`, `TEXT_MAX = 80`, `check(text, kind, deviations_text=None) -> (problems, words)`, `main(argv)`. The docstring and messages must avoid the words that `test_no_project_words.py` forbids.

Reading. UTF-8; a leading U+FEFF is dropped; `\r\n` becomes `\n`. A file that cannot be read, is not UTF-8, is a directory or is over 1000000 bytes gives one line `summary: cannot read '<path>': <reason>` (reason `No such file or directory`-style from the OS, `not valid UTF-8`, or `larger than 1000000 bytes`) and exit 1 without a traceback.

Scanning. A line inside a fenced block (opening line of up to three spaces then three or more backticks or tildes; closes on the same character with at least as many) is never a heading and never a label, but it counts as words when inside the Summary. A line that starts (after up to three spaces) with `>` is never a heading or a label. A heading is a line `## <text>` at column 0 outside fences and quotes; its text is stripped. The Summary section runs from its heading to the next heading or the end of the file; `### ` lines stay inside it.

Problems, in order:

1. Heading. No heading `Summary` gives `no '## Summary' section`. A heading whose text contains "summary" in any case but is not exactly `Summary` gives `the heading must be exactly '## Summary' (found '<clean text>')`. More than one exact heading gives `<n> '## Summary' sections`.
2. Placement. `plan`: `## Summary` is the first heading, and before it only blank lines, at most one `# ` title line and `>` lines are allowed. `pr`: first heading, and before it only blank lines and lines matching `(Closes|Fixes|Resolves) #<n>` (any case, optional final period). `issue`: the first heading is `## Request`, the second is `## Summary`, and nothing but blank lines before `## Request`. Wrong place: `'## Summary' must be the first '## ' section` (`issue`: `'## Summary' must come right after '## Request'`). Other text before it: `text before '## Summary' is not allowed: '<clean first offending line>'`.
3. Labels. A label line is `**<Name>:** <value>` or `- **<Name>:** <value>` at column 0; a value continues on the following lines up to the next label. Allowed names and order: `plan` and `issue`: Use it, Scope, Security, Performance, Review focus (required: Use it, Scope, Review focus); `pr`: Deviations, Scope, Security, Performance, Review focus (required: Deviations, Review focus). In this order: `unknown label '<clean name>'` (names are case-sensitive), `duplicate label '<Name>'`, `missing label '<Name>'`, `label '<Name>' is out of order`.
4. Content. `text before the first label` for any non-blank line between the heading and the first label (fenced lines included). `label '<Name>' needs at least 3 words` (words as in D1 counting) unless its value is exactly `None.` (case-insensitive, period optional) and the name is in `NONE_OK`; `None.` on any other label gives `label '<Name>' cannot be 'None.'`. A value that, lower-cased with a trailing period removed, is `tbd`, `todo`, `n/a`, `see below` or `...`, or is a single `<...>` placeholder, gives `label '<Name>' is a placeholder`. `<!--` or `<details` (any case) anywhere in the Summary gives `the Summary holds hidden markup (an HTML comment or a details block)`.
5. Words. Whitespace-split the whole section, heading line included, and count only tokens that contain a letter or digit (`re.search(r"\w", token)`): table bars and `**` do not count. Over the limit gives `<n> words, the limit for <kind> is <max>`.
6. Deviations (only with `--deviations`). When the deviations file has any line starting `- ` whose text is neither `None.` nor `pending`, and the Deviations value is `None.`: `Deviations says None. but the deviations file records <n> deviations`.

Echoed text is passed through `clean`: every character whose Unicode category is Cc, Cf, Cs, Co, Zl or Zp becomes `?` (this covers C1, bidi marks, zero-width characters and U+2028/2029), then it is cut to `TEXT_MAX` = 80 characters. Only label names, heading text and one offending line are ever echoed. No regular expression may backtrack on a long line: a 200000-character line is checked in well under five seconds.

### D2. Playbook rules for the plan and the issue (`playbooks/make-plan.md`)

- Section 2 (plan): directly under the quote line comes the literal heading `## Summary` (not numbered; the other sections keep their numbers), with the five labels of D1, at most 350 words. `**Use it:**` is the mini user guide: what the user types or does and what they see, in two to four sentences. `**Scope:**` says what changes and what does not. `**Security:**` only when the change touches input handling, secrets, access control, the supply chain or what an agent may do. `**Performance:**` only when cost or time changes measurably. `**Review focus:**` names the two to four riskiest decisions with their section numbers. The author writes in their own words: no pasted issue, comment, research or worker text, no "safe to merge", no "no need to review X", no hidden markup.
- Section 4: the helper review also checks that the Summary matches the Design, that every user-visible change is in Use it or Scope, and that Review focus names the riskiest decisions. Then `tld plan summary-check <plan file> --kind plan` must exit 0 before `validate-manifest`.
- Section 5 (issue body): headings become `## Request`, `## Summary`, `## Goal`, ...; the Summary is the plan's Summary word for word. When the ask has its own `## ` lines, `## Request` holds the ask as a blockquote. The new body is written to a scratch file and `tld plan summary-check <file> --kind issue` must exit 0 before `github.issue_update`.
- Small scope: the issue body gets the same `## Summary` (`issue` kind, labels of D1, the planner writes it fresh), and the prompt's Finish step tells the worker to start the pull request body with the `Closes` lines and then a `## Summary` of at most 175 words (labels Deviations, Review focus, Scope optional) that says how the result differs from the prompt, `None.` allowed for Deviations; the worker writes the body to a scratch file and runs `tld plan summary-check <file> --kind pr` before `github.pr_create`.

### D3. Playbook rules for the pull request (`playbooks/implement.md` 6.3)

The body is: the `Closes` lines (they stay first: GitHub reads closing keywords anywhere, and the ask's "starts with the summary" is read as "the Summary is the first section"), then `## Summary` (at most 175 words), then the existing sections including the full `## Deviations`. The orchestrator writes the Summary in its own words from the deviations file, the final review and the plan Summary. `**Deviations:**` is the focus; the priority order for the 175 words is: design changes, accepted scope drift, owner decisions taken during the run, open non-blocking findings. `**Review focus:**` or `**Security:**` must name every deviation that touches a protected path or came from the security-reviewer. No pasted worker text, no "safe to merge". The orchestrator writes the body to a scratch file and runs `tld plan summary-check <body file> --kind pr --deviations <deviations path>` before `github.pr_create`; exit 1 is fixed, not skipped. A later `github.pr_update` of the body keeps the Summary and runs the check again. `implement` does not check the plan's Summary at start.

### D4. Tests and mutants

See the briefs. Rules that apply to all of them: assert the full stdout, never only the exit code; every exit-1 test also asserts the stdout line; the CLI tests run through `tld_cmd`; the placement tests take the calls from the real playbooks and run them on fixtures; the playbooks' stated limits and labels are compared with the constants of summary.py.

### D5. Mutants

Sixteen mutants for `src/tld/plan/summary.py`, ids SM1 to SM16, each with an `old` text that occurs exactly once in the file: SM1 limit `>` becomes `>=`; SM2 `350` becomes `351`; SM3 the heading is left out of the count; SM4 the count runs to the end of the file; SM5 the section ends at any `#` line; SM6 the fence toggle is removed; SM7 the `\r\n` normalisation is removed; SM8 the duplicate-Summary check `> 1` becomes `> 2`; SM9 the placement check is removed; SM10 the `## Request` exception for `issue` is removed; SM11 label matching ignores case; SM12 the `- ` prefix is dropped; SM13 plan and pr required labels are swapped; SM14 the duplicate-label check is removed; SM15 `clean` no longer cuts to `TEXT_MAX`; SM16 the exit code for problems becomes 0.

## 4. ADRs

None: the profile has no `docs.adr_dir`. The decisions are written into `docs/architecture/design.md` in p3 (fixed limits; placement per kind with the `Closes` lines first; closed label set in a fixed order; `implement` does not check a plan's Summary).

## 5. Manual steps

None. Nothing needs a console, a secret or a device. The owner reviews the pull request, whose Summary is the first thing to read.

## 6. Risks and open questions

- The 175 words may be too few for a run with many deviations (plan 33's deviations file is about 1100 words). A worker sees this as a legitimate `words` failure; it keeps the priority order of D3 and never raises the limit. If real runs hit it often, the limit is the owner's call.
- The rules may be too strict and make agents loop on label errors. Watch the first two plans after the merge.
- Label presence is checkable, quality is not. A useless but well-formed Summary passes; the helper review (D2) and the human catch it.
- `\w` counts underscores and Unicode letters as word characters; that is intended.
- A worker that finds a rule contradictory (for example a fixture that cannot meet both the order rule and a required label) stops with `status=blocked`, and does not change D1.
- Baseline hashes: p2 changes two playbooks, so the eval baseline hashes are refreshed there only. The reason for the commit message: the change adds a section to a plan and a pull request body and cannot change what the stub tasks grade (`make-plan-small` checks the prompt's sections, `make-plan-large` the manifest). If the stub run (`evals/run.py run --agent stub`) fails, stop with `status=blocked`.
- Dogfood: this plan must pass its own check; the final check below runs it.

## Implementation manifest

```yaml
plan_slug: review-summaries
feature_branch: feature/review-summaries
tracking_issue: 36
max_parallel: 1
verify_after_merge:
  - .venv/bin/python -m pytest -q -k summary
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - "`tld plan deviations check --file docs/plans/36/deviations.md --plan docs/plans/36/plan.md --all` exits 0"
  - "`.venv/bin/python cli/tld plan summary-check docs/plans/36/plan.md --kind plan` exits 0"
  - "`.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
  - "`grep -n summary-check CHANGELOG.md` matches a line under Unreleased"
phases:
  - id: p1-summary-check
    title: The summary-check command with tests and mutants
    depends_on: []
    complexity: M
    touches:
      - src/tld/plan/summary.py
      - src/tld/cli.py
      - tests/core/test_plan_summary.py
      - tests/mutation/mutants.yaml
      - tests/core/test_mutants_file.py
    brief: |
      Read first: docs/plans/36/plan.md (Design D1, D4, D5), src/tld/plan/deviations.py, tests/core/test_plan_deviations.py, stacks/python.md, CONTRIBUTING.md (Mutation check).
      Pattern commit to copy for a new plan command: c9eb60c (src/tld/plan/deviations.py, its test, one row in src/tld/cli.py).
      1. Write the failing tests first in tests/core/test_plan_summary.py (the list below), see them fail for the right reason, then implement. Use `tmp_path` files, `capsys`, exact stdout, and `from conftest import tld_cmd` for the CLI tests.
      2. Create src/tld/plan/summary.py exactly as Design D1 specifies: the constants `KINDS`, `MAX_WORDS`, `ORDER`, `REQUIRED`, `NONE_OK`, `TEXT_MAX`; `clean`; `check(text, kind, deviations_text=None)`; `main(argv)` with argparse (`file`, `--kind` required with choices, `--deviations`). Do not import or edit src/tld/plan/deviations.py. Keep the module docstring free of the words `pytest`, `ruff`, `connector` and other words tests/core/test_no_project_words.py forbids. Use no regular expression with nested quantifiers.
      3. Register the command in src/tld/cli.py right after the `("plan", "deviations")` row: `("plan", "summary-check"): ("tld.plan.summary", (), "check the Summary section of a plan, an issue body or a pull request body")`.
      4. Tests in tests/core/test_plan_summary.py, one behaviour each, named for it: exactly 350 words OK and 351 fails (and 175/176 for pr); the heading is counted (349 body words plus the heading fails); the count stops at the next `## `; a 200-word Summary passes plan and fails pr; missing file, a directory and non-UTF-8 bytes give `summary: cannot read` and no exception; an empty Summary gives one line per missing required label; a fenced `## Summary` is not a duplicate; a fenced `## x` inside the Summary does not end it and its words count; a label inside a fence (``` and ~~~) is not a label; CRLF gives the same result as LF; a BOM before the first heading is ignored; Summary after `## Goal` fails placement; `issue` accepts `## Request` then `## Summary` and rejects `## Request`, `## Goal`, `## Summary`; a `>` quoted `## Request`-style heading is ignored; `# Title`, a `>` line and blank lines before the plan Summary are fine, plain prose before it fails; `Closes #1` lines before the pr Summary are fine, other text fails; two real Summary headings fail; `## summary`, `##Summary`, `### Summary`, `## Summary of x` give the near-miss line or the missing line as D1 says, and `## Summary ` with trailing spaces is accepted; duplicate label; wrong-case label gives an unknown line and a missing line; label forms (`- **Use it:** x y z` accepted; `**Use it**: x`, `  **Use it:** x`, `* **Use it:** x` are not labels); `**Use it:**` with no value fails; `Deviations` is rejected in plan and `Use it` in pr, Security and Performance accepted in both, Scope optional in pr and required in plan; out-of-order labels; a one-line Summary with the labels in the middle fails on the missing labels; `None.` accepted for Deviations, Security, Performance and rejected for Scope; placeholders (`TBD`, `see below`, `<x>`) rejected; `<!--` and `<details` rejected; `--deviations` with a bullet and `**Deviations:** None.` fails, with only `- None.` passes, and `--deviations` with `--kind plan` exits 2; a 200000-character line finishes in under 5 seconds (wide margin); an echoed unknown label with ESC, C1 and bidi characters is printed with `?` and a 2000-character label is echoed at exactly `TEXT_MAX` characters; a file with placement, label and word problems prints exactly those lines in the order of D1.
      5. CLI tests through `tld_cmd("plan", "summary-check", ...)` in the same file: valid file gives returncode 0, exact stdout, empty stderr; invalid file gives 1 and the exact lines; missing and non-UTF-8 file give 1, `Traceback` not in stderr; missing `--kind`, `--kind prr` and no FILE give 2; `--help` lists `--kind` and `{plan,issue,pr}`.
      6. Add the sixteen mutants of Design D5 to tests/mutation/mutants.yaml (format: id, file, why, old, new), the `tests:` entry `src/tld/plan/summary.py: [tests/core/test_plan_summary.py]`, and `"src/tld/plan/summary.py"` to `MODULES` in tests/core/test_mutants_file.py. Each `old` text must occur exactly once in summary.py; run `.venv/bin/python -m pytest tests/core/test_mutants_file.py -q`, then `.venv/bin/python tests/mutation/run_mutants.py --only SM1 SM2 SM3 SM4 SM5 SM6 SM7 SM8 SM9 SM10 SM11 SM12 SM13 SM14 SM15 SM16` and make every mutant die by adding the missing test, never by weakening a mutant.
      7. Stop with `status=blocked` if two rules of D1 contradict each other on a case you meet; do not decide it yourself.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_plan_summary.py -q --cov=tld.plan.summary --cov-branch --cov-report=term-missing reports 100%"
      - ".venv/bin/python -m pytest tests/core/test_mutants_file.py tests/core/test_contracts.py tests/core/test_no_project_words.py -q passes"
      - ".venv/bin/python tests/mutation/run_mutants.py --only SM1 SM2 SM3 SM4 SM5 SM6 SM7 SM8 SM9 SM10 SM11 SM12 SM13 SM14 SM15 SM16 exits 0"
      - ".venv/bin/python cli/tld plan summary-check docs/plans/36/plan.md --kind plan exits 0 and prints summary: OK"
      - ".venv/bin/python cli/tld plan summary-check --help lists --kind and --deviations"
  - id: p2-playbooks
    title: Call the check from make-plan and implement
    depends_on: [p1-summary-check]
    complexity: M
    touches:
      - playbooks/make-plan.md
      - playbooks/implement.md
      - tests/core/test_summary_placement.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/36/plan.md (Design D2, D3, D4), playbooks/make-plan.md, playbooks/implement.md, tests/core/test_contracts.py, tests/core/test_plan_active.py (imports from test_contracts), CONTRIBUTING.md (Evals).
      1. Write the failing tests first in tests/core/test_summary_placement.py: `from conftest import ROOT, tld_cmd`, `from test_contracts import tld_calls` and `from tld.plan import summary`. Helper `summary_calls(path)` returns the `tld_calls(path)` entries with group `plan` and command `summary-check`, each with its `--kind` value (regex `--kind (\S+)` on the rest). Tests: (a) make-plan.md has calls with kinds exactly `{"plan", "issue", "pr"}` and every kind is in `summary.KINDS`; (b) implement.md has exactly one kind, `pr`, and its call carries `--deviations`; (c) each call, with its `X` placeholders replaced by valid fixture files written in `tmp_path` (the first X the document, the second the deviations file), run through `tld_cmd`, exits 0 with `summary: OK`; (d) in implement.md the text of `## 6. Finishing` has `summary-check` before `github.pr_create`; (e) in make-plan.md the `--kind plan` call is before `validate-manifest` in the section "## 4. Review before you push" and the `--kind issue` call is before `github.issue_update` in "## 5. Commit, push and hand over"; (f) the helper rejects a temp playbook that uses `--kind prr` (so test (a) can fail); (g) every label in `summary.ORDER["plan"]` and `summary.ORDER["pr"]` appears in make-plan.md as `**<Label>:**`, and the numbers `350` and `175` appear in make-plan.md and `175` in implement.md next to `Summary`.
      2. Edit playbooks/make-plan.md exactly per Design D2: section 2 gets the unnumbered `## Summary` rule (placed before the numbered list of sections, and the list of sections says the Summary comes first); section 4 gets the helper-review additions and the `tld plan summary-check <plan file> --kind plan` call before `tld plan validate-manifest`; section 5 step 2 gets `## Summary` in the heading list after `## Request`, the blockquote rule for an ask with its own `## ` lines, and the scratch-file check `tld plan summary-check <issue body file> --kind issue` before `github.issue_update`; the small-scope section gets the issue Summary and the Finish-step text for the worker (pull request Summary, `tld plan summary-check <body file> --kind pr`). Keep playbooks free of tool and model names and of the forbidden project words.
      3. Edit playbooks/implement.md 6.3 exactly per Design D3: the body order, the priority order of the 175 words, the Review focus or Security rule, the own-words rule, the scratch-file call `tld plan summary-check <body file> --kind pr --deviations <deviations path>` before `github.pr_create`, and the rule that a later body rewrite keeps the Summary and runs the check again.
      4. Run `.venv/bin/python -m pytest tests -q`. The baseline test will fail: run `.venv/bin/python evals/run.py run --agent stub --repeats 1 --require-pass` (must pass), then `.venv/bin/python evals/run.py baseline --refresh-hashes`, and put the reason in the commit message: the change adds a section to a plan and a pull request body and cannot change what the stub tasks grade. If the stub run fails, stop with `status=blocked`.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_summary_placement.py -q passes"
      - ".venv/bin/python -m pytest tests/core/test_contracts.py tests/core/test_evals_baseline.py tests/core/test_no_project_words.py -q passes"
      - ".venv/bin/python evals/run.py run --agent stub --repeats 1 --require-pass exits 0"
      - "grep -c 'plan summary-check' playbooks/make-plan.md prints at least 3"
      - "grep -c 'plan summary-check' playbooks/implement.md prints at least 1"
  - id: p3-docs-retire
    title: Reference, design paragraph and changelog
    depends_on: [p2-playbooks]
    complexity: S
    touches:
      - docs/reference/cli.md
      - docs/architecture/design.md
      - CHANGELOG.md
      - tests/core/test_cli_reference.py
    brief: |
      Read first: docs/plans/36/plan.md (Design D1, D3, section 4), docs/reference/cli.md, docs/architecture/design.md (Plans and manifests), CHANGELOG.md, docs/guides/docs-index.md.
      1. Add `tests/core/test_cli_reference.py` with one test, `test_cli_reference_lists_every_command`: every `f"tld {group} {command}"` of `tld.cli.COMMANDS` occurs in docs/reference/cli.md (it passes before the row exists only for existing commands, so first add the row in step 2 and see it fail without it by temporarily removing it).
      2. In docs/reference/cli.md add, after the `tld plan deviations` row, the row `tld plan summary-check FILE --kind plan|issue|pr [--deviations FILE]` | `tld.plan.summary` | checks the `## Summary` of a plan, a tracking-issue body or a pull-request body: placement, labels in order, word limit 350 / 350 / 175, hidden markup, and with `--deviations` that `None.` is not claimed over a non-empty deviations file; prints `summary: <problem>` lines (exit 1) or `summary: OK (<n> words)`.
      3. In docs/architecture/design.md, section "Plans and manifests", add one paragraph after the deviations paragraph stating the four decisions of plan section 4 and that the Summary is the first thing a human reads in a plan, the tracking issue and the pull request.
      4. In CHANGELOG.md under `## [Unreleased]` / `### Added` add one entry: every plan, its tracking issue and the feature pull request now start with a short checked `## Summary` (350 words for plans, 175 for pull requests, about the deviations), new `tld plan summary-check`; mention that small-scope runs follow the same rules. Do not open a version heading.
      5. Run `.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0. No doc is added, moved or deleted, so no index row changes.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_cli_reference.py tests/core/test_docs_index.py tests/core/test_docs_links.py -q passes"
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - "grep -n 'summary-check' CHANGELOG.md docs/reference/cli.md docs/architecture/design.md matches in all three files"
```
