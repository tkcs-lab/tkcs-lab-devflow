"""Contracts between the neutral core content (playbooks, roles, checklists, stacks) and the code.

These replace the sentence-level greps: instead of asking whether a file still contains a sentence, they check
that what the files name exists and works. Every `tld ...` call parses with the real command line, every
runtime action a playbook uses is defined in playbooks/runtime.md, and every role, checklist, stack and policy
a file names exists.
"""
from __future__ import annotations

import functools
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, CLAUDE, TLD, tld_cmd, _load

PLAYBOOKS = ROOT / "playbooks"
RUNTIME = PLAYBOOKS / "runtime.md"
CORE_DIRS = [ROOT / d for d in ("playbooks", "roles", "checklists", "stacks")]
CORE_FILES = sorted(p for d in CORE_DIRS for p in d.rglob("*.md"))
ADAPTER_FILES = sorted(CLAUDE.rglob("*.md"))
COMMANDS = ("setup", "review", "make-plan", "implement", "dod", "land", "deps", "upstream", "docs", "board")
# Provided by the board's inbox (a later work package); until the CLI has them, runtime.md says so and the
# playbooks fall back to an issue comment.
PROVIDED_BY_BOARD = {("board", "ask"), ("board", "answers")}

cli = _load("tld.cli")
dispatch = _load("tld.roles.dispatch")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# ---- extracting what the files name ---------------------------------------------------------
def code_texts(text: str) -> list[str]:
    """The inline code spans (joined across a wrapped line, blockquote marks removed) and fenced code lines."""
    out, fenced, prose = [], False, []
    for line in text.splitlines():
        if line.lstrip("> ").startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            out.append(line.lstrip("> ").strip())
        else:
            prose.append(re.sub(r"^\s*>\s?", "", line))
    joined = "\n".join(prose)
    for span in re.findall(r"`([^`]+)`", joined):
        out.append(" ".join(span.split()))
    return out


GROUPS = sorted({g for g, _ in cli.COMMANDS})
TLD_CALL = re.compile(r'(?:"\$\{CLAUDE_PLUGIN_ROOT\}/bin/tld"|(?<![\w/.<-])tld)\s+(--help|--version|'
                      + "|".join(GROUPS) + r')\b(?:\s+([a-z][a-z-]*))?(.*)')


def strip_placeholders(text: str) -> str:
    """`<a file with git diff --name-only ...>` is a placeholder, not flags of the call."""
    while True:
        new = re.sub(r"<[^<>]*>", "X", text)
        if new == text:
            return new
        text = new


def tld_calls(path: Path) -> list[tuple[str, str, str, str]]:
    calls = []
    for code in code_texts(path.read_text()):
        for m in TLD_CALL.finditer(code):
            group, command, rest = m.group(1), m.group(2) or "", strip_placeholders(m.group(3))
            calls.append((rel(path), group, command, rest))
    return calls


ALL_CALLS = sorted({c for p in CORE_FILES + ADAPTER_FILES for c in tld_calls(p)})


@functools.lru_cache(maxsize=None)
def help_text(*words: str) -> tuple[int, str]:
    r = subprocess.run([*tld_cmd(*words), "--help"], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def subcommands(text: str) -> list[str]:
    m = re.search(r"\{([a-z0-9,-]+)\}", text)
    return m.group(1).split(",") if m else []


# ---- tld calls ------------------------------------------------------------------------------
def test_the_files_name_tld_commands():
    assert len(ALL_CALLS) > 40


@pytest.mark.parametrize("call", ALL_CALLS, ids=lambda c: f"{c[0]}: tld {c[1]} {c[2]}{c[3][:40]}")
def test_every_tld_call_parses_with_the_real_cli(call):
    path, group, command, rest = call
    if group in ("--help", "--version"):
        assert cli.main([group]) == 0
        return
    if not command:  # the group named in prose (`tld roles`)
        assert group in GROUPS
        return
    if (group, command) in PROVIDED_BY_BOARD and (group, command) not in cli.COMMANDS:
        assert "provided by the board" in RUNTIME.read_text()
        return
    assert (group, command) in cli.COMMANDS, f"{path}: 'tld {group} {command}' is not a tld command"
    code, text = help_text(group, command)
    assert code == 0, f"tld {group} {command} --help failed: {text}"
    words = rest.split()
    if words and words[0] in subcommands(text.split("\n\n")[0]):
        code, text = help_text(group, command, words[0])
        assert code == 0, text
    for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", rest.split("|")[0].split(";")[0]):
        if flag in ("--help",):
            continue
        assert re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text), \
            f"{path}: 'tld {group} {command} {rest.strip()}' uses {flag}, which its --help does not list"


