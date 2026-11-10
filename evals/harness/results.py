"""Result lines, transcripts (scrubbed, stored separately), aggregation and baseline summaries."""
from __future__ import annotations

import json
import re
from pathlib import Path

SCRUB = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\b(bearer|token|authorization:?)\s+[A-Za-z0-9._\-]{24,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b(\s*[=:]\s*)['\"]?[^\s'\"]{12,}"),
]


def scrub(text: str) -> tuple[str, int]:
    n = 0
    for pat in SCRUB:
        text, k = pat.subn("[REDACTED]", text)
        n += k
    return text, n


def write_transcript(directory: Path, task: str, repeat: int, events: list[dict], stamp: str) -> tuple[str, int]:
    """One scrubbed JSONL file per run under the (gitignored) transcripts directory. Returns (file name, redactions)."""
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{stamp.replace(':', '')}-{task}-{repeat}.jsonl"
    total = 0
    lines = []
    for ev in events:
        text, n = scrub(json.dumps(ev, ensure_ascii=False))
        total += n
        lines.append(text)
    (directory / name).write_text("\n".join(lines) + "\n")
    return name, total


def append_results(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def read_results(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def aggregate(records: list[dict]) -> dict:
    """Per task: runs, passes, pass_rate, per-grader pass counts, cost and turns. Skipped runs are listed, not counted;
    aborted and errored runs count as failures."""
    tasks: dict[str, dict] = {}
    for r in records:
        t = tasks.setdefault(r["task"], {"runs": 0, "passes": 0, "skipped": 0, "aborted": 0, "errors": 0,
                                         "graders": {}, "cost_usd": 0.0, "turns": 0})
        if r["status"] == "skipped":
            t["skipped"] += 1
            continue
        t["runs"] += 1
        t["passes"] += 1 if r.get("passed") else 0
        t["aborted"] += r["status"] == "aborted"
        t["errors"] += r["status"] == "error"
        t["cost_usd"] = round(t["cost_usd"] + r.get("cost_usd", 0.0), 4)
        t["turns"] += r.get("turns", 0)
        for g in r.get("graders", []):
            gg = t["graders"].setdefault(g["name"], {"runs": 0, "passes": 0})
            gg["runs"] += 1
            gg["passes"] += 1 if g["passed"] else 0
    for t in tasks.values():
        t["pass_rate"] = round(t["passes"] / t["runs"], 4) if t["runs"] else None
    return tasks


def summary(records: list[dict], created: str = "") -> dict:
    """The small committed form of a results file (a baseline): no transcripts, no per-run detail."""
    first = next((r for r in records if r["status"] != "skipped"), records[0] if records else {})
    return {
        "schema": 1, "created": created, "plugin_sha": first.get("plugin_sha", ""),
        "model": first.get("model", ""), "command_hashes": first.get("command_hashes", {}),
        "tasks": aggregate(records),
    }


def format_table(tasks: dict) -> str:
    rows = [f"{'task':<24} {'pass':>9} {'rate':>6} {'cost$':>8}  notes"]
    for tid, t in sorted(tasks.items()):
        rate = "-" if t["pass_rate"] is None else f"{t['pass_rate']:.0%}"
        notes = []
        if t["skipped"]:
            notes.append(f"{t['skipped']} skipped")
        if t["aborted"]:
            notes.append(f"{t['aborted']} aborted")
        if t["errors"]:
            notes.append(f"{t['errors']} errors")
        rows.append(f"{tid:<24} {t['passes']:>4}/{t['runs']:<4} {rate:>6} {t['cost_usd']:>8.2f}  {', '.join(notes)}")
    return "\n".join(rows)
