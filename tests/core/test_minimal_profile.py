"""A minimal profile (plan 90, section 3.1): `verify` plus empty `deps:`, `spec:` and `sysml:` sections and an
extended base runs every command that reads the profile. Real CLI calls in a tmp repository; no network."""
import json
import os
import subprocess

import yaml

from conftest import tld_cmd
from tld.profile import base as base_mod

REF = base_mod.BaseRef("acme", "org", "tld/base.yaml", "a" * 40)
BASE_TEXT = """\
roles:
  posture: {security: standard}
  required:
    - {role: security-reviewer, at: [dod], blocking: true}
"""
MODEL = "package Core {\n  part def Api { doc /* the api */ }\n}\n"
MANIFEST = {
    "plan_slug": "demo", "feature_branch": "feature/demo",
    "phases": [{"id": "p1-core", "title": "Core", "depends_on": [], "complexity": "S", "touches": ["src/core.py"],
                "brief": "do it", "acceptance": ["make test passes"]}],
}


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k.startswith("GIT_CONFIG_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.test", GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def build(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".tld").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "sysml" / "model").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    profile = (f"tld:\n  extends: {REF.source}@{REF.sha}\n"
               "verify:\n  fast: ['true']\n  dod: ['true']\n"
               "deps:\nspec:\nsysml:\n")
    (repo / ".tld" / "toolkit.yaml").write_text(profile)
    (repo / "docs" / "README.md").write_text("# Docs\n\n- [guide.md](guide.md) - the guide; read when using it.\n")
    (repo / "docs" / "guide.md").write_text("# Guide\n")
    (repo / "CLAUDE.md").write_text("Read [the docs index](docs/README.md).\n")
    (repo / "sysml" / "model" / "api.sysml").write_text(MODEL)
    (repo / "plan.yaml").write_text(yaml.safe_dump(MANIFEST))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "--stdin"], input=BASE_TEXT, capture_output=True,
                          text=True, check=True).stdout.strip()
    base_mod._store(base_mod.common_dir(repo), REF, BASE_TEXT.encode(), blob)
    return repo


def tld(repo, *args):
    return subprocess.run([*tld_cmd(*args[:2]), *args[2:]], cwd=repo, capture_output=True, text=True)


def test_a_minimal_profile_runs_every_command(tmp_path):
    repo = build(tmp_path)
    r = tld(repo, "profile", "validate", "--resolved")
    assert r.returncode == 0, r.stderr
    resolved = json.loads(r.stdout)
    assert resolved["deps"] == {"cooldown_days": 3, "time_budget_minutes": 90}  # the empty sections are on
    assert resolved["spec"]["version"] == "2.1.0" and resolved["sysml"]["subset"] == 1
    assert resolved["git"]["main_branch"] == "main" and resolved["docs"]["index"] == "docs/README.md"
    r = tld(repo, "roles", "required", "--profile", ".tld/toolkit.yaml", "--at", "dod", "--changed", "/dev/null")
    assert r.returncode == 0, r.stderr
    assert [i["role"] for i in json.loads(r.stdout)["required"]] == ["security-reviewer"]  # from the cached base
    r = tld(repo, "plan", "validate-manifest", "plan.yaml", "--profile", ".tld/toolkit.yaml")
    assert r.returncode == 0, r.stderr
    r = tld(repo, "ops", "docs-index", "check")
    assert r.returncode == 0, r.stdout + r.stderr
    r = tld(repo, "ops", "sysml", "check")
    assert r.returncode == 0, r.stdout + r.stderr
