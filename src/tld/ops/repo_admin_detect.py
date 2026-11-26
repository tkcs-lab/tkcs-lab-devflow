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
TAG_RE = re.compile(r"^(\D*?)(\d+\.\d+\.\d+)(.*)$")
SEMVER_SUFFIX = re.compile(r"^-[0-9A-Za-z.-]+$")
PEP440_SUFFIX = re.compile(r"^(a|b|rc)\d+$")
TAG_PUSH = re.compile(r"(?ms)^\s*push:\s*\n(?:[ \t]+.*\n)*?[ \t]+tags:")
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


def tag_workflow_creates_release(texts: list[str]) -> bool:
    """True when a workflow runs on a pushed tag and itself creates the release."""
    return any(TAG_PUSH.search(t) and any(m in t for m in RELEASE_MARKERS) for t in texts)


def release_params(tags: list[str], manifests: list[str], tag_workflow: bool) -> tuple[dict[str, str], list[str]]:
    """Release parameters shown by the tags and manifests; check_script is never guessed."""
    found = [m.groups() for m in (TAG_RE.match(t) for t in tags) if m]
    if not found:
        return {}, ["no version-like tags"]
    counts = Counter(prefix for prefix, _, _ in found)
    top = max(counts.values())
    prefix = min(p for p, n in counts.items() if n == top)
    suffixes = [s for p, _, s in found if p == prefix]
    if any(SEMVER_SUFFIX.match(s) for s in suffixes):
        style = "semver"
    elif any(PEP440_SUFFIX.match(s) for s in suffixes):
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
