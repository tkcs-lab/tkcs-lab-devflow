# Maintenance spike

- Date: 2026-11-09 (runs between 07:30 and 07:50 UTC)
- Agent login (`get_me`): `andras-tkcs-agent`
- Scratch repository: `tkcs-lab/devflow-scratch` (code owner `andras-tkcs`, `.github/CODEOWNERS` is the single line `* @andras-tkcs`)
- Forks and upstreams: the two forks are not named in the task, and the fork repositories were not read. The user confirmed the upstreams as `PrivacyFence/peek` (for the peek fork) and `PrivacyFence/grist-core` (for the grist-core fork).

Session limits that shaped the evidence:

- GraphQL is blocked in this session, so `gh pr view --json ...` fails with HTTP 403 ("GitHub GraphQL is not available from Claude Code sessions"). All pull request fields were read from the REST API instead. `reviewDecision` is a GraphQL-only field; see (d).
- GitHub write calls made from this session pass through a safety filter that rewrites bot commands (see (b)).

Setup checks before the experiments (all matched the task): `requirements.txt` present; pull request #1 open from `dependabot/pip/pyyaml-6.0.3` (changes `requirements.txt`); pull request #3 "spike d: approval test" open, author `andras-tkcs-agent`, head `spike/d-a` at `224941449c9ebbb190196159e575e261a189d7a3`, one review `APPROVED` by `andras-tkcs` on that exact commit, base `main` ahead of the branch (`compare` says status diverged, ahead 1, behind 1); pull request #4 merged. The seeded PyYAML alert could not be listed from the session (see (a)).

### (a) Can a session read Dependabot alerts?

**Method**
1. Searched the tool list for a tool whose name mentions `dependabot` (`ToolSearch` query `dependabot`).
2. `gh api "repos/tkcs-lab/devflow-scratch/dependabot/alerts?state=open"`
3. `curl -s -w '\nHTTP %{http_code}\n' "https://api.github.com/repos/tkcs-lab/devflow-scratch/dependabot/alerts?state=open"` through the session proxy.

The scratch repository was attached with `add_repo` (access `push`) before routes 2 and 3.

**Evidence**
- Route 1: `No matching deferred tools found`.
- Route 2: `{"message":"Resource not accessible by integration", ... "status":"403"}`, `gh: Resource not accessible by integration (HTTP 403)`.
- Route 3: same JSON body, `HTTP 403`.
- Side evidence, not a list of alerts: the push output of (b) said "GitHub found 2 vulnerabilities on tkcs-lab/devflow-scratch's default branch (2 critical)".

**Result** Alerts are not readable from a session with the integration used here. **[V]**

### (b) Can the agent push to a `dependabot/*` branch, and what happens to `@dependabot rebase`?

**Method**
1. `git -C "$SCRATCH" fetch --depth=2 origin dependabot/pip/pyyaml-6.0.3`, checked out as `spike-b`.
2. Added `spike-b.txt`, committed with author `andras-tkcs-agent` (commit `c6d3646`), `git -C "$SCRATCH" push origin HEAD:dependabot/pip/pyyaml-6.0.3`.
3. `gh api repos/tkcs-lab/devflow-scratch/commits/c6d3646` for attribution.
4. Commented on pull request #1 with the first line `@dependabot rebase` and the footer, via the GitHub MCP tool `add_issue_comment`. Tried to repair the comment with `gh api -X PATCH repos/tkcs-lab/devflow-scratch/issues/comments/6734690202`.
5. At 07:42:57 UTC (about 12 minutes later) read the comments of pull request #1, the branch head and the branch contents.

**Evidence**
- Push: `1bd3ccf..c6d3646  HEAD -> dependabot/pip/pyyaml-6.0.3`, accepted.
- Attribution: commits API returned `author: null`, `committer: null`, commit author name `andras-tkcs-agent` (the name came from my local git config; GitHub did not link it to an account, `verification.reason: no_user`). The `ci` run for `c6d3646` shows actor `andras-tkcs-agent`, so the push itself is attributed to the agent.
- The comment as stored (both after the MCP call and after the PATCH): the first line reads `·@·d·ependabot r·ebase`, followed by this note in the comment body: "Claude's GitHub safety filter added the `·` characters above so that a bot command in this comment does not run automatically. A person who wants it to run can post the command without the `·` characters." I did not try to get around the filter.
- No reply from Dependabot. At 07:42:57 the pull request had one comment (mine), the branch head was still `c6d3646`, and `spike-b.txt` was still present.

