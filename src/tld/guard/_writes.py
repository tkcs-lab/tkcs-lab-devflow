"""The paths a Bash command writes, for guards that need the targets and not the protect checks."""
from __future__ import annotations

import glob as globmod
import os
from collections.abc import Iterator

from tld.guard import protect_paths
from tld.guard._common import Ctx
from tld.guard._gitgh import iter_items
from tld.guard._shell import ParseError, is_dynamic


class TooManyPaths(Exception):
    """The argument is the path that expanded to more than protect_paths.BRACE_CAP words."""


def write_targets(ctx: Ctx, command: str) -> Iterator[tuple[str, str]]:
    """Yield (path, directory) for every path `command` writes, as check_bash checks it."""
    try:
        items = list(iter_items(ctx.cwd, command))
    except ParseError:
        return
    seen_env: dict[str, str] = {}  # NAME=value assignments from earlier simple commands
    for it in items:
        for name, value in it.env.items():
            if value and not is_dynamic(value):
                seen_env[name] = value
        for path in protect_paths.written_paths(it):
            path = protect_paths._resolve_env(path, {**seen_env, **it.env})
            if is_dynamic(path):
                continue
            words = protect_paths.expand_braces(path)
            if words is None:
                raise TooManyPaths(path)
            for word in words:
                yield word, it.dir
                if any(ch in word for ch in "*?["):
                    for match in globmod.glob(os.path.join(it.dir, os.path.expanduser(word))):
                        yield match, it.dir
