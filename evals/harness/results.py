"""Result lines, transcripts (scrubbed, stored separately), aggregation and baseline summaries."""
from __future__ import annotations

import functools
import json
import os
import re
import sys
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


_HOOKS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "devflow" / "hooks"

# Whole PEM blocks (real newlines or the literal `\n` of JSON-dumped text), URL userinfo, JSON-quoted secrets.
PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
URL_USERINFO = re.compile(r"(://)[^\s/:@]+:[^\s/@]+@")
JSON_SECRET = re.compile(
    r'(\\?"(?:api[_-]?key|access[_-]?token|secret|password|token)\\?"\s*:\s*\\?")[^"\\]{8,}(\\?")', re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def _hook_patterns() -> tuple[re.Pattern, ...]:
    """The secret-scan hook's SPECIFIC patterns, so the harness and the hook cannot drift apart."""
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    import secret_scan
    return tuple(rx for _name, _desc, rx in secret_scan.SPECIFIC)


def scrub(text: str) -> tuple[str, int]:
    n = 0
    text, k = PEM.subn("[REDACTED]", text)
    n += k
    for pat in (*_hook_patterns(), *SCRUB):
        text, k = pat.subn("[REDACTED]", text)
        n += k
    text, k = URL_USERINFO.subn(r"\1[REDACTED]@", text)
    n += k
    text, k = JSON_SECRET.subn(r"\1[REDACTED]\2", text)
    n += k
    return text, n


def scrub_obj(obj, counter: list[int] | None = None):
    """Scrub every string value (and key) of a JSON-like structure; `counter[0]` accumulates the redactions."""
    if isinstance(obj, str):
        text, k = scrub(obj)
        if counter is not None:
            counter[0] += k
        return text
    if isinstance(obj, list):
        return [scrub_obj(v, counter) for v in obj]
    if isinstance(obj, dict):
        return {(scrub_obj(k, counter) if isinstance(k, str) else k): scrub_obj(v, counter) for k, v in obj.items()}
    return obj


def _write_private(path: Path, text: str, append: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            fd = -1
            f.write(text)
    finally:
        if fd >= 0:
            os.close(fd)


def write_transcript(directory: Path, task: str, repeat: int, events: list[dict], stamp: str) -> tuple[str, int]:
    """One scrubbed JSONL file per run under the (gitignored) transcripts directory, mode 0600. Returns (file name, redactions)."""
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{stamp.replace(':', '')}-{task}-{repeat}.jsonl"
    counter = [0]
    lines = []
    for ev in events:
        text, n = scrub(json.dumps(scrub_obj(ev, counter), ensure_ascii=False))
        counter[0] += n
        lines.append(text)
    _write_private(directory / name, "\n".join(lines) + "\n", append=False)
    return name, counter[0]


def append_results(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = ""
    for r in records:
        text, _ = scrub(json.dumps(scrub_obj(r), ensure_ascii=False, sort_keys=True))
        out += text + "\n"
    _write_private(path, out, append=True)


def read_results(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def aggregate(records: list[dict]) -> dict:
    """Per task: runs, passes, pass_rate, per-grader pass counts, cost and turns. Skipped runs are listed, not counted;
    aborted and errored runs count as failures."""
    tasks: dict[str, dict] = {}
    for r in records:
        t = tasks.setdefault(r["task"], {"runs": 0, "passes": 0, "skipped": 0, "aborted": 0, "errors": 0,
                                         "graders": {}, "cost_usd": 0.0, "turns": 0, "models": []})
        if r["status"] == "skipped":
            t["skipped"] += 1
            continue
        t["runs"] += 1
        if r.get("model") and r["model"] not in t["models"]:
            t["models"].append(r["model"])
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
