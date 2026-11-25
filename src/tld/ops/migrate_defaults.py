"""Files off their default path: `tld migrate . --defaults [--write --answers FILE]` (plan 90, section 3.7).

A repository already on tld may keep a docs index, an ADR directory or a changelog where the built-in defaults do
not look (`docs/index.md`; `docs/adrs`, `docs/decisions`, `doc/adr`, `adr`; `CHANGES.md`, `HISTORY.md`; an
Unreleased heading spelled `## Unreleased` or `## [unreleased]`). `plan` finds them and gives each one question:

- `rename`: move the file to its default path through `tld ops docs-index move` (every reference is rewritten;
  never a delete, never an overwrite: a destination that exists is refused), or fix the heading spelling;
- `keep`: write the explicit key into the profile, so the file stays where it is.

Copying is not offered: it leaves two sources of truth.

It also lists, and never changes: keys now equal to a built-in default or to the base, and
`hooks.protect_paths_allow` entries nothing protects any more. With `--write` it additionally writes the
preserve-behaviour keys without a question: `git.branch_types` for branch types the existing plan manifests use,
and `docs.plan_dir: docs/plans/` when plans already live there.

Without `--write` nothing changes. `--write` needs `--answers FILE`: a JSON (or YAML) mapping from the id printed
in brackets to `rename` or `keep`, one entry per question, no other entry. Profile keys are written as text
edits of `.tld/toolkit.yaml` (comments stay); every edit is checked by parsing the result, and an edit that
cannot be proven safe is not written but printed for the owner to add by hand.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from tld.ops import docs_index
from tld.ops.migrate import NEW_PROFILE, unsafe
from tld.profile import defaults as defaults_mod
from tld.profile import patch as patch_mod
from tld.profile import validate as validate_mod

CHOICES = ("rename", "keep")
INDEX_DEFAULT = "docs/README.md"
INDEX_CANDIDATES = ("docs/index.md",)
ADR_DEFAULT = "docs/adr"
ADR_CANDIDATES = ("docs/adrs", "docs/decisions", "doc/adr", "adr")
CHANGELOG_DEFAULT = "CHANGELOG.md"
CHANGELOG_CANDIDATES = ("CHANGES.md", "HISTORY.md")
HEADING_DEFAULT = "## [Unreleased]"
HEADING_OTHER = ("## Unreleased", "## [unreleased]")
PLAN_DIR_VALUE = "docs/plans/"
MAX_ENTRIES = 500          # files looked at in one directory walk
MAX_BYTES = 1_000_000      # one file read
SAFE_PATH = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]*")
SAFE_TYPE = re.compile(r"[a-z][a-z0-9-]{0,30}")
FEATURE_BRANCH = re.compile(r"^[ \t]*feature_branch:\s*[\"']?([A-Za-z0-9._-]+)/", re.M)
SAFE_SHOWN = re.compile(r"[\x21-\x5a\x5c\x5e-\x7e]{1,200}")  # a repository-derived value we print: printable ASCII, no space, no brackets
SAFE_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}")
PROSE_SUFFIXES = (".md", ".markdown", ".rst")
FRONT_KEYS = {"allowed-tools", "allowed_tools", "hooks", "command", "commands", "tools", "permissions"}
MAX_SNAPSHOT = 20_000_000  # bytes held to put files back
MISSING = object()


class DefaultsError(ValueError):
    """A refusal to write: the message is printed as it is."""


class RolledBack(DefaultsError):
    """A write failed after others had succeeded; everything this run wrote was put back."""


@dataclass
class Change:
    kind: str                    # off-default | heading | equal | moot | preserve
    path: str                    # where the thing is now (a value for equal, moot, preserve)
    default_path: str            # where the default looks ("" for equal, moot, preserve)
    key: str                     # the answer id or profile key
    choices: tuple = ()          # the answers an off-default find takes (empty: no question)
    detail: str = ""
    value: object = None         # preserve: the value to write; heading: the spelling found


# ------------------------------------------------------------------------------------------------ reading

def _get(data: object, dotted: str):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return MISSING
        data = data[part]
    return data


def _same(a: object, b: object) -> bool:
    return type(a) is type(b) and a == b and (not isinstance(a, dict) or a.keys() == b.keys()) and \
        (not isinstance(a, dict) or all(_same(a[k], b[k]) for k in a)) and \
        (not isinstance(a, list) or all(_same(x, y) for x, y in zip(a, b)))


def _read(root: Path, rel: str) -> str | None:
    if unsafe(root, rel) or not (root / rel).is_file():
        return None
    try:
        if (root / rel).stat().st_size > MAX_BYTES:
            return None  # never a truncated read: a caller that writes the text back would lose the tail
        return (root / rel).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_file(root: Path, rel: str) -> bool:
    return not unsafe(root, rel) and (root / rel).is_file()


def _is_dir(root: Path, rel: str) -> bool:
    return not unsafe(root, rel) and (root / rel).is_dir()


def _dir_files(root: Path, rel: str) -> list[str] | None:
    """The repository-relative files under directory `rel`, or None when anything in it cannot be moved safely
    (a symbolic link, an unsafe name, a special file, too many entries, or nothing at all)."""
    out: list[str] = []
    for p in sorted((root / rel).rglob("*")):
        sub = p.relative_to(root).as_posix()
        if p.is_symlink() or unsafe(root, sub) or not SAFE_PATH.fullmatch(sub):
            return None
        if p.is_file():
            out.append(sub)
        elif not p.is_dir():
            return None
        if len(out) > MAX_ENTRIES:
            return None
    return out or None


def _heading(root: Path, rel: str) -> str | None:
    """The spelling of the Unreleased heading in `rel` when it is not the default one, else None."""
    text = _read(root, rel)
    if text is None:
        return None
    lines = [ln.rstrip() for ln in text.splitlines()]
    if HEADING_DEFAULT in lines:
        return None
    for other in HEADING_OTHER:
        if lines.count(other) == 1:
            return other
    return None


# ------------------------------------------------------------------------------------------------- the plan

def _off_default(root: Path, docs: dict) -> list[Change]:
    out: list[Change] = []
    if "index" not in docs and not _is_file(root, INDEX_DEFAULT):
        for cand in INDEX_CANDIDATES:
            if _is_file(root, cand):
                out.append(Change("off-default", cand, INDEX_DEFAULT, "docs.index",
                                  CHOICES if not unsafe(root, INDEX_DEFAULT) else ("keep",),
                                  "" if not unsafe(root, INDEX_DEFAULT) else "its default path is unsafe (a symbolic link)"))
                break
    if "adr_dir" not in docs and not _is_dir(root, ADR_DEFAULT) and not (root / ADR_DEFAULT).exists():
        for cand in ADR_CANDIDATES:
            if _is_dir(root, cand):
                files = _dir_files(root, cand)
                movable = files is not None and not any(
                    unsafe(root, ADR_DEFAULT + f[len(cand):]) or (root / (ADR_DEFAULT + f[len(cand):])).exists()
                    for f in files) and not unsafe(root, ADR_DEFAULT)
                out.append(Change("off-default", cand, ADR_DEFAULT, "docs.adr_dir",
                                  CHOICES if movable else ("keep",),
                                  "" if movable else "it cannot be moved safely (a symbolic link or an odd entry)"))
                break
    if "changelog" not in docs:
        current = CHANGELOG_DEFAULT
        if not _is_file(root, CHANGELOG_DEFAULT) and not (root / CHANGELOG_DEFAULT).exists():
            for cand in CHANGELOG_CANDIDATES:
                if _is_file(root, cand):
                    current = cand
                    ok = not unsafe(root, CHANGELOG_DEFAULT)
                    out.append(Change("off-default", cand, CHANGELOG_DEFAULT, "docs.changelog",
                                      CHOICES if ok else ("keep",), "" if ok else "its default path is unsafe"))
                    break
        if _is_file(root, current):
            found = _heading(root, current)
            if found:
                out.append(Change("heading", current, HEADING_DEFAULT, "docs.changelog.section", CHOICES,
                                  f"the heading is spelled '{found}'", found))
    return out


def _flat(data: object, prefix: str = ""):
    """Leaves of a mapping as (dotted key, value); a list is a leaf."""
    if isinstance(data, dict):
        for k, v in data.items():
            yield from _flat(v, f"{prefix}{k}.")
    elif prefix:
        yield prefix[:-1], data


def _equal_keys(root: Path, raw: dict) -> list[Change]:
    out: list[Change] = []
    table: dict[str, object] = dict(defaults_mod.STATIC)
    for section, values in defaults_mod.SECTION_DEFAULTS.items():
        if section in raw:
            table.update({f"{section}.{k}": v for k, v in values.items()})
    for key, value, path in defaults_mod.FILE_CHECKED:
        if _get(raw, key) is not MISSING and (root / path).exists():
            table[key] = value
    plan_dir = _get(raw, "docs.plan_dir")
    if isinstance(plan_dir, str):
        table["docs.plan_dir"] = "docs/plans" if (root / "docs" / "plans").is_dir() else "docs"
    for key, value in table.items():
        have = _get(raw, key)
        if key == "docs.plan_dir" and isinstance(have, str):
            have = have.rstrip("/")
        if have is not MISSING and _same(have, value):
            out.append(Change("equal", key, "", key, detail="the built-in default"))
    seen = {c.key for c in out}
    base = _base_of(root, raw)
    if base:
        for key, value in _flat(base):
            if key.startswith("tld.") or key in seen or not SAFE_KEY.fullmatch(key):
                continue
            have = _get(raw, key)
            if have is not MISSING and _same(have, value):
                out.append(Change("equal", key, "", key, detail="the base"))
    return out


def _base_of(root: Path, raw: dict) -> dict | None:
    """The cached base the profile extends (never fetched), or None."""
    tld = raw.get("tld")
    if not isinstance(tld, dict) or tld.get("extends") is None:
        return None
    try:
        from tld.profile import resolve
        _ref, base, errors, _warnings = resolve.base_for(raw, root, False)
    except Exception:  # an unreadable cache is no reason to stop a listing
        return None
    return base if isinstance(base, dict) and not errors else None


def _moot(raw: dict) -> list[Change]:
    from tld.guard import _common
    from tld.guard.protect_paths import matches
    allow = _get(raw, "hooks.protect_paths_allow")
    if not isinstance(allow, list):
        return []
    protect = _get(raw, "hooks.protect_paths")
    if not isinstance(protect, list):
        protect = list(defaults_mod.STATIC["hooks.protect_paths"])
    always = list(_common.GUARDED_WORKFLOWS) + [_common.GIT_OPS_WORKFLOW]
    for section in ("release", "git_ops"):
        name = _get(raw, f"{section}.workflow")
        if isinstance(name, str) and name and "/" not in name:
            always.append(f".github/workflows/{name}")
    out = []
    hidden = 0
    for entry in allow:
        if not isinstance(entry, str) or entry in always or entry in _common.BUILTIN_PROTECT_ALLOW:
            continue
        if not SAFE_SHOWN.fullmatch(entry):
            hidden += 1  # repository text with a control character or a space is never printed
            continue
        if not any(isinstance(p, str) and (matches(p, entry) or matches(entry, p)) for p in protect):
            out.append(Change("moot", entry, "", "hooks.protect_paths_allow", detail="no pattern protects it any more"))
    if hidden:
        out.append(Change("moot", f"{hidden} entry(ies) with unsafe characters, not shown", "",
                          "hooks.protect_paths_allow", detail="listed only"))
    return out


def _manifest_files(root: Path, plan_dir: str) -> list[str]:
    base = root / plan_dir.strip("/")
    if unsafe(root, plan_dir.strip("/")) or not base.is_dir():
        return []
    found = sorted({p.relative_to(root).as_posix() for pattern in ("*-plan.md", "*/plan.md")
                    for p in base.glob(pattern) if p.is_file()})
    return [f for f in found if not unsafe(root, f)][:MAX_ENTRIES]


def _preserve(root: Path, raw: dict) -> list[Change]:
    out: list[Change] = []
    docs = raw.get("docs") if isinstance(raw.get("docs"), dict) else {}
    plan_dir = docs.get("plan_dir")
    if "plan_dir" not in docs and _manifest_files(root, "docs/plans"):
        out.append(Change("preserve", PLAN_DIR_VALUE, "", "docs.plan_dir", value=PLAN_DIR_VALUE,
                          detail="plans already live there"))
        plan_dir = PLAN_DIR_VALUE
    git = raw.get("git") if isinstance(raw.get("git"), dict) else {}
    if "branch_types" not in git:
        default = list(defaults_mod.STATIC["git.branch_types"])
        used: set[str] = set()
        dirs = {"docs/plans", (plan_dir if isinstance(plan_dir, str) and plan_dir else "docs").strip("/") or "docs"}
        for d in sorted(dirs):
            for rel in _manifest_files(root, d):
                text = _read(root, rel)
                m = FEATURE_BRANCH.search(text or "")
                if m and SAFE_TYPE.fullmatch(m.group(1)):
                    used.add(m.group(1))
        extra = sorted(used - set(default))
        if extra:
            out.append(Change("preserve", ", ".join(default + extra), "", "git.branch_types",
                              value=default + extra, detail="branch types the existing plan manifests use"))
    return out


def plan(root: Path, raw: object) -> list[Change]:
    """Every find for the repository at `root` whose profile is `raw`. Reads files, writes nothing."""
    root = Path(root).resolve()
    if not isinstance(raw, dict):
        return []
    docs = raw.get("docs") if isinstance(raw.get("docs"), dict) else {}
    return _off_default(root, docs) + _equal_keys(root, raw) + _moot(raw) + _preserve(root, raw)


def questions(changes: list[Change]) -> list[Change]:
    return [c for c in changes if c.kind in ("off-default", "heading")]


# --------------------------------------------------------------------------------------------- the answers

def load_answers(path: str) -> dict:
    p = Path(path)
    try:
        if not p.is_file() or p.is_symlink() or p.stat().st_size > 65536:
            raise DefaultsError(f"--answers {path}: not a regular file of at most 64 KiB")
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DefaultsError(f"--answers {path}: cannot read it: {exc}") from None
    if not isinstance(data, dict):
        raise DefaultsError(f"--answers {path}: must be a mapping from a question id to rename or keep")
    return data


def check_answers(changes: list[Change], answers: object) -> None:
    if not isinstance(answers, dict):
        raise DefaultsError("the answers must be a mapping from a question id to rename or keep")
    asked = {c.key: c for c in questions(changes)}
    for key, value in answers.items():
        if key not in asked:
            raise DefaultsError(f"unknown answer '{key}' (the questions are: {', '.join(asked) or 'none'})")
        if value not in asked[key].choices:
            raise DefaultsError(f"unknown answer {value!r} for '{key}' (one of: {', '.join(asked[key].choices)})")
    missing = [k for k in asked if k not in answers]
    if missing:
        raise DefaultsError(f"no answer for: {', '.join(missing)}")


# --------------------------------------------------------------------------------------------- the writes

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def _front_matter_refusal(text: str) -> bool:
    """True for a file whose YAML front matter configures an agent (tools, hooks, a command) or cannot be read."""
    if not text.startswith("---"):
        return False
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() in ("---", "...")), None)
    if end is None:
        return True
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return True
    return isinstance(data, dict) and bool(FRONT_KEYS & {str(k).lower() for k in data})


def _ctx(root: Path):
    from tld.guard import _common
    from tld.guard.action import Action, Settings
    return _common.make_ctx(Action("write", str(root), str(root), path=str(root)), Settings())


def _check_file(root: Path, f: str, src: str, ctx) -> None:
    """Why a file the move would rewrite may not be touched (DefaultsError), or return."""
    from tld.guard import protect_paths
    shown = f if SAFE_SHOWN.fullmatch(f) else "a file with unsafe characters in its name"
    if unsafe(root, f):
        raise DefaultsError(f"refused: {shown} would be rewritten but it is a symbolic link or outside the repository")
    parts = Path(f).parts
    low = f.lower()
    hand = "answer keep, or move the file by hand and update that mention yourself"
    if (not low.endswith(PROSE_SUFFIXES) or any(p.startswith(".") for p in parts) or "codeowners" in low
            or parts[-1].lower() == "skill.md"):
        raise DefaultsError(f"refused: {shown} mentions {src} and is not a plain prose file (code, config, workflow, "
                            f"agent, hidden-directory and CODEOWNERS files are never rewritten); {hand}")
    why = protect_paths.violation(ctx, str(root / f), str(root))
    if why:
        raise DefaultsError(f"refused: {shown} mentions {src} and is a protected path of this repository; {hand}")
    try:
        if (root / f).stat().st_size > MAX_BYTES:
            raise DefaultsError(f"refused: {shown} is too large to rewrite safely")
        data = (root / f).read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise DefaultsError(f"refused: {shown} is not readable UTF-8, the rewrite would damage it") from None
    if b"\r" in data:
        raise DefaultsError(f"refused: {shown} has CRLF line ends, the rewrite would change every line")
    if _front_matter_refusal(text):
        raise DefaultsError(f"refused: {shown} has front matter that configures an agent (or cannot be read); {hand}")


def _probe(root: Path, src: str, dst: str) -> list[str]:
    """The files `tld ops docs-index move SRC DST` would rewrite, from its dry run, after every check: nothing
    unsafe, protected, agent-facing, non-prose or damageable is among them. Raises DefaultsError otherwise."""
    import argparse as ap
    for rel in (src, dst):
        if unsafe(root, rel):
            raise DefaultsError(f"refused: {unsafe(root, rel)}")
    probe = ap.Namespace(root=str(root), src=src, dst=dst, profile=None, apply=False, exclude=[], json=True)
    pout = io.StringIO()
    with contextlib.redirect_stdout(pout), contextlib.redirect_stderr(io.StringIO()):
        rc = docs_index.run_move(probe)
    try:
        planned = json.loads(pout.getvalue())["changes"] if rc == 0 else None
    except (ValueError, KeyError):
        planned = None
    if planned is None:
        raise DefaultsError(f"cannot plan the move of {src} to {dst}")
    ctx = _ctx(root)
    files = sorted({c["file"] for c in planned})
    for f in files:
        _check_file(root, f, src, ctx)
    return files


def _tracked_clean(root: Path, paths: list[str]) -> None:
    """Every path is tracked by git and equals HEAD, so staging what the move rewrites sweeps in nothing else and a
    rollback can restore it. Anything else (no repository, untracked, edited, a git error) refuses."""
    paths = [p for p in dict.fromkeys(paths) if (root / p).exists()]
    if not paths:
        return
    listed = _git(root, "ls-files", "-z", "--", *paths)
    if listed.returncode != 0 or {p for p in listed.stdout.decode("utf-8", "replace").split("\0") if p} != set(paths):
        raise DefaultsError("refused: a file the rename touches is not tracked by git (or this is not a git "
                            "repository); commit it first, or answer keep")
    if _git(root, "diff", "--quiet", "HEAD", "--", *paths).returncode != 0:
        raise DefaultsError("refused: a file the rename touches has uncommitted changes that staging would sweep "
                            "in (or git could not tell); commit or stash them first, or answer keep")


class Snapshot:
    """The bytes of every file a rename may touch, taken just before the first write that can change it, so a
    failure puts all of them back (a path that did not exist is removed again)."""

    def __init__(self, root: Path) -> None:
        self.root, self.saved, self.size = root, {}, 0

    def add(self, paths: list[str]) -> None:
        for p in paths:
            if p in self.saved:
                continue
            path = self.root / p
            if path.is_symlink() or unsafe(self.root, p):
                raise DefaultsError(f"refused: {p} is unsafe")
            if path.is_file():
                data = path.read_bytes()
                self.size += len(data)
                if self.size > MAX_SNAPSHOT:
                    raise DefaultsError("refused: the files a rename touches are too large to put back safely")
                self.saved[p] = data
            elif path.exists():
                raise DefaultsError(f"refused: {p} is not a regular file")
            else:
                self.saved[p] = None

    def restore(self) -> list[str]:
        problems: list[str] = []
        for p, data in self.saved.items():
            path = self.root / p
            try:
                if data is None:
                    if path.is_file() and not path.is_symlink():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            except OSError as exc:
                problems.append(f"{p}: {type(exc).__name__}")
        for p, data in self.saved.items():  # directories a move created and left empty
            parent = (self.root / p).parent
            while data is None and parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        _git(self.root, "reset", "-q", "HEAD", "--", *self.saved)
        return problems


def _move(root: Path, src: str, dst: str, snap: Snapshot | None = None) -> tuple[str, list[str]]:
    """`tld ops docs-index move SRC DST --apply` as a function; its output is captured. Returns the summary line
    and the files it rewrote (plus the moved file). Raises DefaultsError on failure; with a snapshot the caller
    can put everything back."""
    import argparse as ap
    files = _probe(root, src, dst)
    if snap is not None:
        snap.add(files + [src, dst])
    args = ap.Namespace(root=str(root), src=src, dst=dst, profile=None, apply=True, exclude=[], json=False)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = docs_index.run_move(args)
    except OSError as exc:
        raise DefaultsError(f"cannot move {src} to {dst}: {type(exc).__name__}") from None
    if rc != 0:
        raise DefaultsError(f"cannot move {src} to {dst}: {(err.getvalue() or out.getvalue()).strip()}")
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    return (lines[-1] if lines else f"move: moved {src} -> {dst}"), [dst if f == src else f for f in files] + [dst]


def _safe_value(root: Path, rel: str) -> str:
    if not SAFE_PATH.fullmatch(rel) or ".." in Path(rel).parts or unsafe(root, rel):
        raise DefaultsError(f"'{rel}' is not a safe repository path")
    return rel


def set_key(text: str, key: str, value: object) -> str:
    """Set `section.child` in profile text as a text edit (comments stay) and prove the result: it must parse to
    exactly the old data plus that one key. Raises DefaultsError otherwise."""
    section, _, child = key.partition(".")
    if not child or "." in child:
        raise DefaultsError(f"cannot edit '{key}'")
    try:
        before = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise DefaultsError(f"the profile is not valid YAML: {exc}") from None
    if not isinstance(before, dict) or (section in before and not isinstance(before[section], dict)):
        raise DefaultsError(f"'{section}' is not a mapping")
    if child in (before.get(section) or {}):
        raise DefaultsError(f"'{key}' is already written")
    lines = patch_mod.split_lines(text)
    start = patch_mod.find_key(lines, section, 0)
    if start is None:
        head = text if text.endswith("\n") or not text else text + "\n"
        new = head + ("\n" if head else "") + patch_mod.render(section, {child: value}, 0)
    else:
        if not re.match(r"^" + re.escape(section) + r"[ \t]*:[ \t]*(#.*)?$", lines[start].rstrip("\n")):
            raise DefaultsError(f"'{section}' is not written as a block")
        end = patch_mod.block_end(lines, start)
        indent = 2
        for ln in lines[start + 1:end + 1]:
            if ln.strip() and not ln.strip().startswith("#"):
                indent = patch_mod.indent_of(ln)
                break
        piece = patch_mod.render(child, value, indent)
        last = lines[end]
        if not last.endswith("\n"):
            lines[end] = last + "\n"
        new = "".join(lines[:end + 1]) + piece + "".join(lines[end + 1:])
    want = copy.deepcopy(before)
    if not isinstance(want.get(section), dict):
        want[section] = {}
    want[section][child] = value
    try:
        got = yaml.safe_load(new)
    except yaml.YAMLError:
        got = None
    if got != want:
        raise DefaultsError(f"cannot edit '{key}' safely in this profile")
    return new


def _rename_heading(root: Path, rel: str, found: str, snap: Snapshot) -> str:
    text = _read(root, rel)
    if text is None:
        raise DefaultsError(f"cannot read {rel}")
    lines = text.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.rstrip() == found]
    if len(hits) != 1 or any(ln.rstrip() == HEADING_DEFAULT for ln in lines):
        raise DefaultsError(f"{rel}: the heading '{found}' is not a single line to rename")
    ending = lines[hits[0]][len(lines[hits[0]].rstrip("\r\n")):]
    lines[hits[0]] = HEADING_DEFAULT + ending
    snap.add([rel])
    (root / rel).write_text("".join(lines), encoding="utf-8")
    return f"renamed the heading '{found}' to '{HEADING_DEFAULT}' in {rel}"


def _git_add(root: Path, *paths: str) -> None:
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode == 0:
        _git(root, "add", "--", *paths)


def _prepare(root: Path, c: Change, answers: dict, changes: list[Change]) -> list[tuple[str, str]]:
    """The moves one `rename` answer needs, probed and checked against git before anything is written. Raises
    DefaultsError (a refusal of this answer alone)."""
    if c.key == "docs.adr_dir":
        pairs = [(f, ADR_DEFAULT + f[len(c.path):]) for f in _dir_files(root, c.path) or []]
        if not pairs:
            raise DefaultsError(f"{c.path}: nothing to move")
    else:
        pairs = [(c.path, c.default_path)]
    touched: list[str] = []
    for src, dst in pairs:
        touched += _probe(root, src, dst) + [src]
    _tracked_clean(root, touched)
    return pairs


def apply(root: Path, changes: list[Change], answers: dict) -> list[str]:
    """Do what the answers say and write the preserve keys. Returns the messages. Raises DefaultsError before
    changing anything when the answers do not fit the questions, and RolledBack (after putting every file back
    and writing nothing to the profile) when a write fails. A rename that is refused before any write is
    reported as `not done:` and the other answers go on."""
    root = Path(root).resolve()
    check_answers(changes, answers)
    messages: list[str] = []
    edits: list[tuple[str, object]] = []
    staged: list[str] = []
    changelog_file, changelog_section = CHANGELOG_DEFAULT, HEADING_DEFAULT
    changelog_touched = False
    renames = [c for c in questions(changes) if answers[c.key] == "rename" and c.key != "docs.changelog.section"]
    prepared: dict[str, list[tuple[str, str]]] = {}
    refused: set[str] = set()
    for c in renames:  # phase 1: read only
        try:
            prepared[c.key] = _prepare(root, c, answers, changes)
        except DefaultsError as exc:
            refused.add(c.key)
            messages.append(f"not done: {c.key}: {exc}")
    snap = Snapshot(root)
    try:  # phase 2: one transaction
        for c in questions(changes):
            choice = answers[c.key]
            if c.key in refused:
                continue
            try:
                if c.key in prepared:
                    for src, dst in prepared[c.key]:
                        msg, files = _move(root, src, dst, snap)
                        messages.append(msg)
                        staged += files
                    changelog_touched = changelog_touched or c.key == "docs.changelog"
                elif c.key == "docs.index":
                    edits.append(("docs.index", _safe_value(root, c.path)))
                elif c.key == "docs.adr_dir":
                    edits.append(("docs.adr_dir", _safe_value(root, c.path)))
                    if _is_file(root, f"{c.path}/README.md"):
                        edits.append(("docs.adr_index", _safe_value(root, f"{c.path}/README.md")))
                elif c.key == "docs.changelog":
                    changelog_touched = True
                    changelog_file = _safe_value(root, c.path)
                elif c.key == "docs.changelog.section":
                    changelog_touched = True
                    if choice == "rename":
                        moved = "docs.changelog" in prepared
                        target = CHANGELOG_DEFAULT if moved else c.path
                        if not moved:
                            _tracked_clean(root, [target])
                            _check_file(root, target, c.path, _ctx(root))
                        messages.append(_rename_heading(root, target, str(c.value), snap))
                        staged.append(target)
                    else:
                        if c.value not in HEADING_OTHER:
                            raise DefaultsError(f"'{c.value}' is not a known heading")
                        changelog_section = str(c.value)
            except DefaultsError as exc:
                if c.key in prepared or (c.key == "docs.changelog.section" and choice == "rename"):
                    raise
                messages.append(f"not done: {c.key}: {exc}")
    except (DefaultsError, OSError) as exc:
        problems = snap.restore()
        raise RolledBack(f"{exc}; everything this run changed was put back and nothing was written to the profile"
                         + (f" (could not restore: {'; '.join(problems)})" if problems else "")) from None
    if changelog_touched and (changelog_file, changelog_section) != (CHANGELOG_DEFAULT, HEADING_DEFAULT):
        edits.append(("docs.changelog", {"file": changelog_file, "section": changelog_section, "policy": "unreleased"}))
    for c in changes:
        if c.kind == "preserve":
            edits.append((c.key, c.value))
    profile = root / NEW_PROFILE
    if edits:
        if unsafe(root, NEW_PROFILE) or not profile.is_file():
            messages.append(f"not written: {NEW_PROFILE} is missing or unsafe; add " +
                            ", ".join(f"{k}: {v!r}" for k, v in edits) + " by hand")
        else:
            text = original = profile.read_text(encoding="utf-8")
            for key, value in edits:
                try:
                    text = set_key(text, key, value)
                    messages.append(f"wrote {key}: {value!r}")
                except DefaultsError as exc:
                    messages.append(f"not written: {key}: {exc}; add `{key}: {value!r}` to {NEW_PROFILE} by hand")
            if text != original:
                profile.write_text(text, encoding="utf-8")
                staged.append(NEW_PROFILE)
    staged = [p for p in dict.fromkeys(staged) if (root / p).exists() or (root / p).is_symlink()]
    if staged:
        _git_add(root, *staged)
    return messages


# ------------------------------------------------------------------------------------------------ the output

def render(root: Path, changes: list[Change], write: bool) -> str:
    out = [f"tld migrate --defaults: {root}" + ("" if write else " (dry run; --write --answers FILE applies it)")]
    asks = questions(changes)
    if not asks:
        out.append("nothing is off its default path")
    else:
        out.append(f"Off their default path ({len(asks)}): one question each, rename or keep "
                   "(rename moves it to the default; keep writes the explicit key)")
        for c in asks:
            tail = f"  [{c.detail}]" if c.detail else ""
            out.append(f"  [{c.key}] {c.path} (default: {c.default_path}): {' | '.join(c.choices)}{tail}")
    equal = [c for c in changes if c.kind == "equal"]
    if equal:
        out.append("Keys now equal to a default or the base (listed only; delete them by hand to follow the default):")
        out += [f"  {c.key}: same as {c.detail}" for c in equal]
    moot = [c for c in changes if c.kind == "moot"]
    if moot:
        out.append("hooks.protect_paths_allow entries made moot (listed only):")
        out += [f"  {c.path}: {c.detail}" for c in moot]
    keep = [c for c in changes if c.kind == "preserve"]
    if keep:
        out.append("Preserve behaviour (written by --write, no question):")
        out += [f"  {c.key}: {c.path} ({c.detail})" for c in keep]
    return "\n".join(out)


def note_for(root: Path, raw: object) -> str | None:
    """One line for `tld migrate` where it says there is nothing to migrate, when finds exist."""
    try:
        n = len(questions(plan(root, raw)))
    except Exception:  # a hint never stops a plain dry run
        return None
    return f"{n} file(s) are off their default path: run tld migrate . --defaults" if n else None


def run(root: Path, write: bool, answers_path: str | None) -> int:
    """The `--defaults` mode of `tld migrate`. Exit 0 done, 1 refused or invalid profile, 2 usage."""
    root = Path(root).resolve()
    if write and not answers_path:
        print("tld migrate: --write with --defaults needs --answers FILE (one answer per question)", file=sys.stderr)
        return 2
    if answers_path and not write:
        print("tld migrate: --answers needs --write", file=sys.stderr)
        return 2
    why = unsafe(root, NEW_PROFILE)
    profile = root / NEW_PROFILE
    if why or not profile.is_file():
        print(f"tld migrate: {why or f'no {NEW_PROFILE} in {root}; run tld migrate . first'}", file=sys.stderr)
        return 1
    try:
        raw = yaml.safe_load(profile.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        print(f"tld migrate: {NEW_PROFILE}: cannot read it: {str(exc)!r}", file=sys.stderr)
        return 1
    if not isinstance(raw, dict):
        print(f"tld migrate: {NEW_PROFILE}: the profile must be a YAML mapping", file=sys.stderr)
        return 1
    changes = plan(root, raw)
    print(render(root, changes, write))
    if not write:
        return 0
    try:
        messages = apply(root, changes, load_answers(answers_path))
    except RolledBack as exc:
        print(f"tld migrate: not done: {exc}", file=sys.stderr)
        return 1
    except DefaultsError as exc:
        print(f"tld migrate: {exc}", file=sys.stderr)
        return 2
    print()
    for m in messages:
        print(f"  {m}")
    after = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    errors, warnings, _ = validate_mod.validate(after, root)
    print()
    print(f"Validation of {NEW_PROFILE}:")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  error: {e}")
    if not errors:
        print("  OK")
    return 1 if errors or any(m.startswith("not ") for m in messages) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld migrate --defaults", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--answers", metavar="FILE")
    args = ap.parse_args(argv)
    return run(Path(args.root), args.write, args.answers)


if __name__ == "__main__":
    sys.exit(main())
