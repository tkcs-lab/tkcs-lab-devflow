"""Command wrappers (`sudo`, `env`, `time`, `flock` ...) that run the command following them.

Standard library only. `strip_wrapper(name, rest)` returns the words of the wrapped command.
"""
from __future__ import annotations

import re
import shlex


class ParseError(ValueError):
    pass


ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
WRAPPERS = {"sudo", "doas", "env", "nice", "ionice", "timeout", "command", "builtin", "exec", "nohup",
            "stdbuf", "setsid", "chronic", "unbuffer", "time", "flock", "script", "taskset", "unshare",
            "chroot", "strace"}
WRAPPER_VALUE_OPTS = {
    "sudo": {"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "nice": {"-n"},
    "ionice": {"-c", "-n", "-p", "-P", "-u"},
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "exec": {"-a"},
    "flock": {"-w", "--timeout", "-E", "--conflict-exit-code"},
    "taskset": {"-c", "--cpu-list"},
    "chroot": {"--userspec", "--groups"},
    "strace": {"-e", "-o", "-p", "-s", "-u", "-E", "-a"},
    "unshare": set(),
    "script": {"-c", "--command"},
}
# leading positional words to skip after the options (flock: the lock file, chroot: the new root,
# taskset: the mask unless -c / -p was used)
WRAPPER_POSITIONALS = {"flock": 1, "chroot": 1, "taskset": 1}
_SCRIPT_CLUSTER = re.compile(r"^-[A-Za-z]*c$")


def script_command(rest: list[str]) -> str | None:
    """The command string of `script -c CMD`, `--command CMD`, `--command=CMD` or `-qc CMD`."""
    for k, tok in enumerate(rest):
        if tok.startswith("--command="):
            return tok[len("--command="):]
        if (tok == "--command" or _SCRIPT_CLUSTER.match(tok)) and k + 1 < len(rest):
            return rest[k + 1]
        if tok == "--":
            break
    return None


def strip_wrapper(name: str, rest: list[str]) -> list[str]:
    value_opts = WRAPPER_VALUE_OPTS.get(name, set())
    positionals = WRAPPER_POSITIONALS.get(name, 0)
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--":
            i += 1
            break
        if name == "env" and (tok in ("-S", "--split-string") or tok.startswith(("-S", "--split-string="))):
            if tok in ("-S", "--split-string"):
                if i + 1 >= len(rest):
                    return []
                value, i = rest[i + 1], i + 2
            else:
                value, i = tok.split("=", 1)[1] if tok.startswith("--") else tok[2:], i + 1
            try:
                return shlex.split(value) + rest[i:]
            except ValueError as exc:
                raise ParseError(str(exc)) from None
        if tok.startswith("-") and tok != "-":
            if name == "taskset" and tok in ("-c", "--cpu-list", "-p"):
                positionals = 0
            consumes = tok in value_opts or (name == "script" and _SCRIPT_CLUSTER.match(tok) is not None)
            i += 2 if consumes else 1
        elif name == "env" and ASSIGN.match(tok):
            i += 1
        else:
            break
    rest = rest[i + positionals:] if name != "timeout" else rest[i:]
    return rest[1:] if name == "timeout" and rest else rest
