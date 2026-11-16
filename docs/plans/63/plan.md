# Plan 63: warn when a session runs in the wrong environment

> Historical record once merged: read it only to understand why a change was made.

## Summary

**Use it:** Set the variable `TLD_ENVIRONMENT` to the environment's own name in each working environment's settings, and, once a release with this change is installed, list the environments a repository's sessions belong in, in its `.tld/toolkit.yaml` (`runtime: environments: [TLD]`; an older tld rejects the unknown key). A cloud session that starts in any other environment shows a warning at its start and again when a tld command starts. The command also sends one phone alert and repeats the warning in its first reply, then carries on.

**Scope:** Adds the advisory hook `env-check`, the profile key `runtime.environments`, the runtime action `environment_name()` with a step 5 in the shared profile loading policy, tests, docs and a changelog line. Nothing stops or changes behaviour on a mismatch. A repository without the key, a local session and the research environment (it has no repository) stay silent. `hooks.disable: [env-check]` switches the hook off.

**Security:** The hook never denies and adds nothing to the agent's context. Names from the variable and from the profile lose their control characters and are cut at 100 characters before they are shown. The variable is the session's own claim and nothing relies on it for anything else.

**Review focus:** 3.1 the name comes from a variable the owner sets, so a duplicated or renamed environment keeps a stale name, which the command check of 3.5 catches. 3.4 it is not known whether the claude.ai app shows a start-of-session message (risk 1, manual step ma2). 3.5 one shared step in the profile policy changes what every command does at its start.

## 1. Goal

A person who works in one claude.ai environment (here "TLD": limited network, board credentials) and starts a session in another by accident (Default, TLD Research, TLD Swift) should be told, because the session then runs with the wrong network, variables and credentials. Issue: https://github.com/tkcs-lab/tkcs-lab-devflow/issues/63. The owner chose warnings only (decision `hook_and_warn`): a hook warning, and every tld command warns with a phone alert on a mismatch but carries on.

## 2. Current state

- A cloud session runs in a named environment. The container carries `CLAUDE_CODE_REMOTE=true` and `CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE=cloud_default`, and no variable holds the environment's name (observed in the planning session on 2026-11-15, all variable names listed). The runtime tool `get_environment` of the `claude-code-remote` server returns the name (`TLD` there), the network settings and the variable names; it is a tool for the model, a hook cannot call it.
- The pattern to copy is `model-check`: `src/tld/guard/model_check.py` (a neutral guard over an `Action`, notice only), `adapters/claude/hooks/model_check.py` (the entry shim), `adapters/claude/hooks/claude_adapter.py:195-206` (`to_action` for `UserPromptSubmit` and `SessionStart`), `adapters/claude/hooks/hooks.json:60-72` (both events), `src/tld/guard/_common.py:20-21` (`HOOK_NAMES`) and `:234` (the guards that look up `hooks.disable` only when they would warn, because the lookup can take a `git ls-remote` of up to 12 s), `src/tld/schema/profile.schema.json:547-561` (the `hooks.disable` enum).
- `src/tld/guard/action.py:35-36` holds `session_level` and `command_level`; there is no field for the environment.
- Every playbook loads the profile through `playbooks/policies/profile.md` "Loading the profile" (steps 1-4, lines 14-26). The runtime actions are defined in `playbooks/runtime.md` and mapped in `adapters/claude/skills/runtime/SKILL.md` (`tests/core/test_contracts.py` requires both).
- Pins that will fail on purpose: `tests/adapters/claude/test_structure.py:52-59` (`SessionStart` only for model-check), `tests/adapters/claude/test_hooks_config.py:43-44` (the list of registered scripts), `tests/hooks_helpers.py:23-34` (hook maps), `tests/adapters/claude/test_structure.py:171-181` (every schema key must appear in `docs/reference/profile-reference.md`).
- `.tld/toolkit.yaml` is protected from agent edits (`protect-paths`), so this repository's own profile cannot get the new key from a phase.

## 3. Design

### 3.1 Where the name comes from, and the key

The hook reads the variable `TLD_ENVIRONMENT`, which the owner sets in each working environment's settings to that environment's name. Rejected: inferring the environment from other variables (for example `TLD_BOARD_URL` unset); it cannot tell "TLD" from "TLD Swift" and ties the check to the board. Rejected: a hook that asks the model to call `get_environment`; it depends on the model, and `claude_adapter.py:229` hardcodes `hookEventName: "UserPromptSubmit"`. Rejected: a network call or the proxy status inside a hook.

