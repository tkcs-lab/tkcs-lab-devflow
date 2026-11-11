"""Command line: python3 evals/run.py {list,validate,run,aggregate,baseline,compare}. Python 3.11, stdlib + PyYAML."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

from . import graders as graders_mod
from .agents import ClaudeCodeAgent, StubAgent, CHECKED_AGAINST
from .common import BASELINES_DIR, CLAUDE, RESULTS_DIR, TRANSCRIPTS_DIR
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


def command_frontmatter_model(task) -> str | None:
    """The `model:` key in the front matter of the plugin command the task runs, or None."""
    words = (task.command or "").split(maxsplit=1)
    if not words:
        return None
    cmd = words[0].rsplit(":", 1)[-1].lstrip("/")
    path = CLAUDE / "commands" / f"{cmd}.md"
    if not cmd or not path.is_file():
        return None
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip().strip("\"'") or None
    return None


def print_plan(tasks, repeats, run_ceiling, model) -> None:
    total = 0.0
    print(f"Dry run: no model is called. Headless flags checked against Claude Code {CHECKED_AGAINST}.")
    for t in tasks:
        n = repeats or t.repeats
        unmet = unmet_requirements(t)
        worst = 0.0 if unmet else n * t.cost_ceiling_usd
        total += worst
        pinned = command_frontmatter_model(t)
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
    if args.dry_run:
        print_plan(tasks, args.repeats, args.run_ceiling, args.model)
        return 0
    if args.agent == "stub":
        if not args.stub_dir:
            print("evals: --agent stub needs --stub-dir", file=sys.stderr)
            return 1
        agent = StubAgent.from_dir(Path(args.stub_dir))
    else:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
            print("evals: set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN; the agent runs with an empty HOME "
                  "and cannot use a stored login.", file=sys.stderr)
            return 2
        agent = ClaudeCodeAgent(keep_proxy=args.keep_proxy)
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
    return 0


def cmd_aggregate(args) -> int:
    print(format_table(aggregate(read_results(Path(args.results)))))
    return 0


def cmd_baseline(args) -> int:
    recs = read_results(Path(args.results))
    out = Path(args.out) if args.out else BASELINES_DIR / f"{args.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary(recs, dt.date.today().isoformat()), indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


def cmd_compare(args) -> int:
    base = json.loads(Path(args.baseline).read_text())
    cur = aggregate(read_results(Path(args.results)))
    cmp = compare(base, cur, args.threshold)
    print("\n".join(cmp.lines))
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
    p.add_argument("--agent", choices=["claude", "stub"], default="claude", help="claude (default, calls the model) or stub (canned replies, needs --stub-dir)")
    p.add_argument("--stub-dir", help="directory of canned agent outputs for --agent stub")
    p.add_argument("--out", help="results file (default evals/results/<timestamp>.jsonl)")
    p.add_argument("--keep-proxy", action="store_true", help="pass the proxy and CA variables through to the agent")
    p.add_argument("--keep", action="store_true", help="keep the temp directory of each run")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("aggregate", help="print the pass rate per task of a results file")
    p.add_argument("results", help="a results .jsonl file")
    p.set_defaults(fn=cmd_aggregate)
    p = sub.add_parser("baseline", help="write a small summary of a results file as a baseline")
    p.add_argument("results", help="a results .jsonl file")
    p.add_argument("--name", default="default", help="baseline name (default: default)")
    p.add_argument("--out", help="output file (default evals/baselines/<name>.json)")
    p.set_defaults(fn=cmd_baseline)
    p = sub.add_parser("compare", help="compare a results file with a baseline; exit 1 on a regression")
    p.add_argument("results", help="a results .jsonl file")
    p.add_argument("--baseline", required=True, help="baseline JSON written by the baseline command")
    p.add_argument("--threshold", type=float, default=1.0, help="flag a drop of more than this many repeats (default 1)")
    p.set_defaults(fn=cmd_compare)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
