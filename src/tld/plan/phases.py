#!/usr/bin/env python3
"""The mechanical parts of running a plan: where it may come from, branch names, which phases to start.

    tld plan check-url URL [--repo OWNER/NAME] [--main BRANCH] [--plan-dir DIR]
    tld plan check-commands PLAN --profile PROFILE
    tld plan branch-name (--plan-slug SLUG | --review-slug SLUG | --manifest PLAN [--phase ID [--rev N] | --fix N])
    tld plan phase-status PLAN [--ref REF] [--running ID]... [--approved ID]... [--repo DIR]

`check-url` (S14) parses `https://github.com/<owner>/<repo>/blob/<ref>/<path>` and accepts it only when
`<owner>/<repo>` is this repository (`--repo`, default: the `origin` remote of the current directory) and
`<ref>` is the main branch (`--main`, default `main`) or a `<type>/<kebab>` feature branch and the path ends in
`<plan-dir>/<n>/plan.md` (`--plan-dir`, default `docs/plans`); the old `main/` and `plan/<slug>` layouts are still
accepted with `"legacy": true`. It prints `{"owner", "repo", "ref", "path", "legacy"}` as JSON. `phase-status`
also prints `started` and `plan_blob` (from the newest `Plan-Started: <slug> <blob>` trailer). A plan from anywhere else is refused (exit 1): its
`verify_after_merge` commands would run on this machine.

`check-commands` (S14, part two) sorts the manifest's `verify_after_merge` commands into those the profile
trusts and those the owner must see first. PROFILE is the main branch's profile, never a plan branch's. A
command is trusted when it is `dispatch <workflow>` for a `ci.dispatchable` workflow, equals a `verify.fast`
or `verify.dod` entry (a mapping entry with `cwd` never counts), or starts, word by word, with a
`verify.after_merge_allow` prefix and has no shell metacharacter. It prints `{"trusted", "unknown"}` as
JSON, both in manifest order. A `verify.after_merge_allow` that is not a list of strings is an error (exit 1).

`branch-name` prints one branch name (C12): `plan/<slug>`, `review/<slug>`, the manifest's
`feature_branch`, a phase branch `<feature>--<phase>`, a revision `<feature>--<phase>-rev<n>` or a fix
branch `<feature>--fix-<n>`.

`phase-status` reads the first-parent history of REF (default `HEAD`), the commits made on the feature
branch itself, so a trailer a worker wrote on its phase branch counts only through the orchestrator's merge:

- `Plan-Phase: <plan slug>/<id>` marks a phase done, unless that commit was reverted: a commit whose message
  says `This reverts commit <sha>` undoes the commit it names (and a revert of that revert re-instates it).
  A revert commit's own `Plan-Phase` trailer never counts.
- `Plan-Gate-Approved: <plan slug>/<id>` (an empty commit the orchestrator makes after the human approved a
  `human_gate` phase) approves that phase when it is newer than the phase's latest counted merge, so a
  revision merged after the approval is gated again. `--approved ID` approves a phase as well.

It prints JSON: `done`, `approved` (done gate phases approved by a trailer or `--approved`), `gated` (done
phases with `human_gate: true` that are not approved), `ready` (not done, not `--running`, every
`depends_on` done and none of them gated), `waiting` (the rest), and `start` (the first `ready` phases that
fit in `max_parallel` next to the running ones). Exit 0, or 1 with `plan: <message>` on stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from tld.plan import manifest as vm

URL = re.compile(r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/blob/(?P<rest>.+)$")
REMOTE = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$")
DISPATCH = re.compile(r"dispatch ([^\s]+)")
PLAIN = re.compile(r"[A-Za-z0-9_./=:@%+,*?\[\]\- '\"]*")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TOKEN = re.compile(r"[A-Za-z0-9_./:%+,=-]+")
STACKS = Path(__file__).resolve().parents[3] / "stacks"
OPTIONS_BLOCK = re.compile(r"^```yaml after-merge-options\n(.*?)^```", re.S | re.M)
# The options a command may carry after a `verify.after_merge_allow` prefix, keyed by the program the prefix
# names: null takes no value, "token" a plain word, "path" a plain repo-relative path, a list one of its words.
# tld's own options are here; a stack guide adds its tools' options in an `after-merge-options` block. A
# program no table names takes no option; no command takes a positional word after its prefix.
TLD_OPTIONS: dict[str, object] = {"--json": None, "--strict": None, "--no-file-checks": None, "--index": "path",
                                  "--ref": "token"}


class PlanError(Exception):
    """Printed as `plan: <message>`."""


def origin_repo(cwd: str | None = None) -> str:
    try:
        out = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=cwd,
                             timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PlanError(f"cannot read the origin remote ({exc}); pass --repo") from None
    m = REMOTE.search(out.stdout.strip()) if out.returncode == 0 else None
    if not m:
        raise PlanError("the origin remote is not a GitHub repository; pass --repo")
    return f"{m['owner']}/{m['repo']}"


FEATURE_REF = re.compile(r"^[a-z0-9]+/[a-z0-9-]+$")


def check_url(url: str, repo: str, main: str, plan_dir: str = "docs/plans") -> dict:
    m = URL.match(url.strip())
    if not m:
        raise PlanError("not a plan URL of the form https://github.com/<owner>/<repo>/blob/<ref>/<path>")
    if f"{m['owner']}/{m['repo']}".lower() != repo.lower():
        raise PlanError(f"the plan is in {m['owner']}/{m['repo']}, not in this repository ({repo}): "
                        "only plans of this repository run here")
    rest = m["rest"]
    suffix = re.compile(r"^(?P<ref>.+)/(?P<path>" + re.escape(plan_dir.strip("/")) + r"/[^/]+/plan\.md)$")
    sm = suffix.match(rest)
    legacy = sm is None
    if sm:
        ref, path = sm["ref"], sm["path"]
        if ref != main and (not FEATURE_REF.match(ref) or "--" in ref):
            raise PlanError(f"the plan must be on '{main}' or on a <type>/<kebab> feature branch, not on {ref!r}")
    elif rest.startswith(f"{main}/"):
        ref, path = main, rest[len(main) + 1:]
    elif rest.startswith("plan/"):
        slug, _, path = rest[len("plan/"):].partition("/")
        if not SLUG.match(slug) or not path:
            raise PlanError("a plan branch is plan/<kebab-case slug> followed by the file path")
        ref = f"plan/{slug}"
    else:
        raise PlanError(f"the plan must be at {plan_dir}/<n>/plan.md on '{main}' or on its feature branch")
    if not path or ".." in path.split("/"):
        raise PlanError("the URL names no file, or a path with '..'")
    return {"owner": m["owner"], "repo": m["repo"], "ref": ref, "path": path, "legacy": legacy}


def load_manifest(path: str) -> dict:
    p = Path(path)
    try:
        text = p.read_text()
    except OSError as exc:
        raise PlanError(f"cannot read '{path}': {exc.strerror or exc}") from None
    try:
        raw = vm.extract_manifest(text) if p.suffix == ".md" else text
        manifest = yaml.safe_load(raw)
    except (ValueError, yaml.YAMLError) as exc:
        raise PlanError(str(exc)) from None
    errors, _ = vm.validate(manifest)
    if errors:
        raise PlanError("the manifest is not valid: " + errors[0] + " (run tld plan validate-manifest)")
    return manifest


def branch_name(args) -> str:
    for slug in (args.plan_slug, args.review_slug):
        if slug is not None and not SLUG.match(slug):
            raise PlanError(f"'{slug}' is not a kebab-case slug")
    if args.plan_slug:
        return f"plan/{args.plan_slug}"
    if args.review_slug:
        return f"review/{args.review_slug}"
    manifest = load_manifest(args.manifest)
    feature = manifest["feature_branch"]
    if args.fix is not None:
        if args.phase or args.rev is not None:
            raise PlanError("--fix takes no --phase or --rev")
        return f"{feature}--fix-{args.fix}"
    if args.phase is None:
        if args.rev is not None:
            raise PlanError("--rev needs --phase")
        return feature
    ids = [ph["id"] for ph in manifest["phases"]]
    if args.phase not in ids:
        raise PlanError(f"no phase '{args.phase}' in the manifest (phases: {', '.join(ids)})")
    if args.rev is not None:
        return f"{feature}--{args.phase}-rev{args.rev}"
    return f"{feature}--{args.phase}"


REVERTS = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.I)


def history(ref: str, cwd: str | None) -> list[tuple[str, str]]:
    """(sha, message) of each first-parent commit of REF, newest first."""
    try:
        out = subprocess.run(["git", "log", "--first-parent", "--format=%H%x00%B%x1e", ref], capture_output=True,
                             text=True, cwd=cwd, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PlanError(f"git log failed: {exc}") from None
    if out.returncode != 0:
        raise PlanError(f"git log {ref} failed: {out.stderr.strip()}")
    commits = []
    for chunk in out.stdout.split("\x1e"):
        sha, sep, body = chunk.strip("\n").partition("\x00")
        if sep:
            commits.append((sha, body))
    return commits


def trailers(ref: str, slug: str, cwd: str | None) -> tuple[set[str], set[str], str | None]:
    """The done phases, the phases whose gate approval is newer than their latest counted merge, and the
    plan blob of the newest active non-revert commit with a Plan-Started trailer (None when there is none)."""
    commits = history(ref, cwd)
    shas = [sha for sha, _ in commits]
    reverters: dict[str, list[str]] = {}
    for sha, body in commits:
        for target in REVERTS.findall(body):
            full = next((s for s in shas if s.startswith(target.lower())), None)
            if full:
                reverters.setdefault(full, []).append(sha)

    memo: dict[str, bool] = {}

    def active(sha: str, depth: int = 0) -> bool:
        if sha not in memo:
            memo[sha] = depth > 50 or not any(active(r, depth + 1) for r in reverters.get(sha, []))
        return memo[sha]

    phase_rx = re.compile(r"^Plan-Phase:\s*" + re.escape(slug) + r"/(\S+)\s*$", re.M)
    gate_rx = re.compile(r"^Plan-Gate-Approved:\s*" + re.escape(slug) + r"/(\S+)\s*$", re.M)
    started_rx = re.compile(r"^Plan-Started:[ \t]*" + re.escape(slug) + r"[ \t]+([0-9a-f]{40}|[0-9a-f]{64})[ \t]*$", re.M)
    plan_blob = None
    merged_at: dict[str, int] = {}  # phase -> index of its newest counted merge (0 = newest commit)
    approved_at: dict[str, int] = {}
    for i, (sha, body) in enumerate(commits):
        if not active(sha):
            continue
        for pid in gate_rx.findall(body):
            approved_at.setdefault(pid, i)
        if REVERTS.search(body):
            continue
        if plan_blob is None:
            started = started_rx.findall(body)
            if started:
                plan_blob = started[0]
        for pid in phase_rx.findall(body):
            merged_at.setdefault(pid, i)
    approved = {pid for pid, i in approved_at.items() if pid in merged_at and i < merged_at[pid]}
    return set(merged_at), approved, plan_blob


def phase_status(manifest: dict, done_ids: set[str], running: list[str], approved: list[str],
                 plan_blob: str | None = None) -> dict:
    phases = manifest["phases"]
    by_id = {ph["id"]: ph for ph in phases}
    done = [ph["id"] for ph in phases if ph["id"] in done_ids]
    gates = [pid for pid in done if by_id[pid].get("human_gate") is True]
    gated = [pid for pid in gates if pid not in approved]
    ready, waiting = [], []
    for ph in phases:
        pid = ph["id"]
        if pid in done_ids or pid in running:
            continue
        deps = ph.get("depends_on") or []
        if all(d in done_ids and d not in gated for d in deps):
            ready.append(pid)
        else:
            waiting.append(pid)
    room = max(0, int(manifest.get("max_parallel") or 2) - len(running))
    return {"plan_slug": manifest["plan_slug"], "feature_branch": manifest["feature_branch"],
            "done": done, "approved": [pid for pid in gates if pid in approved], "gated": gated,
            "running": list(running), "ready": ready, "waiting": waiting,
            "start": ready[:room], "all_done": len(done) == len(phases),
            "started": plan_blob is not None, "plan_blob": plan_blob}


def _entries(items: object) -> list[str]:
    """The stripped command strings of a verify list; items that are no command, or run elsewhere, are skipped."""
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            out.append(item.strip())
        elif isinstance(item, dict) and isinstance(item.get("run"), str) and "cwd" not in item:
            out.append(item["run"].strip())
    return out


def stack_options(stacks: object) -> dict[str, dict[str, object]]:
    """The safe options per program: tld's own plus the `after-merge-options` block of each listed stack guide."""
    table: dict[str, dict[str, object]] = {"tld": dict(TLD_OPTIONS)}
    for name in stacks if isinstance(stacks, list) else []:
        if not isinstance(name, str) or not SLUG.match(name):
            continue
        try:
            text = (STACKS / f"{name}.md").read_text()
        except (OSError, UnicodeError):
            continue
        m = OPTIONS_BLOCK.search(text)
        if not m:
            continue
        data = yaml.safe_load(m.group(1))
        if not isinstance(data, dict):
            raise PlanError(f"stacks/{name}.md: the after-merge-options block must be a mapping")
        for program, opts in data.items():
            if not isinstance(program, str) or not isinstance(opts, dict) or not all(
                    isinstance(o, str) and o.startswith("-") and (v is None or v in ("token", "path") or (
                        isinstance(v, list) and all(isinstance(c, str) for c in v))) for o, v in opts.items()):
                raise PlanError(f"stacks/{name}.md: bad after-merge-options entry '{program}'")
            table.setdefault(program, {}).update(opts)
    return table