The profile key is `runtime.environments`: a non-empty list of names, each 1 to 100 characters without control characters. Per repository, not per user, because the right environment is a property of the repository (a Swift repository wants "TLD Swift") and a cloud container is fresh at every session. `runtime` and not `environment`: the bare word reads like a deploy or Python environment. A name matches when, after trimming whitespace and ignoring case, it equals one of the listed names.

### 3.2 `Action`

`src/tld/guard/action.py`: two new fields after `command_level`, `remote: bool = False` (a cloud session; session_start and prompt) and `runtime_environment: str | None = None` (the name the session says it runs in; session_start and prompt). The adapter sets them; the core never reads the process environment.

### 3.3 The guard `env-check`

New `src/tld/guard/env_check.py`, a separate guard (its own `hooks.disable` name and tests; folding it into `model-check` would tie the two switches together). Constants and strings, exactly:

```python
NAME = "env-check"
MAX_NAME = 100
NOTICE_UNSET = ('this cloud session does not say which environment it runs in (the variable TLD_ENVIRONMENT is not set), '
                'and this repository\'s profile expects {expected}. If that is not the environment you meant to use, '
                'stop and start a new session in the right one.')
NOTICE_OTHER = ('this session says it runs in the environment "{got}", and this repository\'s profile expects '
                '{expected}. If that is not the environment you meant to use, stop and start a new session in the right one.')
```

`run_guard` puts `tld env-check: ` in front. Functions:

- `_clean(text: str) -> str`: drop every character whose Unicode category (`unicodedata.category`) is `Cc` or `Cf` (the C0 and C1 controls, DEL, and the format characters such as zero-width and bidirectional overrides), then cut to `MAX_NAME`. The cleaning runs before the cut.
- `_names(profile: dict | None) -> list[str]`: `profile["runtime"]["environments"]` when `runtime` is a mapping and `environments` a non-empty list of strings; each entry is `_clean(...).strip()`, empty ones are dropped; any other shape gives `[]`.
- `evaluate(ctx: Ctx) -> None`, in this order: set `ctx.notice = None`; return unless `ctx.action.kind` is `session_start` or `prompt` and `ctx.action.remote`; for a `prompt` return when `invoked` is empty; `names = _names(ctx.profile)`, return when empty; `got = _clean(ctx.action.runtime_environment or "").strip()`, return when `got.casefold()` is in `{n.casefold() for n in names}`; then `try: off = ctx.disabled(NAME)` with `except ProfileError: return None`, return when `off`; `expected = " or ".join('"' + n + '"' for n in names)`; `warning = NOTICE_OTHER.format(got=got, expected=expected)` when `got` else `NOTICE_UNSET.format(expected=expected)`, then `ctx.notice = f"{ctx.notice}; {warning}" if ctx.notice else warning` (the trust lookup of `ctx.disabled` may have set a notice of its own, which stays, as in `model_check.py`). It never denies and never sets `ctx.context`.

The profile is the working tree's (the hook only advises, as `model-check` does). `hooks.disable` is looked up only just before the warning, so the guard is added to the tuple at `_common.py:234` and to `HOOK_NAMES`; without that every prompt would run the trust lookup (a `git ls-remote` of up to 12 s) in a 10 s hook.

### 3.4 The adapter

`claude_adapter.py`: `GUARDS["env-check"] = ("tld.guard.env_check", False)`. In `to_action`, the `UserPromptSubmit` and `SessionStart` actions get `remote=os.environ.get("CLAUDE_CODE_REMOTE") == "true"` and `runtime_environment=os.environ.get("TLD_ENVIRONMENT") or None`. New entry script `adapters/claude/hooks/env_check.py` (a copy of `model_check.py`, `main("env-check")`). `hooks.json` registers it as its own group after the `model_check` group, under `UserPromptSubmit` and under `SessionStart`. The output is a `systemMessage` only (`to_result` already does that for a notice without context); a test pins that no `hookSpecificOutput` appears. The warning repeats after a compaction (the session starts again); that is accepted for an advisory hook.

### 3.5 The command check (shared step)

New runtime action `environment_name()` in `playbooks/runtime.md` (section after `secrets_help()`): the name of the environment the session runs in, or nothing when the runtime cannot say; never an error, never a reason to stop. Claude map in `SKILL.md`: `get_environment` of the `claude-code-remote` server with no arguments, its `name` field; nothing when the tool is not in the tool list, is refused or errors. The check lives once, as step 5 of "Loading the profile" in `playbooks/policies/profile.md`, so all playbooks get it and none drifts; the validation of steps 1-4 comes first, so a broken profile still stops the run before this step. Exact text of step 5:

