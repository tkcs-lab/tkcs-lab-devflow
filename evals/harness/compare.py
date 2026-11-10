"""Compare a results file with a stored baseline summary."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Comparison:
    lines: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.regressions


def compare(baseline: dict, current_tasks: dict, threshold_repeats: float = 1.0) -> Comparison:
    """Flag a task whose pass count dropped by MORE than `threshold_repeats` repeats.

    The drop is (baseline pass rate - current pass rate) x the current number of runs, so a baseline of 3
    runs and a current of 5 are comparable. A task missing from the current results is reported, not flagged.
    A current task with no runs (all skipped) is reported, not flagged.
    """
    out = Comparison()
    base_tasks = baseline.get("tasks", {})
    for tid in sorted(set(base_tasks) | set(current_tasks)):
        b, c = base_tasks.get(tid), current_tasks.get(tid)
        if b is None:
            out.lines.append(f"{tid:<24} new task (no baseline): {c['passes']}/{c['runs']}")
            continue
        if c is None or not c["runs"]:
            out.lines.append(f"{tid:<24} not run (baseline {b['passes']}/{b['runs']})")
            continue
        if not b["runs"]:
            out.lines.append(f"{tid:<24} baseline had no runs; now {c['passes']}/{c['runs']}")
            continue
        b_rate, c_rate = b["passes"] / b["runs"], c["passes"] / c["runs"]
        drop = (b_rate - c_rate) * c["runs"]
        delta = c_rate - b_rate
        line = f"{tid:<24} {b_rate:.0%} -> {c_rate:.0%} ({delta:+.0%}, {c['passes']}/{c['runs']})"
        if drop > threshold_repeats + 1e-9:
            line += f"  DROP of {drop:.1f} repeats (threshold {threshold_repeats:g})"
            out.regressions.append(tid)
        elif delta > 0:
            line += "  improved"
        out.lines.append(line)
        for g in sorted(b.get("graders", {})):
            bg, cg = b["graders"][g], c.get("graders", {}).get(g)
            if cg and cg["runs"] and bg["runs"] and cg["passes"] / cg["runs"] < bg["passes"] / bg["runs"]:
                out.lines.append(f"    grader {g}: {bg['passes']}/{bg['runs']} -> {cg['passes']}/{cg['runs']}")
    return out