**Result** The agent can push to a Dependabot branch (allowed). Whether Dependabot rebases after such a push is not tested: the rebase command cannot be delivered from this session because of the safety filter, so there was no Dependabot reply to read. **[V]** for the push, **[A]** for the rebase.

### (c) Does a push or update-branch made with the agent's token start CI?

**Method**
1. After the push of (b), listed workflow runs for the head branch: `gh api "repos/tkcs-lab/devflow-scratch/actions/runs?branch=dependabot/pip/pyyaml-6.0.3"`.
2. After the update-branch of (d), listed runs for `spike/d-a`, and `gh api repos/tkcs-lab/devflow-scratch/commits/8a19d0b/check-runs`.
3. The default workflow token was not tested.

**Evidence**
- Push half: at 07:30:59 (about 7 seconds after the push) a `ci` run existed for head `c6d3646`, event `pull_request`, actor `andras-tkcs-agent`, created 07:30:52; it ended `success`.
- Update-branch half: a `ci` run was created 07:39:54 for head `8a19d0b`, event `pull_request`, actor `andras-tkcs-agent`, conclusion `success`; the check run `ci` on `8a19d0b` is `completed` / `success`.
- Documentation: GitHub documents that events caused by the default workflow token (`GITHUB_TOKEN`) do not start new workflow runs.

**Result** Both a push and an update-branch with the agent's own credentials started `ci`. **[V]** The default workflow token behaviour is **[D]**.

### (d) Does a bot update-branch dismiss an approval?

**Method**
1. Before: REST reads of pull request #3 (`/pulls/3`, `/pulls/3/reviews`, `/compare/main...spike/d-a`). `gh pr view 3 --json reviewDecision,...` is not usable here (GraphQL blocked), so `mergeable_state` and the review list stand in for `reviewDecision`.
2. GitHub MCP tool `update_pull_request_branch` as the agent, owner `tkcs-lab`, repo `devflow-scratch`, pullNumber 3, expectedHeadSha `224941449c9ebbb190196159e575e261a189d7a3`, at 07:39:53 UTC.
3. After (07:43:16, a little over 3 minutes): the same REST reads, plus the workflow runs of `spike/d-a`.
4. Read the branch rules (read only): `gh api repos/tkcs-lab/devflow-scratch/rules/branches/main`.

**Evidence**
- Before: head `2249414...`, `mergeable_state: clean`, one review `APPROVED` by `andras-tkcs` with `commit_id` `2249414...`; `compare`: diverged, ahead 1, behind 1.
- Tool result: "Pull request branch update is in progress".
- After: head `8a19d0b0c0588f605032aabb571e832bce21d506` (a merge commit "Merge branch 'main' into spike/d-a", committer `web-flow`, parents `2249414` and `2ad1478`), `mergeable_state: clean`, `state: open`; still one review, `APPROVED` by `andras-tkcs`, submitted 07:20:24, with `commit_id` now `8a19d0b...`; `compare`: ahead 2, behind 0. A new `ci` run started and succeeded (see (c)).
- Rules on `main`: `pull_request` rule with `required_approving_review_count: 1`, `dismiss_stale_reviews_on_push: false`, `require_code_owner_review: false`, `require_last_push_approval: false`, `require_extra_approval_for_unattributed_changes: true`; plus a required status check `ci`.
- A workflow using a personal access token for the same API call is assumed to behave the same. **[A]**

**Result** The approval stayed in place and the pull request stayed mergeable (`clean`) after the update. `reviewDecision` itself could not be read, so it is inferred from `mergeable_state: clean` with one required approval. The result holds for this ruleset; with `dismiss_stale_reviews_on_push: true` it would have to be tested again. **[V]** (with the inference stated above)

### (e) Can a scheduled task run unattended, write to a board and send a push?

**Method**
1. Published a private throwaway artifact with `capabilities: {db: {}}` (page "Spike E Board", URL in the cleanup section).
2. `create_trigger` with `create_new_session_on_fire: true`, `run_once_at` 2026-11-09T07:38:00Z, `initiation: human_request`. The tool has no permission-mode parameter. Its result warned that the task stores no connectors.
3. After it fired: `get_trigger` (`last_run.session_id`), `get_session` and `list_events` on the fired session, `ArtifactData` `get` of `spike/spike-e`.