> 5. **Check the environment.** When the profile has `runtime.environments`, call `environment_name()` ([../runtime.md](../runtime.md)). When it returns a name that is none of the listed names (compared after trimming, ignoring case), call `notify_human("<project>: this session runs in the environment <name>, this repository expects <names>")` once and say the same in your first reply, then carry on: this step never stops a run and never changes what the playbook does. A worker started by another session puts the line in its final report and does not call `notify_human`. When `environment_name()` returns nothing, or the profile has no such key, skip this step without a word. Whenever `environment_name()` returns a name and the shell variable `TLD_ENVIRONMENT` is set and differs from it (also when the name is listed), say in your first reply the line `TLD_ENVIRONMENT says <value> but the session runs in <name>: update the variable in the environment's settings.` and add it to the alert when one is sent.

Every playbook but `ask.md` (a read-only discussion that never loads the profile) links `profile.md`, so the step reaches every command. Why also a command check when the hook exists: the variable is the environment's own claim, so a duplicated environment keeps the old name and a rename leaves it stale; the runtime's name is the cross-check, and the phone alert reaches an unattended session, which a hook message does not. A new profile table row (before `project_steward`) says the key is used by step 5 and the hook.

### 3.6 Schema, docs and template

`profile.schema.json`: add `"env-check"` to the `hooks.disable` enum; add the top-level property `runtime` (`type object`, `additionalProperties false`) with `environments` (`type array`, `minItems 1`, items `{"type": "string", "pattern": "^[^\\x00-\\x1f\\x7f-\\x9f\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2064\\u2066-\\u2069\\ufeff]{1,100}(?![\\s\\S])"}`) and a description that does not name the host product. The validator is schema-driven, has no `uniqueItems` or `maxLength`, and applies a pattern with `re.search`, where `$` would also accept a trailing newline; the pattern therefore ends in the lookahead `(?![\s\S])` (end of input, valid in Python and in ECMAScript), excludes the C0 and C1 controls and the common zero-width and bidirectional format characters, and carries the length. Phase p1 documents what a test requires it to document: the rows `runtime`, `runtime.environments` and `env-check` in `docs/reference/profile-reference.md`, and the hook in `docs/architecture/hooks.md` (a test requires every hook name there in backticks). The last phase adds the owner's steps in `cloud-environments.md`, the template block, the README line, the `design.md` note and the changelog.

### 3.7 Rejected alternatives

- Warn in every cloud session that has a profile and no `TLD_ENVIRONMENT`, with no key: changes behaviour for every repository and cannot tell TLD from TLD Swift.
- A user-level list: a fresh container keeps nothing between sessions; the only persistent per-user setting is the environment variable, which 3.1 already uses.
- Stopping the command on a mismatch: the owner chose warn-and-carry-on.
- The check copied into each of the 14 playbooks: they would drift; one shared step is enough.

## 4. Manual steps

### Before implementation

None.

### After implementation

**ma1-set-environment-variable** (about 5 minutes, at any time; the variable does nothing until a profile lists environments)

1. Open the working environment's settings in claude.ai: in a session, the menu in the title bar, then Edit. The repository's guide for it: https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/environment-check/docs/guides/cloud-environments.md; current wording of the settings: https://code.claude.com/docs/en/claude-code-on-the-web. You see the environment's name, network access and variables.
2. Under Environment variables add `TLD_ENVIRONMENT` with the environment's name exactly as shown, for the working environment `TLD`. It is not a secret, so a plain variable is right. Save. Do the same in every other working environment you use (its own name as the value). Do not add it to the research environment.
3. Report back: pass if the variable is saved in each working environment, fail with the environment that is missing.

**ma2-add-profile-key-and-try-it** (about 15 minutes, only after a release that carries this change is installed in your Project; ticked in the pull request after the merge and the release)

1. Check that the release is installed: https://github.com/tkcs-lab/tkcs-lab-devflow/blob/feature/environment-check/README.md#install says where the plugin is installed. Do not continue before it is: the profile schema of an older tld rejects the unknown key `runtime` and would stop every command in that repository.
2. In each repository that should warn, add to `.tld/toolkit.yaml` (agents cannot edit that file) and merge it like any change. For this repository: https://github.com/tkcs-lab/tkcs-lab-devflow/blob/main/.tld/toolkit.yaml.
   ```yaml
   runtime:
     environments: [TLD]
   ```
