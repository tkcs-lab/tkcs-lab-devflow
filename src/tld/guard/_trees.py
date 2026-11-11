"""Whole-directory writes for `protect-paths`: a recursive `cp` / `rsync` of a directory, `git checkout <ref> --
<dir>` and `git restore --source <ref> <dir>`, and archives extracted with `tar x` or `unzip`.

A directory written as a whole is denied when it is the repository root, lies inside a protected tree, would hold a
protected path (an anchored pattern under it, such as `.github/workflows/**` under `.github`) or holds an existing
protected file. When the source tree or the archive can be read, the files it would write are checked one by one.
"""
from __future__ import annotations

import glob as globmod
import os
import re

from tld.guard import protect_paths as pp
from tld.guard._common import Ctx
from tld.guard._gitgh import Item
from tld.guard._shell import base, is_dynamic

TREE_CAP = 20000  # files looked at under one directory or in one archive; more is denied
SKIP_DIRS = ("node_modules", ".venv", "__pycache__")


def _patterns(ctx: Ctx) -> list[str]:
    return (ctx.list_key("protect_paths", pp.DEFAULT_PROTECT_PATHS) + pp.ALWAYS_PROTECTED + list(pp.GUARDED_WORKFLOWS)
            + [p for p in ctx.settings.extra_protected if not p.startswith(("~", "/"))])


def _literal_prefix(pattern: str) -> str:
    pattern = pattern[2:] if pattern.startswith("./") else pattern.lstrip("/")
    cut = min([pattern.find(c) for c in "*?[" if c in pattern] or [len(pattern)])
    return pattern[:cut]


