"""The committed baseline is measured against the current commands: a change to a command file, its playbook, or
a policy, role, checklist or stack the playbook links makes it stale, and this test fails until the baseline is
refreshed (`python3 evals/run.py baseline --refresh-hashes`, see docs/architecture/evals.md)."""
import json
import shutil

from conftest import ROOT

from evals.harness import baseline


def test_committed_baseline_is_current():
    data = json.loads(baseline.DEFAULT.read_text())
    stale = baseline.stale(data, baseline.command_hashes())
    assert not stale, (f"evals/baselines/default.json is stale for {stale}: re-run their tasks, or run "
                       "`python3 evals/run.py baseline --refresh-hashes`")


def _tree(tmp_path):
    for rel in ("adapters/claude/commands/land.md", "playbooks/land.md", "playbooks/runtime.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    shutil.copytree(ROOT / "playbooks" / "policies", tmp_path / "playbooks" / "policies")
    return tmp_path / "adapters/claude/commands/land.md"


def test_the_hash_covers_the_playbook_and_what_it_links(tmp_path):
    cmd = _tree(tmp_path)
    files = {str(p.relative_to(tmp_path)) for p in baseline.procedure_files(baseline.playbook_of(cmd, tmp_path), tmp_path)}
    assert {"playbooks/land.md", "playbooks/policies/profile.md", "playbooks/policies/status-board.md"} <= files
    before = baseline.command_hash(cmd, tmp_path)
    for rel in ("playbooks/land.md", "playbooks/policies/untrusted-text.md", "adapters/claude/commands/land.md"):
        path = tmp_path / rel
        text = path.read_text()
        path.write_text(text + "\nOne more line.\n")
        assert baseline.command_hash(cmd, tmp_path) != before, rel
        path.write_text(text)
    assert baseline.command_hash(cmd, tmp_path) == before
    (tmp_path / "playbooks" / "unlinked.md").write_text("not linked from land\n")
    assert baseline.command_hash(cmd, tmp_path) == before


def test_refresh_rewrites_only_the_hashes(tmp_path):
    path = tmp_path / "b.json"
    data = json.loads(baseline.DEFAULT.read_text())
    data["command_hashes"] = {**data["command_hashes"], "land.md": "0" * 16}
    path.write_text(json.dumps(data))
    assert baseline.refresh(path, "2026-01-02") == ["land.md"]
    new = json.loads(path.read_text())
    assert new["tasks"] == data["tasks"] and new["hashes_refreshed"] == "2026-01-02"
    assert baseline.stale(new, baseline.command_hashes()) == []


def test_check_baseline_command(tmp_path, capsys):
    from evals.harness import cli
    path = tmp_path / "b.json"
    data = json.loads(baseline.DEFAULT.read_text())
    path.write_text(json.dumps({**data, "command_hashes": {"land.md": "x"}}))
    assert cli.main(["check-baseline", "--baseline", str(path)]) == 1
    assert "stale for" in capsys.readouterr().err
    assert cli.main(["baseline", "--refresh-hashes", "--out", str(path)]) == 0
    assert cli.main(["check-baseline", "--baseline", str(path)]) == 0
