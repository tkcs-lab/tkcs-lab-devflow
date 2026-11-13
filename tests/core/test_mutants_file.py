"""The hand-written mutants of the mutation check (tests/mutation/) still apply to the code: each `old` text is in
its file exactly once, and its tests exist. The check itself runs weekly (.github/workflows/mutation.yml)."""
import subprocess
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tests" / "mutation"))
import run_mutants  # noqa: E402

MODULES = ("src/tld/guard/", "src/tld/profile/validate.py", "src/tld/plan/manifest.py", "src/tld/plan/active.py",
           "src/tld/plan/summary.py",
           "src/tld/ops/release_prepare.py")


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
