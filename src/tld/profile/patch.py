#!/usr/bin/env python3
"""Text-level edits of `.tld/toolkit.yaml` for /setup: set one block, or diff a proposal.

    profile_patch.py set-block PROFILE KEY VALUE.json [--write]
    profile_patch.py diff PROFILE PROPOSAL.json [--root DIR]

`set-block`: KEY is `agents` (top level) or `docs.website` (a child of `docs`). VALUE.json is the
value itself or the whole output of profile_survey.py (a top-level `proposal` key; the value is then
`proposal.profile` at the key path). Only the block is rendered with `yaml.safe_dump`; every other
byte of the profile, comments included, is kept. The new text goes to stdout, or into PROFILE with
`--write`. The block is the key line plus the following lines up to the last non-blank, non-comment
line indented deeper than the key; blank and comment lines after it belong to what follows.

`diff`: PROPOSAL.json is the `profile` object or the whole survey output. Prints JSON
`{"new", "changed", "same", "stale"}`; `stale` is computed from the existing profile against ROOT
(default: the directory two levels above the profile file).

Exit 0 ok; 1 on any error (`profile_patch: <message>` on stderr). Python 3.11+, stdlib and PyYAML.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

from tld.plan import manifest as vm  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "build", "dist", "Pods", ".build",
             "__pycache__", "DerivedData"}
MAX_FILES = 5000
KEYS = ("agents", "docs.website")
COMPARED = ("stacks", "git.main_branch", "docs.must_read", "docs.adr_dir", "docs.adr_index",
            "docs.changelog", "docs.website", "ci.dispatchable", "agents")
MISSING = object()


class PatchError(Exception):
    """A message for stderr, without the `profile_patch: ` prefix."""


# ---- reading ---------------------------------------------------------------------------------
def read_text(path: str) -> str:
    try:
        return Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PatchError(f"cannot read '{path}': {exc}") from None


def load_json(path: str):
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise PatchError(f"'{path}' is not valid JSON: {exc}") from None


def lookup(obj, dotted: str):
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return MISSING
        obj = obj[part]
    return obj


def proposal_profile(data) -> dict:
    """The `profile` object of D8, from either accepted shape."""
    if isinstance(data, dict) and "proposal" in data:
        prop = data["proposal"]
        profile = prop.get("profile") if isinstance(prop, dict) else None
        return profile if isinstance(profile, dict) else {}
    return data if isinstance(data, dict) else {}


# ---- text blocks -----------------------------------------------------------------------------
def split_lines(text: str) -> list[str]:
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def block_end(lines: list[str], start: int) -> int:
    """Index of the last line of the block whose key line is `lines[start]`."""
    key_indent = indent_of(lines[start])
    end = start
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if indent_of(lines[j]) > key_indent:
            end = j
        else:
            break
    return end


def find_key(lines: list[str], key: str, indent: int, lo: int = 0, hi: int | None = None) -> int | None:
    rx = re.compile(r"^" + " " * indent + re.escape(key) + r"[ \t]*:")
    for i in range(lo, len(lines) if hi is None else hi):
        if rx.match(lines[i]):
            return i
    return None


def render(key: str, value, indent: int) -> str:
    body = yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False)
    pad = " " * indent
    return "".join(pad + ln if ln.strip() else ln for ln in body.splitlines(keepends=True))


def set_block(text: str, key: str, value) -> str:
    if key not in KEYS:
        raise PatchError(f"unknown key '{key}' (one of {', '.join(KEYS)})")
    lines = split_lines(text)
    if key == "agents":
        new = render("agents", value, 0)
        start = find_key(lines, "agents", 0)
        if start is not None:
            end = block_end(lines, start)
            return "".join(lines[:start]) + new + "".join(lines[end + 1:])
        head = text if text.endswith("\n") or not text else text + "\n"
        return head + "\n" + new
    docs = find_key(lines, "docs", 0)
    if docs is None:
        raise PatchError("no 'docs' block to add 'website' to")
    docs_end = block_end(lines, docs)
    new = render("website", value, 2)
    start = find_key(lines, "website", 2, docs + 1, docs_end + 1)
    if start is not None:
        end = block_end(lines, start)
        return "".join(lines[:start]) + new + "".join(lines[end + 1:])
    last = lines[docs_end]
    if not last.endswith("\n"):
        lines[docs_end] = last + "\n"
    return "".join(lines[:docs_end + 1]) + new + "".join(lines[docs_end + 1:])


# ---- diff ------------------------------------------------------------------------------------
def walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if len(found) >= MAX_FILES:
                return found
            found.append((Path(base) / name).relative_to(root).as_posix())
    return found


def stale_keys(profile: dict, root: Path) -> list[dict]:
    out: list[dict] = []

    def check(key: str, value, path: str | None = None) -> None:
        if not isinstance(value, str) or not value:
            return
        target = value.split("#", 1)[0] if path is None else path
        if target and not (root / target).exists():
            out.append({"key": key, "value": value, "why": "path not found"})

    docs = profile.get("docs") if isinstance(profile.get("docs"), dict) else {}
    for i, item in enumerate(docs.get("must_read") or []):
        check(f"docs.must_read[{i}]", item, item if isinstance(item, str) else None)
    check("docs.adr_dir", docs.get("adr_dir"), docs.get("adr_dir"))
    check("docs.adr_index", docs.get("adr_index"), docs.get("adr_index"))
    check("docs.adr_bar", docs.get("adr_bar"))
    changelog = docs.get("changelog")
    if isinstance(changelog, dict):
        check("docs.changelog.file", changelog.get("file"), changelog.get("file"))
    website = docs.get("website")
    if isinstance(website, dict):
        check("docs.website.dir", website.get("dir"), website.get("dir"))
    verify = profile.get("verify") if isinstance(profile.get("verify"), dict) else {}
    check("verify.dod_doc", verify.get("dod_doc"))
    check("project_steward", profile.get("project_steward"), profile.get("project_steward"))
    admin = profile.get("admin") if isinstance(profile.get("admin"), dict) else {}
    check("admin.policy", admin.get("policy"), admin.get("policy"))
    ci = profile.get("ci") if isinstance(profile.get("ci"), dict) else {}
    for i, entry in enumerate(ci.get("dispatchable") or []):
        if isinstance(entry, dict) and isinstance(entry.get("workflow"), str):
            wf = entry["workflow"]
            check(f"ci.dispatchable[{i}].workflow", wf, f".github/workflows/{wf}")
    agents = profile.get("agents") if isinstance(profile.get("agents"), dict) else {}
    files: list[str] | None = None
    for i, entry in enumerate(agents.get("required") or []):
        if not isinstance(entry, dict):
            continue
        for j, glob in enumerate(entry.get("when") or []):
            if files is None:
                files = walk_files(root)
            if not any(vm.path_matches(f, glob) for f in files):
                out.append({"key": f"agents.required[{i}].when[{j}]", "value": glob, "why": "no file matches"})
    return out


def diff(profile: dict, proposed: dict, root: Path) -> dict:
    result: dict = {"new": [], "changed": [], "same": [], "stale": []}
    for key in COMPARED:
        want = lookup(proposed, key)
        if want is MISSING:
            continue
        have = lookup(profile, key)
        if have is MISSING:
            result["new"].append(key)
        elif have == want:
            result["same"].append(key)
        else:
            result["changed"].append({"key": key, "from": have, "to": want})
    result["stale"] = stale_keys(profile, root)
    return result


# ---- CLI -------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="profile_patch.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sb = sub.add_parser("set-block")
    sb.add_argument("profile")
    sb.add_argument("key")
    sb.add_argument("value")
    sb.add_argument("--write", action="store_true")
    df = sub.add_parser("diff")
    df.add_argument("profile")
    df.add_argument("proposal")
    df.add_argument("--root")
    args = parser.parse_args(argv)
    try:
        text = read_text(args.profile)
        data = load_json(args.value if args.cmd == "set-block" else args.proposal)
        if args.cmd == "set-block":
            if args.key not in KEYS:
                raise PatchError(f"unknown key '{args.key}' (one of {', '.join(KEYS)})")
            if isinstance(data, dict) and "proposal" in data:
                value = lookup(proposal_profile(data), args.key)
                if value is MISSING:
                    raise PatchError(f"the proposal has no '{args.key}'")
            else:
                value = data
            new = set_block(text, args.key, value)
            if args.write:
                Path(args.profile).write_bytes(new.encode("utf-8"))
            else:
                sys.stdout.write(new)
            return 0
        try:
            profile = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise PatchError(f"cannot parse '{args.profile}': {exc}") from None
        if not isinstance(profile, dict):
            raise PatchError(f"'{args.profile}' is not a YAML mapping")
        root = Path(args.root) if args.root else Path(args.profile).resolve().parent.parent
        print(json.dumps(diff(profile, proposal_profile(data), root), indent=2))
        return 0
    except PatchError as exc:
        print(f"profile_patch: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
