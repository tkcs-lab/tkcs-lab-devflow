"""Command line: python3 evals/run.py {list,validate,run,aggregate,baseline,check-baseline,compare}. Python 3.11, stdlib + PyYAML."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

from . import baseline as baseline_mod
from . import graders as graders_mod
from .agents import ADAPTERS, StubAgent, adapter
from .common import BASELINES_DIR, RESULTS_DIR, STUBS_DIR, TRANSCRIPTS_DIR
from .compare import compare
from .results import aggregate, append_results, format_table, read_results, summary
from .runner import Budget, run_tasks, unmet_requirements
from .taskspec import discover

DEFAULT_RUN_CEILING = 3.0


def _tasks(args):
    return discover(graders_known=set(graders_mod.GRADERS), only=getattr(args, "task", None) or None)


def cmd_list(args) -> int:
    for t in _tasks(args):
        unmet = unmet_requirements(t)
        print(f"{t.id:<24} {t.full_prompt()[:50]!r:<54} repeats={t.repeats} ceiling=${t.cost_ceiling_usd:g}"
              + (f"  [skipped: needs {', '.join(unmet)}]" if unmet else ""))
    return 0


def cmd_validate(args) -> int:
    try:
        tasks = _tasks(args)
    except ValueError as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 1
    print(f"evals: {len(tasks)} task(s) valid")
    return 0


def print_plan(tasks, repeats, run_ceiling, model, runtime: str = "claude") -> None:
    total = 0.0
    ad = adapter(runtime)
    print(f"Dry run: no model is called. Adapter {runtime}: headless flags checked against version {ad.CHECKED_AGAINST}.")
    for t in tasks:
        n = repeats or t.repeats
        unmet = unmet_requirements(t)
        worst = 0.0 if unmet else n * t.cost_ceiling_usd
        total += worst
        pinned = ad.command_model(t.command)
        shown = f"{pinned} (command frontmatter)" if pinned else (model or t.model or "default")
        print(f"  {t.id:<24} {n} run(s)  model={shown}  per-run ceiling ${t.cost_ceiling_usd:g}  "
              f"worst case ${worst:g}" + (f"  SKIPPED (needs {', '.join(unmet)})" if unmet else ""))
    print(f"Worst case if every run hit its ceiling: ${total:g}. Run ceiling (hard stop): ${run_ceiling:g}.")


def cmd_run(args) -> int:
    if not (math.isfinite(args.run_ceiling) and args.run_ceiling > 0):
        print("evals: run ceiling must be a positive finite number", file=sys.stderr)
        return 2
    try:
        tasks = _tasks(args)
    except ValueError as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 1
    if not tasks:
        print("evals: no tasks selected", file=sys.stderr)
        return 1
    runtime = "claude" if args.agent == "stub" else args.agent
    if args.dry_run:
        print_plan(tasks, args.repeats, args.run_ceiling, args.model, runtime)
        return 0
    if args.agent == "stub":
        agent = StubAgent.from_dir(Path(args.stub_dir) if args.stub_dir else STUBS_DIR)
    else:
        ad = adapter(args.agent)
        problem = ad.credential_problem()
        if problem:
            print(f"evals: {problem}", file=sys.stderr)
            return 2
        agent = ad.Agent(keep_proxy=args.keep_proxy)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else RESULTS_DIR / f"{stamp}.jsonl"
    budget = Budget(args.run_ceiling)
    outcomes = run_tasks(tasks, agent, budget, repeats=args.repeats, model_override=args.model,
                         plugin_ref=args.plugin_ref, transcripts_dir=TRANSCRIPTS_DIR, keep=args.keep)
    records = [o.record for o in outcomes]
    append_results(out, records)
    for r in records:
        status = r["status"] + (f" ({r['reason']})" if r.get("reason") else "")
        print(f"{r['task']} #{r['repeat']}: {status} passed={r.get('passed')} cost=${r.get('cost_usd', 0)}")
    print()
    print(format_table(aggregate(records)))
    print(f"\nspent ${budget.spent:.4f} of ${budget.ceiling:g}; results: {out}")
    if any(r.get("reason") == "run cost ceiling reached before this run" or r.get("reason") == "cost_ceiling" for r in records):
        print("evals: stopped by the cost ceiling", file=sys.stderr)
        return 3
    failed = [f"{r['task']} #{r['repeat']}" for r in records if r["status"] != "skipped" and not r.get("passed")]
    if args.require_pass and failed:
        print(f"evals: {len(failed)} run(s) did not pass: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def cmd_aggregate(args) -> int:
    print(format_table(aggregate(read_results(Path(args.results)))))
    return 0


def cmd_baseline(args) -> int:
    if args.refresh_hashes:
        path = Path(args.out) if args.out else BASELINES_DIR / f"{args.name}.json"
        changed = baseline_mod.refresh(path, dt.date.today().isoformat())
        print(f"{path}: " + (f"hashes refreshed for {', '.join(changed)}" if changed else "hashes already current"))
        return 0
    if not args.results:
        print("evals: baseline needs a results file (or --refresh-hashes)", file=sys.stderr)
        return 2
    recs = read_results(Path(args.results))
    out = Path(args.out) if args.out else BASELINES_DIR / f"{args.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary(recs, dt.date.today().isoformat()), indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


def cmd_check_baseline(args) -> int:
    path = Path(args.baseline)
    stale = baseline_mod.stale(json.loads(path.read_text()), baseline_mod.command_hashes())
    if stale:
        print(f"evals: {path} is stale for {', '.join(stale)}: re-run their tasks and write a new baseline, or "
              f"`python3 evals/run.py baseline --refresh-hashes` (docs/architecture/evals.md)", file=sys.stderr)
        return 1
    print(f"{path}: command hashes current")
    return 0


def cmd_compare(args) -> int:
    base = json.loads(Path(args.baseline).read_text())
    cur = aggregate(read_results(Path(args.results)))
    cmp = compare(base, cur, args.threshold)
    print("\n".join(cmp.lines))
    changed = baseline_mod.stale(base, baseline_mod.command_hashes())
    if changed:
        print(f"note: the commands {', '.join(changed)} changed since the baseline was written")
    if cmp.regressions:
        print(f"\nREGRESSION: {', '.join(cmp.regressions)}", file=sys.stderr)
        return 1
    print("\nno regression beyond the threshold")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals/run.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, text in (("list", cmd_list, "list the tasks, their repeats and ceilings"),
                           ("validate", cmd_validate, "check every task.yaml against the schema")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--task", action="append", help="task id (repeatable); default all")
        p.set_defaults(fn=fn)
    p = sub.add_parser("run", help="run tasks (calls the model unless --dry-run or --agent stub)")
    p.add_argument("--task", action="append", help="task id (repeatable); default all")
    p.add_argument("--repeats", type=int, help="override each task's repeats")
    p.add_argument("--model", help="passed as --model; ignored when the command's frontmatter sets model:")
    p.add_argument("--plugin-ref", help="git ref of the plugin to test, or 'worktree' (default: the task's, HEAD)")
    p.add_argument("--run-ceiling", type=float, default=DEFAULT_RUN_CEILING, help="total USD ceiling for this invocation; positive and finite (default 3)")
    p.add_argument("--dry-run", action="store_true", help="print what would run and the worst-case cost; call no model")
    p.add_argument("--agent", choices=[*sorted(ADAPTERS), "stub"], default="claude",
                   help="a runtime adapter (claude, the default, calls the model) or stub (canned replies, no model)")
    p.add_argument("--stub-dir", help="directory of canned agent outputs for --agent stub (default evals/stubs)")
    p.add_argument("--require-pass", action="store_true", help="exit 1 when a run that was not skipped did not pass")
    p.add_argument("--out", help="results file (default evals/results/<timestamp>.jsonl)")
    p.add_argument("--keep-proxy", action="store_true", help="pass the proxy and CA variables through to the agent")
    p.add_argument("--keep", action="store_true", help="keep the temp directory of each run")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("aggregate", help="print the pass rate per task of a results file")
    p.add_argument("results", help="a results .jsonl file")
    p.set_defaults(fn=cmd_aggregate)
    p = sub.add_parser("baseline", help="write a small summary of a results file as a baseline")
    p.add_argument("results", nargs="?", help="a results .jsonl file")
    p.add_argument("--refresh-hashes", action="store_true", help="only rewrite the command hashes of the baseline to the current files")
    p.add_argument("--name", default="default", help="baseline name (default: default)")
    p.add_argument("--out", help="output file (default evals/baselines/<name>.json)")
    p.set_defaults(fn=cmd_baseline)
    p = sub.add_parser("check-baseline", help="exit 1 when a command changed since the baseline was written")
    p.add_argument("--baseline", default=str(baseline_mod.DEFAULT), help="baseline JSON (default evals/baselines/default.json)")
    p.set_defaults(fn=cmd_check_baseline)
    p = sub.add_parser("compare", help="compare a results file with a baseline; exit 1 on a regression")
    p.add_argument("results", help="a results .jsonl file")
    p.add_argument("--baseline", required=True, help="baseline JSON written by the baseline command")
    p.add_argument("--threshold", type=float, default=1.0, help="flag a drop of more than this many repeats (default 1)")
    p.set_defaults(fn=cmd_compare)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
