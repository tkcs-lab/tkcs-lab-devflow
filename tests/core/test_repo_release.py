"""This repository's own release workflow (.github/workflows/release.yml) and the one version it tags."""
from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys

import pytest
import yaml

import tld
from conftest import ROOT, need_tool

WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(WORKFLOW.read_text())


BUILD_STEPS = ["Read the version", "Check that the tag is new and find the previous one", "Set up Python",
               "Build the wheel and the sdist", "Set up QEMU", "Set up Buildx", "Log in to ghcr",
               "Build the board image", "Collect the release assets", "Upload the release assets"]
PUBLISH_STEPS = ["Download the release assets", "Check the release assets against SHA256SUMS",
                 "Check that the commit is green", "Write the release notes", "Publish the tag and the release"]


def step(doc, name):
    """The step called NAME, looked up in the job that owns it (the names are unique across both jobs)."""
    job = "publish" if name in PUBLISH_STEPS else "build"
    return next(s for s in doc["jobs"][job]["steps"] if s.get("name") == name)


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
    assert list(doc["jobs"]) == ["build", "publish"]
    for job in doc["jobs"].values():
        assert job["environment"] == "tld-release" and job["if"] == "github.ref == 'refs/heads/main'"
    assert doc["jobs"]["publish"]["needs"] == "build" and "needs" not in doc["jobs"]["build"]
    publish = step(doc, "Publish the tag and the release")
    assert publish["if"] == "inputs.dry_run == false"
    assert publish["env"]["GH_TOKEN"] == "${{ secrets.TLD_RELEASE_TOKEN }}"
    for job in doc["jobs"].values():
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


# ---- the steps that build the assets and the image (Design D4) ----

def names(job):
    return [s["name"] for s in yaml.safe_load(WORKFLOW.read_text())["jobs"][job]["steps"] if "name" in s]


NEW_STEPS = ["Set up Python", "Build the wheel and the sdist", "Set up QEMU", "Set up Buildx", "Log in to ghcr",
             "Build the board image", "Collect the release assets", "Upload the release assets"]


def test_each_job_has_its_steps_in_order(doc):
    assert names("build") == BUILD_STEPS
    assert names("publish") == PUBLISH_STEPS
    assert BUILD_STEPS[2:] == NEW_STEPS


def test_image_is_built_before_the_tag_and_pushed_only_when_not_a_dry_run(doc):
    # the image is built in the build job, which publish needs: so it precedes the tag
    assert "Build the board image" in names("build") and "Publish the tag and the release" in names("publish")
    assert doc["jobs"]["publish"]["needs"] == "build"
    assert step(doc, "Build the board image")["with"]["push"] == "${{ inputs.dry_run == false }}"
    assert step(doc, "Log in to ghcr")["if"] == "inputs.dry_run == false"


def test_build_step_has_platforms_tags_and_file(doc):
    build = step(doc, "Build the board image")
    assert build["id"] == "image"
    w = build["with"]
    assert w["platforms"] == "linux/amd64,linux/arm64" and w["file"] == "deploy/board/Dockerfile" and w["context"] == "."
    image = "ghcr.io/${{ github.repository_owner }}/tld-board"
    assert w["tags"].strip().splitlines() == [f"{image}:${{{{ steps.version.outputs.version }}}}", f"{image}:latest"]


def test_new_actions_are_the_pinned_shas_of_d4(doc):
    expected = {
        "Set up Python": "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "Set up QEMU": "docker/setup-qemu-action@c7c53464625b32c7a7e944ae62b3e17d2b600130",
        "Upload the release assets": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
        "Download the release assets": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
        "Set up Buildx": "docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
        "Log in to ghcr": "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9",
        "Build the board image": "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
    }
    for name, uses in expected.items():
        assert step(doc, name)["uses"] == uses, name
    assert step(doc, "Set up Python")["with"]["python-version"] == "3.13"
    login = step(doc, "Log in to ghcr")["with"]
    assert login == {"registry": "ghcr.io", "username": "${{ github.actor }}", "password": "${{ github.token }}"}


