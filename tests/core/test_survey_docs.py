"""survey_docs.scan on the /setup fixtures and on small hand-made trees."""
import json
import subprocess
import sys

from conftest import tld_cmd

from tld.profile import survey_docs as sd  # noqa: E402
from evals.fixtures.setup_repos import build  # noqa: E402


def test_docs_website(tmp_path):
    build(tmp_path, "docs_website")
    out = sd.scan(tmp_path)
    assert out["must_read"][0] == "README.md"
    assert out["adr_dir"] == "docs/adr"
    assert out["adr_index"] == "docs/adr/README.md"
    assert out["changelog"] == {"file": "CHANGELOG.md", "section": "## [Unreleased]"}
    web = out["website"]
    assert (web["dir"], web["tool"]) == ("website", "docusaurus")
    assert (web["build"], web["links"]) == ("npm run build", "npm run check-links")


def test_bare(tmp_path):
    build(tmp_path, "bare")
    out = sd.scan(tmp_path)
    assert out == {"must_read": ["README.md"], "adr_dir": None, "adr_index": None,
                   "changelog": None, "website": None}


def test_root_mkdocs(tmp_path):
    (tmp_path / "mkdocs.yml").write_text("site_name: x\n")
    web = sd.scan(tmp_path)["website"]
    assert (web["dir"], web["tool"], web["build"], web["links"]) == (".", "mkdocs", "mkdocs build --strict", None)
    assert web["evidence"] == ["mkdocs.yml"]


def test_docusaurus_without_package_json(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "docusaurus.config.js").write_text("module.exports = {};\n")
    web = sd.scan(tmp_path)["website"]
    assert web["tool"] == "docusaurus" and web["build"] is None and web["dir"] == "site"


def test_changelog_without_unreleased(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.0]\n- x\n")
    assert sd.scan(tmp_path)["changelog"] == {"file": "CHANGELOG.md", "section": None}


def test_adr_index_falls_back_to_index_md(tmp_path):
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / "docs" / "decisions" / "index.md").write_text("# ADRs\n")
    out = sd.scan(tmp_path)
    assert out["adr_dir"] == "docs/decisions"
    assert out["adr_index"] == "docs/decisions/index.md"


def test_must_read_extras_sorted(tmp_path):
    (tmp_path / "docs").mkdir()
    for n in ("docs/design-b.md", "docs/architecture.md", "docs/design.md", "SECURITY.md", "README.md"):
        (tmp_path / n).write_text("x\n")
    assert sd.scan(tmp_path)["must_read"] == [
        "README.md", "SECURITY.md", "docs/architecture.md", "docs/design-b.md", "docs/design.md"]


def test_cli(tmp_path):
    build(tmp_path, "docs_website")
    res = subprocess.run([*tld_cmd("profile", "survey-docs"), str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode == 0
    assert json.loads(res.stdout)["adr_dir"] == "docs/adr"
    assert sd.main([str(tmp_path / "missing")]) == 1