3. Start a new session on this repository in the Default environment. If the app shows a start message you see `tld env-check: this cloud session does not say which environment it runs in (the variable TLD_ENVIRONMENT is not set), and this repository's profile expects "TLD". ...`.
4. In that session run `/tld:board`. You get a phone alert `<project>: this session runs in the environment Default, this repository expects TLD`, the same line in the command's first reply, and the command runs on.
5. Start a new session in the TLD environment and run `/tld:board` again: no message and no alert.
6. Report back four lines, pass or fail each: the profile key merged in each repository; start message shown in the app; phone alert and first-reply line on a mismatch; TLD silent.

## 5. Risks and open questions

1. It is not known whether the claude.ai app shows a `SessionStart` hook's `systemMessage` (or a `UserPromptSubmit` one). If ma2 step 1 shows nothing, only the alert of the command check reaches you, and a session that no tld command starts gets no warning. Then the fix is a different channel, not more hooks.
2. The variable is the environment's own claim (3.1); a duplicated environment copies it. The command check covers tld commands only.
3. `environment_name()` may not exist in scheduled or worker sessions; then step 5 is skipped silently (a missed warning, never a failure). A worker started with `create_session` inherits its parent's environment when none is given (the tool's own description), so workers in the right parent do not warn.
4. One mismatch can show three messages (session start, the hook at the command prompt, the playbook alert). Accepted; the start message repeats after a compaction.
5. A phase that finds a test failing for a reason other than the new hook, the new schema key or the new runtime action stops with `status=blocked` and quotes the failure.
6. The plan's tests of the policy text (p2) check wording, not behaviour: the behaviour of step 5 is the model's, and ma2 is its real test.
7. Whether the claude.ai client renders control or format characters in a message is not known; the guard drops every `Cc` and `Cf` character and the schema rejects the common ones, so the question needs no research.
8. An older tld rejects the new key (`additionalProperties: false`) and stops every command in that repository; that is why ma2 waits for a release and the guide says so.

## Implementation manifest

