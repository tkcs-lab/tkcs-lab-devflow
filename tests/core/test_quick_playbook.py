"""The quick playbook: its wording contract, its order of steps and the record it writes."""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from conftest import ROOT, CLAUDE, FIXTURES, tld_cmd, _load

PLAYBOOK = ROOT / "playbooks" / "quick.md"
TEXT = PLAYBOOK.read_text()
FLAT = " ".join(TEXT.split())
record = _load("tld.board.record")


def part(heading, next_heading=None):
    start = TEXT.index(heading)
    end = TEXT.index(next_heading, start + 1) if next_heading else len(TEXT)
    return TEXT[start:end]


def test_command_file_names_the_playbook_path():
    text = (CLAUDE / "commands" / "quick.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/playbooks/quick.md" in text
    assert len(text.encode()) < 1500


def test_quick_names_the_checks_and_the_refusal():
    assert re.search(r"tld plan summary-check .*--findings", TEXT)
    refusal = part("## 1. The size check", "## 2. The worker")
    assert "make-plan" in refusal
    assert "/tld:" not in TEXT
    assert "tld board record-id" in TEXT and "--run --plan-slug issue-" in FLAT
    assert "tld dod exempt" in TEXT
    assert "Too large:" in TEXT


def test_quick_never_names_the_manifest_or_the_plan_file():
    stripped = FLAT.replace("no plan file", "").replace("the manifest entry", "")
    assert "manifest" not in stripped
    assert "plan file" not in stripped


def test_quick_writes_a_run_record():
    assert "quick" not in record.COMMANDS


@pytest.mark.parametrize("name", ["untrusted-text", "status-board", "research", "protected-changes", "pr-steward",
                                  "roles", "findings-fix", "profile"])
def test_quick_links_the_policies(name):
    assert f"policies/{name}.md" in FLAT


def test_allow_plan_belongs_to_the_worker_section_on():
    head = TEXT[:TEXT.index("## 2. The worker")]
    assert "tld guard allow-plan" not in " ".join(head.split())
    assert "tld guard allow-plan" in " ".join(TEXT[TEXT.index("## 2. The worker"):].split())


def test_no_worker_starts_before_the_size_check():
    size = FLAT.index("## 1. The size check")
    make_plan = FLAT.index("Run make-plan #<n>")
    worker = FLAT.index("start_worker(")
    assert size < make_plan < worker
    step = " ".join(part("3. When it is not small", "## 2. The worker").split())
    assert "Never start a worker for a change that is not small" in step
    assert "refused: too large" in step


def test_quick_runs_the_protected_path_check_three_times():
    for heading, nxt in (("## 2. The worker", "## 3. The final review"), ("## 5. The fix round", "## 6. The pull request"),
                         ("## 6. The pull request", None)):
        assert "--no-renames" in part(heading, nxt), heading
    six = part("## 6. The pull request")
    create = six.index("github.pr_create")
    assert six.index("--no-renames") < create
    assert six.index("tld plan summary-check") < create


def test_quick_pushes_each_fix_merge_before_the_checks_that_read_origin():
    four = " ".join(part("## 4. The definition of done", "## 5. The fix round").split())
    assert "push `<feature>`" in four
    five = " ".join(part("## 5. The fix round", "## 6. The pull request").split())
    assert "push `<feature>`" in five and "never force" in five
    assert five.index("push `<feature>`") < five.index("--no-renames")
    assert FLAT.index("push `<feature>`", FLAT.index("## 5. The fix round")) < FLAT.index("github.pr_create")


def run_record(**changes):
    items = [{"id": i, "title": i, "depends_on": [], "complexity": "S", "state": "pending", "session": None,
              "branch": None, "started_at": None, "finished_at": None}
             for i in ("implement", "final-review", "dod", "fix-findings", "pr")]
    base = json.loads((FIXTURES / "status-records" / "good-run.json").read_text())
    base.update({"plan_slug": "issue-7", "plan_url": None, "kind": "run", "command": None, "phases": items,
                 "status": "running", "last_event": "starting"})
    base.update(changes)
    return base


def test_quick_record_validates(tmp_path):
    rec = run_record()
    doc = subprocess.run(tld_cmd("board", "record-id", "--repo", "o/r", "--run", "--plan-slug", "issue-7"),
                         capture_output=True, text=True)
    assert doc.returncode == 0, doc.stderr
    assert rec["phases"][0]["state"] == "pending"
    path = tmp_path / "rec.json"
    path.write_text(json.dumps({**rec, "project": "r", "repo": "o/r"}))
    r = subprocess.run(tld_cmd("board", "validate-record", str(path), "--doc-id", doc.stdout.strip()),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert record.validate({**rec, "project": "r", "repo": "o/r"}, doc.stdout.strip()) == []


def test_quick_pr_step_passes_changed():
    calls = re.findall(r"tld plan summary-check [^`]*", TEXT)
    assert len(calls) == 1 and "--changed" in calls[0]
    six = " ".join(part("## 6. The pull request").split())
    assert "changes a workflow or the profile" in six and "Security" in six
