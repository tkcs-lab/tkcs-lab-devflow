#!/usr/bin/env python3
"""Scope-drift monitoring for /implement: which files did a phase change outside its `touches`?

    scope_check.py check   --plan PLAN.md|MANIFEST.yaml --phase ID --base REF --head REF
                           [--label LABEL] [--profile .claude/toolkit.yaml]
                           [--plan-slug SLUG --feature REF] --results FILE
    scope_check.py disposition --results FILE --base REF --head REF
    scope_check.py record  --results FILE --label LABEL
    scope_check.py section --results FILE [--cap 20]

Monitoring only: this script never blocks anything and `check` always exits 0, even when the check
itself fails (the entry then says `unavailable`). Mechanical only, no judgement. Paths only: no file
contents, diffs or commit messages are read or written. Python 3.11+, stdlib and PyYAML, no network.

`--results FILE` is the accumulator, a JSON list with one entry per merged phase (or fix session);
`check` adds or replaces the entry for its label, `disposition` updates every entry, `record` prints
the status-record `scope` object of one entry, `section` prints the pull request's "Scope" section.
Glob semantics are validate_manifest.path_matches, the same as the manifest validator uses.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_manifest as vm  # noqa: E402

PATH_CAP = 20          # paths kept per phase in a record and in the pull request section
PATH_MAX_LEN = 300     # characters of one path kept
DISPOSITIONS = ("accepted", "partly_reverted", "reverted")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ScopeError(Exception):
    """The check could not be made; the message is a short reason without any file content."""


def safe_path(path: str) -> str:
    """A path as it may appear in a record or a pull request: no control characters, capped length."""
    path = CONTROL.sub("?", path)
    return path if len(path) <= PATH_MAX_LEN else path[: PATH_MAX_LEN - 1] + "…"


def classify(paths: list[str], touches: list[str], others: dict[str, list[str]], ignore: list[str]) -> dict:
    """Split changed paths into in-scope, ignored and out-of-scope.

    `others` maps every other phase id to its touches. A path inside `touches` is in scope (even if an
    ignore glob also names it); else a path matching `ignore` is ignored; else it is out of scope, and
    `collides_with` lists the other phases whose touches name it.
    """
    in_scope = ignored = 0
    out: list[dict] = []
    for path in sorted(set(paths)):
        if any(vm.path_matches(path, t) for t in touches):
            in_scope += 1
        elif any(vm.path_matches(path, g) for g in ignore):
            ignored += 1
        else:
            owners = sorted(pid for pid, ts in others.items() if any(vm.path_matches(path, t) for t in ts))
            out.append({"path": path, "collides_with": owners})
    return {"in_scope": in_scope, "ignored": ignored, "out_of_scope": out}


def _git(repo: str, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    except OSError:
        raise ScopeError("git is not available")
    if done.returncode != 0:
        raise ScopeError(f"git {args[0]} failed")
    return done.stdout


def changed_paths(repo: str, base: str, head: str) -> list[str]:
    """Paths that differ between the merge base of base and head, and head. Renames count as the
    old path deleted and the new path added, so both are checked."""
    merge_base = _git(repo, "merge-base", base, head).strip()
    if not merge_base:
        raise ScopeError("no merge base")
    out = _git(repo, "diff", "--name-only", "--no-renames", "-z", merge_base, head)
    return [p for p in out.split("\0") if p]


def final_paths(repo: str, base: str, head: str) -> set[str]:
    """Paths the whole feature branch changes relative to the main branch (three-dot diff)."""
    return {p for p in _git(repo, "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}").split("\0") if p}


def already_merged(repo: str, feature: str, slug: str, phase: str) -> bool:
    """True when the feature branch history holds the trailer `Plan-Phase: <slug>/<phase>` exactly."""
    wanted = f"Plan-Phase: {slug}/{phase}"
    log = _git(repo, "log", "--fixed-strings", f"--grep={wanted}", "--format=%B%x00", feature)
    return any(line.strip() == wanted for line in log.splitlines())


def load_manifest(plan: str) -> dict:
    try:
        path = Path(plan)
        text = path.read_text(encoding="utf-8")
        raw = vm.extract_manifest(text) if path.suffix == ".md" else text
        manifest = yaml.safe_load(raw)
    except (OSError, ValueError, yaml.YAMLError):
        raise ScopeError("manifest unreadable")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("phases"), list):
        raise ScopeError("manifest unreadable")
    return manifest


def phase_touches(manifest: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ph in manifest["phases"]:
        if isinstance(ph, dict) and isinstance(ph.get("id"), str):
            t = ph.get("touches")
            out[ph["id"]] = [x for x in t if isinstance(x, str)] if isinstance(t, list) else []
    return out


def load_ignore(profile: str | None) -> list[str]:
    """`scope.ignore` of the profile, plus the changelog file when the profile has `docs.changelog`
    (the worker brief demands that line from every phase, so it is expected everywhere)."""
    if not profile:
        return []
    try:
        data = yaml.safe_load(Path(profile).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raise ScopeError("profile unreadable")
    ignore: list[str] = []
    scope = data.get("scope") if isinstance(data, dict) else None
    if isinstance(scope, dict) and isinstance(scope.get("ignore"), list):
        ignore += [g for g in scope["ignore"] if isinstance(g, str)]
    docs = data.get("docs") if isinstance(data, dict) else None
    changelog = docs.get("changelog") if isinstance(docs, dict) else None
    if isinstance(changelog, dict) and isinstance(changelog.get("file"), str):
        ignore.append(changelog["file"])
    return ignore


def unavailable(label: str, reason: str) -> dict:
    return {"label": label, "check": "unavailable", "reason": reason, "in_scope": None, "ignored": None,
            "out_of_scope": [], "disposition": None}


def run_check(repo: str, plan: str, phase: str, base: str, head: str, label: str, profile: str | None,
              plan_slug: str | None = None, feature: str | None = None) -> dict:
    """The result entry for one merge. Never raises."""
    try:
        if plan_slug and feature and already_merged(repo, feature, plan_slug, phase):
            return {"label": label, "check": "skipped", "reason": "merged before this run resumed", "in_scope": None,
                    "ignored": None, "out_of_scope": [], "disposition": None}
        touches = phase_touches(load_manifest(plan))
        if phase not in touches:
            raise ScopeError("phase not in the manifest")
        if not touches[phase]:
            raise ScopeError("phase declares no touches")
        ignore = load_ignore(profile)
        paths = changed_paths(repo, base, head)
        others = {pid: ts for pid, ts in touches.items() if pid != phase}
        found = classify(paths, touches[phase], others, ignore)
    except ScopeError as exc:
        return unavailable(label, str(exc))
    except Exception:  # the check must never fail the merge
        return unavailable(label, "unexpected error")
    return {"label": label, "check": "ok", "reason": None, **found,
            "disposition": "accepted" if found["out_of_scope"] else None}


def update_dispositions(entries: list[dict], final: set[str]) -> None:
    """accepted: every recorded out-of-scope path is still in the final diff; reverted: none is;
    partly_reverted: some are."""
    for entry in entries:
        if entry.get("check") != "ok" or not entry.get("out_of_scope"):
            continue
        kept = sum(1 for item in entry["out_of_scope"] if item["path"] in final)
        total = len(entry["out_of_scope"])
        entry["disposition"] = "accepted" if kept == total else "reverted" if kept == 0 else "partly_reverted"


def ordered(entry: dict) -> list[dict]:
    """Out-of-scope items, collisions first, then by path; the order the caps keep."""
    return sorted(entry["out_of_scope"], key=lambda i: (not i["collides_with"], i["path"]))


def record_field(entry: dict) -> dict:
    """The status record's per-phase `scope` object (schema/status-record.schema.json)."""
    if entry.get("check") != "ok":
        return {"check": "unavailable", "in_scope": None, "out_of_scope_count": None, "collision_count": None,
                "paths": [], "disposition": None}
    return {
        "check": "ok",
        "in_scope": entry["in_scope"],
        "out_of_scope_count": len(entry["out_of_scope"]),
        "collision_count": sum(1 for i in entry["out_of_scope"] if i["collides_with"]),
        "paths": [safe_path(i["path"]) for i in ordered(entry)[:PATH_CAP]],
        "disposition": entry.get("disposition"),
    }


