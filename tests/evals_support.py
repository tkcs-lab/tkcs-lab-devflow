"""Builders of canned run outputs for the eval harness tests (no model involved)."""
from __future__ import annotations

import copy

import yaml

from evals.harness.model import Artifacts, Doc, GradeContext

PROFILE = (
    "docs:\n  must_read: [README.md]\ngit:\n  main_branch: main\n  branch_pattern: \"<type>/<kebab-case>\"\n"
    "  branch_types: [feature, fix, chore]\nverify:\n  fast: [\"true\"]\n  dod: [\"true\"]\nstacks: []\n"
)

GOOD_MANIFEST = {
    "plan_slug": "tags",
    "feature_branch": "feature/tags",
    "tracking_issue": 1,
    "phases": [
        {"id": "p1-store", "title": "Tags in the store", "depends_on": [], "complexity": "S",
         "touches": ["notes/store.py", "tests/test_store.py"], "brief": "1. Add tags.",
         "acceptance": ["`python3 -m unittest tests.test_store`"]},
        {"id": "p2-cli", "title": "CLI filter", "depends_on": ["p1-store"], "complexity": "S",
         "touches": ["notes/cli.py"], "brief": "1. Add --tag.",
         "acceptance": ["tests/test_cli.py::test_tag_filter passes"]},
        {"id": "p2-export", "title": "Markdown export", "depends_on": ["p1-store"], "complexity": "S",
         "touches": ["notes/export_md.py"], "brief": "1. Export.",
         "acceptance": ["grep -c 'def export' notes/export_md.py prints 1"]},
        {"id": "p3-docs", "title": "Docs", "depends_on": ["p2-cli", "p2-export"], "complexity": "S",
         "touches": ["README.md", "docs/"], "brief": "1. Docs.",
         "acceptance": ["`grep -q '--tag' README.md`"]},
    ],
}


def plan_text(manifest: dict | None = None) -> str:
    m = GOOD_MANIFEST if manifest is None else manifest
    return "# Plan\n\n## Goal\nx\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(m, sort_keys=False) + "```\n"


def mutated(fn) -> dict:
    m = copy.deepcopy(GOOD_MANIFEST)
    fn(m)
    return m


def ctx(documents=(), expected=None, transcript=(), result_text="", refs=None, changed=(), merges=(), diff="", **params) -> GradeContext:
    art = Artifacts(base_sha="base", refs=dict(refs or {}), changed_files=list(changed), merge_commits=list(merges),
                    diff=diff, documents=[Doc(*d) for d in documents])
    return GradeContext(art, expected or {}, list(transcript), result_text, None, params)


def bash(cmd: str, is_error: bool | None = False, call_id: str = "t1") -> list[dict]:
    """A Bash tool call and its result, as stream-json events."""
    evs = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": cmd}}]}}]
    if is_error is not None:
        evs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "is_error": is_error, "content": "x"}]}})
    return evs


REVIEW_GOOD = """\
# Review

## Findings to fix

### SEC-1 · high · Shell injection in export

- **Where:** `notes/export.py:6`
- **Evidence:** `os.system("tar czf " + name ...)`
- **Why:** command injection through the archive name.

### TST-1 · medium · No test for the token check

- **Where:** `notes/auth.py:8`
- **Evidence:** missing test: nothing under tests/ imports notes.auth.

## Not doing

### DOC-9 · low · Typo
- **Where:** `README.md`
"""

SEEDED = {
    "seeded": [
        {"id": "injection", "file": "notes/export.py", "class": "injection", "class_words": ["injection", "shell"]},
        {"id": "missing-test", "file": "notes/auth.py", "class": "missing-test", "class_words": ["missing test", "untested"]},
    ],
    "acceptable_files": ["notes/store.py", "README.md"],
}