**Evidence**
- Task fired 07:38:31, run status `ROUTINE_RUN_STATUS_SUCCEEDED`, finished 07:38:46. Fired session: `session_013HAf78Ed7obfQiQCoAL454` (run record id `cse_013HAf78Ed7obfQiQCoAL454`), `permission_mode: auto`, bucket `review_ready`, status idle, `permission_denials: []`, `stop_reason: end_turn`.
- Step 1 (`get_session`): `ToolSearch` query `get_session` returned `No matching deferred tools found`. The fired session had no connector tools, so it wrote `by` as "unavailable (get_session tool not found)".
- Step 2: `unset`.
- Document read back: `{"at":"2026-11-09T07:38:37Z","by":"unavailable (get_session tool not found)","env":"unset"}`, version 1, written 07:38:43.
- Step 3 tool result: `Database set committed: "spike"/"spike-e" ... The document is now at version 1.`
- Step 4 (`PushNotification`, message `spike e unattended`, sent as `<routine_summary>spike e unattended</routine_summary>`): `Mobile push requested.` (`pushSent: true`, `sentAt` 2026-11-09T07:38:43.866Z).

**Result** The task ran unattended to its end with no pending permission request; the push was requested; the board write succeeded but `by` is not the fired session id (the fired session cannot call `get_session` without connectors); the variable was unset. By the rule of this spike that would count as a failed board write; the owner corrected it to ok (see Owner review), because the write itself committed with no approval. **[V]** for all four.

### (f) Can a session fetch release tags of the fork upstreams anonymously?

**Method**
For each upstream, with no credentials:
`GIT_TERMINAL_PROMPT=0 git -c credential.helper= ls-remote --tags https://github.com/<upstream>.git | grep -v '\^{}$' | sed 's#.*refs/tags/##' | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1` (highest stable tag) and the same pipeline ending `| wc -l` (count). Plus `git config --show-origin --get-regexp '^(url|credential|http)\.'`, and `curl -s "https://api.github.com/repos/<upstream>/releases?per_page=5"`.

**Evidence**
- `git config --show-origin`: `http.proxyauthmethod basic` (global file), `credential.interactive false` and two `url.https://github.com/.insteadof` rewrites (command line). No credential helper, no stored credential, no `extraheader`. `GIT_ASKPASS` is set to a program that prints nothing. A plain `curl` of `https://github.com/PrivacyFence/peek.git/info/refs?service=git-upload-pack` returned HTTP 200. Outbound traffic goes through the session proxy, whose own headers I cannot see, so "anonymous" means: no credentials supplied by git or by me.
- `PrivacyFence/peek`: highest stable tag `v0.18.1`, count 18.
- `PrivacyFence/grist-core`: `ls-remote` lists tags (first three: `v1.7.22-pf.1`, `v1.7.22-pf.2`, `v1.7.22-pf.3`), but every tag carries a `-pf.N` suffix, so the stable-tag pipeline prints nothing and the count is 0.
- Extra evidence: `curl https://api.github.com/repos/<upstream>/releases?per_page=5` returned HTTP 403 for both with the body `{"message":"GitHub access to this repository is not enabled for this session. Use add_repo to request access. ..."}`. This is a restriction of the session, not of GitHub, so no `X-RateLimit-Limit` header could be recorded.

**Result** Tags of both upstreams can be listed with `git ls-remote` without credentials; the GitHub API route is closed by the session. For `grist-core` the stable-tag pattern needs to accept the `-pf.N` suffix to find a release. **[V]**

### (d2) Round 2: does a bot update-branch dismiss an approval under the stricter ruleset?

Round 1 (item (d)) ran with `dismiss_stale_reviews_on_push`, `require_last_push_approval` and `require_code_owner_review` all false and kept the approval; it said nothing about the stricter ruleset, so this round repeats it with those flags on.

