"""The safe file layer for the architecture model and its outputs.

The only module that touches the filesystem for the model; every path is repository-relative with `/`
separators. Each component from the root down is checked with `os.lstat`: a symbolic link anywhere is
refused, and so is anything that is not a directory (or, at the end, a regular file). Nothing here uses
`Path.resolve` or `os.path.realpath`. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from pathlib import Path

from tld.sysml.types import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, ModelError

MODEL_DIR = "sysml/model"
RELPATH_RE = re.compile(r"[a-z0-9_-]+(/[a-z0-9_-]+)*\.sysml")


def check_relpath(rel: str) -> str:
    """Return `rel` when it is a model relpath (below sysml/model/), else raise ModelError."""
    if not RELPATH_RE.fullmatch(rel):
        raise ModelError(f"invalid file '{rel}': use a path like core/api.sysml")
    return rel


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parts(rel_path: str) -> list[str]:
    parts = rel_path.split("/")
    if not rel_path or rel_path.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ModelError(f"invalid path '{rel_path}'")
    return parts


def _check_components(root: Path, rel_path: str, final: str = "any") -> os.stat_result | None:
    """Walk `rel_path` from `root` with lstat; return the lstat of the last component or None when absent.

    `final` is what the last component may be: "any" (a regular file or a directory), "file" (a regular
    file), "dir" (a directory), "write" (a regular file with one hard link, for a write) or "new" (it must
    not exist at all).
    """
    parts = _parts(rel_path)
    current = root
    st: os.stat_result | None = None
    for i, part in enumerate(parts):
        current = current / part
        sofar = "/".join(parts[: i + 1])
        last = i == len(parts) - 1
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return None
        if last and final == "new":
            raise ModelError(f"path '{sofar}' already exists")
        if stat.S_ISLNK(st.st_mode):
            raise ModelError(f"path '{sofar}' is a symbolic link")
        if not last:
            if not stat.S_ISDIR(st.st_mode):
                raise ModelError(f"path '{sofar}' is not a regular file or directory")
            continue
        is_dir = stat.S_ISDIR(st.st_mode)
        is_file = stat.S_ISREG(st.st_mode)
        wanted = {
            "any": is_dir or is_file,
            "file": is_file,
            "write": is_file,
            "dir": is_dir,
        }[final]
        if not wanted:
            raise ModelError(f"path '{sofar}' is not a regular file or directory")
        if final == "write" and st.st_nlink != 1:
            raise ModelError(f"path '{sofar}' has more than one hard link")
    return st


def _read_bytes(root: Path, rel_path: str) -> bytes:
    fd = os.open(root / rel_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as fh:
        return fh.read()


def _decode(rel_path: str, data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ModelError(f"{rel_path} is not valid UTF-8") from None


def read_text(root: Path, rel_path: str) -> str | None:
    """The UTF-8 text of a regular file, or None when it does not exist."""
    if _check_components(root, rel_path, "file") is None:
        return None
    return _decode(rel_path, _read_bytes(root, rel_path))


def load_tree(root: Path, base: str = MODEL_DIR) -> dict[str, str]:
    """All `.sysml` files below `root/base`, relpath (below `base`) -> text, sorted by relpath."""
    if _check_components(root, base, "dir") is None:
        return {}
    found: list[str] = []

    def walk(prefix: str) -> None:
        directory = root / base / prefix if prefix else root / base
        with os.scandir(directory) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            shown = f"{base}/{rel}"
            st = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode):
                raise ModelError(f"path '{shown}' is a symbolic link")
            if stat.S_ISDIR(st.st_mode):
                walk(rel)
            elif stat.S_ISREG(st.st_mode):
                found.append(check_relpath(rel))
            else:
                raise ModelError(f"path '{shown}' is not a regular file or directory")

    walk("")
    found.sort()
    if len(found) > MAX_FILES:
        raise ModelError(f"more than {MAX_FILES} model files")
    tree: dict[str, str] = {}
    total = 0
    for rel in found:
        shown = f"{base}/{rel}"
        data = _read_bytes(root, shown)
        if len(data) > MAX_FILE_BYTES:
            raise ModelError(f"{shown} is longer than {MAX_FILE_BYTES} bytes")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ModelError(f"the model is larger than {MAX_TOTAL_BYTES} bytes")
        tree[rel] = _decode(shown, data)
    return tree


def check_writable(root: Path, rel_path: str) -> None:
    """Run every check `write_text` makes before it opens the file; write nothing."""
    _check_components(root, rel_path, "write")


def _make_parents(root: Path, rel_path: str) -> None:
    parts = _parts(rel_path)
    for i in range(1, len(parts)):
        directory = root.joinpath(*parts[:i])
        if not directory.exists() and not os.path.islink(directory):
            os.mkdir(directory)
        # a link or a file that appeared (or was already there) is refused here
        _check_components(root, "/".join(parts[:i]), "dir")


def write_text(root: Path, rel_path: str, text: str) -> None:
    """Write `text` to a regular file below `root`, creating directories one level at a time."""
    check_writable(root, rel_path)
    _make_parents(root, rel_path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        fd = os.open(root / rel_path, flags, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ModelError(f"path '{rel_path}' is a symbolic link") from None
        raise
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))


def remove_file(root: Path, rel_path: str) -> None:
    """Delete a regular file below `root`."""
    if _check_components(root, rel_path, "file") is None:
        raise ModelError(f"path '{rel_path}' does not exist")
    os.unlink(root / rel_path)


def move_dir(root: Path, src: str, dst: str) -> None:
    """Move the directory `src` to `dst`, which must not exist; every component of both is checked."""
    if _check_components(root, src, "dir") is None:
        raise ModelError(f"path '{src}' does not exist")
    _check_components(root, dst, "new")
    _make_parents(root, dst)
    os.rename(root / src, root / dst)


__all__ = [
    "MODEL_DIR",
    "RELPATH_RE",
    "check_relpath",
    "check_writable",
    "load_tree",
    "move_dir",
    "read_text",
    "remove_file",
    "sha256_text",
    "write_text",
]
