#!/usr/bin/env python3
"""Turn survey evidence into a profile proposal (input to /setup).

Usage: survey_proposal.py EVIDENCE.json

`build(evidence)` returns `{"profile": {...}, "rationale": [...]}`. `profile` holds the keys
`stacks`, `git`, `docs`, `ci` and `agents`, each only when it has a value (`stacks` always). `rationale`
lists `{key, value, evidence}` for every proposed top-level value and every `agents.required` entry.
EVIDENCE.json is the `evidence` object of profile_survey.py, or its whole output.

Pure: reads nothing but its input. Exit 0 ok; 1 unreadable input (`survey_proposal: <message>`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CRITICAL_SCORE = 3
DOC_CUT = 5
TECH_WRITER_MARKDOWN = 8


def _website(docs: dict) -> dict | None:
    site = docs.get("website")
    if not isinstance(site, dict) or not site.get("build"):
        return None
    out = {"dir": site.get("dir"), "build": site["build"]}
    if site.get("links"):
        out["links"] = site["links"]
    return out


def _required(signals: dict) -> tuple[list[dict], list[list[str]]]:
    """The agents.required entries and, in step, their evidence strings."""
    if not signals.get("source_files"):
        return [], []
    sec = signals.get("security") or {}
    score = sec.get("score", 0)
    firing = sec.get("firing") or []
    cats = sec.get("categories") or {}
    entries: list[dict] = []
    evid: list[list[str]] = []
    critical = score >= CRITICAL_SCORE
    if critical:
        entries.append({"agent": "security-reviewer", "at": ["implement_phase", "implement_final"],
                        "blocking": True})
    else:
        entries.append({"agent": "security-reviewer", "at": ["implement_final"], "blocking": False})
    ev = [f"security score {score}"]
    for name in firing:
        files = (cats.get(name) or {}).get("files") or []
        ev.append(f"{name}: " + (", ".join(files[:2]) if files else "no files"))
    evid.append(ev)
    globs = (signals.get("ui") or {}).get("globs") or []
    if globs:
        entries.append({"agent": "ux-reviewer", "at": ["implement_final"], "blocking": False,
                        "when": list(globs)})
        evid.append(["ui globs: " + ", ".join(globs)])
    levels = ((signals.get("tests") or {}).get("levels")) or {}
    found = [k for k in ("unit", "integration", "e2e") if levels.get(k)]
    if len(found) < 2 or not levels.get("e2e"):
        entries.append({"agent": "test-architect", "at": ["make_plan"], "blocking": False})
        evid.append(["test levels found: " + (", ".join(found) or "none"), f"e2e={bool(levels.get('e2e'))}"])
    md = signals.get("markdown_files", 0)
    if md >= TECH_WRITER_MARKDOWN:
        entries.append({"agent": "tech-writer", "at": ["dod"], "blocking": False})
        evid.append([f"markdown_files={md}"])
    return entries, evid


def build(evidence: dict) -> dict:
    docs_ev = evidence.get("docs") or {}
    signals = evidence.get("signals") or {}
    git = evidence.get("git") or {}
    ci = evidence.get("ci") or {}
    rationale: list[dict] = []
    profile: dict = {}

    stacks = [s["name"] for s in evidence.get("stacks") or []]
    profile["stacks"] = stacks
    rationale.append({"key": "stacks", "value": stacks,
                      "evidence": [f"{s['name']}: " + ", ".join(s.get("evidence") or [])
                                   for s in evidence.get("stacks") or []]})

    if git.get("main_branch"):
        profile["git"] = {"main_branch": git["main_branch"]}
        rationale.append({"key": "git.main_branch", "value": git["main_branch"],
                          "evidence": ["from the git remote or the current branch"]})

    docs: dict = {"must_read": list(docs_ev.get("must_read") or [])}
    rationale.append({"key": "docs.must_read", "value": docs["must_read"], "evidence": docs["must_read"]})
    for key in ("adr_dir", "adr_index"):
        if docs_ev.get(key):
            docs[key] = docs_ev[key]
            rationale.append({"key": f"docs.{key}", "value": docs[key], "evidence": [docs[key]]})
    cl = docs_ev.get("changelog")
    if isinstance(cl, dict) and cl.get("section"):
        docs["changelog"] = {"file": cl.get("file"), "section": cl["section"]}
        rationale.append({"key": "docs.changelog", "value": docs["changelog"], "evidence": [str(cl.get("file"))]})
    site = _website(docs_ev)
    if site:
        docs["website"] = site
        rationale.append({"key": "docs.website", "value": site,
                          "evidence": list((docs_ev.get("website") or {}).get("evidence") or [])})
    profile["docs"] = docs

    dispatchable = list(ci.get("dispatchable") or [])
    if dispatchable:
        profile["ci"] = {"dispatchable": dispatchable}
        rationale.append({"key": "ci.dispatchable", "value": dispatchable,
                          "evidence": [d["workflow"] for d in dispatchable]})

    score = (signals.get("security") or {}).get("score", 0)
    agents: dict = {"posture": {"security": "critical" if score >= CRITICAL_SCORE else "standard"}}
    firing = (signals.get("security") or {}).get("firing") or []
    rationale.append({"key": "agents.posture.security", "value": agents["posture"]["security"],
                      "evidence": [f"security score {score}"] + [f"fires: {n}" for n in firing]})
    if "website" not in docs:
        agents["disable"] = ["website-maintainer"]
    required, evid = _required(signals)
    if required:
        agents["required"] = required
    profile["agents"] = agents
    for entry, ev in zip(required, evid):
        rationale.append({"key": "agents.required." + entry["agent"], "value": entry, "evidence": ev})
    return {"profile": profile, "rationale": rationale}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("survey_proposal: usage: survey_proposal.py EVIDENCE.json", file=sys.stderr)
        return 1
    try:
        data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"survey_proposal: {exc}", file=sys.stderr)
        return 1
    if isinstance(data, dict) and "evidence" in data:
        data = data["evidence"]
    print(json.dumps(build(data), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