def test_every_playbook_command_calls_parse_helper_detects_a_wrong_flag():
    """The checker itself: a made-up flag is caught."""
    code, text = help_text("plan", "validate-manifest")
    assert code == 0 and "--profile" in text and "--no-such-flag" not in text


# ---- runtime actions ------------------------------------------------------------------------
def defined_actions() -> set[str]:
    text = RUNTIME.read_text()
    names = set()
    for line in text.splitlines():
        if line.startswith("### ") or line.startswith("| `"):
            names |= set(re.findall(r"`?([a-z_]+(?:\.[a-z_]+)?)\(", line.split("|")[1] if line.startswith("|") else line))
    return names


def used_actions(path: Path) -> set[str]:
    used = set()
    for code in code_texts(path.read_text()):
        used |= set(re.findall(r"^(github\.[a-z_]+)", code))
        m = re.match(r"^([a-z_]+(?:\.[a-z_]+)?)\(", code)
        if m:
            used.add(m.group(1))
    return used


def test_runtime_defines_the_actions_of_the_plan():
    names = defined_actions()
    for action in ("start_worker", "wait_for_workers", "check_in", "message_worker", "stop_worker", "run_role",
                   "ask_human", "notify_human", "schedule_wakeup", "identity", "read_worker", "run_helper"):
        assert action in names, action
    assert any(n.startswith("github.") for n in names)


@pytest.mark.parametrize("path", sorted(PLAYBOOKS.rglob("*.md")), ids=rel)
def test_every_action_a_file_uses_is_defined_in_runtime(path):
    unknown = used_actions(path) - defined_actions()
    assert not unknown, f"{rel(path)} uses runtime actions runtime.md does not define: {sorted(unknown)}"


# ---- names that must exist ------------------------------------------------------------------
LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")
CORE_PATH = re.compile(r"(?<![\w/.-])((?:playbooks|roles|checklists|stacks)/[a-z0-9/_-]+\.md)")


@pytest.mark.parametrize("path", CORE_FILES, ids=rel)
def test_links_and_named_core_files_exist(path):
    text = path.read_text()
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    prose = re.sub(r"`[^`]*`", "", prose)
    for target in LINK.findall(prose):
        if re.match(r"[a-z]+:", target) or "<" in target:
            continue
        assert (path.parent / target).exists(), f"{rel(path)} links {target}"
    for named in CORE_PATH.findall(text):
        assert (ROOT / named).exists(), f"{rel(path)} names {named}"


@pytest.mark.parametrize("path", CORE_FILES, ids=rel)
def test_every_role_a_file_runs_exists(path):
    for role in set(re.findall(r"run_role\(([a-z-]+),", path.read_text())) - {"role"}:
        assert (ROOT / "roles" / f"{role}.md").is_file(), f"{rel(path)} runs unknown role {role}"


def test_roles_agree_with_the_code_and_the_schema():
    cards = sorted(p.stem for p in (ROOT / "roles").glob("*.md"))
    assert cards == sorted(dispatch.ROLES)
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    entry = schema["properties"]["roles"]["properties"]["required"]["items"]["properties"]
    assert sorted(entry["role"]["enum"]) == cards
    assert sorted(schema["properties"]["roles"]["properties"]["disable"]["items"]["enum"]) == cards
    review = _load("tld.profile.validate").REVIEW_ROLES
    assert set(review) <= set(cards)