def _code(text: str) -> str:
    fence = "``" if "`" in text else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


DISPOSITION_WORDS = {"accepted": "accepted (merged as is)", "reverted": "reverted by a later commit",
                     "partly_reverted": "partly reverted by a later commit"}


def build_section(entries: list[dict], cap: int = PATH_CAP) -> str:
    """The pull request's `## Scope` section: per phase, out-of-scope paths and collisions, or none."""
    lines = [
        "## Scope", "",
        "Files a phase changed outside its declared `touches`. Monitoring only: nothing was blocked and "
        "every phase was merged. A collision is an out-of-scope path that another phase's `touches` names. "
        "Paths only; paths the profile's `scope.ignore` names are not listed.",
        "",
    ]
    if not entries:
        lines.append("- none recorded")
    for entry in entries:
        name = f"**{entry['label']}**"
        check = entry.get("check")
        if check == "skipped":
            lines.append(f"- {name}: not checked ({entry.get('reason') or 'skipped'})")
            continue
        if check != "ok":
            lines.append(f"- {name}: scope check unavailable ({entry.get('reason') or 'unknown'})")
            continue
        items = ordered(entry)
        if not items:
            lines.append(f"- {name}: none")
            continue
        collisions = sum(1 for i in items if i["collides_with"])
        head = f"{len(items)} out of scope, {collisions} collision{'s' if collisions != 1 else ''}"
        word = DISPOSITION_WORDS.get(entry.get("disposition") or "")
        lines.append(f"- {name}: {head}" + (f", {word}" if word else ""))
        for item in items[:cap]:
            note = f" (collides with {', '.join(_code(c) for c in item['collides_with'])})" if item["collides_with"] else ""
            lines.append(f"  - {_code(safe_path(item['path']))}{note}")
        if len(items) > cap:
            lines.append(f"  - and {len(items) - cap} more")
    return "\n".join(lines) + "\n"