```yaml
plan_slug: environment-check
feature_branch: feature/environment-check
tracking_issue: 63
max_parallel: 2
manual_before: []
manual_after:
  - id: ma1-set-environment-variable
    title: Set TLD_ENVIRONMENT in each working environment
    why: only the owner can edit the environment settings; the variable does nothing until a profile lists environments, so it can be set before the pull request merges
  - id: ma2-add-profile-key-and-try-it
    title: After the release, add runtime.environments to each profile and start a session in the wrong environment
    why: the profile schema of an older tld rejects the unknown key runtime and would stop every command, so this waits for a release; .tld/toolkit.yaml is protected from agent edits; CI cannot start a session in another environment. Done after the merge and the release, ticked in the pull request.
verify_after_merge:
  - .venv/bin/python -m pytest -q -k env_check
  - .venv/bin/python cli/tld profile validate .tld/toolkit.yaml
  - .venv/bin/python cli/tld ops docs-index check
final_checks:
  - "`tld plan deviations check --file docs/plans/63/deviations.md --plan docs/plans/63/plan.md --all` exits 0"
  - "the changelog has entries under docs.changelog.section and no version heading"
  - "`tld ops docs-index check --profile .tld/toolkit.yaml` exits 0"
phases:
  - id: p1-env-hook
    title: The env-check hook, the Action fields, the adapter entry, the runtime.environments key and the hook's docs
    depends_on: []
    complexity: M
    touches:
      - src/tld/guard/action.py
      - src/tld/guard/env_check.py
      - src/tld/guard/_common.py
      - adapters/claude/hooks/claude_adapter.py
      - adapters/claude/hooks/env_check.py
      - adapters/claude/hooks/hooks.json
      - src/tld/schema/profile.schema.json
      - docs/reference/profile-reference.md
      - docs/architecture/hooks.md
      - tests/hooks_helpers.py
      - tests/core/test_hook_env_check.py
      - tests/adapters/claude/test_hooks_env_check.py
      - tests/adapters/claude/test_hooks_config.py
      - tests/adapters/claude/test_structure.py
      - tests/core/test_validate_profile.py
    brief: |
      Read first: docs/plans/63/plan.md sections 3.1 to 3.4 and 3.6, src/tld/guard/model_check.py, src/tld/guard/action.py, src/tld/guard/_common.py, adapters/claude/hooks/claude_adapter.py, tests/core/test_hook_model_check.py, tests/adapters/claude/test_hooks_model_check.py, tests/hooks_helpers.py.
      1. In src/tld/guard/action.py add after the `command_level` field the two fields of section 3.2: `remote: bool = False` and `runtime_environment: str | None = None`, each with a trailing comment in the style of the neighbours.
      2. Create src/tld/guard/env_check.py with a module docstring in the style of model_check.py and implement section 3.3 exactly: the constants NAME, MAX_NAME, NOTICE_UNSET, NOTICE_OTHER with the strings given there, `_clean` (with `unicodedata`), `_names` and `evaluate`, with type hints; the notice is appended to an existing one as section 3.3 says. Import `Ctx, ProfileError` from tld.guard._common. Do not write the word SessionStart anywhere in this file, in a comment or docstring either (tests/adapters/claude/test_structure.py scans src/tld for it); write session_start.
      3. In src/tld/guard/_common.py add "env-check" to HOOK_NAMES (after "board-gate") and to the tuple in `run_guard` (`if name not in ("plan-gate", "model-check", "board-gate", "env-check")`), and extend the comment above it to name env-check.
      4. In adapters/claude/hooks/claude_adapter.py add `"env-check": ("tld.guard.env_check", False)` to GUARDS. In `to_action`, add to the `Action("prompt", ...)` call and to the `Action("session_start", ...)` call the two keyword arguments `remote=os.environ.get("CLAUDE_CODE_REMOTE") == "true"` and `runtime_environment=os.environ.get("TLD_ENVIRONMENT") or None`.
      5. Create adapters/claude/hooks/env_check.py as a copy of adapters/claude/hooks/model_check.py with the docstring naming `env-check` and `main("env-check")`.
      6. In adapters/claude/hooks/hooks.json add, in `UserPromptSubmit` after the model_check group and in `SessionStart` after the model_check group, a group `{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/env_check.py\"", "timeout": 10}]}`.
      7. In src/tld/schema/profile.schema.json append "env-check" to the `hooks.disable` enum after "board-gate", and add the top-level property `runtime` of section 3.6 inside "properties" (next to "hooks"), with the pattern string of section 3.6 exactly (JSON-escaped as written there) and a description that says: the environment names this repository's sessions belong in; the env-check hook and every command warn on another; nothing stops. The description names no product or host.
      8. Docs. In docs/reference/profile-reference.md add after the `hooks.board_gate.enabled` row the rows `` | `runtime` | no | Facts about where this repository's sessions run | `` and `` | `runtime.environments` | no | Non-empty list of environment names (1 to 100 characters, no control or format characters) this repository's sessions are meant to run in. The `env-check` hook warns in a cloud session whose `TLD_ENVIRONMENT` is missing or not in the list, and every command's profile loading warns when the runtime reports another name; names are compared after trimming, ignoring case. Warnings only, nothing stops. An older tld rejects this key. See [hooks.md](../architecture/hooks.md) | ``, and add `env-check` after `board-gate` in the name list of the `hooks.disable` row. In docs/architecture/hooks.md: (a) after the `model-check` row of the table "The hooks" add the row `` | `env-check` | SessionStart, UserPromptSubmit | nothing (a `systemMessage` warning only) | A session started in the wrong environment works with the wrong network, variables and credentials | a cloud session whose `TLD_ENVIRONMENT` is `Default` with a profile that lists `TLD` warns; with `TLD` it is silent | ``; (b) insert before the heading `### `plan-gate`` a section `### `env-check`` with five bullets in this order, in the words of plan sections 3.1 to 3.5: **The key** (`runtime.environments` of the working tree's profile; silent without it or when malformed), **The name** (the variable `TLD_ENVIRONMENT`; trimmed and compared ignoring case; the runtime puts no name into the container), **When** (SessionStart and a prompt that starts a tld command, only when `CLAUDE_CODE_REMOTE` is `true`; local sessions silent; repeats after a compaction), **Output** (`systemMessage` only, never denies, control and format characters removed and names cut at 100 characters, `hooks.disable: [env-check]` turns it off and is looked up only when it would warn), **Limits** (the variable is the environment's own claim, which is why every command also asks the runtime for the name in step 5 of [profile.md](../../playbooks/policies/profile.md); whether the claude.ai app shows a SessionStart message is not known); (c) in the yaml comment of "Disabling a hook" append `, env-check` after `board-gate`.
      9. Existing tests. tests/hooks_helpers.py: add "env-check" to MODULES ("env_check"), CORE ("tld.guard.env_check") and FAIL_CLOSED (False). tests/adapters/claude/test_hooks_config.py: add "env_check.py" once to the extra list of `expected` (line 43, next to "model_check.py", because MODULES already counts it once) and change the message to say env_check.py twice (UserPromptSubmit and SessionStart). tests/adapters/claude/test_structure.py: rename test_session_start_is_only_used_by_model_check to test_session_start_is_only_used_by_model_check_and_env_check, keep `allowed` as it is, and replace the last assertion by one that the set of SessionStart script names equals {"model_check.py", "env_check.py"}.
      10. Create tests/core/test_hook_env_check.py in the pattern of tests/core/test_hook_model_check.py (a `decide(action)` helper through `_common.run_guard("env-check", env_check.evaluate, False, action)`; a repo whose profile is `hh.PROFILE + "runtime:\n  environments: [TLD, TLD Swift]\n"`; `Action("prompt", ..., invoked="make-plan", remote=True, runtime_environment=...)`). A helper `silent(d)` asserts `d.verdict == "allow" and d.notice is None and d.context is None`; every silent case uses it. One test per behaviour, each name starting test_env_check_: silent when not remote; silent without the profile key; silent when the name is listed (parametrised "TLD", "  tld  ", "TLD SWIFT"); warns when the name is unset, for a prompt and for a session_start (notice starts "tld env-check: this cloud session does not say", contains `"TLD" or "TLD Swift"`, verdict "allow", context None); warns when the name is another ("Default": contains `runs in the environment "Default"`); a prompt without `invoked` is silent while a session_start warns; other action kinds (a shell action and a stop action, remote True, unlisted name) are silent; names from the variable are cleaned and cut (value "A\x1b[31mB\x9b‮" plus 200 "x": none of "\x1b", "\x9b", "‮" in the notice, and the quoted name starts "A[31mB" and is exactly 100 characters); names from the profile are cleaned and cut (a profile written with `yaml.safe_dump` whose entry is "T\x1bLD" plus 150 "y": the notice has no "\x1b" and the quoted name is at most 100 characters); malformed shapes are silent (`runtime: TLD`, `environments: TLD`, `[]`, `[3]`, `["  "]`); `hooks.disable: [env-check]` switches it off (committed and working profile both hold the runtime key and the disable list, name "Default", via make_repo_with_origin, and the same repo without the disable list warns); a malformed disable list never denies (`hooks:\n  disable: env-check\n` with the runtime key and name "Default": `verdict != "deny"`); the disable lookup runs only when it would warn (monkeypatch `_common.Ctx.disabled` with a function that counts its calls and returns False: a listed name is silent with 0 calls, an unlisted one warns with 1 call); a missing profile is silent (make_repo with profile=None).
      11. Create tests/adapters/claude/test_hooks_env_check.py in the pattern of tests/adapters/claude/test_hooks_model_check.py, with an autouse fixture that removes CLAUDE_CODE_REMOTE and TLD_ENVIRONMENT from the environment, through `hh.run("env-check", payload, project=repo)` and `monkeypatch.setenv`; names start test_env_check_: a SessionStart event with CLAUDE_CODE_REMOTE=true and no TLD_ENVIRONMENT gives code 0 and a stdout JSON whose `systemMessage` starts with "tld env-check: " and has no `hookSpecificOutput` key; a UserPromptSubmit event with prompt "/tld:board" and TLD_ENVIRONMENT=Default warns, names "Default" and has no `hookSpecificOutput` key; prompt "hello" is silent (empty stdout); CLAUDE_CODE_REMOTE unset, "1" and "false" are silent (`claude_adapter.to_action(...)` gives `remote` False); TLD_ENVIRONMENT=TLD is silent; an empty TLD_ENVIRONMENT gives `runtime_environment` None; one `hh.run_script("env-check", payload, project=repo, extra_env={"CLAUDE_CODE_REMOTE": "true", "TLD_ENVIRONMENT": "Default"})` has returncode 0 and a stdout JSON with a `systemMessage`.
      12. In tests/core/test_validate_profile.py add, in the style of its neighbours and asserting on the message text the validator prints (read src/tld/profile/validate.py lines 55-100 for the texts), tests named test_env_check_*: `runtime: {environments: [TLD]}` validates; `[]` is rejected with "needs at least 1 item"; entries "a\x01", "a\x9b", "a‮", "TLD\n" and 3 are rejected; 100 characters validate and 101 are rejected; "" is rejected; an unknown key under `runtime` is rejected; `hooks.disable: [env-check]` validates.
      13. Run `.venv/bin/python -m pytest tests -q`. Tests are edited only where steps 9 to 12 name them. A test that lists hook names or hook scripts and fails only because env-check is new: add env-check to its expectation. A docs test is satisfied by the docs of step 8, never by weakening it. A failing test for any other reason: stop with status=blocked and quote the failure.
      Stop condition: if `tests/core/test_no_project_words.py` fails on a new line, or `claude_adapter.py` has no `Action("session_start", ...)` call to extend, stop with status=blocked and quote it.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_hook_env_check.py tests/adapters/claude/test_hooks_env_check.py -q passes"
      - ".venv/bin/python -m pytest tests/core/test_validate_profile.py tests/adapters/claude/test_hooks_config.py tests/adapters/claude/test_structure.py -q passes"
      - ".venv/bin/python -m pytest tests/adapters/claude/test_hooks_config.py::test_hook_names_agree_everywhere tests/adapters/claude/test_hooks_config.py::test_docs_cover_every_hook_and_key -q passes"
      - "grep -n env_check adapters/claude/hooks/hooks.json prints two lines"
      - ".venv/bin/python cli/tld profile validate .tld/toolkit.yaml passes"
      - ".venv/bin/python -m pytest tests -q passes"
  - id: p2-env-command-check
    title: The runtime action environment_name() and step 5 of the profile loading policy
    depends_on: [p1-env-hook]
    complexity: S
    touches:
      - playbooks/runtime.md
      - adapters/claude/skills/runtime/SKILL.md
      - playbooks/policies/profile.md
      - tests/core/test_env_check_policy.py
      - tests/core/test_contracts.py
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/63/plan.md section 3.5, playbooks/policies/profile.md, playbooks/runtime.md (the sections "The human" and "Time"), adapters/claude/skills/runtime/SKILL.md (the table "The human"), tests/core/test_contracts.py (RUNTIME_WORDS).
      1. In playbooks/runtime.md insert, after the `### secrets_help()` section and before `## Time`, the section `### environment_name()` with the text: "The name of the environment the session runs in (the named setup of network access, variables and setup script the runtime started it with), or nothing when the runtime cannot say: a local session, a runtime without named environments, a refused or failed lookup. Never an error, and never a reason to stop."
      2. In adapters/claude/skills/runtime/SKILL.md insert after the `secrets_help()` row of the table "The human" the row: `` | `environment_name()` | `get_environment` of the `claude-code-remote` server with no arguments; its `name` field. Nothing when the tool is not in the tool list, is refused or returns an error (a local session has no such tool). It needs no approval and widens nothing. | ``.
      3. In playbooks/policies/profile.md add after step 4 of "Loading the profile" the step 5 of plan section 3.5, word for word (the block quote there, without the "> "). In the table "Keys, in the order the playbooks use them" add before the `project_steward` row: `` | `runtime.environments` | The environment names this repository's sessions run in; step 5 of "Loading the profile" and the `env-check` hook warn on another | ``.
      4. In tests/core/test_contracts.py add `|get_environment|claude-code-remote` to RUNTIME_WORDS (inside the alternation, before `|claude\.ai`) and to test_runtime_words_catch_the_claude_ai_host_and_not_a_lookalike the assertions that `RUNTIME_WORDS.search("get_environment")` and `RUNTIME_WORDS.search("claude-code-remote")` find a match.
      5. Create tests/core/test_env_check_policy.py (import ROOT from conftest as the neighbouring tests do). Constant STEP5 holds the text of step 5 from plan section 3.5, whitespace-normalised with `" ".join(text.split())`. Tests, all named test_env_check_*: the normalised section of profile.md between "## Loading the profile" and "## Keys" contains STEP5; the lines of that section that start with a digit and a dot, as numbers, are [1, 2, 3, 4, 5]; the row `| `runtime.environments` |` comes before the row `| `project_steward` |` in profile.md; in runtime.md the line "### secrets_help()" comes before "### environment_name()" which comes before "## Time", and the text between the second and the third contains "Never an error"; the SKILL.md row that starts "| `environment_name()`" contains "get_environment", "claude-code-remote" and "Nothing when"; every file in playbooks/ except ask.md (read-only, never loads the profile) and runtime.md contains "policies/profile.md".
      6. Run `python3 evals/run.py check-baseline`. It fails, because runtime.md and profile.md are linked by every command: run `python3 evals/run.py baseline --refresh-hashes`, and say in the commit message "hash refresh only: step 5 is skipped when the profile has no runtime.environments and changes no command's other behaviour".
      7. Run `.venv/bin/python -m pytest tests -q`. A failure for a reason other than the new action, the new step or the new RUNTIME_WORDS entries: stop with status=blocked and quote it.
      Stop condition: if tests/core/test_contracts.py fails with a message about a runtime action other than environment_name, or a core file already contains "get_environment" or "claude-code-remote", stop with status=blocked and quote it.
    acceptance:
      - ".venv/bin/python -m pytest tests/core/test_env_check_policy.py tests/core/test_contracts.py -q passes"
      - "python3 evals/run.py check-baseline prints: command hashes current"
      - "grep -rn get_environment playbooks prints nothing"
      - "grep -n environment_name playbooks/policies/profile.md playbooks/runtime.md adapters/claude/skills/runtime/SKILL.md prints at least one line in each file"
      - ".venv/bin/python -m pytest tests -q passes"
  - id: p3-retire
    title: Retirement - cloud-environments.md, template, README, design note and changelog
    depends_on: [p1-env-hook, p2-env-command-check]
    complexity: S
    touches:
      - docs/architecture/design.md
      - docs/guides/cloud-environments.md
      - README.md
      - src/tld/templates/toolkit.yaml
      - CHANGELOG.md
      - evals/baselines/default.json
    brief: |
      Read first: docs/plans/63/plan.md sections 3.1 to 3.6 and 4, docs/architecture/hooks.md (the `env-check` section phase p1 wrote), docs/guides/cloud-environments.md, CHANGELOG.md (the top).
      1. docs/architecture/design.md: replace the sentence "(The `model-check` hook does use a SessionStart event, but only to record the" and its next line "session's model; it installs or fetches nothing.)" with "(The `model-check` and `env-check` hooks do use a SessionStart event, `model-check` only to record the session's model and `env-check` only to compare the environment name with the profile; neither installs or fetches anything.)", keeping the two-space indent of the continuation line.
      2. README.md: in the "Seatbelt: the hooks" bullet replace "`model-check` only warns when a session runs on the most expensive level." with "`model-check` only warns when a session runs on the most expensive level, and `env-check` only warns when a cloud session runs in an environment the profile does not list (`runtime.environments`)."
      3. docs/guides/cloud-environments.md: (a) in the table "The working environment" add after the "Environment variables" row the row `` | Environment variable for the environment check | `TLD_ENVIRONMENT=<this environment's name>`, for example `TLD_ENVIRONMENT=TLD` | the `env-check` hook compares it with the profile's `runtime.environments`; a session in this environment without it warns | ``; (b) add before the section "## Checking the working environment" the section "## Telling tld which environment a repository belongs in" with three numbered steps: set `TLD_ENVIRONMENT` to the environment's name in its settings, in every working environment and never in the research environment; after a release that carries the `env-check` hook is installed, add `runtime:` and `environments: [<name>]` to the repository's `.tld/toolkit.yaml` (show the yaml block, and say that an older tld rejects the key, so the order matters); start a session in another environment and see the warning; and one sentence that a warning never stops a command; (c) add a step 3 to "Checking the working environment": "Start a session in a different environment on a repository whose profile has `runtime.environments`. It must warn at its start and when a tld command starts, and the command must carry on."
      4. src/tld/templates/toolkit.yaml: insert before the line starting `# hooks:` the three commented lines `# runtime:               # optional: where this repository's sessions run (docs/reference/profile-reference.md).`, `#   environments:        # the environment names the sessions belong in; the env-check hook and every command warn on another`, `#     - TLD`, followed by one empty line.
      5. CHANGELOG.md: under `## [Unreleased]` add `### Added` and the bullet: "- The `env-check` hook and the profile key `runtime.environments`: a cloud session that runs in an environment the profile does not list gets a warning at its start and when a tld command starts. Set `TLD_ENVIRONMENT=<environment name>` in each working environment's settings, and add the key to a profile only after the release is installed (an older tld rejects it). Every tld command also checks the name through the new runtime action `environment_name()` when it loads the profile, sends one alert and carries on. Switch the hook off with `hooks.disable: [env-check]`." Never add a version heading.
      6. Run `python3 evals/run.py check-baseline`. When it fails, run `python3 evals/run.py baseline --refresh-hashes` and say in the commit message "hash refresh only: documentation".
      7. Run `.venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml` until it exits 0, and `.venv/bin/python -m pytest tests -q`. The plan adds no doc, so no index row changes; a docs-index error about a row: stop with status=blocked and quote it.
      Stop condition: if a sentence quoted in step 1 or 2 is not found verbatim, stop with status=blocked and quote the lines around it.
    acceptance:
      - ".venv/bin/python cli/tld ops docs-index check --profile .tld/toolkit.yaml exits 0"
      - "python3 evals/run.py check-baseline prints: command hashes current"
      - "grep -n 'env-check' docs/architecture/design.md README.md CHANGELOG.md prints at least one line in each file"
      - "grep -n TLD_ENVIRONMENT docs/guides/cloud-environments.md prints at least two lines"
      - "grep -n 'runtime:' src/tld/templates/toolkit.yaml prints one line"
      - ".venv/bin/python -m pytest tests -q passes"
```
