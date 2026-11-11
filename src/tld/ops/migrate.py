"""Move a repository that still uses claude-toolkit (the `devflow` plugin) to tld.

    tld migrate [ROOT] [--write]

Without `--write` it prints the plan and changes nothing. With `--write` it applies the plan (in a git
repository it stages every change: `git mv` for the profile, `git rm` for the old workflows, `git add` for the
rest; it never commits). Then it validates the profile and prints the steps only the owner can do.

What it changes:

- `.claude/toolkit.yaml` moves to `.tld/toolkit.yaml`; an existing `.tld/toolkit.yaml` is never overwritten.
- The profile: `agents` becomes `roles` (each entry's `agent` becomes `role`), `models.*` values `opus`,
  `sonnet`, `haiku` become `strong`, `standard`, `fast`, `models.planner` and `models.orchestrator` go, the removed
  sections `toolkit` and `status` go, `.claude/toolkit.yaml` in its values becomes `.tld/toolkit.yaml`, and
  `tld.version: ">=1.0,<2"` is added. Comments are kept; when a text-level edit cannot be proven equal to the
  intended data, the profile is rewritten from the data and its comments are lost (the plan says so).
- Implementation manifests in `<docs.plan_dir>/*-plan.md`: `worker_model` becomes `worker_level` (with the
  level), `worker_model_reason` becomes `worker_level_reason`, `manual_steps_artifact` / `manual_steps_source` go.
- `.github/workflows/devflow-{land,release,git-ops}.yml` are replaced by the current `tld-*.yml` templates.
- In CLAUDE.md, AGENTS.md, README*, CONTRIBUTING*, docs/**/*.md and .github/**/*.md exactly these texts:
  `devflow:` (command and skill prefixes) becomes `tld:`, `.claude/toolkit.yaml` becomes `.tld/toolkit.yaml`
  and `DEVFLOW_` becomes `TLD_`.

Running it on a migrated repository changes nothing. Exit 0: done, or nothing to do; 1: no profile, a conflict,
or the migrated profile does not validate; 2: usage.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tld.ops.repo_admin import TEMPLATES, render_template
from tld.profile import validate as validate_mod

OLD_PROFILE = ".claude/toolkit.yaml"
NEW_PROFILE = ".tld/toolkit.yaml"
VERSION_SPEC = ">=1.0,<2"
LEVELS = {"opus": "strong", "sonnet": "standard", "haiku": "fast"}
DROPPED_MODELS = ("planner", "orchestrator")
REMOVED_SECTIONS = ("toolkit", "status")
WORKFLOWS = ("land", "release", "git-ops")
TEXT_RULES = [  # (label, pattern, replacement): only these exact texts are rewritten
    ("devflow: -> tld:", re.compile(r"(?<![\w.-])devflow:(?=[A-Za-z])"), "tld:"),
    (".claude/toolkit.yaml -> .tld/toolkit.yaml", re.compile(re.escape(OLD_PROFILE)), NEW_PROFILE),
    ("DEVFLOW_ -> TLD_", re.compile(r"(?<![\w])DEVFLOW_"), "TLD_"),
]
TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


@dataclass
class Change:
    kind: str          # move | profile | manifest | workflow | text
    path: str          # the file written (repository-relative)
    detail: str
    content: str | None = None    # new content of `path`; None for a pure move
    source: str | None = None     # the file moved or removed
    remove: bool = False          # remove `source` (no move)


@dataclass
class Plan:
    root: Path
    git: bool
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    profile: dict | None = None
    profile_text: str | None = None


# --------------------------------------------------------------------------- the profile


def _map_strings(value, fn):
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
    return fn(value) if isinstance(value, str) else value


def migrate_profile_data(data: dict) -> tuple[dict, list[str]]:
    """The profile as tld reads it, and one note per change."""
    out, notes = dict(data), []
    for key in REMOVED_SECTIONS:
        if key in out:
            out.pop(key)
            notes.append(f"'{key}' removed (tld no longer reads it)")
    if "agents" in out:
        agents = out.pop("agents")
        if "roles" in out:
            notes.append("'agents' dropped: the profile already has 'roles'")
        else:
            roles = dict(agents or {})
            if isinstance(roles.get("required"), list):
                roles["required"] = [{("role" if k == "agent" else k): v for k, v in e.items()}
                                     if isinstance(e, dict) else e for e in roles["required"]]
            out = _insert_after(out, "roles", roles, before=list(data).index("agents"))
            notes.append("'agents' renamed to 'roles' (each entry's 'agent' to 'role')")
    if isinstance(out.get("models"), dict):
        models = {}
        for key, value in out["models"].items():
            if key in DROPPED_MODELS:
                notes.append(f"'models.{key}' removed (a command's own level decides)")
                continue
            if value in LEVELS:
                notes.append(f"'models.{key}': {value} -> {LEVELS[value]}")
                value = LEVELS[value]
            models[key] = value
        if models:
            out["models"] = models
        else:
            out.pop("models")
    tld_block = out.get("tld")
    if not (isinstance(tld_block, dict) and "version" in tld_block):
        out = {"tld": {**(tld_block or {}), "version": VERSION_SPEC}, **{k: v for k, v in out.items() if k != "tld"}}
        notes.append(f"'tld.version: \"{VERSION_SPEC}\"' added")
    moved = _map_strings(out, lambda s: s.replace(OLD_PROFILE, NEW_PROFILE))
    if moved != out:
        notes.append(f"'{OLD_PROFILE}' in values -> '{NEW_PROFILE}'")
    return moved, notes


def _insert_after(d: dict, key: str, value, before: int) -> dict:
    items = list(d.items())
    items.insert(min(before, len(items)), (key, value))
    return dict(items)


def _blocks(lines: list[str]) -> list[tuple[str, int, int]]:
    """(top-level key, first line, end line) of every top-level block."""
    starts = [(m.group(1), i) for i, line in enumerate(lines) if (m := TOP_KEY.match(line))]
    return [(k, s, starts[n + 1][1] if n + 1 < len(starts) else len(lines)) for n, (k, s) in enumerate(starts)]


def migrate_profile_text(text: str, data: dict, target: dict) -> tuple[str, bool]:
    """Edit the profile text so it loads as `target`, keeping comments. (text, comments kept)."""
    lines = text.splitlines(keepends=True)
    for key, start, end in reversed(_blocks(lines)):
        block = lines[start:end]
        if key in REMOVED_SECTIONS:
            del lines[start:end]
        elif key == "agents" and "roles" in data:
            del lines[start:end]
        elif key == "agents":
            block[0] = re.sub(r"^agents(\s*:)", r"roles\1", block[0])
            block = [re.sub(r"(?<![\w-])agent(\s*:)", r"role\1", ln) for ln in block]
            lines[start:end] = block
        elif key == "models":
            kept = []
            for ln in block:
                if re.match(rf"^\s+({'|'.join(DROPPED_MODELS)})\s*:", ln):
                    continue
                kept.append(re.sub(r"^(\s+[\w-]+\s*:\s*)(opus|sonnet|haiku)\b",
                                   lambda m: m.group(1) + LEVELS[m.group(2)], ln))
            if not any(re.match(r"^\s+[\w-]+\s*:", ln) for ln in kept[1:]) and ":" in kept[0] \
                    and not kept[0].split(":", 1)[1].strip():
                kept = []  # nothing left under models:
            lines[start:end] = kept
    new = "".join(lines).replace(OLD_PROFILE, NEW_PROFILE)
    tld_block = data.get("tld")
    if not (isinstance(tld_block, dict) and "version" in tld_block) and "tld" not in data:
        out = new.splitlines(keepends=True)
        first = next((i for i, ln in enumerate(out) if TOP_KEY.match(ln)), len(out))
        out[first:first] = [f'tld:\n  version: "{VERSION_SPEC}"\n', "\n"]
        new = "".join(out)
    try:
        if yaml.safe_load(new) == target:
            return new, True
    except yaml.YAMLError:
        pass
    header = "".join(ln for ln in text.splitlines(keepends=True)[:3] if ln.startswith("#"))
    return header + yaml.safe_dump(target, sort_keys=False, allow_unicode=True, width=110), False


# --------------------------------------------------------------------------- manifests


MANIFEST_RULES = [
    (re.compile(r"^(\s*)worker_model(\s*:\s*)(opus|sonnet|haiku)\b", re.M), lambda m: f"{m[1]}worker_level{m[2]}{LEVELS[m[3]]}"),
    (re.compile(r"^(\s*)worker_model_reason(\s*:)", re.M), lambda m: f"{m[1]}worker_level_reason{m[2]}"),
    (re.compile(r"^\s*manual_steps_(artifact|source)\s*:.*\n", re.M), lambda m: ""),
]


def migrate_manifest_text(text: str) -> tuple[str, int]:
    """Rewrite the legacy manifest keys inside the '## Implementation manifest' yaml block."""
    start = text.find("## Implementation manifest")
    if start < 0:
        return text, 0
    m = re.search(r"```yaml[^\n]*\n(.*?\n)```", text[start:], re.S)
    if not m:
        return text, 0
    body, count = m.group(1), 0
    for pattern, repl in MANIFEST_RULES:
        body, n = pattern.subn(repl, body)
        count += n
    a, b = start + m.start(1), start + m.end(1)
    return text[:a] + body + text[b:], count


# --------------------------------------------------------------------------- the plan


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _tracked(root: Path, rel: str) -> bool:
    return _git(root, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def text_files(root: Path) -> list[Path]:
    found: set[Path] = set()
    for pattern in ("CLAUDE.md", "AGENTS.md", "README*", "CONTRIBUTING*"):
        found |= {p for p in root.glob(pattern) if p.is_file()}
    for base in ("docs", ".github"):
        if (root / base).is_dir():
            found |= {p for p in (root / base).rglob("*.md") if p.is_file()}
    return sorted(p for p in found if not p.is_symlink() and ".git" not in p.relative_to(root).parts)


def rewrite_text(text: str) -> tuple[str, list[str]]:
    counts = []
    for label, pattern, repl in TEXT_RULES:
        text, n = pattern.subn(repl, text)
        if n:
            counts.append(f"{label} ({n})")
    return text, counts


def _workflow(root: Path, name: str, profile: dict) -> str:
    template = (TEMPLATES / f"tld-{name}.yml").read_text()
    params = {"main_branch": str((profile.get("git") or {}).get("main_branch") or "main")}
    if name == "release":
        old = (root / ".github" / "workflows" / f"devflow-{name}.yml").read_text(errors="replace")
        m = re.search(r'^\s*PREFIX:\s*"([^"]*)"', old, re.M)
        prefix = m.group(1) if m and "__" not in m.group(1) else "v"
        params.update(tag_prefix=prefix, release_environment="tld-release")
    return render_template(template, params)


def build_plan(root: Path) -> Plan:
    plan = Plan(root=root, git=_git(root, "rev-parse", "--is-inside-work-tree").returncode == 0)
    old, new = root / OLD_PROFILE, root / NEW_PROFILE
    if old.is_file() and new.is_file():
        plan.notes.append(f"both {OLD_PROFILE} and {NEW_PROFILE} exist: {NEW_PROFILE} is kept and migrated, "
                          f"{OLD_PROFILE} is left alone; delete it once you have compared the two")
        source = new
    elif old.is_file():
        source = old
        plan.changes.append(Change("move", NEW_PROFILE, f"{OLD_PROFILE} -> {NEW_PROFILE}"
                                   + (" (git mv)" if plan.git and _tracked(root, OLD_PROFILE) else ""),
                                   source=OLD_PROFILE))
    elif new.is_file():
        source = new
    else:
        plan.errors.append(f"no profile: neither {OLD_PROFILE} nor {NEW_PROFILE} exists in {root}")
        return plan
    text = source.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        plan.errors.append(f"{source.relative_to(root)}: not valid YAML: {exc}")
        return plan
    if not isinstance(data, dict):
        plan.errors.append(f"{source.relative_to(root)}: the profile must be a YAML mapping")
        return plan
    target, notes = migrate_profile_data(data)
    plan.profile = target
    plan.profile_text = text
    if notes:
        new_text, kept = migrate_profile_text(text, data, target)
        if not kept:
            notes.append("the profile is rewritten from its data: its comments are lost, add back the ones you need")
        plan.profile_text = new_text
        plan.changes.append(Change("profile", NEW_PROFILE, "; ".join(notes), content=new_text))

    plan_dir = root / str((target.get("docs") or {}).get("plan_dir") or "docs/").rstrip("/")
    if plan_dir.is_dir():
        for doc in sorted(plan_dir.glob("*-plan.md")):
            body, n = migrate_manifest_text(doc.read_text())
            if n:
                plan.changes.append(Change("manifest", doc.relative_to(root).as_posix(),
                                           f"{n} legacy manifest key(s): worker_model -> worker_level, "
                                           "manual_steps_* removed", content=body))

    for name in WORKFLOWS:
        legacy = f".github/workflows/devflow-{name}.yml"
        if not (root / legacy).is_file():
            continue
        dest = f".github/workflows/tld-{name}.yml"
        if (root / dest).exists():
            plan.changes.append(Change("workflow", legacy, f"remove {legacy} ({dest} already exists, kept)",
                                       source=legacy, remove=True))
        else:
            plan.changes.append(Change("workflow", dest, f"{legacy} -> {dest} (the current tld template)",
                                       content=_workflow(root, name, target), source=legacy, remove=True))

    for path in text_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            original = path.read_text()
        except UnicodeDecodeError:
            continue
        already = next((c for c in plan.changes if c.path == rel and c.content is not None), None)
        body, counts = rewrite_text(already.content if already else original)
        if counts:
            if already:
                already.content, already.detail = body, already.detail + "; " + ", ".join(counts)
            else:
                plan.changes.append(Change("text", rel, ", ".join(counts), content=body))
    return plan


# --------------------------------------------------------------------------- apply, validate, checklist


def apply(plan: Plan) -> None:
    root, staged = plan.root, []
    for c in plan.changes:
        if c.kind == "move":
            (root / c.path).parent.mkdir(parents=True, exist_ok=True)
            if plan.git and _tracked(root, c.source):
                r = _git(root, "mv", "--", c.source, c.path)
                if r.returncode != 0:
                    raise RuntimeError(f"git mv {c.source} {c.path}: {r.stderr.strip()}")
            else:
                (root / c.source).rename(root / c.path)
            staged.append(c.path)
    for c in plan.changes:
        if c.content is not None:
            target = root / c.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(c.content)
            staged.append(c.path)
        if c.remove and c.source and (root / c.source).exists():
            if plan.git and _tracked(root, c.source):
                _git(root, "rm", "-q", "--", c.source)
            else:
                (root / c.source).unlink()
    if plan.git and staged:
        _git(root, "add", "--", *dict.fromkeys(staged))


def validate_profile(plan: Plan) -> tuple[list[str], list[str]]:
    errors, warnings, _ = validate_mod.validate(plan.profile, plan.root)
    return errors, warnings


def checklist(plan: Plan) -> list[str]:
    root, profile = plan.root, plan.profile or {}
    main = str((profile.get("git") or {}).get("main_branch") or "main")
    items = [
        "In every Claude Project whose sessions use this repository: remove the marketplace claude-toolkit, add the "
        "marketplace tkcs-lab/tkcs-lab-devflow, enable the plugin tld, and disable devflow and the stack-* plugins.",
        "Rename the repository secrets DEVFLOW_* to TLD_*. Move TLD_AGENT_TOKEN into the environment tld-agent and "
        f"TLD_RELEASE_TOKEN into the environment tld-release (both limited to {main}); delete the repository-level copies.",
        "Board: deploy the board server (docs/guides/board-server.md in tkcs-lab/tkcs-lab-devflow), set TLD_BOARD_URL and TLD_BOARD_TOKEN in the "
        "cloud environment's settings, and allow the board's host in its network settings.",
        "With an owner token: tld ops repo-admin audit --policy <policy>, then tld ops repo-admin apply --policy "
        "<policy> --yes for the rulesets tld-main and tld-tags and the environments tld-agent and tld-release.",
    ]
    leftovers = []
    if (root / ".claude" / "admin-policy.yaml").exists():
        leftovers.append(".claude/admin-policy.yaml (move it to .tld/admin-policy.yaml and update admin.policy)")
    if (root / ".claude" / "devflow").exists() or (root / ".claude" / "devflow").is_symlink():
        leftovers.append(".claude/devflow (the old script root; delete it)")
    settings = root / ".claude" / "settings.json"
    if settings.is_file() and re.search(r"devflow|claude-toolkit", settings.read_text(errors="replace")):
        leftovers.append(".claude/settings.json (it still names devflow or claude-toolkit)")
    if (root / OLD_PROFILE).exists() and (root / NEW_PROFILE).exists() and \
            not any(c.kind == "move" for c in plan.changes):
        leftovers.append(f"{OLD_PROFILE} (both profiles exist; delete the old one)")
    if (root / ".git" / "devflow").exists():
        leftovers.append(".git/devflow (old local hook state; safe to delete)")
    admin_policy = str((profile.get("admin") or {}).get("policy") or "")
    if admin_policy.startswith(".claude/"):
        leftovers.append(f"admin.policy is {admin_policy}: move the file under .tld/ and update the key")
    wf_dir = root / ".github" / "workflows"
    if wf_dir.is_dir():
        named = sorted(p.name for p in wf_dir.glob("*.y*ml")
                       if not p.name.startswith("devflow-") and "DEVFLOW_" in p.read_text(errors="replace"))
        if named:
            leftovers.append("workflows that still read DEVFLOW_* secrets: " + ", ".join(named))
    if leftovers:
        items.append("Remove or update the claude-toolkit leftovers: " + "; ".join(leftovers) + ".")
    items.append("Review and merge the migration pull request (a session never merges it).")
    return items


def render(plan: Plan, write: bool) -> str:
    out = [f"tld migrate: {plan.root}" + ("" if write else " (dry run; --write applies it)")]
    if not plan.changes:
        out.append("Nothing to migrate: the repository already uses tld.")
    else:
        out.append(("Applied" if write else "Plan") + f" ({len(plan.changes)} change(s)):")
        for c in plan.changes:
            out.append(f"  {c.kind:<8} {c.path}: {c.detail}")
    for note in plan.notes:
        out.append(f"note: {note}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld migrate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="the repository to migrate (default: .)")
    ap.add_argument("--write", action="store_true", help="apply the plan (default: print it)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"tld migrate: not a directory: {root}", file=sys.stderr)
        return 2
    plan = build_plan(root)
    if plan.errors:
        for e in plan.errors:
            print(f"tld migrate: {e}", file=sys.stderr)
        return 1
    if args.write and plan.changes:
        apply(plan)
    print(render(plan, args.write))
    errors, warnings = validate_profile(plan)
    print()
    print("Validation of " + NEW_PROFILE + (" (as it will be)" if not args.write and plan.changes else "") + ":")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  error: {e}")
    if not errors:
        print("  OK")
    print()
    print("Owner checklist (only you can do these):")
    for item in checklist(plan):
        print(f"  [ ] {item}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
