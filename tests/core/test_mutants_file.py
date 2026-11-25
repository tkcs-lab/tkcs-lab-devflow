"""The hand-written mutants of the mutation check (tests/mutation/) still apply to the code: each `old` text is in
its file exactly once, and its tests exist. The check itself runs weekly (.github/workflows/mutation.yml)."""
import subprocess
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tests" / "mutation"))
import run_mutants  # noqa: E402

MODULES = ("src/tld/board/record.py", "src/tld/guard/", "src/tld/profile/validate.py", "src/tld/profile/merge.py",
           "src/tld/profile/resolve.py", "src/tld/profile/base.py", "src/tld/profile/defaults.py", "src/tld/roles/reflektor.py", "src/tld/roles/page_note.py", "src/tld/plan/manifest.py", "src/tld/plan/active.py",
           "src/tld/plan/summary.py", "src/tld/plan/findings.py",
           "src/tld/ops/release_prepare.py", "src/tld/ops/spec.py", "src/tld/ops/sysml.py",
           "src/tld/sysml/files.py", "src/tld/sysml/change.py",
           "src/tld/ops/deps_checks.py", "src/tld/ops/deps_prepare.py", "src/tld/ops/deps_body.py")


def test_every_mutant_applies():
    tests, mutants = run_mutants.load()
    assert run_mutants.problems(tests, mutants) == []
    assert len(mutants) >= 50
    assert all(m["file"].startswith(MODULES) for m in mutants)
    assert {m["file"] for m in mutants} >= {"src/tld/guard/no_merge.py", "src/tld/guard/secret_scan.py",
                                            "src/tld/guard/protect_paths.py", "src/tld/profile/validate.py",
                                            "src/tld/plan/manifest.py"}


def test_a_mutant_that_no_longer_applies_is_reported(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n")
    (tmp_path / "t.py").write_text("")
    bad = run_mutants.problems({"a.py": ["t.py"]}, [{"id": "A", "file": "a.py", "old": "x = 1", "new": "x = 2"},
                                                     {"id": "A", "file": "b.py", "old": "y", "new": "z"}], tmp_path)
    assert any("occurs 2 times" in b for b in bad) and any("duplicate id" in b for b in bad)
    assert any("no file b.py" in b for b in bad)


def test_the_runner_rejects_an_unknown_mutant():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "mutation" / "run_mutants.py"), "--only", "NOPE"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "no such mutant: NOPE" in r.stderr


def test_a_mutant_whose_tests_are_all_slow_is_reported(tmp_path, monkeypatch):
    """pytest exits 5 when nothing is collected: that is not a kill, it is a mutant that was never tried."""
    repo = tmp_path / "src"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / "test_a.py").write_text("import pytest\n\n\n@pytest.mark.slow\ndef test_x():\n    assert False\n")
    monkeypatch.setattr(run_mutants, "ROOT", repo)
    mutant = {"id": "A", "file": "a.py", "why": "w", "old": "x = 1", "new": "x = 2"}
    (mutant_, verdict, detail), = run_mutants.run([mutant], {"a.py": ["test_a.py"]}, 120)
    assert verdict == "PROBLEM" and "no test selected" in detail
