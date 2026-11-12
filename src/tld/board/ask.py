#!/usr/bin/env python3
"""Validate a tld ask (a question set for the owner, answered on the board) and its answers.

    tld board validate-ask FILE|-

Exit 0 and `ask: OK`, or exit 1 and one line per error, each starting `ask: `. The file is an ask as a
session posts it (no id, state open, no answers). The rules are plain Python; the schema file
src/tld/schema/ask.schema.json documents the shape. Every text of an ask is shown as text only: the page
never interprets it as HTML. Python 3.11+, stdlib only.

    validate_new(ask)              # errors of an ask a session posts
    validate_stored(ask)           # errors of an ask as the board stores it (id, state, answers)
    validate_answers(ask, answers) # errors of the owner's answers to an open ask
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from tld.board.record import COMMANDS, DOC_ID_RE, REPO, SLUG, TIMESTAMP, project_slug

FIELDS = ("schema", "kind", "id", "project", "repo", "title", "created_by", "context_url", "questions",
          "state", "answers", "created_at", "answered_at", "fallback_issue", "record")
REQUIRED = ("schema", "kind", "project", "repo", "title", "created_by", "questions")
SERVER_FIELDS = ("id", "created_at", "answered_at")
QUESTION_FIELDS = ("id", "text", "kind", "options", "required")
OPTION_FIELDS = ("value", "label")
KINDS = ("choice", "confirm", "text")
STATES = ("open", "answered", "cancelled")

MAX_QUESTIONS = 30
MAX_OPTIONS = 10
MAX_TITLE = 120
MAX_TEXT = 2000
MAX_LABEL = 200
MAX_ANSWER = 4000
MAX_URL = 500
MAX_ASK = 65536

ID_RE = re.compile(r"^a-[0-9a-f]{16}$")
QID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
VALUE_RE = QID_RE
CREATED_BY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}$")
ISSUE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(#[1-9][0-9]{0,9})?$")
# Control characters other than newline and tab, and the bidi controls that can disguise text.
BAD_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f‪-‮⁦-⁩]")


def _text(value, limit: int, multiline: bool) -> str | None:
    """The reason a text field is not acceptable, or None."""
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty string"
    if len(value) > limit:
        return f"must be at most {limit} characters"
    if BAD_CHARS.search(value):
        return "must not contain control characters"
    if not multiline and ("\n" in value or "\t" in value):
        return "must be one line"
    return None


def _check_question(q, n: int, seen: set[str], errors: list[str]) -> None:
    where = f"'questions[{n}]'"
    if not isinstance(q, dict):
        errors.append(f"{where} must be an object")
        return
    for key in ("id", "text", "kind"):
        if key not in q:
            errors.append(f"{where} is missing '{key}'")
    for key in q:
        if key not in QUESTION_FIELDS:
            errors.append(f"{where} has unknown field '{key}'")
    qid = q.get("id")
    if "id" in q:
        if not (isinstance(qid, str) and QID_RE.match(qid)):
            errors.append(f"{where} field 'id' must match {QID_RE.pattern}")
        elif qid in seen:
            errors.append(f"{where} field 'id' '{qid}' is used twice")
        else:
            seen.add(qid)
    if "text" in q:
        why = _text(q["text"], MAX_TEXT, True)
        if why:
            errors.append(f"{where} field 'text' {why}")
    kind = q.get("kind")
    if "kind" in q and kind not in KINDS:
        errors.append(f"{where} field 'kind' must be one of {', '.join(KINDS)}")
    if "required" in q and not isinstance(q["required"], bool):
        errors.append(f"{where} field 'required' must be true or false")
    options = q.get("options")
    if kind == "choice":
        if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
            errors.append(f"{where} field 'options' must list 2 to {MAX_OPTIONS} options for a choice")
            return
        values: set[str] = set()
        for m, opt in enumerate(options):
            ow = f"{where} option {m}"
            if not isinstance(opt, dict) or set(opt) - set(OPTION_FIELDS) or "value" not in opt:
                errors.append(f"{ow} must be an object with 'value' and an optional 'label'")
                continue
            value = opt["value"]
            if not (isinstance(value, str) and VALUE_RE.match(value)):
                errors.append(f"{ow} field 'value' must match {VALUE_RE.pattern}")
            elif value.lower() in values:
                errors.append(f"{ow} field 'value' '{value}' is used twice")
            else:
                values.add(value.lower())
            if "label" in opt:
                why = _text(opt["label"], MAX_LABEL, False)
                if why:
                    errors.append(f"{ow} field 'label' {why}")
    elif "options" in q:
        errors.append(f"{where} field 'options' is only allowed for a choice")


def _check(ask, errors: list[str]) -> None:
    if not isinstance(ask, dict):
        errors.append("the ask must be a JSON object")
        return
    for key in REQUIRED:
        if key not in ask:
            errors.append(f"'{key}' is required")
    for key in ask:
        if key not in FIELDS:
            errors.append(f"'{key}' is not a known field")
    if "schema" in ask and not (ask["schema"] == 1 and not isinstance(ask["schema"], bool)):
        errors.append("'schema' must be 1")
    if "kind" in ask and ask["kind"] != "ask":
        errors.append("'kind' must be 'ask'")
    project, repo = ask.get("project"), ask.get("repo")
    if "project" in ask and not (isinstance(project, str) and SLUG.match(project) and "--" not in project):
        errors.append("'project' must match ^[a-z0-9-]+$ without a double hyphen")
    if "repo" in ask:
        if not (isinstance(repo, str) and REPO.match(repo)):
            errors.append("'repo' must look like owner/name")
        elif isinstance(project, str) and project != project_slug(repo):
            errors.append(f"'project' must be '{project_slug(repo)}', the slug of the repository name")
    if "title" in ask:
        why = _text(ask["title"], MAX_TITLE, False)
        if why:
            errors.append(f"'title' {why}")
    created_by = ask.get("created_by")
    if "created_by" in ask and not (isinstance(created_by, str) and CREATED_BY_RE.match(created_by)):
        errors.append("'created_by' must be a session id or a command name (letters, digits, _ . : / -)")
    url = ask.get("context_url")
    if url is not None and not (isinstance(url, str) and url.startswith("https://") and len(url) <= MAX_URL
                                and not BAD_CHARS.search(url) and not re.search(r"\s", url)):
        errors.append(f"'context_url' must be null or an https:// URL of at most {MAX_URL} characters")
    issue = ask.get("fallback_issue")
    if issue is not None and not (isinstance(issue, str) and ISSUE_RE.match(issue)):
        errors.append("'fallback_issue' must be null, owner/repo or owner/repo#<n>")
    record = ask.get("record")
    if "record" in ask and record is not None:
        allowed = {project} | {f"{project}--{c}" for c in COMMANDS} if isinstance(project, str) and SLUG.match(project) else None
        if not (isinstance(record, str) and DOC_ID_RE.match(record) and (allowed is None or record in allowed)):
            errors.append("'record' must be null, the project slug, or '<project>--<command>'")
    questions = ask.get("questions")
    if "questions" in ask:
        if not isinstance(questions, list) or not 1 <= len(questions) <= MAX_QUESTIONS:
            errors.append(f"'questions' must list 1 to {MAX_QUESTIONS} questions")
        else:
            seen: set[str] = set()
            for n, q in enumerate(questions):
                _check_question(q, n, seen, errors)
    try:
        size = len(json.dumps(ask, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        size = 0
    if size > MAX_ASK:
        errors.append(f"the ask is larger than {MAX_ASK} bytes")


def validate_new(ask) -> list[str]:
    """The errors of an ask as a session posts it: the server assigns the id and the timestamps."""
    errors: list[str] = []
    _check(ask, errors)
    if not isinstance(ask, dict):
        return errors
    for key in SERVER_FIELDS:
        if key in ask and ask[key] is not None:
            errors.append(f"'{key}' is set by the board; leave it out")
    if ask.get("state", "open") != "open":
        errors.append("'state' must be 'open' (or left out) when an ask is posted")
    if ask.get("answers", {}) != {}:
        errors.append("'answers' must be empty (or left out) when an ask is posted")
    return errors


def validate_stored(ask) -> list[str]:
    """The errors of an ask as the board stores it."""
    errors: list[str] = []
    _check(ask, errors)
    if not isinstance(ask, dict):
        return errors
    if not (isinstance(ask.get("id"), str) and ID_RE.match(ask["id"])):
        errors.append("'id' must be a board ask id")
    if ask.get("state") not in STATES:
        errors.append(f"'state' must be one of {', '.join(STATES)}")
    if not isinstance(ask.get("answers"), dict):
        errors.append("'answers' must be an object")
    for key in ("created_at", "answered_at"):
        value = ask.get(key)
        if value is not None and not (isinstance(value, str) and TIMESTAMP.match(value)):
            errors.append(f"'{key}' must be null or a timestamp YYYY-MM-DDTHH:MM:SSZ")
    if (ask.get("state") == "answered") != (ask.get("answered_at") is not None):
        errors.append("'answered_at' is set exactly when 'state' is 'answered'")
    return errors


def is_required(question: dict) -> bool:
    return question.get("required", True) is not False


def check_value(question: dict, value) -> object | None:
    """The normalised answer when `value` fits the question, else None."""
    kind = question.get("kind")
    if kind == "choice":
        if not isinstance(value, str):
            return None
        for opt in question.get("options") or []:
            if opt["value"].lower() == value.strip().lower():
                return opt["value"]
        return None
    if kind == "confirm":
        return value if isinstance(value, bool) else None
    if kind == "text":
        if not isinstance(value, str) or len(value) > MAX_ANSWER or BAD_CHARS.search(value):
            return None
        return value.strip() or None
    return None


def validate_answers(ask: dict, answers) -> tuple[dict, list[str]]:
    """(normalised answers, errors) for the owner's answers to `ask`. Every required question needs one."""
    if not isinstance(answers, dict):
        return {}, ["'answers' must be an object"]
    questions = {q["id"]: q for q in ask.get("questions", [])}
    clean: dict[str, object] = {}
    errors: list[str] = []
    for qid, value in answers.items():
        if qid not in questions:
            errors.append(f"'{qid}' is not a question of this ask")
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        fit = check_value(questions[qid], value)
        if fit is None:
            errors.append(f"the answer to '{qid}' does not fit its kind or options")
        else:
            clean[qid] = fit
    for qid, q in questions.items():
        if is_required(q) and qid not in clean and not any(qid in e for e in errors):
            errors.append(f"'{qid}' needs an answer")
    return clean, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tld board validate-ask", description="Validate a tld ask.")
    parser.add_argument("file", help="path of the JSON ask, or - for stdin")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        ask = json.loads(text)
    except (OSError, ValueError) as exc:
        print(f"ask: cannot read a JSON ask from '{args.file}' ({exc})")
        return 1
    errors = validate_new(ask)
    for message in errors:
        print(f"ask: {message}")
    if errors:
        return 1
    print("ask: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
