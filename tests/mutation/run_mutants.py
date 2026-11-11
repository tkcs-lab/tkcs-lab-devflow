#!/usr/bin/env python3
"""Mutation check: apply each hand-written mutant of tests/mutation/mutants.yaml, run the tests named for its file,
and report whether the tests killed it (failed) or it SURVIVED.

    python3 tests/mutation/run_mutants.py [--only ID ...] [--report FILE] [--timeout S]

The work happens in a copy of the working tree in a temporary directory, so the checkout is never edited, even
when the run is killed. Exit 0 when every mutant was killed, 1 when one survived or a mutant no longer applies
(its `old` text is not in the file exactly once), 2 on a usage error. Python 3.11+, PyYAML and pytest.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MUTANTS = Path(__file__).with_name("mutants.yaml")
SKIP = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache", "node_modules", ".venv", "venv",
                              ".coverage*", "htmlcov", "evals/results", "evals/transcripts")


def load(path: Path = MUTANTS) -> tuple[dict[str, list[str]], list[dict]]:
    data = yaml.safe_load(path.read_text())
    return data["tests"], data["mutants"]


def problems(tests: dict[str, list[str]], mutants: list[dict], root: Path = ROOT) -> list[str]:
    """Why the mutant list does not fit the code (empty when every mutant applies)."""
    out, seen = [], set()
    for m in mutants:
        mid = m.get("id")
        if mid in seen:
            out.append(f"{mid}: duplicate id")
        seen.add(mid)
        f = root / m["file"]
        if not f.is_file():
            out.append(f"{mid}: no file {m['file']}")
            continue
        n = f.read_text().count(m["old"])
        if n != 1:
            out.append(f"{mid}: `old` occurs {n} times in {m['file']} (it must occur once)")
        if m["old"] == m["new"]:
            out.append(f"{mid}: `new` equals `old`")
        if not tests.get(m["file"]):
            out.append(f"{mid}: no tests listed for {m['file']}")
    for f, names in tests.items():
        out += [f"tests for {f}: no file {t}" for t in names if not (root / t).is_file()]
    return out


def run(mutants: list[dict], tests: dict[str, list[str]], timeout: int) -> list[tuple[dict, str, str]]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
    results = []
    with tempfile.TemporaryDirectory(prefix="tld-mutants-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(ROOT, work, ignore=SKIP, symlinks=True)
        for m in mutants:
            path = work / m["file"]
            original = path.read_text()
            path.write_text(original.replace(m["old"], m["new"], 1))
            start = time.monotonic()
            try:
                p = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-m", "not slow",
                                    *tests[m["file"]]], cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
                lines = (p.stdout or p.stderr).strip().splitlines()
                verdict = "killed" if p.returncode != 0 else "SURVIVED"
                detail = next((l for l in lines if l.startswith("FAILED")), lines[-1] if lines else "")
            except subprocess.TimeoutExpired:
                verdict, detail = "killed", f"timeout after {timeout} s"
            finally:
                path.write_text(original)
            results.append((m, verdict, f"{detail[:150]} ({time.monotonic() - start:.0f} s)"))
            print(f"{verdict:<8} {m['id']:<5} {m['why']}: {results[-1][2]}", flush=True)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="+", metavar="ID", help="run only these mutants")
    ap.add_argument("--report", help="also write the results to this file")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per mutant (default 900); a timeout counts as killed")
    args = ap.parse_args(argv)
    tests, mutants = load()
    bad = problems(tests, mutants)
    if bad:
        print("mutants.yaml does not fit the code:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    if args.only:
        unknown = set(args.only) - {m["id"] for m in mutants}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        mutants = [m for m in mutants if m["id"] in args.only]
    results = run(mutants, tests, args.timeout)
    survived = [m["id"] for m, v, _ in results if v == "SURVIVED"]
    summary = f"{len(results) - len(survived)} of {len(results)} mutants killed" + (f"; survived: {', '.join(survived)}" if survived else "")
    print(summary)
    if args.report:
        Path(args.report).write_text("\n".join(f"{v} {m['id']} {m['file']}: {m['why']} - {d}" for m, v, d in results) + f"\n{summary}\n")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
