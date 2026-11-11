"""What a baseline was measured against: one hash per command over everything the command makes the agent read.

A command file of an adapter is thin ("follow playbooks/<name>.md"), so its own hash says almost nothing. The
hash of a command covers the command file, the playbook it points to, and every playbook, policy, role,
checklist or stack file reachable from that playbook through relative Markdown links (runtime.md and the
policies included). A change to any of them changes the hash, and `stale` names the command.

Refresh: `python3 evals/run.py baseline --refresh-hashes` rewrites `command_hashes` of evals/baselines/default.json
to the current files. Do it after re-running the tasks of the changed commands (or when you decide the change
cannot affect them, and say so in the commit message): the pass rates in the file are only as good as the runs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .common import BASELINES_DIR, ROOT

DEFAULT = BASELINES_DIR / "default.json"
CONTENT_DIRS = ("playbooks", "roles", "checklists", "stacks")
PLAYBOOK_REF = re.compile(r"playbooks/([a-z0-9-]+)\.md")
LINK = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)]*)?\)")


def playbook_of(command_file: Path, root: Path = ROOT) -> Path | None:
    """The playbook a thin command file points to (`.../playbooks/<name>.md`), or None."""
    m = PLAYBOOK_REF.search(command_file.read_text())
    return root / "playbooks" / f"{m.group(1)}.md" if m else None


def procedure_files(playbook: Path, root: Path = ROOT) -> list[Path]:
    """The playbook and every content file reachable from it through relative Markdown links, sorted."""
    allowed = [(root / d).resolve() for d in CONTENT_DIRS]
    seen: set[Path] = set()
    todo = [playbook.resolve()]
    while todo:
        p = todo.pop()
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        for target in LINK.findall(p.read_text()):
            if re.match(r"[a-z]+:", target):
                continue
            q = (p.parent / target).resolve()
            if any(q.is_relative_to(a) for a in allowed):
                todo.append(q)
    return sorted(seen)


def command_hash(command_file: Path, root: Path = ROOT) -> str:
    files = [command_file.resolve()]
    pb = playbook_of(command_file, root)
    if pb is not None:
        files += procedure_files(pb, root)
    h = hashlib.sha256()
    for f in files:
        h.update(str(f.relative_to(root.resolve())).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def command_hashes(root: Path = ROOT, adapter: str = "claude") -> dict[str, str]:
    """`<command>.md` -> hash, for every command of the adapter."""
    from .agents import adapter as get_adapter
    files = get_adapter(adapter).command_files(root)
    return {f"{name}.md": command_hash(path, root) for name, path in files.items()}


def stale(baseline: dict, current: dict[str, str]) -> list[str]:
    """Commands whose files changed since the baseline was written, plus commands it does not know."""
    old = baseline.get("command_hashes", {})
    return sorted(k for k in set(old) | set(current) if old.get(k) != current.get(k))


def refresh(path: Path = DEFAULT, created: str = "", root: Path = ROOT) -> list[str]:
    """Rewrite the command hashes of a baseline to the current files; returns the commands that changed."""
    data = json.loads(path.read_text())
    current = command_hashes(root)
    changed = stale(data, current)
    data["command_hashes"] = current
    if changed and created:
        data["hashes_refreshed"] = created
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return changed
