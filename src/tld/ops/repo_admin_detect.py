"""repo_admin_detect.py: pure detection of a repository's override values (plan 93, section 3.9).

Everything here works on plain data and imports nothing from tld.ops.repo_admin. The proposal is
only a proposal: the owner confirms it in the pull request.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

DETECT_PRS = 10
DETECT_MIN_PRS = 3

FAILED = ("failure", "timed_out", "startup_failure", "action_required")
SKIPPED = ("skipped", "neutral", "cancelled", "stale")
TAG_RE = re.compile(r"(\D*?)(\d+\.\d+\.\d+)(.*)")
SEMVER_SUFFIX = re.compile(r"-[0-9A-Za-z.-]+")
PEP440_SUFFIX = re.compile(r"(a|b|rc)\d+")
PUSH_LINE = re.compile(r"^([ \t]*)push:[ \t]*(?:#.*)?$")
TAGS_LINE = re.compile(r"^[ \t]+tags:")
HEAD_RE = re.compile(r"[0-9a-f]{40}")
SAFE_NAME = re.compile(r"[^\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]{1,100}")
MAX_TAGS = 100  # one page of the tags list
MAX_WORKFLOW_BYTES = 65536  # of each workflow text that is scanned
MANIFESTS = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod")
RELEASE_MARKERS = ("gh release create", "action-gh-release", "create-release")
OWN_TEMPLATE_FILE = "tld-release.yml"


@dataclass(frozen=True)
class Run:
    """One check run or commit status on a pull request's head; `conclusion` is None until it completed."""
    name: str
    conclusion: str | None


@dataclass(frozen=True)
class Sample:
    """One merged pull request and the runs seen on its head commit."""
    number: int
    runs: tuple[Run, ...]


def _reason(name: str, samples: list[Sample]) -> str | None:
    """Why `name` is not a reliable required check, or None when it succeeded on every sample."""
    per = [(s.number, [r.conclusion for r in s.runs if r.name == name]) for s in samples]
    for number, got in per:
        if "success" in got and any(c in FAILED for c in got):
            return f"flaky: success and failure on the same commit in #{number}"
    for number, got in per:
        if any(c in FAILED for c in got):
            return f"failed on #{number}"
    for number, got in per:
        if any(c in SKIPPED for c in got):
            return f"skipped on #{number}"
    for number, got in per:
        if any(c != "success" for c in got):
            return f"pending on #{number}"
    seen = sum(1 for _, got in per if got)
    if seen < len(samples):
        return f"seen on {seen} of {len(samples)} pull requests (path filter or new)"
    return None


def status_checks(samples: list[Sample]) -> tuple[list[str], dict[str, str]]:
    """The check names to require (sorted) and, for every other name seen, why it is left out."""
    if len(samples) < DETECT_MIN_PRS:
        return [], {"": f"too few merged pull requests ({len(samples)})"}
    names = sorted({r.name for s in samples for r in s.runs})
    kept: list[str] = []
    excluded: dict[str, str] = {}
    for name in names:
        why = _reason(name, samples)
        if why is None:
            kept.append(name)
        else:
            excluded[name] = why
    return kept, excluded


def _pushes_on_tags(text: str) -> bool:
    """True when a `push:` block (the lines indented deeper than it) holds a `tags:` key; one pass, linear."""
    block_indent: int | None = None
    for line in text.splitlines():
        if block_indent is not None:
            if not line.strip():
                continue
            if len(line) - len(line.lstrip(" \t")) > block_indent:
                if TAGS_LINE.match(line):
                    return True
                continue
            block_indent = None
        m = PUSH_LINE.match(line.rstrip())
        if m:
            block_indent = len(m.group(1))
    return False


def tag_workflow_creates_release(texts: list[str]) -> bool:
    """True when a workflow runs on a pushed tag and itself creates the release."""
    return any(_pushes_on_tags(t) and any(m in t for m in RELEASE_MARKERS) for t in texts)


def release_params(tags: list[str], manifests: list[str], tag_workflow: bool) -> tuple[dict[str, str], list[str]]:
    """Release parameters shown by the tags and manifests; check_script is never guessed."""
    found = [m.groups() for m in (TAG_RE.fullmatch(t) for t in tags) if m]
    if not found:
        return {}, ["no version-like tags"]
    counts = Counter(prefix for prefix, _, _ in found)
    top = max(counts.values())
    prefix = min(p for p, n in counts.items() if n == top)
    suffixes = [s for p, _, s in found if p == prefix]
    if any(SEMVER_SUFFIX.fullmatch(s) for s in suffixes):
        style = "semver"
    elif any(PEP440_SUFFIX.fullmatch(s) for s in suffixes):
        style = "pep440"
    else:
        style = "pep440" if "pyproject.toml" in manifests else "semver"
    params = {"tag_prefix": prefix, "version_style": style}
    if tag_workflow:
        params["create_release"] = "false"
    return params, []