def _files_under(path_abs: str):
    """Yield the files under a directory (symlinks included, not followed); raises OverflowError past TREE_CAP."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(path_abs):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        links = [os.path.join(d, "x") for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames + links:  # a linked directory: anything may be under it
            seen += 1
            if seen > TREE_CAP:
                raise OverflowError
            yield os.path.relpath(os.path.join(dirpath, fn), path_abs)


def dir_violation(ctx: Ctx, path: str, here: str) -> str | None:
    """`path` is written as a whole tree (a recursive copy, a checkout of a directory, an archive extracted into
    it): denied when it is the repository root, lies in a protected tree, would hold a protected path (an anchored
    pattern under it such as `.github/workflows/**` under `.github`) or holds an existing protected file."""
    msg = pp.violation(ctx, os.path.join(path, "x"), here)
    if msg:
        return msg
    path_abs = pp._abspath(path, here)
    for cand in dict.fromkeys([path_abs, os.path.realpath(path_abs)]):
        for root in dict.fromkeys([os.path.normpath(ctx.project_dir), os.path.realpath(ctx.project_dir)]):
            rel = os.path.relpath(cand, root)
            if rel == ".." or rel.startswith("../"):
                continue
            if rel == ".":
                return (f"blocked: `{path}` is the repository root, so this writes every path in it, protected ones "
                        "included. Write the individual files you need instead.")
            for pat in _patterns(ctx):
                prefix = _literal_prefix(pat)
                if "/" in pat.strip("/") and prefix.startswith(rel + "/"):
                    return (f"blocked: `{rel}` holds the protected path `{prefix.rstrip('/') or pat}` ({pat}), so "
                            "writing the whole directory would change it. Write the individual files you need "
                            "instead.")
    if os.path.isdir(path_abs):
        try:
            for sub in _files_under(path_abs):
                msg = pp.violation(ctx, os.path.join(path_abs, sub), here)
                if msg:
                    return msg
        except OverflowError:
            return f"blocked: `{path}` holds more than {TREE_CAP} files, so it cannot be checked for protected paths."
    return None


def _copy_tree_violation(ctx: Ctx, sources: list[str], dest: str, here: str, rsync: bool) -> str | None:
    """A recursive copy of directories into `dest`: every file it would write, from the source tree as it is now;
    a source that cannot be read (a run-time value, missing) makes the whole destination the target."""
    dest_abs = os.path.join(here, os.path.expanduser(dest))
    into = os.path.isdir(dest_abs)  # cp: into an existing directory, else the copy becomes `dest` itself
    for src in sources:
        if is_dynamic(src):
            return dir_violation(ctx, dest, here)
        for one in (globmod.glob(os.path.join(here, os.path.expanduser(src))) if any(c in src for c in "*?[")
                    else [src]):
            src_abs = os.path.join(here, os.path.expanduser(one))
            if os.path.isfile(src_abs):
                continue  # a file: written_paths names its target
            if rsync:
                target = dest if one.endswith("/") or one.endswith("/.") else os.path.join(dest, os.path.basename(one))
            else:
                target = os.path.join(dest, os.path.basename(one.rstrip("/"))) if into else dest
            if not os.path.isdir(src_abs):
                msg = dir_violation(ctx, target, here)
            else:
                try:
                    msg = next((m for m in (pp.violation(ctx, os.path.join(target, f), here)
                                            for f in _files_under(src_abs)) if m), None)
                except OverflowError:
                    msg = dir_violation(ctx, target, here)
            if msg:
                return msg
    return None


def _recursive(opts: list[tuple[str, str | None]], letters: str, longs: tuple[str, ...]) -> bool:
    return any(o in longs or (o.startswith("-") and not o.startswith("--") and any(c in o[1:] for c in letters))
               for o, _ in opts)


RSYNC_VALUE = {"-e", "--rsh", "-f", "--filter", "--exclude", "--include", "--exclude-from", "--include-from", "-T",
               "--temp-dir", "--files-from", "--log-file", "--chmod", "--partial-dir", "--backup-dir", "-B",
               "--block-size", "--suffix", "--compare-dest", "--copy-dest", "--link-dest", "--rsync-path", "-M"}


def _members_violation(ctx: Ctx, names: list[str], target: str, here: str, strip: int = 0) -> str | None:
    for name in names[:TREE_CAP]:
        parts = [p for p in name.lstrip("/").split("/") if p not in ("", ".")][strip:]
        if parts:
            msg = pp.violation(ctx, os.path.join(target, *parts), here)
            if msg:
                return msg
    if len(names) > TREE_CAP:
        return dir_violation(ctx, target, here) or f"blocked: the archive holds more than {TREE_CAP} entries."
    return None


def _archive_names(kind: str, path: str) -> list[str] | None:
    try:
        if kind == "zip":
            import zipfile
            with zipfile.ZipFile(path) as zf:
                return zf.namelist()
        import tarfile
        with tarfile.open(path, "r:*") as tf:
            return tf.getnames()
    except Exception:  # noqa: BLE001 - not readable: the whole target directory is checked instead
        return None


def _tar_extract(args: list[str]) -> tuple[bool, str | None, str | None, int]:
    """(extracts, archive file, -C directory, --strip-components) of a tar command line."""
    extract, archive, directory, strip = False, None, None, 0
    words = list(args)
    if words and not words[0].startswith("-") and re.fullmatch(r"[A-Za-z]+", words[0]):
        words[0] = "-" + words[0]  # old style: `tar xzf a.tgz`
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if w.startswith("--"):
            name, eq, val = w.partition("=")
            if name in ("--extract", "--get"):
                extract = True
            elif name in ("--file", "--directory", "--strip-components"):
                if not eq:
                    val, i = (words[i] if i < len(words) else ""), i + 1
                if name == "--file":
                    archive = val
                elif name == "--directory":
                    directory = val
                elif val.isdigit():
                    strip = int(val)
        elif w.startswith("-") and len(w) > 1:
            for k, ch in enumerate(w[1:], 1):
                if ch == "x":
                    extract = True
                elif ch in "fC":
                    val = w[k + 1:] or (words[i] if i < len(words) else "")
                    if not w[k + 1:]:
                        i += 1
                    if ch == "f":
                        archive = val
                    else:
                        directory = val
                    break
    return extract, archive, directory, strip


def tree_violation(ctx: Ctx, it: Item) -> str | None:
    """Writes of whole directories: `cp -r` / `rsync` of a directory, `git checkout <ref> -- <dir>` and
    `git restore --source <ref> <dir>`, and archives extracted with `tar x` or `unzip`."""
    if not it.words:
        return None
    name, args = base(it.words[0]), it.words[1:]
    if name == "git" and it.git and it.git.sub in ("checkout", "restore"):
        gargs = it.git.args
        if it.git.sub == "checkout":
            if "--" in gargs:
                before = pp.parse_args(gargs[:gargs.index("--")], {"-b", "-B", "--orphan", "--conflict"})[0]
                paths = gargs[gargs.index("--") + 1:] if before else []
            else:
                positional = pp.parse_args(gargs, {"-b", "-B", "--orphan", "--conflict", "--pathspec-from-file"})[0]
                paths = positional[1:] if len(positional) >= 2 else []
        else:
            positional, opts = pp.parse_args(gargs, {"--source", "-s", "--pathspec-from-file"})
            source = any(o in ("--source", "-s") or (o.startswith("-s") and not o.startswith("--")) for o, _ in opts)
            paths = positional if source else []
        for path in paths:
            if is_dynamic(path):
                continue
            msg = dir_violation(ctx, "." if path.startswith(":") else path, it.dir)
            if msg:
                return msg
    elif name in ("cp", "rsync"):
        positional, opts = pp.parse_args(args, pp.VALUE_OPTS["cp"] if name == "cp" else RSYNC_VALUE)
        if name == "cp" and not _recursive(opts, "rRa", ("--recursive", "--archive")):
            return None
        if name == "rsync" and not _recursive(opts, "ra", ("--recursive", "--archive")):
            return None
        target = next((v for o, v in opts if o in pp.TARGET_DIR_OPTS), None) if name == "cp" else None
        dest, sources = (target, positional) if target else (positional[-1], positional[:-1]) if positional else (None, [])
        if not dest or is_dynamic(dest) or (name == "rsync" and re.match(r"^[^/]*:", dest)):
            return None
        return _copy_tree_violation(ctx, sources, dest, it.dir, name == "rsync")
    elif name in ("tar", "bsdtar", "gtar"):
        extract, archive, directory, strip = _tar_extract(args)
        if not extract:
            return None
        target = directory or "."
        if is_dynamic(target):
            return None
        names = _archive_names("tar", os.path.join(it.dir, os.path.expanduser(archive))) if archive and archive != "-" \
            and not is_dynamic(archive) else None
        return dir_violation(ctx, target, it.dir) if names is None else _members_violation(ctx, names, target,
                                                                                            it.dir, strip)
    elif name == "unzip":
        positional, opts = pp.parse_args(args, {"-d", "-P", "-x"})
        target = next((v for o, v in opts if o == "-d" and v), ".")
        if not positional or is_dynamic(target):
            return None
        names = None if is_dynamic(positional[0]) else _archive_names(
            "zip", os.path.join(it.dir, os.path.expanduser(positional[0])))
        return dir_violation(ctx, target, it.dir) if names is None else _members_violation(ctx, names, target, it.dir)
    return None
