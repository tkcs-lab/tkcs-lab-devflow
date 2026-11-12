# The review flow: `/review` → decisions → `/make-plan`

`/review` is a deep review of a repository, part of one, or a pull request (the procedure is
[playbooks/review.md](../../playbooks/review.md)). Its dimensions are roles, and it decides, finding by finding, what
should be fixed. Its output is a review document that `/make-plan` turns into a plan.

```
/review [scope]  ──►  review/<slug> branch: <plan_dir>/<slug>-review.md
                       │
                       ├─ open items? ──► one ask on the board (plan | issue | drop per item)
                       │                    └─ you answer, then message the session
                       │                         └─ review updated, issues created
                       ▼
/make-plan <review URL>  ──►  feature branch  ──►  /implement
```

## Running it

| Arguments | Reviews |
|---|---|
| none | the whole repository at `origin/<main>` |
| paths or globs | those paths, with whatever they call where it matters |
| `#<n>` or a PR URL | the PR's diff, in the context of the files it touches |
| a branch name | the branch's diff against `<main>` |
| `apply <review URL>` | no review: reads the answers of the decisions ask and applies them (for a new session) |

It needs the project profile (`.tld/toolkit.yaml`), like every tld command. It runs at the `strong` level
and runs its roles and verifiers at `models.reviewer` (default `strong`), so a whole-repository review of a
large codebase takes a while and a fair number of tokens.

## What it checks

Each dimension is one role with its checklist (C11), so a finding has exactly one id:

| Dimension | Id | Role | Checklist | In short |
|---|---|---|---|---|
| Security | `SEC-n` | `security-reviewer` | `checklists/security.md` | threat model, every entry point traced, CI and automation, secrets across the git history, defaults, security docs |
| Dependencies | `DEP-n` | `dependency-auditor` | `checklists/security.md` (supply chain) | only when the profile requires the role at `review`: advisories, pins, new dependencies |
| Tests | `TST-n` | `test-architect` | `checklists/test.md` | suites per level (unit, integration, e2e) and whether CI runs them, measured or estimated coverage, a behaviour-to-test map, tests that cannot fail, disabled and flaky tests |
| Documentation | `DOC-n` | `tech-writer` | `checklists/docs.md` | accuracy and validity against the code (commands run, links checked), completeness, consistency, clarity, readability, staleness |
| Website | `WEB-n` | `website-maintainer` | `checklists/docs.md` | only when the repository holds one: builds, navigation, drift from the repository docs, basics a visitor relies on, its security config |

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

## The decisions ask

When there are open items, the review posts one ask to the status board: one question per item (its title and
summary, the recommendation first, the choices **plan**, **issue** and **drop**) and a notes field. You answer in the
board's page after logging in, then tell the session (any message) that you answered. It then:

- moves "plan" items into "Findings to fix" (your note goes with them);
- moves "drop" items into "Not doing";
- creates an issue for each "issue" item, or links an open issue that already covers it;
- sets the review's status to `ready-for-plan` and gives you the `/make-plan` line.

When the board cannot be reached, the questions go to the tracking issue as a comment that mentions you, and only a
reply by an owner or collaborator counts. If the session has ended, run `/review apply <review URL>` in a new one.

## The review document

`<plan_dir>/<slug>-review.md` on `review/<slug>`, with a YAML header (`review_slug`, `repository`,
`commit`, `scope`, `status`, `decisions_ask`) and these sections: Summary, What was reviewed,
Findings to fix (with Suggested grouping), Issues created, Not doing, Open decisions, Rejected on
verification. Each finding has where, evidence, why, fix, an acceptance check, cost, confidence and
who decided it.

`/make-plan` accepts its URL only when `status` is `ready-for-plan`, plans exactly the findings to
fix, re-checks each against the current `<main>`, and puts each finding id into the acceptance of the
phase that fixes it. The review branch is never merged; delete it once the plan has landed.