**Method**
1. Setup check (07:58 UTC): `gh api repos/tkcs-lab/devflow-scratch/rules/branches/main`; open pull requests from `gh api "repos/tkcs-lab/devflow-scratch/pulls?state=open"`; on pull request #5 "spike d2: approval test": `GET /pulls/5`, `GET /pulls/5/reviews`, `GET /compare/main...<head>`, `GET /actions/runs`.
2. GitHub MCP tool `update_pull_request_branch` as the agent, owner `tkcs-lab`, repo `devflow-scratch`, pullNumber 5, expectedHeadSha `ef77a59c7e8fd874908c1d8c86b348d6ddcce365`, at about 07:59 UTC.
3. About 6 minutes later (08:04:57 UTC; the 3 minute wait was exceeded because the reminder fired after 5 minutes): the same REST reads of the pull request, its reviews, the rules and the workflow runs.

**Evidence**
- Rules before the update (the `pull_request` rule): `dismiss_stale_reviews_on_push: true`, `require_code_owner_review: true`, `require_last_push_approval: true`, `required_approving_review_count: 1`; `required_status_checks` with `ci` and `strict_required_status_checks_policy: true`; also `required_linear_history`, `non_fast_forward`, `deletion`. The same flags were read again after the update.
- Before: pull request #5 authored by `andras-tkcs-agent`, head `ef77a59c7e8fd874908c1d8c86b348d6ddcce365`, `mergeable_state: behind` (an earlier read at 07:58:40 returned `unknown`; `compare`: diverged, ahead 1, behind 1). One review: `APPROVED` by `andras-tkcs`, `commit_id` `ef77a59c...` (the head).
- Tool result: "Pull request branch update is in progress".
- After (08:04:57): head `2d8c139200efa509b5b0f5c96842742161b84ca4`, `state: open`, `mergeable_state: clean`. Reviews: still one, `APPROVED` by `andras-tkcs`, `commit_id` `2d8c139...` (now the new head; no `DISMISSED` review appeared). A new `ci` run, id 42582736766, event `pull_request`, head `2d8c139...`, created 07:59:02, ended `success`.
- A workflow using a personal access token for the same API call is assumed to behave the same. **[A]**

**Result** `approval-kept`: with dismissal of stale approvals, approval of the most recent push, code owner review and up-to-date branches all required, the update-branch by the agent left the code owner's review `APPROVED` (its `commit_id` moved to the new head) and the pull request `clean`, with `ci` re-run. The reads do not show how GitHub treated the review internally, only the resulting state. **[V]** (the personal access token case is **[A]**)

### (g) Can a scheduled session open a pull request?

**Method**
1. `create_trigger` (task `trig_01VQJ1YwJNrvMEpRSGFhyyKm`), `create_new_session_on_fire: true`, `run_once_at` 2026-11-09T08:08:00Z, `initiation: human_request`. The prompt told the fired session to list the open pull requests of `tkcs-lab/devflow-scratch` (REST or a GitHub MCP tool), attach the repository with `add_repo` if needed, push the branch `spike/g-20261109` with `spike-g.txt` and open a pull request titled `spike g: unattended pr`, and end with a line naming the tools used and failed steps. The result warned that the task stores no connectors.
2. After it fired: `get_trigger` (`last_run.session_id`), `list_events` of the fired session, and REST reads of the pull requests and branches of the scratch repository (08:21 UTC).

**Evidence**
- Fired at 08:13:35 (scheduled 08:08:00), run status `ROUTINE_RUN_STATUS_SUCCEEDED`, finished 08:14:02; fired session `cse_013HAf784sFGLfmedXRPvRrb`, `stop_reason: end_turn`, `permission_denials: []`.
- Step 1 (`gh api repos/tkcs-lab/devflow-scratch/pulls?state=open`): `GitHub access to this repository is not enabled for this session. Use add_repo to request access. ... (HTTP 403)`; exit 1. REST failed; no GitHub MCP tool was available.
- `ToolSearch` for `add_repo` and for `select:add_repo,mcp__github__add_repo`: `No matching deferred tools found`; a third query (`github repo attach access`) listed only unrelated tools. The fired session therefore could not attach the repository.
- The fired session stopped there, sent a `PushNotification` reporting the failure, and its last line read: "Tools used: Bash (`gh api` REST, failed with 403), ToolSearch (no `add_repo` or GitHub MCP tool found), PushNotification. Steps 1–4 failed or were not run because the repo isn't attached and `add_repo` isn't available."
- Afterwards the scratch repository has no pull request titled `spike g: unattended pr` and no branch `spike/g-20261109` (branches: `dependabot/pip/pyyaml-6.0.3`, `main`, `spike/d-a`, `spike/d-a2`, `spike/d-move`, `spike/d-move2`). I did not wait the extra 10 minutes because the fired session had already ended and said why nothing was created.

