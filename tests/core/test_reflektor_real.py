"""Runs the real pinned Reflektor release end to end (opt-in: TLD_REFLEKTOR_REAL=1; needs network and node)."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, need_browser
from tld.board import report_check
from tld.roles import reflektor

pytestmark = [
    pytest.mark.skipif(os.environ.get("TLD_REFLEKTOR_REAL") != "1", reason="needs network and node: set TLD_REFLEKTOR_REAL=1"),
    pytest.mark.slow,
]

REPORT = {
    "version": 1, "tag": "FEATURE", "title": "Add sub to math", "summary": "Adds a sub function next to add.",
    "targets": [], "reviewMinutes": 0, "beforeMerge": [], "flows": [],
    "sections": [{
        "title": "Core change", "kind": "backend", "review": "must", "reason": "New public function.",
        "highlights": [{"kind": "behavior", "text": "sub(a, b) returns a - b.", "ref": {"path": "src/math.js", "line": 4}}],
        "questions": [], "files": [{"path": "src/math.js", "note": "New sub function."}],
    }],
    "testing": {"gaps": ["No test covers sub."]},
}


def git(cwd, *args):
    done = subprocess.run(["git", "-c", "user.email=t@t.t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    existed_before = (Path.home() / ".reflektor").exists()
    base = tmp_path_factory.mktemp("reflektor")
    src = base / "repo"
    src.mkdir()
    git(src, "init", "-q", "-b", "main")
    (src / "src").mkdir()
    (src / "src" / "math.js").write_text("export function add(a, b) {\n  return a + b;\n}\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "add")
    git(src, "checkout", "-q", "-b", "feature/x")
    with open(src / "src" / "math.js", "a") as fh:
        fh.write("export function sub(a, b) {\n  return a - b;\n}\n")
    git(src, "commit", "-q", "-am", "sub")
    base_sha = git(src, "rev-parse", "main")
    clone = base / "clone"
    git(base, "clone", "-q", "--local", str(src), str(clone))
    git(clone, "checkout", "-q", "feature/x")
    s = base / "s"
    s.mkdir()
    out = base / "out"
    out.mkdir()
    home = base / "home"
    home.mkdir()
    rdir = reflektor.prepare(s, clone, base_sha)
    node = shutil.which("node")
    env = ["env", "-i", f"PATH={Path(node).parent}:/usr/bin:/bin", "LANG=C.UTF-8", f"HOME={home}",
           f"REFLEKTOR_HOME={home / '.reflektor'}", "GIT_CONFIG_NOSYSTEM=1", "timeout", "600", node]
    collect = subprocess.run([*env, str(rdir / "scripts" / "collect.mjs"), "--repo", str(clone), "--base", base_sha,
                              "--no-fetch", "--no-uncommitted", "--out", str(out / "diff.json")],
                             capture_output=True, text=True)
    report_text = json.dumps(REPORT, separators=(",", ":")) + "\n"
    (out / "report.json").write_text(report_text)
    assert reflektor.check_report(report_text, clone) == []
    build = subprocess.run([*env, str(rdir / "scripts" / "build.mjs"), "--diff", str(out / "diff.json"),
                            "--report", str(out / "report.json"), "--html", str(out / "report.html")],
                           capture_output=True, text=True)
    page = out / "report.html"
    if build.returncode == 0 and page.exists():
        reflektor.harden_html(page)
    return {"base": base, "clone": clone, "s": s, "out": out, "rdir": rdir, "collect": collect, "build": build,
            "existed_before": existed_before}


def test_collect_and_build_succeed(real):
    assert real["collect"].returncode == 0, real["collect"].stdout + real["collect"].stderr
    assert real["build"].returncode == 0, real["build"].stdout + real["build"].stderr
    assert (real["out"] / "report.html").is_file()
    assert (real["out"] / "pr-description.md").is_file()


def test_viewer_parts_match_the_real_viewer(real):
    text = (real["rdir"] / "assets" / "viewer.html").read_text(encoding="utf-8")
    head = "<head>"
    title = "<title>PR report</title>"
    mark = "__REFLEKTOR_DATA__"
    assert text.count(head) == 1 and text.count(title) == 1 and text.count(mark) == 1
    a = text.index(head) + len(head)
    b = text.index(title)
    c = b + len(title)
    d = text.index(mark)
    parts = (text[:a], text[a:b], text[c:d], text[d + len(mark):])
    found = tuple((len(p), hashlib.sha256(p.encode("utf-8")).hexdigest()) for p in parts)
    assert found == report_check.VIEWER_PARTS, [n for n, _h in found]


def test_page_verifies_and_a_changed_byte_does_not(real):
    text = (real["out"] / "report.html").read_text(encoding="utf-8")
    assert reflektor.verify_html(text) == []
    mid = text.index(report_check.TITLE_CLOSE) + len(report_check.TITLE_CLOSE) + report_check.VIEWER_PARTS[2][0] // 2
    flipped = text[:mid] + ("a" if text[mid] != "a" else "b") + text[mid + 1:]
    assert flipped != text
    assert any("part 3" in r for r in reflektor.verify_html(flipped))


def test_send_copy(real, tmp_path):
    page = real["out"] / "report.html"
    answer = tmp_path / "answer.txt"
    answer.write_text(f"Findings: none.\nREPORT-HTML {page}\n")
    dest = tmp_path / "sent"
    sent = reflektor.send_copy(answer, dest)
    assert sent == dest / "report.html"
    assert sent.read_bytes() == page.read_bytes()


def test_home_reflektor_untouched(real):
    assert (Path.home() / ".reflektor").exists() == real["existed_before"]


@pytest.mark.slow
def test_page_renders_in_a_browser(real):
    need_browser()
    done = subprocess.run(["node", str(ROOT / "tests" / "reflektor_page_check.js"), str(real["out"] / "report.html")],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["requests"] == ["file://" + str(real["out"] / "report.html")]
    assert result["errors"] == []
    assert "Add sub to math" in result["text"]


def test_page_that_quotes_the_allow_mark_is_built_and_stored(real, tmp_path):
    clone = tmp_path / "clone-copy"  # the shared clone stays on its branch for the other tests
    shutil.copytree(real["clone"], clone, symlinks=True)
    git(clone, "checkout", "-q", "-b", "feature/quote")
    (clone / "NOTES.md").write_text(f"The guard skips a line that ends in {reflektor.ALLOW_MARK} in prose.\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "quote the mark")
    base_sha = git(clone, "rev-parse", "origin/main")
    out = tmp_path / "out"
    out.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    node = shutil.which("node")
    env = ["env", "-i", f"PATH={Path(node).parent}:/usr/bin:/bin", "LANG=C.UTF-8", f"HOME={home}",
           f"REFLEKTOR_HOME={home / '.reflektor'}", "GIT_CONFIG_NOSYSTEM=1", "timeout", "600", node]
    rdir = real["rdir"]
    collect = subprocess.run([*env, str(rdir / "scripts" / "collect.mjs"), "--repo", str(clone), "--base", base_sha,
                              "--no-fetch", "--no-uncommitted", "--out", str(out / "diff.json")],
                             capture_output=True, text=True)
    assert collect.returncode == 0, collect.stdout + collect.stderr
    (out / "report.json").write_text(json.dumps(REPORT, separators=(",", ":")) + "\n")
    build = subprocess.run([*env, str(rdir / "scripts" / "build.mjs"), "--diff", str(out / "diff.json"),
                            "--report", str(out / "report.json"), "--html", str(out / "report.html")],
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    page = out / "report.html"
    reflektor.harden_html(page)
    text = page.read_text(encoding="utf-8")
    assert report_check.check(text) == []
    assert reflektor.ALLOW_MARK not in text
    assert reflektor.REDACTED_MARK in text
    assert reflektor.ALLOW_MARK not in (rdir / "assets" / "viewer.html").read_text(encoding="utf-8")
