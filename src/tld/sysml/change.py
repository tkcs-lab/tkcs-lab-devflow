"""The architecture change: whole replacement files with base hashes, checked and planned in memory.

A change lives in `sysml/changes/<id>/`: `proposal.md`, `model/<relpath>.sysml` (the whole new content of a
model file, or a new file) and `base.json` (the sha256 of every model file the change replaces or deletes), so a
later archive cannot silently revert a merged edit of another plan. Everything here reads and writes through
`tld.sysml.files` (bounded reads, symbolic links refused); `check_change` and `archive_plan` write nothing, only
`new_change` does, and it checks every path before it writes the first. The subset is intended to parse in SysML
v2 tools; tld does not check it against one. Model and change text is untrusted: every name echoed in a message
is escaped, and apart from an OSError of the real file system (a full disk, a permission error), which the
wrapper maps to exit 2, only ModelError and Finding leave this module. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass

from pathlib import Path

from tld.sysml.files import (
    RELPATH_RE,
    _check_components,
    check_relpath,
    check_writable,
    load_tree,
    read_text,
    sha256_text,
    write_text,
)
from tld.sysml.model import Model, _show, build
from tld.sysml.types import Finding, ModelError

CHANGES_DIR = "sysml/changes"
HEADINGS = ("## Why", "## What Changes", "## Impact")
NO_MODEL = "no model files under sysml/model (run the sysml command's init first)"
# A change id becomes a directory name and part of the archive name; a longer one would fail in the operating
# system with an OSError, which must not escape.
MAX_ID = 100

_ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_HEADING_LINE = re.compile(r"#{1,2}\s")


@dataclass(frozen=True)
class ChangeFiles:
    """What a change folder holds. `base` is None when base.json is absent or invalid, else
    `{"files": {relpath: sha256}, "removed": {relpath: sha256}}`; `overlay` is relpath -> new file text."""

    proposal: str | None
    base: dict | None
    overlay: dict[str, str]


@dataclass(frozen=True)
class ArchivePlan:
    """What an archive will do: the composed model, the relpaths to write and to delete (below sysml/model)
    and the repository-relative destination of the change folder."""

    composed: dict[str, str]
    write: tuple[str, ...]
    delete: tuple[str, ...]
    dest: str


def skeleton(id: str) -> str:
    """The text of a new proposal.md."""
    return f"# {id}\n\n" + "".join(f"{heading}\n\nTODO\n\n" for heading in HEADINGS)


def valid_id(id: str) -> str:
    """Return `id` when it is a usable change id; the only place the reserved id `archive` is checked."""
    if not isinstance(id, str) or len(id) > MAX_ID or not _ID_RE.fullmatch(id):
        shown = _show(id) if isinstance(id, str) else "?"
        raise ModelError(f"invalid id '{shown}': use lower-case words joined by hyphens")
    if id == "archive":
        raise ModelError("'archive' is reserved")
    return id


def _dir(id: str) -> str:
    return f"{CHANGES_DIR}/{valid_id(id)}"


def _parse_base(text: str | None) -> dict | None:
    """The validated content of base.json, or None when it is absent or invalid."""
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    schema = data.get("schema")
    if type(schema) is not int or schema != 1:
        return None
    out: dict[str, dict[str, str]] = {}
    for section in ("files", "removed"):
        entries = data.get(section)
        if not isinstance(entries, dict):
            return None
        for key, value in entries.items():
            if not RELPATH_RE.fullmatch(key) or not isinstance(value, str) or not _HASH_RE.fullmatch(value):
                return None
        out[section] = dict(entries)
    return out


def _dump_base(state: dict) -> str:
    data = {"schema": 1, "files": state["files"], "removed": state["removed"]}
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def new_change(root: Path, id: str, files: list[str], removes: list[str]) -> str:
    """Create or extend `sysml/changes/<id>`; returns "created" or "updated". Only ever adds.

    Everything is checked before the first write, and base.json is written last, so a failure leaves a state
    that a repeated call completes."""
    c = _dir(id)
    files = list(dict.fromkeys(files))
    removes = list(dict.fromkeys(removes))
    for rel in (*files, *removes):
        check_relpath(rel)
    base_files = load_tree(root)
    if not base_files:
        raise ModelError(NO_MODEL)
    for rel in (*files, *removes):
        if rel not in base_files:
            raise ModelError(f"model file {rel} does not exist")
    for rel in files:
        if rel in removes:
            raise ModelError(f"{rel} cannot be both replaced and removed")

    proposal = read_text(root, f"{c}/proposal.md")
    base_text = read_text(root, f"{c}/base.json")
    state = {"files": {}, "removed": {}} if base_text is None else _parse_base(base_text)
    if state is None:
        raise ModelError(f"{c}/base.json is invalid; delete it or fix it")
    for rel in files:
        if rel in state["removed"]:
            raise ModelError(f"{rel} cannot be both replaced and removed")
    for rel in removes:
        if rel in state["files"]:
            raise ModelError(f"{rel} cannot be both replaced and removed")

    copies: dict[str, str] = {}
    for rel in files:
        dest = f"{c}/model/{rel}"
        existing = read_text(root, dest)  # a link or a non-file is refused here
        if existing is None:
            copies[dest] = base_files[rel]
        elif rel not in state["files"] and existing != base_files[rel]:
            # A copy nobody recorded a base for: its base is unknown, so recording the hash of the current
            # model file would hide another plan's merged edit from the later archive.
            raise ModelError(
                f"{_show(dest)} exists but is not recorded in base.json; move it aside, run new-change "
                f"--file {rel} and apply your edit again")
        # otherwise the existing copy is kept: it may hold an edit, and its base is recorded or identical
        state["files"].setdefault(rel, sha256_text(base_files[rel]))
    for rel in removes:
        state["removed"].setdefault(rel, sha256_text(base_files[rel]))

    targets = list(copies) + [f"{c}/base.json"]
    if proposal is None:
        targets.append(f"{c}/proposal.md")
    for path in targets:
        check_writable(root, path)

    if proposal is None:
        write_text(root, f"{c}/proposal.md", skeleton(id))
    for dest, text in copies.items():
        write_text(root, dest, text)
    write_text(root, f"{c}/base.json", _dump_base(state))
    return "created" if proposal is None and base_text is None else "updated"


def load_change(root: Path, id: str) -> ChangeFiles:
    """Read a change folder. A missing folder, a symbolic link anywhere under it or an overlay file whose name
    is not a model relpath is a ModelError."""
    c = _dir(id)
    if _check_components(root, c, "dir") is None:
        raise ModelError(f"change '{id}' does not exist")
    proposal = read_text(root, f"{c}/proposal.md")
    base = _parse_base(read_text(root, f"{c}/base.json"))
    overlay = load_tree(root, f"{c}/model")
    return ChangeFiles(proposal, base, overlay)


def compose(base_files: dict[str, str], overlay: dict[str, str], removed) -> dict[str, str]:
    """The current files, replaced and added by the overlay, minus the removed ones."""
    composed = dict(base_files)
    composed.update(overlay)
    for rel in removed:
        composed.pop(rel, None)
    return dict(sorted(composed.items()))


def _sections(proposal: str | None, file: str) -> list[Finding]:
    """The proposal findings: each heading must be present with a body that is not empty and not TODO."""
    lines = [] if proposal is None else [ln.rstrip("\r") for ln in proposal.split("\n")]
    findings: list[Finding] = []
    for heading in HEADINGS:
        at = next((i for i, ln in enumerate(lines) if ln.rstrip() == heading), None)
        if at is None:
            findings.append(Finding(file, 1, f"missing section '{heading}'"))
            continue
        body: list[str] = []
        for ln in lines[at + 1:]:
            if _HEADING_LINE.match(ln):
                break
            body.append(ln)
        text = "\n".join(body).strip()
        if text in ("", "TODO"):
            findings.append(Finding(file, at + 1, f"section '{heading}' is empty or still TODO"))
    return findings


def check_change(root: Path, id: str, base_files: dict[str, str]) -> tuple[dict[str, str], Model | None, list[Finding]]:
    """Check a change against the current model files `base_files`.

    Returns the composed files, the composed model (None when base.json is missing or invalid) and every
    finding: the change-level ones first, then those of the composed model. Writes nothing."""
    cf = load_change(root, id)
    c = _dir(id)
    base_file = f"{c}/base.json"
    findings = _sections(cf.proposal, f"{c}/proposal.md")
    if cf.base is None:
        findings.append(Finding(base_file, 1, "base.json is missing or invalid"))
        return dict(base_files), None, sorted(findings, key=lambda f: (f.file, f.line, f.message))

    replaced: dict[str, str] = cf.base["files"]
    removed: dict[str, str] = cf.base["removed"]
    problems: list[str] = []
    if not cf.overlay and not removed:
        problems.append(f"change '{id}' changes nothing")
    for rel in sorted(set(cf.overlay) | set(replaced)):
        if rel in removed:
            problems.append(f"{rel} cannot be both replaced and removed")
    for rel in sorted(cf.overlay):
        if rel not in replaced and rel in base_files:
            problems.append(f"{rel} is in the change but exists in the model; move {c}/model/{rel} aside, run new-change "
                f"--file {rel} and apply your edit again")
    for rel in sorted(replaced):
        if rel not in cf.overlay:
            problems.append(f"{rel} is listed in base.json but missing from the change")
        if rel not in base_files or sha256_text(base_files[rel]) != replaced[rel]:
            problems.append(
                f"{rel} changed since the change was written; delete {c}/model/{rel} and its entry in "
                f"base.json, run new-change --file {rel} and apply your edit again")
    for rel in sorted(removed):
        if rel not in base_files or sha256_text(base_files[rel]) != removed[rel]:
            problems.append(
                f"{rel} changed since the change was written; delete its entry in base.json and run "
                f"new-change --remove {rel} again")
    findings.extend(Finding(base_file, 1, message) for message in problems)
    findings.sort(key=lambda f: (f.file, f.line, f.message))

    composed = compose(base_files, cf.overlay, removed)
    names = {rel: f"{c}/model/{rel}" for rel in cf.overlay}
    model, model_findings = build(composed, names)
    return composed, model, findings + model_findings


def archive_plan(root: Path, id: str, today: datetime.date, composed: dict[str, str],
                 base_files: dict[str, str]) -> ArchivePlan:
    """Plan an archive in memory from a change `check_change` found clean; writes nothing.

    `write` is every relpath whose composed text is new or differs, `delete` the removed ones. A destination
    that exists is a ModelError."""
    valid_id(id)
    for rel in composed:
        check_relpath(rel)
    dest = f"{CHANGES_DIR}/archive/{today.isoformat()}-{id}"
    _check_components(root, dest, "new")
    write = tuple(rel for rel in sorted(composed) if base_files.get(rel) != composed[rel])
    delete = tuple(rel for rel in sorted(base_files) if rel not in composed)
    return ArchivePlan(composed, write, delete, dest)
