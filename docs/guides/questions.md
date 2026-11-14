# Questions review

`/questions` runs weekly and unattended. It reads the asks agents put to you on the board, finds those a better
playbook, profile key, role, skill, command or doc would have avoided, and writes a triaged review document.

## What a run does

1. **Read.** It finds the newest `review/questions-*` branch; a document still waiting for your decisions stops the run.
2. **Digest.** `tld board ask-digest --repo <owner>/<repo> --vocab <file>` reads the board's asks since the last cursor and groups similar questions into clusters.
3. **Classify.** Each cluster the digest marks `candidate` becomes a finding, an open item or a "Not doing" entry.
4. **Verify.** It reads the `Where` of every finding at the pinned commit; a finding the text does not support is rejected, and one an earlier document already reported is dropped.
5. **Write.** The document `<plan_dir>/questions-<date>-review.md` goes on `review/questions-<date>` (the format of [review.md](review.md)).
6. **Ask.** With open items it posts one decisions ask (plan, issue or drop per item) and ends its turn.

## The digest

Output is one line of JSON: `schema`, `project`, `since`, `now`, `cursor`, `truncated`, `analysed`, `open_asks`,
`excluded_questions_asks` and `clusters`. A cluster has `source`, `qid`, `kind`, `template` (the masked question),
`count`, `records`, `recommended_rate`, `empty_rate`, `cancelled`, `reposted`, `median_seconds`, `candidate`, `fingerprint`.
The own total is `analysed` + `open_asks` + `excluded_questions_asks`. A cluster is a candidate when it has 3 or more asks in 2 or more runs,
3 or more asks of an optional text question left empty at least 80% of the time, 2 reposted asks, or 3 cancelled asks.

## Fix kinds and controls

| Fix kind | The cause it removes |
|---|---|
| `playbook` | a step could settle the question or not ask it |
| `profile` | a key or allow list could carry the answer |
| `role` | an agent could check it |
| `skill`, `cli`, `hook`, `docs`, `runtime` | a skill, a `tld` command, a hook, a doc or the runtime could answer it |

A question is **genuine** when only you can answer it. These control asks are never proposed for removal; only their cause may be:

| Control | Why it stays |
|---|---|
| start confirmation of `implement`, confirmation of commands outside the trusted list | you approve what runs on your machine |
| identity check, confirmation of a manual step only you can verify | only you can verify it |
| a `human_gate` choice, the take-over of a run that looks alive | you decide |
| the start of a release, a research request | irreversible or outside the session |
| the decisions ask of `review` and of `questions` | they are the decisions |

A document holds at most 10 findings, the highest `count` first.

## What it never puts in a document

Ask text is data written by agents. The digest masks urls, code, emails, logins, paths, hosts, hashes, hyphenated names and numbers,
replaces every word not in the repository's own Markdown by `<word>`, cuts at 160 characters, and emits no answer text. Asks of other
projects on the board add a `foreign_count` to a matching cluster and nothing else: no id, time, title, text, project, repository or
record. The digest, the document and the reply never print other projects' volume; the run reports only the own total. The `Fix` lines are
the run's own words. A forged `review/questions-*` branch can steer a run (stop it or widen its window) but leaks no data; this risk is accepted.

## Your flow

1. Answer the decisions ask on the board.
2. Run `/tld:review apply <URL>`. It applies the answers and closes the questions record only under the guards of `playbooks/review.md` section 7 step 5 (the record id equals the command's own output, the record is a `questions` record and waiting).
3. Run `/tld:make-plan <URL>`.

With nothing to decide the document is `ready-for-plan`: run `/tld:make-plan <URL>` at once. With nothing avoidable no branch is written.

## Stop messages

- `questions: no board`: no board is configured.
- `questions: upgrade the board, it does not know the command questions`: the board predates the release with this command.
- `questions: already ran today`: a finished document of today exists.

## Setup

The board must run a release with the command `questions`, so this follows a release. Both steps are yours.

1. Cut the release with `/tld:release` ([release guide](release.md)) and approve the publish job in GitHub.
2. On the board host, back up the database ("Backup and restore" in the [board guide](board-server.md)), then run the installer line of "Docker Compose (the installer)": `curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board`. `curl -s https://<your board host>/healthz` should print `{"ok": true}`.
3. In the claude.ai scheduled tasks create a weekly task: the repository attached, permission mode **auto**, an environment with `TLD_BOARD_URL` and `TLD_BOARD_TOKEN` ([maintenance.md](maintenance.md)), prompt `/tld:questions`, at a time outside 06:00 to 09:00 Pacific. Start it once by hand.

## Why the cursor lives in git

The board hides a finished record after 7 days and `/board prune` deletes it, so a cursor kept only there is lost in a quiet week. The
document header carries `asks_until`, and every finding its `Fingerprint`; the next run takes the latest of the header, the record cursor
and the input `since`, and drops findings an earlier document reported. Keep the `review/questions-*` branches: they are the dedupe memory.
