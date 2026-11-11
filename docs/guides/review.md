# The review flow: `/review` → decisions → `/make-plan`

`/review` is a deep review of a repository, part of one, or a pull request. It covers three
dimensions and decides, finding by finding, what should be fixed. Its output is a review document
that `/make-plan` turns into a plan.

```
/review [scope]  ──►  review/<slug> branch: <plan_dir>/<slug>-review.md
                       │
                       ├─ open items? ──► decisions page (add to plan | create issue | drop)
                       │                    └─ you tell the session you are done
                       │                         └─ review updated, issues created
                       ▼
/make-plan <review URL>  ──►  plan/<slug>  ──►  /implement
```

## Running it

| Arguments | Reviews |
|---|---|
| none | the whole repository at `origin/<main>` |
| paths or globs | those paths, with whatever they call where it matters |
| `#<n>` or a PR URL | the PR's diff, in the context of the files it touches |
| a branch name | the branch's diff against `<main>` |
| `apply <review URL>` | no review: reads the decisions from the page and applies them (for a new session) |

It needs the project profile (`.claude/toolkit.yaml`), like every devflow command. It runs on Opus
and starts Opus subagents for the dimensions and for verification, so a whole-repository review of a
large codebase takes a while and a fair number of tokens.

## What it checks

| Dimension | Id | Skill | In short |
|---|---|---|---|
| Security | `SEC-n` | `secure-code-review` | threat model, every entry point traced, CI and automation, secrets across the git history, dependencies, defaults, security docs |
| Tests | `TST-n` | `test-review` | suites per level (unit, integration, e2e) and whether CI runs them, measured or estimated coverage, a behaviour-to-test map, tests that cannot fail, disabled and flaky tests |
| Documentation | `DOC-n` | `docs-review` | accuracy and validity against the code (commands run, links checked), completeness, consistency, clarity, readability, staleness |
| Website | `WEB-n` | `docs-review` | only when the repository holds one: builds, navigation, drift from the repository docs, basics a visitor relies on, its security config |

It runs the project's gate (`verify.dod`) and the other suites it finds, reads coverage reports
the gate produces, and never adds tooling to the repository. It never deploys, publishes, or writes
to an outside service.

## How it decides

Every candidate finding is verified before it is kept: the evidence is re-read at the reviewed
commit, and the path from a real entry point or reader to the harm is traced. What does not hold is
listed under "Rejected on verification", so a later run does not raise it again.

Each kept finding then gets one decision:

- **fix**: goes to "Findings to fix", the input for `/make-plan`. Realistic security findings, wrong
  or broken documentation, missing documentation people need, missing tests for what matters,
  tests that cannot fail, suites nothing runs.
- **not doing**: recorded with the reason. Far-fetched paths, fixes that cost more than they
  prevent, preferences no project rule backs, things an accepted decision covers, things already
  tracked in an issue or PR.
- **open**: yours to decide, with the reviewer's recommendation. Product or policy calls, large
  investments the project has not committed to (such as an e2e harness where there is none), risks
  you may knowingly accept, findings only you can confirm.

## The decisions page

When there are open items, the review publishes a page with one row per item: severity, where, why,
the recommendation, three choices (**Add to plan**, **Create issue**, **Drop**) and an optional note.
Choices are saved as you make them. Press **Finish** when all are decided, then tell the review
session you are done. It then:

- moves "add to plan" items into "Findings to fix" (your note goes with them);
- moves "drop" items into "Not doing";
- creates an issue for each "create issue" item, or links an open issue that already covers it;
- marks the page as applied and shows the issue links on it;
- sets the review's status to `ready-for-plan` and gives you the `/make-plan` line.

If the page cannot save (for example, you opened it somewhere the store is not available), it keeps
your choices in the browser and offers **Copy as text** to paste into the session. If the session
cannot publish pages at all, it asks the same questions in chat. If the session has ended, run
`/review apply <review URL>` in a new one.

## The review document

`<plan_dir>/<slug>-review.md` on `review/<slug>`, with a YAML header (`review_slug`, `repository`,
`commit`, `scope`, `status`, `decisions_artifact`) and these sections: Summary, What was reviewed,
Findings to fix (with Suggested grouping), Issues created, Not doing, Open decisions, Rejected on
verification. Each finding has where, evidence, why, fix, an acceptance check, cost, confidence and
who decided it.

`/make-plan` accepts its URL only when `status` is `ready-for-plan`, plans exactly the findings to
fix, re-checks each against the current `<main>`, and puts each finding id into the acceptance of the
phase that fixes it. The review branch is never merged; delete it once the plan has landed.