def read_results(path: str) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise ScopeError("results file unreadable")
    if not isinstance(data, list):
        raise ScopeError("results file unreadable")
    return data


def write_results(path: str, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check one phase branch against its touches")
    c.add_argument("--plan", required=True)
    c.add_argument("--phase", required=True, help="manifest phase id whose touches apply")
    c.add_argument("--label", help="name in the results (default: the phase id), e.g. fix-1 for a fix session")
    c.add_argument("--base", required=True, help="the feature branch ref")
    c.add_argument("--head", required=True, help="the phase branch ref")
    c.add_argument("--profile")
    c.add_argument("--plan-slug")
    c.add_argument("--feature", help="with --plan-slug: skip a phase whose Plan-Phase trailer is already in this ref")
    c.add_argument("--results", required=True)
    c.add_argument("--repo", default=".")

    d = sub.add_parser("disposition", help="mark each drift accepted or reverted from the final diff")
    d.add_argument("--results", required=True)
    d.add_argument("--base", required=True, help="the main branch ref")
    d.add_argument("--head", required=True, help="the feature branch ref")
    d.add_argument("--repo", default=".")

    r = sub.add_parser("record", help="print the status-record scope object of one entry")
    r.add_argument("--results", required=True)
    r.add_argument("--label", required=True)

    s = sub.add_parser("section", help="print the pull request Scope section")
    s.add_argument("--results", required=True)
    s.add_argument("--cap", type=int, default=PATH_CAP)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            label = args.label or args.phase
            entry = run_check(args.repo, args.plan, args.phase, args.base, args.head, label, args.profile,
                              args.plan_slug, args.feature)
            try:
                entries = [e for e in read_results(args.results) if e.get("label") != label] + [entry]
                write_results(args.results, entries)
            except (ScopeError, OSError) as exc:
                print(f"scope_check: results not saved ({exc})", file=sys.stderr)
            print(json.dumps(entry))
        elif args.cmd == "disposition":
            entries = read_results(args.results)
            try:
                update_dispositions(entries, final_paths(args.repo, args.base, args.head))
                write_results(args.results, entries)
            except (ScopeError, OSError) as exc:
                print(f"scope_check: dispositions unchanged ({exc})", file=sys.stderr)
        elif args.cmd == "record":
            match = [e for e in read_results(args.results) if e.get("label") == args.label]
            if not match or match[0].get("check") == "skipped":
                print("null")
            else:
                print(json.dumps(record_field(match[0])))
        else:
            sys.stdout.write(build_section(read_results(args.results), max(args.cap, 1)))
    except ScopeError as exc:
        # Reading the accumulator failed: say so, but never fail the caller.
        print(f"scope_check: {exc}", file=sys.stderr)
        if args.cmd == "section":
            sys.stdout.write("## Scope\n\n- scope check unavailable (results unreadable)\n")
        elif args.cmd == "record":
            print(json.dumps(record_field(unavailable(args.label, str(exc)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