def test_job_permissions(doc):
    assert doc["jobs"]["build"]["permissions"] == {"contents": "read", "packages": "write"}
    assert doc["jobs"]["publish"]["permissions"] == {"contents": "read"}


def test_the_build_job_never_references_the_release_token(doc):
    build = yaml.safe_dump(doc["jobs"]["build"])
    assert "secrets" not in build.lower() and "env" not in doc
    text = WORKFLOW.read_text()
    assert "secrets" not in text.split("\n  build:\n")[1].split("\n  publish:\n")[0]


def test_release_token_is_only_in_the_publish_job_steps_that_use_it(doc):
    using = [(name, s["name"]) for name, job in doc["jobs"].items() for s in job["steps"]
             if "secrets.TLD_RELEASE_TOKEN" in yaml.safe_dump(s)]
    assert using == [("publish", n) for n in
                     ("Check that the commit is green", "Write the release notes", "Publish the tag and the release")]
    assert WORKFLOW.read_text().count("secrets.") == 3


def test_publish_job_runs_no_third_party_build_code(doc):
    uses = [s["uses"] for s in doc["jobs"]["publish"]["steps"] if "uses" in s]
    assert uses == ["actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"]
    run = "\n".join(s.get("run", "") for s in doc["jobs"]["publish"]["steps"])
    for word in ("pip install", "docker ", "python -m", "setup.py"):
        assert word not in run, word


def test_build_exposes_what_publish_needs(doc):
    out = doc["jobs"]["build"]["outputs"]
    assert out["version"] == "${{ steps.version.outputs.version }}" and out["tag"] == "${{ steps.version.outputs.tag }}"
    assert out["digest"] == "${{ steps.image.outputs.digest }}"
    assert out["previous"] == "${{ steps.previous.outputs.previous }}"
    assert step(doc, "Publish the tag and the release")["env"]["TAG"] == "${{ needs.build.outputs.tag }}"
    assert step(doc, "Write the release notes")["env"]["PREVIOUS"] == "${{ needs.build.outputs.previous }}"


def test_artifact_carries_dist_and_the_notes_and_is_kept_explicitly(doc):
    up = step(doc, "Upload the release assets")["with"]
    assert up["name"] == "release-dist" and up["path"].split() == ["dist/", "release-notes.md"]
    assert up["retention-days"] == 14 and up["if-no-files-found"] == "error"
    assert step(doc, "Download the release assets")["with"] == {"name": "release-dist", "path": "."}


def test_qemu_image_is_pinned_by_digest(doc):
    assert re.fullmatch(r"docker\.io/tonistiigi/binfmt@sha256:[0-9a-f]{64}", step(doc, "Set up QEMU")["with"]["image"])


def test_green_check_skips_its_own_job(doc):
    assert step(doc, "Check that the commit is green")["env"]["SELF"] == "publish"


def test_publish_creates_a_draft_with_every_asset_then_publishes(doc):
    run = step(doc, "Publish the tag and the release")["run"]
    for needle in ("--verify-tag", "--draft", "--repo", "dist/*", "--draft=false", '-- "$TAG" ./dist/*'):
        assert needle in run, needle
    assert run.index("git/tags") < run.index("release create") < run.index("--draft=false")
    assert "release edit" in run


def test_publish_failure_names_the_artifact_and_the_summary_links_the_public_release(doc):
    s = step(doc, "Publish the tag and the release")
    assert s["env"]["RUN_ID"] == "${{ github.run_id }}"
    assert "release-dist" in s["run"] and "gh run download" in s["run"]
    assert 'gh release view "$TAG" --repo "$REPO" --json url -q .url' in s["run"]
    assert s["run"].index("release edit") < s["run"].index("release view")