def own_release_workflow(profile_release_workflow: str | None, workflows: list | None) -> list | None:
    """The workflows list without the release template when the repository releases by its own workflow, else None."""
    if not profile_release_workflow or profile_release_workflow == OWN_TEMPLATE_FILE:
        return None
    entries = list(workflows or [])
    if not any(isinstance(w, dict) and w.get("template") == "release" for w in entries):
        return None
    return [w for w in entries if not (isinstance(w, dict) and w.get("template") == "release")]


def detected_override(checks: list[str] | None, params: dict[str, str] | None, workflows: list | None) -> dict:
    """The override mapping the detection proposes (empty when nothing was detected)."""
    doc: dict = {}
    if checks:
        doc["rulesets"] = {"default_branch": {"required_status_checks": list(checks)}}
    if params:
        doc["workflow_params"] = {"release": dict(params)}
    if workflows is not None:
        doc["workflows"] = list(workflows)
    return doc


def pr_notes(checks: list[str] | None, excluded: dict[str, str], params: dict[str, str] | None, notes: list[str]) -> list[str]:
    """The lines for the pull request body; the escaping happens where they are written (_cell)."""
    lines = ["required_status_checks: " + (", ".join(checks) if checks else "none proposed")]
    for name, why in sorted(excluded.items()):
        lines.append(f"excluded: {name or '(all)'} ({why})")
    if params:
        lines.append("release parameters: " + " ".join(f"{k}={v}" for k, v in params.items()))
    lines.extend(notes)
    return lines


@dataclass(frozen=True)
class Gathered:
    """What the API shows about one repository: the merged pull requests' runs, the tags, the top-level manifests,
    whether a tag workflow creates the release, and the release workflow its profile names (None without one)."""
    samples: tuple[Sample, ...]
    tags: tuple[str, ...]
    manifests: tuple[str, ...]
    tag_workflow: bool
    profile_release_workflow: str | None


def _name(value) -> str | None:
    """A check name or tag that may be written into a policy: printable, one line, at most 100 characters."""
    return value if isinstance(value, str) and SAFE_NAME.fullmatch(value) else None


def _runs(ctx, fn: str, sha: str) -> tuple[Run, ...]:
    """The check runs and commit statuses of one head, at most 100 of each (one request each, never paged)."""
    found: list[Run] = []
    data = ctx.c.get(f"/repos/{fn}/commits/{sha}/check-runs", {"filter": "all", "per_page": "100"})
    for item in ((data or {}).get("check_runs") or [])[:100] if isinstance(data, dict) else []:
        name = _name(item.get("name")) if isinstance(item, dict) else None
        if name is None:
            continue
        done = item.get("status") == "completed"
        conclusion = item.get("conclusion") if done else None
        found.append(Run(name, conclusion if isinstance(conclusion, str) else None))
    data = ctx.c.get(f"/repos/{fn}/commits/{sha}/status")
    for item in ((data or {}).get("statuses") or [])[:100] if isinstance(data, dict) else []:
        name = _name(item.get("context")) if isinstance(item, dict) else None
        if name is None:
            continue
        state = item.get("state")
        found.append(Run(name, "success" if state == "success" else "failure" if state in ("failure", "error") else None))
    return tuple(found)


def gather(ctx, repo: dict, want_checks: bool = True) -> Gathered:
    """The API reads of section 3.9: one list of pull requests, two reads per sampled head (DETECT_PRS at most), one
    page of tags, and the files the snapshot and the memoised workflow reads already hold. An ApiError propagates."""
    from tld.ops import repo_admin_profile
    fn = repo["full_name"]
    samples: list[Sample] = []
    if want_checks:
        branch = ctx.snapshot(repo).branch
        pulls = ctx.c.get(f"/repos/{fn}/pulls", {"state": "closed", "base": branch, "sort": "updated",
                                                  "direction": "desc", "per_page": "50"})
        for pr in pulls if isinstance(pulls, list) else []:
            if len(samples) >= DETECT_PRS:
                break
            if not isinstance(pr, dict) or not pr.get("merged_at"):
                continue
            head, number = (pr.get("head") or {}).get("sha") if isinstance(pr.get("head"), dict) else None, pr.get("number")
            if not isinstance(head, str) or not HEAD_RE.fullmatch(head) or type(number) is not int:
                continue
            samples.append(Sample(number, _runs(ctx, fn, head)))
    data = ctx.c.get(f"/repos/{fn}/tags", {"per_page": str(MAX_TAGS)})
    tags = tuple(n for n in (_name(t.get("name")) for t in (data if isinstance(data, list) else [])[:MAX_TAGS]
                             if isinstance(t, dict)) if n)
    snap = ctx.snapshot(repo)
    manifests = tuple(sorted(e["path"] for e in snap.entries if e.get("type") == "blob" and e.get("path") in MANIFESTS))
    files, _ = ctx.automation_files(repo)
    tag_workflow = tag_workflow_creates_release([t[:MAX_WORKFLOW_BYTES] for path, t in files
                                                 if path.startswith(".github/workflows/")])
    profile = repo_admin_profile.repo_profile(ctx, repo)
    release = profile.get("release") if isinstance(profile, dict) else None
    workflow = release.get("workflow") if isinstance(release, dict) else None
    return Gathered(tuple(samples), tags, manifests, tag_workflow, workflow if isinstance(workflow, str) else None)
