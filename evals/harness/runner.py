"""Run tasks: fresh temp clone per run, agent via the adapter, capture the final git state, grade."""
from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .agents import Agent, AgentError
from .common import PLUGIN, ROOT, command_hashes, git, plugin_git_sha
from .graders import run_graders
from .model import AgentRequest, AgentResult, Artifacts, Doc, GradeContext
from .results import scrub, write_transcript
from .taskspec import Task

MIN_ALLOWANCE_USD = 0.01
MAX_DOC_BYTES = 200_000
MAX_DIFF_BYTES = 200_000
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}


class Budget:
    """The per-run ceiling over all runs of one invocation."""

    def __init__(self, run_ceiling_usd: float):
        self.ceiling = run_ceiling_usd
        self.spent = 0.0

    def remaining(self) -> float:
        return round(self.ceiling - self.spent, 6)

    def allowance(self, task: Task) -> float:
        return min(task.cost_ceiling_usd, self.remaining())

    def add(self, cost: float) -> None:
        self.spent += cost


def prepare_plugin(ref: str, dest: Path, names: list[str] | None = None) -> tuple[list[Path], str]:
    """Export the plugin(s) at `ref` into dest. ref 'worktree' copies the working tree (uncommitted changes included).

    Returns (plugin dirs, resolved ref for the record).
    """
    if ref.startswith("-"):
        raise RuntimeError("plugin ref must not start with '-'")
    names = ["devflow", *(names or [])]
    sha = ref
    if ref != "worktree":
        v = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
                           cwd=ROOT, capture_output=True, text=True)
        if v.returncode != 0:
            raise RuntimeError(f"plugin ref {ref!r} does not name a commit: {v.stderr.strip()}")
        sha = v.stdout.strip()
    dirs = []
    for name in names:
        out = dest / name
        out.mkdir(parents=True)
        if ref == "worktree":
            shutil.copytree(ROOT / "plugins" / name, out, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            tar = subprocess.run(["git", "archive", sha, f"plugins/{name}"], cwd=ROOT, capture_output=True)
            if tar.returncode != 0:
                raise RuntimeError(f"git archive {sha} plugins/{name} failed: {tar.stderr.decode().strip()}")
            stage = dest / "_x"
            stage.mkdir(exist_ok=True)
            subprocess.run(["tar", "-x", "-C", str(stage), "-f", "-"], input=tar.stdout, check=True)
            shutil.copytree(stage / "plugins" / name, out, dirs_exist_ok=True)
        dirs.append(out)
    shutil.rmtree(dest / "_x", ignore_errors=True)
    resolved = "worktree" if ref == "worktree" else sha
    return dirs, resolved


def build_fixture(task: Task, base: Path) -> tuple[Path, dict]:
    """Build the fixture, then create origin.git (bare) and work/ (the clone the agent gets). Returns (work, expected)."""
    src, origin, work = base / "src", base / "origin.git", base / "work"
    if task.fixture.get("builder"):
        from evals.fixtures import builder
        mod = builder(task.fixture["builder"])
        expected = mod.build(src, **task.fixture.get("params", {}))
    else:
        mod = None
        shutil.copytree(task.dir / task.fixture["path"], src)
        git("init", "-q", "-b", "main", cwd=src)
        git("add", "-A", cwd=src)
        git("commit", "-q", "-m", "Initial commit", cwd=src)
        expected = {}
    git("clone", "-q", "--bare", str(src), str(origin), cwd=base)
    git("clone", "-q", str(origin), str(work), cwd=base)
    if mod is not None and hasattr(mod, "post_clone"):
        mod.post_clone(work, expected)
    expected = {**expected, **task.expected}
    return work, expected


def capture(work: Path, base_sha: str, origin: Path | None = None) -> Artifacts:
    a = Artifacts(base_sha=base_sha, origin_path=str(origin) if origin is not None else None)
    a.head = git("rev-parse", "HEAD", cwd=work).strip()
    for line in git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/remotes", "refs/tags", cwd=work).splitlines():
        ref, sha = line.split()
        if ref.startswith("refs/heads/"):
            a.refs[ref.removeprefix("refs/heads/")] = sha
        elif ref.startswith("refs/remotes/"):
            name = ref.removeprefix("refs/remotes/")
            if name != "origin/HEAD":
                a.refs[name] = sha
        else:
            a.refs["tag:" + ref.removeprefix("refs/tags/")] = sha
    # branches the agent pushed to origin are in origin.git, not necessarily fetched into the clone
    git("fetch", "-q", "--tags", "origin", "+refs/heads/*:refs/remotes/origin/*", cwd=work, check=False)
    for line in git("for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes", "refs/tags", cwd=work).splitlines():
        ref, sha = line.split()
        if ref.startswith("refs/remotes/") and not ref.endswith("/HEAD"):
            a.refs[ref.removeprefix("refs/remotes/")] = sha
        elif ref.startswith("refs/tags/"):
            a.refs["tag:" + ref.removeprefix("refs/tags/")] = sha
    a.status = git("status", "--porcelain", cwd=work)
    changed: set[str] = set()
    for line in a.status.splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if path.endswith("/"):
            changed.update(str(p.relative_to(work)) for p in (work / path).rglob("*") if p.is_file())
        else:
            changed.add(path)
    diffs = [git("diff", base_sha, cwd=work)]
    other_refs = [r for r, sha in a.refs.items() if not r.startswith("tag:") and sha != base_sha]
    for r in other_refs:
        changed.update(git("diff", "--name-only", base_sha, r, cwd=work, check=False).split())
        diffs.append(git("diff", base_sha, r, cwd=work, check=False))
    changed.update(git("diff", "--name-only", base_sha, cwd=work).split())
    a.changed_files = sorted(changed)
    a.diff = "\n".join(diffs)[:MAX_DIFF_BYTES]
    a.merge_commits = git("rev-list", "--merges", "--all", f"^{base_sha}", cwd=work, check=False).split()

    def add(ref: str, path: str, data: bytes) -> None:
        if len(data) <= MAX_DOC_BYTES and b"\0" not in data[:2000]:
            a.documents.append(Doc(ref, path, data.decode("utf-8", "replace")))

    for p in sorted(work.rglob("*")):
        if p.is_file() and not (set(p.relative_to(work).parts) & SKIP_DIRS):
            add("worktree", str(p.relative_to(work)), p.read_bytes()[:MAX_DOC_BYTES + 1])
    for r in other_refs:
        for path in git("diff", "--name-only", "--diff-filter=AM", base_sha, r, cwd=work, check=False).split():
            data = subprocess.run(["git", "show", f"{r}:{path}"], cwd=work, capture_output=True).stdout
            add(r, path, data)
    return a


@dataclass
class RunOutcome:
    record: dict
    result: AgentResult | None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unmet_requirements(task: Task) -> list[str]:
    return [r for r in task.requires if not (ROOT / r).exists()]


def run_once(task: Task, repeat: int, agent: Agent, budget: Budget, *, model_override: str | None = None,
             plugin_ref: str | None = None, transcripts_dir: Path | None = None, keep: bool = False) -> RunOutcome:
    ref = plugin_ref or task.plugin_ref
    record: dict = {"schema": 1, "task": task.id, "repeat": repeat, "started_at": _now(), "agent": agent.name,
                    "plugin_ref": ref, "plugin_sha": plugin_git_sha(), "command_hashes": command_hashes()}
    missing = unmet_requirements(task)
    if missing:
        record.update(status="skipped", reason="requires: " + ", ".join(missing) + " (not in this checkout)", passed=None, graders=[])
        return RunOutcome(record, None)
    allowance = budget.allowance(task)
    if allowance < MIN_ALLOWANCE_USD:
        record.update(status="aborted", reason="run cost ceiling reached before this run", passed=False, graders=[])
        return RunOutcome(record, None)

    tmp = Path(tempfile.mkdtemp(prefix=f"eval-{task.id}-"))
    try:
        work, expected = build_fixture(task, tmp)
        base_sha = git("rev-parse", "HEAD", cwd=work).strip()
        plugin_dirs, resolved = prepare_plugin(ref, tmp / "plugins", task.plugin_extra)
        record["plugin_resolved"] = resolved
        req = AgentRequest(workdir=work, prompt=task.full_prompt(), plugin_dirs=plugin_dirs,
                           model=model_override or task.model, timeout_s=task.timeout_s,
                           max_budget_usd=allowance, task_id=task.id, repeat=repeat)
        t0 = time.monotonic()
        try:
            res = agent.run(req)
        except AgentError as exc:
            res = AgentResult(exit_status=-1, error=str(exc))
        res.duration_s = res.duration_s or round(time.monotonic() - t0, 2)
        # a timed-out or killed run may have spent more than it reported: charge the whole allowance
        budget.add(max(res.cost_usd, allowance) if res.aborted == "timeout" else res.cost_usd)
        art = capture(work, base_sha, tmp / "origin.git")
        ctx = GradeContext(art, expected, res.transcript, res.result_text, work)
        graded = run_graders(ctx, task.graders)
        status, reason = "ok", ""
        if res.aborted:
            status, reason = "aborted", res.aborted
        elif res.error:
            status, reason = "error", res.error
        elif res.cost_usd > allowance + 1e-9:  # the agent did not honour its allowance
            status, reason = "aborted", "cost_ceiling"
        record.update(
            status=status, reason=reason, model=res.model or (model_override or task.model or ""),
            passed=status == "ok" and all(g["passed"] for g in graded), graders=graded,
            turns=res.turns, tokens=res.tokens, cost_usd=round(res.cost_usd, 4), duration_s=round(res.duration_s, 2),
            exit_status=res.exit_status, transcript_file=None, transcript_redactions=0,
        )
        if transcripts_dir is not None and res.transcript:
            f, n = write_transcript(transcripts_dir, task.id, repeat, res.transcript, record["started_at"])
            record["transcript_file"], record["transcript_redactions"] = f, n
        return RunOutcome(record, res)
    finally:
        if keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


STOP_REASONS = {"run cost ceiling reached before this run", "cost_ceiling"}


def run_tasks(tasks: list[Task], agent: Agent, budget: Budget, *, repeats: int | None = None, **kw) -> list[RunOutcome]:
    """Run every task `repeats` times (default: the task's own). Stops cleanly once the run ceiling is spent."""
    outcomes: list[RunOutcome] = []
    for task in tasks:
        for r in range(1, (repeats or task.repeats) + 1):
            out = run_once(task, r, agent, budget, **kw)
            outcomes.append(out)
            if out.record["status"] == "aborted" and out.record.get("reason") in STOP_REASONS:
                return outcomes
    return outcomes