def run_check(doc, work, tag="v9.9.9", previous=""):
    s = step(doc, "Check the release assets against SHA256SUMS")
    return subprocess.run(["bash", "-c", s["run"]], cwd=work, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "TAG": tag, "PREVIOUS": previous})


def good_dist(work):
    dist = work / "dist"
    dist.mkdir()
    names = ["compose.yaml", "install.sh", "tld-9.9.9-py3-none-any.whl", "tld-9.9.9.tar.gz"]
    for n in names:
        (dist / n).write_text(n)
    subprocess.run("sha256sum " + " ".join(names) + " > SHA256SUMS", shell=True, cwd=dist, check=True)
    return dist


@pytest.mark.parametrize("tag, previous", [("--foo", ""), ("v9.9.9\nx", ""), ("v9.9", ""), ("v9.9.9", "v1.0"),
                                           ("v9.9.9", "-x"), ("v9.9.8", "")])
def test_publish_refuses_a_tag_the_build_job_made_up(doc, tmp_path, tag, previous):
    need_tool("sha256sum")
    good_dist(tmp_path)
    r = run_check(doc, tmp_path, tag, previous)
    assert r.returncode != 0 and "::error::" in r.stdout + r.stderr


def test_publish_accepts_a_clean_dist_and_refuses_extra_files(doc, tmp_path):
    need_tool("sha256sum")
    dist = good_dist(tmp_path)
    assert run_check(doc, tmp_path, previous="v9.9.8").returncode == 0
    (dist / "extra.sh").write_text("x")
    assert run_check(doc, tmp_path).returncode != 0
    (dist / "extra.sh").unlink()
    (dist / "link").symlink_to("install.sh")
    assert run_check(doc, tmp_path).returncode != 0


def test_publish_checks_the_checksums_and_fails_on_a_mismatch(doc, tmp_path):
    need_tool("sha256sum")
    s = step(doc, "Check the release assets against SHA256SUMS")
    assert names("publish").index(s["name"]) < names("publish").index("Check that the commit is green")
    dist = good_dist(tmp_path)
    assert run_check(doc, tmp_path).returncode == 0
    (dist / "install.sh").write_text("tampered")
    bad = run_check(doc, tmp_path)
    assert bad.returncode != 0 and "::error::" in bad.stdout + bad.stderr


def fake_python(directory, writes_dist):
    """A `python` that accepts `-m pip install ...` and, for `-m build`, creates the wheel and the sdist or nothing."""
    directory.mkdir(parents=True, exist_ok=True)
    body = ['#!/bin/sh', 'case "$1 $2" in', '  "-m build")']
    if writes_dist:
        body += ['    mkdir -p dist', '    : > "dist/tld-$VERSION-py3-none-any.whl"', '    : > "dist/tld-$VERSION.tar.gz"']
    body += ['    exit 0 ;;', '  "-m pip") exit 0 ;;', 'esac', 'exit 0']
    script = directory / "python"
    script.write_text("\n".join(body) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def run_build_step(doc, tmp_path, writes_dist):
    fake_python(tmp_path / "fake", writes_dist)
    work = tmp_path / "work"
    work.mkdir()
    env = {"PATH": f"{tmp_path / 'fake'}:/usr/bin:/bin", "VERSION": "9.9.9"}
    return subprocess.run(["bash", "-c", step(doc, "Build the wheel and the sdist")["run"]], cwd=work,
                          capture_output=True, text=True, env=env)


def test_build_step_fails_without_the_wheel(doc, tmp_path):
    r = run_build_step(doc, tmp_path, writes_dist=False)
    assert r.returncode != 0 and "::error::" in r.stdout + r.stderr


def test_build_step_passes_with_both_files(doc, tmp_path):
    r = run_build_step(doc, tmp_path, writes_dist=True)
    assert r.returncode == 0, r.stderr
    assert "::error::" not in r.stdout + r.stderr


def prepare_collect(tmp_path, extra_compose=""):
    work = tmp_path / "collect"
    (work / "deploy" / "board").mkdir(parents=True)
    (work / "dist").mkdir()
    shutil.copy(ROOT / "deploy" / "install.sh", work / "deploy" / "install.sh")
    compose = (ROOT / "deploy" / "board" / "compose.yaml").read_text() + extra_compose
    (work / "deploy" / "board" / "compose.yaml").write_text(compose)
    (work / "dist" / "tld-9.9.9-py3-none-any.whl").write_bytes(b"")
    (work / "dist" / "tld-9.9.9.tar.gz").write_bytes(b"")
    return work


def run_collect(doc, work, tmp_path, **overrides):
    env = {"PATH": "/usr/bin:/bin", "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"), "VERSION": "9.9.9",
           "IMAGE": "ghcr.io/x/tld-board", "DIGEST": "sha256:abc", "DRY_RUN": "false", **overrides}
    return subprocess.run(["bash", "-c", step(doc, "Collect the release assets")["run"]], cwd=work,
                          capture_output=True, text=True, env=env)


