"""survey_signals.scan on the /setup fixtures and on small hand-made trees."""
import json
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "plugins" / "devflow" / "scripts"))
import survey_signals as ss  # noqa: E402
from evals.fixtures.setup_repos import build  # noqa: E402


def scan_fixture(tmp_path, repo):
    build(tmp_path, repo)
    return ss.scan(tmp_path)


def test_security_heavy(tmp_path):
    out = scan_fixture(tmp_path, "security_heavy")
    assert out["security"]["score"] == 6
    assert out["security"]["firing"] == ["auth", "crypto", "credentials", "egress", "user_data", "policy_docs"]
    assert out["ui"]["globs"] == []
    assert out["tests"]["levels"] == {"unit": True, "integration": False, "e2e": False}
    assert out["source_files"] > 0


def test_ios_ui_app(tmp_path):
    out = scan_fixture(tmp_path, "ios_ui_app")
    assert out["security"]["firing"] == ["egress"]
    assert out["security"]["score"] == 1
    assert out["ui"]["globs"] == ["Sources/App/Views/**"]
    assert out["tests"]["levels"] == {"unit": True, "integration": False, "e2e": True}


def test_docs_website(tmp_path):
    out = scan_fixture(tmp_path, "docs_website")
    assert out["security"]["score"] == 0
    assert out["markdown_files"] == 11
    assert out["tests"]["levels"] == {"unit": True, "integration": False, "e2e": False}


def test_bare(tmp_path):
    out = scan_fixture(tmp_path, "bare")
    assert out["source_files"] == 0
    assert out["security"]["firing"] == [] and out["security"]["score"] == 0
    assert all(c["count"] == 0 and c["files"] == [] for c in out["security"]["categories"].values())
    assert out["ui"] == {"files": [], "globs": []}
    assert out["tests"]["levels"] == {"unit": False, "integration": False, "e2e": False}


def put(root, rel, text="x"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_root_ui_file_is_its_own_glob(tmp_path):
    put(tmp_path, "App.tsx")
    assert ss.scan(tmp_path)["ui"]["globs"] == ["App.tsx"]


def test_nested_ui_dirs_collapse(tmp_path):
    put(tmp_path, "web/a/B.vue")
    put(tmp_path, "web/a/c/D.vue")
    assert ss.scan(tmp_path)["ui"]["globs"] == ["web/a/**"]


def test_one_file_does_not_fire(tmp_path):
    put(tmp_path, "a.py", "def login(): pass")
    sec = ss.scan(tmp_path)["security"]
    assert sec["categories"]["auth"]["count"] == 1
    assert sec["firing"] == []
    put(tmp_path, "b.py", "def login(): pass")
    assert ss.scan(tmp_path)["security"]["firing"] == ["auth"]


def test_policy_docs_fires_with_one_file(tmp_path):
    put(tmp_path, "SECURITY.md")
    sec = ss.scan(tmp_path)["security"]
    assert sec["firing"] == ["policy_docs"] and sec["score"] == 1


def test_skipped_dirs(tmp_path):
    for d in ("node_modules/x", ".git/y"):
        put(tmp_path, f"{d}/a.py", "login")
        put(tmp_path, f"{d}/b.py", "login")
    out = ss.scan(tmp_path)
    assert out["source_files"] == 0
    assert out["security"]["firing"] == []


def test_large_file_not_read(tmp_path):
    put(tmp_path, "big.py", "login " + "#" * ss.MAX_BYTES)
    put(tmp_path, "small.py", "login")
    out = ss.scan(tmp_path)
    assert out["source_files"] == 2
    assert out["security"]["categories"]["auth"]["files"] == ["small.py"]


def test_list_cut_keeps_count(tmp_path):
    for i in range(25):
        put(tmp_path, f"m{i:02d}.py", "login")
    auth = ss.scan(tmp_path)["security"]["categories"]["auth"]
    assert auth["count"] == 25
    assert len(auth["files"]) == 20 and auth["files"] == sorted(auth["files"])


def test_test_paths_are_not_scanned(tmp_path):
    put(tmp_path, "tests/a.py", "login")
    put(tmp_path, "b_test.go", "login")
    assert ss.scan(tmp_path)["security"]["categories"]["auth"]["count"] == 0


def test_cli_prints_json(tmp_path):
    put(tmp_path, "a.py")
    res = subprocess.run([sys.executable, str(ROOT / "plugins/devflow/scripts/survey_signals.py"), str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode == 0 and json.loads(res.stdout)["source_files"] == 1
    assert ss.main([str(tmp_path / "nope")]) == 1