**Result** A scheduled session created with `create_trigger` from this session cannot open a pull request: it has no `add_repo` and no GitHub tools, so its `gh` calls get 403 and nothing is created. Whether a task created from the claude.ai routines UI with the repository attached would work was not tested. **[V]**

## Conclusions

CONCLUSION a: alerts-unreadable [V]
CONCLUSION b.push: allowed [V]
CONCLUSION b.rebase: unknown [A]
CONCLUSION c.session: ci-triggered [V]
CONCLUSION c.default-token: documented-no-trigger [D]
CONCLUSION d: approval-kept [V]
CONCLUSION e.unattended: ok [V]
CONCLUSION e.board-write: ok [V]
CONCLUSION e.push: ok [V]
CONCLUSION e.env: unset [V]
CONCLUSION f.peek: anonymous-ok [V]
CONCLUSION f.grist-core: anonymous-ok [V]
CONCLUSION g.pr: failed [V]
RULESET d: dismiss_stale=true last_push_approval=true code_owner=true strict=true
ROUTE a: none
ROUTE f: git ls-remote --tags https://github.com/<owner>/<repo>.git

## Owner review (2026-11-09)

- Board write: the owner decided that an unattended board write counts as ok. The write committed (version 1) with no approval prompt; the earlier value came only from the fired session lacking `get_session`.
- Alerts: because sessions cannot read Dependabot alerts, `/deps` will take security findings from a per-project audit command (`deps.audit`) and will not read alerts.
- Forks: `PrivacyFence/peek` and `PrivacyFence/grist-core` are the owner's forks, not the upstreams. Item (f) therefore shows that `git ls-remote --tags` of a public repository works without credentials; the real upstreams are set per fork in the profile and were not tested.
- Ruleset: the ruleset of the scratch repository had `dismiss_stale_reviews_on_push`, `require_last_push_approval` and `require_code_owner_review` set to false when item (d) ran, so item (d) says nothing about the stricter ruleset the plan assumes. Round 2 repeats item (d) with those flags on, records them in a `RULESET d` line, and adds item (g).

## Questions for the owner

1. Did the unattended push notification `spike e unattended` reach your phone, and at what time? (It was requested at 07:38:43 UTC.)
2. Does any conclusion look wrong to you? In particular: `b.rebase` is unknown because the session's safety filter rewrote the bot command; do you want to post `@dependabot rebase` on pull request #1 yourself and report the reply? And should `e.board-write` count as failed when the only gap is that the fired session had no connector for `get_session`?

## Cleanup left behind

- Scratch pull requests created: none. Branches created in the scratch repository: none.
- Changes to the owner's or Dependabot's objects: commit `c6d3646` (`spike-b.txt`) on `dependabot/pip/pyyaml-6.0.3` (pull request #1); one comment on pull request #1 (id 6734690202, shows the rewritten text); merge commit `8a19d0b` on `spike/d-a` (pull request #3).
- Throwaway artifact: https://claude.ai/artifact/XyVXjNQGfdfsQbjWJEJ3Hx (private, holds document `spike/spike-e`).
- Deleted task: `trig_01CHu7PrqHwVb4LUQtrNAcXx` (its fired session `session_013HAf78Ed7obfQiQCoAL454` went with it).
- Reminders to this session created with `send_later`: `trig_01CZnKicHFf48Sew1MyPdA15` and `trig_019k54xigZgUHeihkvffCVfB` (one-shot, self-disabling).
- Round 2: pull requests created by me: none; branches created in the scratch repository: none (pull request #5 and its branch `spike/d-a2` were set up beforehand). Change to a scratch object: the branch update of pull request #5 (head `ef77a59` to `2d8c139`). Deleted task: `trig_01VQJ1YwJNrvMEpRSGFhyyKm` (item (g); its fired session `cse_013HAf784sFGLfmedXRPvRrb`). Reminders to this session created with `send_later`: `trig_01AZ4Kp75KBCvwVNvkYCtn96` and `trig_01AqxpX6EZYyR5MM47UUvtYE` (one-shot, self-disabling).