def test_collect_step_stamps_and_checksums(doc, tmp_path):
    need_tool("sha256sum")
    work = prepare_collect(tmp_path)
    r = run_collect(doc, work, tmp_path)
    assert r.returncode == 0, r.stderr
    dist = work / "dist"
    assert sorted(f.name for f in dist.iterdir()) == sorted([
        "tld-9.9.9-py3-none-any.whl", "tld-9.9.9.tar.gz", "install.sh", "compose.yaml", "SHA256SUMS"])
    for name in ("install.sh", "compose.yaml"):
        assert "@TLD_" not in (dist / name).read_text()
    assert "ghcr.io/x/tld-board@sha256:abc" in (dist / "compose.yaml").read_text()
    lines = (dist / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == 4 and all("/" not in line.split("  ", 1)[1] for line in lines)
    assert subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=dist, capture_output=True).returncode == 0
    assert step(doc, "Collect the release assets")["run"].startswith("set -euo pipefail")
    summary = (tmp_path / "summary").read_text()
    assert "ghcr.io/x/tld-board@sha256:abc" in summary and "install.sh" in summary


def test_collect_step_without_a_digest_fails_unless_dry_run(doc, tmp_path):
    work = prepare_collect(tmp_path)
    r = run_collect(doc, work, tmp_path, DIGEST="")
    assert r.returncode != 0 and "::error::" in r.stdout + r.stderr


def test_collect_step_in_a_dry_run_uses_a_placeholder_digest(doc, tmp_path):
    work = prepare_collect(tmp_path)
    r = run_collect(doc, work, tmp_path, DIGEST="", DRY_RUN="true")
    assert r.returncode == 0, r.stderr
    assert "sha256:dry-run" in (work / "dist" / "compose.yaml").read_text()


def test_collect_step_refuses_an_unstamped_token(doc, tmp_path):
    work = prepare_collect(tmp_path, extra_compose="# @TLD_OTHER@\n")
    r = run_collect(doc, work, tmp_path)
    assert r.returncode != 0 and "::error::" in r.stdout + r.stderr


@pytest.mark.slow
def test_stamped_installer_from_the_collect_step_is_not_refused(doc, tmp_path):
    need_tool("sh")
    need_tool("curl")
    work = prepare_collect(tmp_path)
    assert run_collect(doc, work, tmp_path).returncode == 0
    empty = tmp_path / "empty"
    empty.mkdir()
    home = tmp_path / "home"
    tmp = tmp_path / "tmp"
    home.mkdir()
    tmp.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "XDG_DATA_HOME": str(home / "data"),
           "TLD_BIN_DIR": str(home / "bin"), "TMPDIR": str(tmp), "TLD_PYTHON": sys.executable,
           "TLD_RELEASE_BASE": f"file://{empty}"}
    r = subprocess.run(["sh", str(work / "dist" / "install.sh")], capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "cannot download" in r.stderr and "not from a release" not in r.stderr