@pytest.mark.parametrize("role", sorted(p.stem for p in (ROOT / "roles").glob("*.md")))
def test_role_card_shape(role):
    text = (ROOT / "roles" / f"{role}.md").read_text()
    level = re.search(r"\*\*Default level:\*\* `(strong|standard|fast)`", text)
    assert level, f"{role}: no default level"
    modes = re.search(r"\*\*Modes:\*\* (.+)", text).group(1)
    assert ("`edit`" in modes and "(fix" in modes) == (role in dispatch.EDIT_ROLES), role
    assert re.search(rf"^AGENT-REPORT {re.escape(role)} at=<point\|adhoc> verdict=<pass\|findings\|n/a> "
                     r"blocking=<n> non_blocking=<n>$", text, re.M), f"{role}: report line"
    assert [h for h in re.findall(r"^## (.+)$", text, re.M)] == ["Role", "Inputs", "Method", "Report", "Limits"]


def test_report_grammar_matches_the_verifier():
    """The AGENT-REPORT line the roles policy shows is the one `tld roles verify` reads."""
    text = (PLAYBOOKS / "policies" / "roles.md").read_text()
    sample = "AGENT-REPORT code-reviewer at=dod verdict=findings blocking=1 non_blocking=2"
    assert "AGENT-REPORT <role> at=<point|adhoc> verdict=<pass|findings|n/a> blocking=<n> non_blocking=<n>" in text
    assert dispatch.REPORT_LINE.search(sample)


def test_stack_guides_and_checklists_exist():
    assert sorted(p.stem for p in (ROOT / "stacks").glob("*.md")) == ["go", "ipados", "python", "swift"]
    assert sorted(p.stem for p in (ROOT / "checklists").glob("*.md")) == ["docs", "review", "security", "test"]


def test_every_command_has_a_playbook():
    for name in COMMANDS:
        assert (PLAYBOOKS / f"{name}.md").is_file(), name


# ---- policies (S15, C7) ---------------------------------------------------------------------
@pytest.mark.parametrize("path", sorted(PLAYBOOKS.glob("*.md")), ids=rel)
def test_every_playbook_links_the_untrusted_text_policy(path):
    if path.name == "runtime.md":
        assert "policies/untrusted-text.md" in path.read_text()
        return
    assert "(policies/untrusted-text.md)" in path.read_text(), rel(path)


@pytest.mark.parametrize("name", COMMANDS)
def test_every_command_playbook_writes_a_status_record_or_says_why_not(name):
    text = (PLAYBOOKS / f"{name}.md").read_text()
    if name in ("dod", "board"):  # a report and a check; they change nothing
        return
    assert "policies/status-board.md" in text, name
    assert re.search(r"`attended: (true|false)`", text), f"{name}: no attended value (C7)"


def test_record_commands_cover_the_playbooks():
    record = _load("tld.board.record")
    expected = {"setup", "review", "make-plan", "deps", "upstream", "land", "docs"}
    assert set(record.COMMANDS) == expected


# ---- neutrality -----------------------------------------------------------------------------
RUNTIME_WORDS = re.compile(
    r"create_session|send_later|send_message|get_session|archive_session|AskUserQuestion|Artifact|PushNotification|"
    r"SendUserFile|subagent|get_me|mcp__|\bAgent tool|CLAUDE_PLUGIN_ROOT|/tld:|\bopus\b|\bsonnet\b|\bhaiku\b|"
    r"claude-(opus|sonnet|haiku)|ToolSearch|subscribe_pr_activity|actions_run_trigger|issue_write\b")


@pytest.mark.parametrize("path", CORE_FILES, ids=rel)
def test_core_content_names_no_runtime_tool_or_model(path):
    hits = [f"{n}: {line.strip()[:90]}" for n, line in enumerate(path.read_text().splitlines(), 1)
            if RUNTIME_WORDS.search(line)]
    assert hits == [], f"{rel(path)} names runtime tools or models:\n" + "\n".join(hits)


def test_model_ids_live_in_one_file():
    ids = re.compile(r"claude-(opus|sonnet|haiku)-\d")
    found = sorted(rel(p) for d in [ROOT / "adapters", ROOT / "src", *CORE_DIRS] for p in d.rglob("*")
                   if p.is_file() and p.suffix in (".md", ".py", ".json", ".yaml") and ids.search(p.read_text()))
    assert found == ["adapters/claude/skills/runtime/SKILL.md"]
