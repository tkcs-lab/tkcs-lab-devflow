#!/usr/bin/env python3
"""Validate a devflow status record (the document the board shows).

    validate_status_record.py FILE|- [--doc-id ID]

Exit 0 and `status-record: OK`, or exit 1 and one line per error, each starting `status-record: `
and naming the field in single quotes. The rules are plain Python (no schema interpreter); the schema
file plugins/devflow/schema/status-record.schema.json documents the shape. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

FIELDS = (
    "schema", "kind", "command", "project", "repo", "plan_slug", "plan_url", "feature_branch",
    "orchestrator_session", "status", "needs_you", "needs_you_reason", "needs_you_since",
    "phases", "pr", "last_event", "next_check_at", "finished_at", "updated_at",
)
ITEM_FIELDS = ("id", "title", "depends_on", "complexity", "state", "session", "branch", "started_at", "finished_at", "pr", "scope")
ITEM_REQUIRED = ITEM_FIELDS[:-2]
SCOPE_FIELDS = ("check", "in_scope", "out_of_scope_count", "collision_count", "paths", "disposition")
SCOPE_CHECKS = ("ok", "unavailable")
SCOPE_DISPOSITIONS = ("accepted", "partly_reverted", "reverted")
SCOPE_PATHS_MAX = 20
SCOPE_PATH_MAX_LEN = 300
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
PR_FIELDS = ("number", "url", "state", "ci", "awaiting")

KINDS = ("run", "maintenance")
COMMANDS = ("deps", "upstream", "land", "setup")
STATUSES = ("starting", "running", "waiting_user", "reviewing", "pr_open", "done", "failed")
ITEM_STATES = {
    "run": ("pending", "running", "merged", "failed", "gate"),
    "maintenance": ("pending", "running", "done", "failed", "gate"),
}
PR_ENUMS = {"state": ("open", "merged", "closed"), "ci": ("pending", "success", "failure"), "awaiting": ("ci", "codeowner", "none")}
NO_TIMER = ("waiting_user", "pr_open", "done", "failed")
REASON_MAX = 140

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SLUG = re.compile(r"^[a-z0-9-]+$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _is_timestamp(value) -> bool:
    if not isinstance(value, str) or not TIMESTAMP.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _count(value) -> bool:
    return _is_int(value) and value >= 0


def _check_scope(scope, where: str, kind, errors: list[str]) -> None:
    """The optional per-phase scope-drift field: counts and paths only."""
    where = f"{where} field 'scope'"
    if kind == "maintenance":
        errors.append(f"{where} is only allowed in a run record")
        return
    if not isinstance(scope, dict):
        errors.append(f"{where} must be an object")
        return
    for key in SCOPE_FIELDS:
        if key not in scope:
            errors.append(f"{where} is missing '{key}'")
    for key in scope:
        if key not in SCOPE_FIELDS:
            errors.append(f"{where} has unknown field '{key}'")
    check = scope.get("check")
    if "check" in scope and check not in SCOPE_CHECKS:
        errors.append(f"{where} field 'check' must be 'ok' or 'unavailable'")
    counts = [scope.get(k) for k in ("in_scope", "out_of_scope_count", "collision_count")]
    for key in ("in_scope", "out_of_scope_count", "collision_count"):
        if key in scope and scope[key] is not None and not _count(scope[key]):
            errors.append(f"{where} field '{key}' must be a non-negative integer or null")
    paths = scope.get("paths")
    if "paths" in scope:
        if not isinstance(paths, list):
            errors.append(f"{where} field 'paths' must be a list")
            paths = None
        elif len(paths) > SCOPE_PATHS_MAX:
            errors.append(f"{where} field 'paths' holds {len(paths)} paths, at most {SCOPE_PATHS_MAX} are allowed")
        for path in paths or []:
            if not (isinstance(path, str) and path):
                errors.append(f"{where} field 'paths' must hold non-empty strings")
            elif len(path) > SCOPE_PATH_MAX_LEN or CONTROL.search(path) or path.startswith("/") or ".." in path.split("/"):
                errors.append(f"{where} field 'paths' must hold repository-relative file paths (no control characters, no '..', at most {SCOPE_PATH_MAX_LEN} characters)")
    if "disposition" in scope and scope["disposition"] is not None and scope["disposition"] not in SCOPE_DISPOSITIONS:
        errors.append(f"{where} field 'disposition' must be null, accepted, partly_reverted or reverted")
    if check == "unavailable":
        if any(c is not None for c in counts) or paths or scope.get("disposition") is not None:
            errors.append(f"{where} must have null counts, no paths and a null disposition when 'check' is 'unavailable'")
    elif check == "ok":
        if any(c is None for c in counts):
            errors.append(f"{where} needs all three counts when 'check' is 'ok'")
        elif all(_count(c) for c in counts):
            _, out, collisions = counts
            if collisions > out:
                errors.append(f"{where} field 'collision_count' must not exceed 'out_of_scope_count'")
            if isinstance(paths, list) and len(paths) > out:
                errors.append(f"{where} field 'paths' must not hold more paths than 'out_of_scope_count'")
            if (out == 0) != (scope.get("disposition") is None) and "disposition" in scope:
                errors.append(f"{where} field 'disposition' must be null exactly when 'out_of_scope_count' is 0")


def _check_item(item, n: int, kind, errors: list[str]) -> None:
    where = f"'phases[{n}]'"
    if not isinstance(item, dict):
        errors.append(f"{where} must be an object")
        return
    for key in ITEM_REQUIRED:
        if key not in item:
            errors.append(f"{where} is missing '{key}'")
    for key in item:
        if key not in ITEM_FIELDS:
            errors.append(f"{where} has unknown field '{key}'")
    for key in ("id", "title"):
        if key in item and not _nonempty_str(item[key]):
            errors.append(f"{where} field '{key}' must be a non-empty string")
    if "depends_on" in item and not (isinstance(item["depends_on"], list) and all(isinstance(d, str) for d in item["depends_on"])):
        errors.append(f"{where} field 'depends_on' must be a list of strings")
    if "complexity" in item and item["complexity"] not in ("S", "M", None):
        errors.append(f"{where} field 'complexity' must be 'S', 'M' or null")
    if "state" in item:
        allowed = ITEM_STATES.get(kind, ITEM_STATES["run"])
        if item["state"] not in allowed:
            errors.append(f"{where} field 'state' must be one of {', '.join(allowed)}")
    for key in ("session", "branch"):
        if key in item and item[key] is not None and not isinstance(item[key], str):
            errors.append(f"{where} field '{key}' must be a string or null")
    for key in ("started_at", "finished_at"):
        if key in item and item[key] is not None and not _is_timestamp(item[key]):
            errors.append(f"{where} field '{key}' must be null or a timestamp YYYY-MM-DDTHH:MM:SSZ")
    if item.get("pr") is not None and not (_is_int(item["pr"]) and item["pr"] > 0):
        errors.append(f"{where} field 'pr' must be a positive integer or null")
    if "scope" in item:
        _check_scope(item["scope"], where, kind, errors)
    if kind == "maintenance":
        if item.get("depends_on") not in ([], None):
            errors.append(f"{where} field 'depends_on' must be empty for a maintenance record")
        if item.get("complexity") is not None:
            errors.append(f"{where} field 'complexity' must be null for a maintenance record")
        if item.get("session") is not None:
            errors.append(f"{where} field 'session' must be null for a maintenance record")


def validate(rec, doc_id: str | None = None) -> list[str]:
    """The error messages (without the `status-record: ` prefix) of a parsed record."""
    errors: list[str] = []
    if not isinstance(rec, dict):
        return ["the record must be a JSON object"]

    # Rule 1: exactly the known fields; schema is 1.
    for key in FIELDS:
        if key not in rec:
            errors.append(f"'{key}' is required")
    for key in rec:
        if key not in FIELDS:
            errors.append(f"'{key}' is not a known field")
    if "schema" in rec and not (_is_int(rec["schema"]) and rec["schema"] == 1):
        errors.append("'schema' must be 1")

    # Rule 2: kind, command, project, repo, document id, maintenance constraints.
    kind = rec.get("kind")
    command = rec.get("command")
    if "kind" in rec and kind not in KINDS:
        errors.append("'kind' must be 'run' or 'maintenance'")
        kind = None
    if "command" in rec:
        if kind == "run" and command is not None:
            errors.append("'command' must be null when 'kind' is 'run'")
        elif kind == "maintenance" and command not in COMMANDS:
            errors.append("'command' must be 'deps', 'upstream', 'land' or 'setup' when 'kind' is 'maintenance'")
        elif kind is None and command is not None and command not in COMMANDS:
            errors.append("'command' must be null, 'deps', 'upstream', 'land' or 'setup'")
    project = rec.get("project")
    if "project" in rec:
        if not (isinstance(project, str) and SLUG.match(project)):
            errors.append("'project' must match ^[a-z0-9-]+$")
        elif "--" in project:
            errors.append("'project' must not contain a double hyphen (it separates project and command)")
    if "repo" in rec and not (isinstance(rec["repo"], str) and REPO.match(rec["repo"])):
        errors.append("'repo' must look like owner/name")
    if doc_id is not None and isinstance(project, str):
        if kind == "maintenance" and command in COMMANDS:
            expected = f"{project}--{command}"
        else:
            expected = project
        if doc_id != expected:
            errors.append(f"'--doc-id' is '{doc_id}' but the document id of this record is '{expected}'")
    if kind == "maintenance":
        for key in ("plan_slug", "plan_url", "feature_branch", "next_check_at"):
            if key in rec and rec[key] is not None:
                errors.append(f"'{key}' must be null for a maintenance record")
        if "orchestrator_session" in rec:
            if command == "setup":
                if not _nonempty_str(rec["orchestrator_session"]):
                    errors.append("'orchestrator_session' must be a non-empty string for a 'setup' record")
            elif rec["orchestrator_session"] != "scheduled":
                errors.append("'orchestrator_session' must be \"scheduled\" for a maintenance record")
    elif kind == "run":
        for key in ("plan_slug", "plan_url", "feature_branch"):
            if key in rec and not _nonempty_str(rec[key]):
                errors.append(f"'{key}' must be a non-empty string for a run")
        if "orchestrator_session" in rec and not _nonempty_str(rec["orchestrator_session"]):
            errors.append("'orchestrator_session' must be a non-empty string")

    # Rule 3: enums.
    status = rec.get("status")
    if "status" in rec and status not in STATUSES:
        errors.append(f"'status' must be one of {', '.join(STATUSES)}")
    if "needs_you" in rec and not isinstance(rec["needs_you"], bool):
        errors.append("'needs_you' must be true or false")
    if "phases" in rec:
        if not isinstance(rec["phases"], list):
            errors.append("'phases' must be a list")
        else:
            for n, item in enumerate(rec["phases"]):
                _check_item(item, n, kind, errors)
    if "last_event" in rec and not isinstance(rec["last_event"], str):
        errors.append("'last_event' must be a string")
    pr = rec.get("pr")
    if "pr" in rec:
        if not isinstance(pr, dict):
            errors.append("'pr' must be an object")
        else:
            for key in PR_FIELDS:
                if key not in pr:
                    errors.append(f"'pr' is missing '{key}'")
            for key in pr:
                if key not in PR_FIELDS:
                    errors.append(f"'pr' has unknown field '{key}'")
            if pr.get("number") is not None and not (_is_int(pr["number"]) and pr["number"] > 0):
                errors.append("'pr.number' must be a positive integer or null")
            if pr.get("url") is not None and not isinstance(pr["url"], str):
                errors.append("'pr.url' must be a string or null")
            for key, allowed in PR_ENUMS.items():
                if pr.get(key) is not None and pr[key] not in allowed:
                    errors.append(f"'pr.{key}' must be null or one of {', '.join(allowed)}")
            if kind == "maintenance" and any(pr.get(key) is not None for key in PR_FIELDS):
                errors.append("'pr' must have all fields null for a maintenance record (the items carry the pull requests)")

    # Rule 4: needs_you pairing.
    needs = rec.get("needs_you")
    reason = rec.get("needs_you_reason")
    since = rec.get("needs_you_since")
    if needs is True:
        if not (isinstance(reason, str) and reason.strip()):
            errors.append("'needs_you_reason' must be non-empty when 'needs_you' is true")
        elif len(reason) > REASON_MAX:
            errors.append(f"'needs_you_reason' must be at most {REASON_MAX} characters")
        elif "\n" in reason:
            errors.append("'needs_you_reason' must be one line")
        if not _is_timestamp(since):
            errors.append("'needs_you_since' must be a timestamp when 'needs_you' is true")
    elif needs is False:
        if "needs_you_reason" in rec and reason != "":
            errors.append("'needs_you_reason' must be \"\" when 'needs_you' is false")
        if "needs_you_since" in rec and since is not None:
            errors.append("'needs_you_since' must be null when 'needs_you' is false")

    # Rule 5: timestamps, finished_at versus status.
    if "updated_at" in rec and not _is_timestamp(rec["updated_at"]):
        errors.append("'updated_at' must be a timestamp YYYY-MM-DDTHH:MM:SSZ")
    for key in ("next_check_at", "finished_at"):
        if key in rec and rec[key] is not None and not _is_timestamp(rec[key]):
            errors.append(f"'{key}' must be null or a timestamp YYYY-MM-DDTHH:MM:SSZ")
    if "finished_at" in rec and status in STATUSES:
        finished = rec["finished_at"] is not None
        if status in ("done", "failed") and not finished:
            errors.append(f"'finished_at' must be set when 'status' is '{status}'")
        if status not in ("done", "failed") and finished:
            errors.append(f"'finished_at' must be null when 'status' is '{status}'")

    # Rule 6: no timer when nobody is waiting on the clock.
    if status in NO_TIMER and rec.get("next_check_at") is not None:
        errors.append(f"'next_check_at' must be null when 'status' is '{status}'")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a devflow status record.")
    parser.add_argument("file", help="path of the JSON record, or - for stdin")
    parser.add_argument("--doc-id", help="the document id the record is stored under")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        rec = json.loads(text)
    except (OSError, ValueError) as exc:
        print(f"status-record: cannot read a JSON record from '{args.file}' ({exc})")
        return 1
    errors = validate(rec, args.doc_id)
    if errors:
        for message in errors:
            print(f"status-record: {message}")
        return 1
    print("status-record: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