def _program(prefix: list[str], table: dict) -> dict[str, object]:
    """The safe options of the program a prefix runs (matched by a word's base name), or none."""
    for word in prefix:
        base = word.rsplit("/", 1)[-1]
        if base in table:
            return table[base]
    return {}


def _plain_value(word: str, kind: object) -> bool:
    """An option's value: a plain word without a leading `-`; a path also has no leading `/` and no segment
    that starts with `.` (no `..`, `.git`, `.env`)."""
    if isinstance(kind, list):
        return word in kind
    if not TOKEN.fullmatch(word) or word.startswith("-"):
        return False
    return kind != "path" or not (word.startswith("/") or any(seg.startswith(".") or not seg
                                                              for seg in word.split("/")))


def _safe_tail(tail: list[str], options: dict[str, object]) -> bool:
    """Whether every word after an allowed prefix is one of the program's safe options (with its value)."""
    i = 0
    while i < len(tail):
        name, eq, value = tail[i].partition("=")
        i += 1
        if name not in options:
            return False
        kind = options[name]
        if kind is None:
            if eq:
                return False
            continue
        if not eq:
            if i >= len(tail):
                return False
            value = tail[i]
            i += 1
        if not _plain_value(value, kind):
            return False
    return True


def check_commands(manifest: dict, profile: dict) -> dict:
    """Split `verify_after_merge` into the commands the profile trusts and the unknown ones (S14)."""
    verify = profile.get("verify")
    verify = verify if isinstance(verify, dict) else {}
    ci = profile.get("ci")
    ci = ci if isinstance(ci, dict) else {}
    allow = verify.get("after_merge_allow", [])
    if not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
        raise PlanError("verify.after_merge_allow must be a list of strings")
    prefixes = []
    for a in allow:
        try:
            words = shlex.split(a)
        except ValueError:
            continue
        if words:
            prefixes.append(words)
    exact = set(_entries(verify.get("fast")) + _entries(verify.get("dod")))
    table = stack_options(profile.get("stacks"))
    dispatchable = {d["workflow"] for d in ci.get("dispatchable") or [] if isinstance(d, dict)
                    and isinstance(d.get("workflow"), str)} if isinstance(ci.get("dispatchable"), list) else set()

    def trusted(cmd: str) -> bool:
        m = DISPATCH.fullmatch(cmd.strip())
        if m and m.group(1) in dispatchable:
            return True
        if cmd.strip() in exact:
            return True
        if not PLAIN.fullmatch(cmd):
            return False
        try:
            words = shlex.split(cmd)
        except ValueError:
            return False
        return any(words[:len(p)] == p and _safe_tail(words[len(p):], _program(p, table)) for p in prefixes)

    result: dict = {"trusted": [], "unknown": []}
    for cmd in manifest.get("verify_after_merge") or []:
        result["trusted" if isinstance(cmd, str) and trusted(cmd) else "unknown"].append(cmd)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld plan", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("check-url", help="accept a plan URL (<plan_dir>/<n>/plan.md on main or its feature branch; plan/* deprecated)")
    cu.add_argument("url")
    cu.add_argument("--repo", help="owner/name of this repository (default: the origin remote)")
    cu.add_argument("--main", default="main", help="the main branch (git.main_branch)")
    cu.add_argument("--plan-dir", default="docs/plans", help="the directory that holds <n>/plan.md")
    cc = sub.add_parser("check-commands", help="which verify_after_merge commands the profile trusts, as JSON")
    cc.add_argument("plan", help="plan file (.md) or manifest (.yaml)")
    cc.add_argument("--profile", required=True, help="the main branch's profile (never a plan branch's copy)")
    bn = sub.add_parser("branch-name", help="print a plan, review, feature, phase, revision or fix branch name")
    grp = bn.add_mutually_exclusive_group(required=True)
    grp.add_argument("--plan-slug", help="deprecated: plans now live on the feature branch")
    grp.add_argument("--review-slug")
    grp.add_argument("--manifest", help="plan file (.md) or manifest (.yaml)")
    bn.add_argument("--phase")
    bn.add_argument("--rev", type=int)
    bn.add_argument("--fix", type=int)
    ps = sub.add_parser("phase-status", help="which phases are done, gated, ready or waiting, as JSON")
    ps.add_argument("plan")
    ps.add_argument("--ref", default="HEAD", help="the feature branch to read Plan-Phase and Plan-Gate-Approved trailers from")
    ps.add_argument("--running", action="append", default=[], metavar="ID")
    ps.add_argument("--approved", action="append", default=[], metavar="ID", help="a human_gate phase the human approved")
    ps.add_argument("--repo", help="the checkout to run git in (default: the current directory)")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check-url":
            result = check_url(args.url, args.repo or origin_repo(), args.main, args.plan_dir)
            if result["legacy"]:
                print("tld plan: warning: old-layout plans are deprecated; make-plan now commits the plan "
                      "to the feature branch", file=sys.stderr)
            print(json.dumps(result))
        elif args.cmd == "check-commands":
            try:
                profile = yaml.safe_load(Path(args.profile).read_text())
            except (OSError, UnicodeError, yaml.YAMLError):
                raise PlanError(f"cannot read the profile '{args.profile}'") from None
            if not isinstance(profile, dict):
                raise PlanError(f"cannot read the profile '{args.profile}'")
            print(json.dumps(check_commands(load_manifest(args.plan), profile)))
        elif args.cmd == "branch-name":
            if (args.rev is not None and args.rev < 1) or (args.fix is not None and args.fix < 1):
                raise PlanError("--rev and --fix count from 1")
            print(branch_name(args))
        else:
            manifest = load_manifest(args.plan)
            ids = {ph["id"] for ph in manifest["phases"]}
            for pid in [*args.running, *args.approved]:
                if pid not in ids:
                    raise PlanError(f"no phase '{pid}' in the manifest")
            done, gate_ok, plan_blob = trailers(args.ref, manifest["plan_slug"], args.repo)
            approved = sorted((gate_ok & ids) | set(args.approved))
            print(json.dumps(phase_status(manifest, done & ids, args.running, approved, plan_blob), indent=2))
        return 0
    except PlanError as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
