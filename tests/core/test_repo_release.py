"""This repository's own release workflow (.github/workflows/release.yml) and the one version it tags."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
import yaml

import tld
from conftest import ROOT

WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(WORKFLOW.read_text())


def step(doc, name):
    return next(s for s in doc["jobs"]["release"]["steps"] if s.get("name") == name)


def test_one_version_and_its_changelog_entry():
    package = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert package == plugin == tld.__version__
    if re.fullmatch(r"\d+\.\d+\.\d+", package):
        assert re.search(rf"^## \[{re.escape(package)}\]", (ROOT / "CHANGELOG.md").read_text(), re.M)


def test_triggers_environment_and_tokens(doc):
    on = doc.get("on", doc.get(True))
    assert list(on) == ["workflow_dispatch"]
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True
    assert doc["permissions"] == {"contents": "read"}
    job = doc["jobs"]["release"]
    assert job["environment"] == "tld-release" and job["if"] == "github.ref == 'refs/heads/main'"
    publish = step(doc, "Publish the tag and the release")
    assert publish["if"] == "inputs.dry_run == false"
    assert publish["env"]["GH_TOKEN"] == "${{ secrets.TLD_RELEASE_TOKEN }}"
    for s in job["steps"]:
        assert "${{" not in s.get("run", ""), s.get("name")
        if "git/tags" in s.get("run", "") or "release create" in s.get("run", ""):
            assert s["env"]["GH_TOKEN"] == "${{ secrets.TLD_RELEASE_TOKEN }}", s["name"]
    notes = step(doc, "Write the release notes")["run"]
    assert "generate-notes" in notes and "previous_tag_name" in notes


def run_version_step(doc, tmp_path, edit=None):
    for rel in ("pyproject.toml", ".claude-plugin/plugin.json", "src/tld/__init__.py", "CHANGELOG.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    if edit:
        edit(tmp_path)
    out, summary = tmp_path / "out", tmp_path / "summary"
    out.write_text("")
    r = subprocess.run(["bash", "-c", step(doc, "Read the version")["run"]], cwd=tmp_path, capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)})
    return r, out.read_text()


def test_version_step_reads_the_tag_and_the_changelog_entry(doc, tmp_path):
    r, out = run_version_step(doc, tmp_path)
    assert r.returncode == 0, r.stderr
    assert f"tag=v{tld.__version__}" in out.splitlines()
    assert (tmp_path / "release-notes.md").read_text().strip()


@pytest.mark.parametrize("edit, needle", [
    (lambda d: (d / "src/tld/__init__.py").write_text('__version__ = "9.9.9"\n'), "versions differ"),
    (lambda d: [(d / f).write_text((d / f).read_text().replace(f'"{tld.__version__}"', '"9.0.0.dev0"')) for f in
                ("pyproject.toml", ".claude-plugin/plugin.json", "src/tld/__init__.py")], "not a release version"),
    (lambda d: (d / "CHANGELOG.md").write_text("# Changelog\n"), "has no '## ["),
])
def test_version_step_refuses(doc, tmp_path, edit, needle):
    r, out = run_version_step(doc, tmp_path, edit)
    assert r.returncode != 0 and needle in r.stderr and "tag=" not in out
