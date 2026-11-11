"""The tld-release workflow template: structure, and its scripts run for real against a stub gh."""
import json
import os
import re
import shutil
import subprocess

import pytest
import yaml

from conftest import TLD, FORBIDDEN
from conftest import FORBIDDEN

TEMPLATE = TLD / "templates" / "tld-release.yml"

# Stub gh: serves JSON from $STUB_DIR, applies the --jq expression with the real jq, logs every call.
STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_DIR/calls.log"
args="$*"
jqexpr=""; prev=""
for a in "$@"; do [ "$prev" = "--jq" ] && jqexpr=$a; prev=$a; done
if [ "$1" = release ] && [ "$2" = create ]; then
  [ -n "${FAIL_RELEASE:-}" ] && exit 1
  echo "https://example.test/releases/$3"; exit 0
fi
[ "$1" = api ] || exit 2
case "$args" in
  *matching-refs*) jq -r "$jqexpr" "$STUB_DIR/refs.json" ;;
  *git/ref/tags/*)
    tag=${args##*git/ref/tags/}; tag=${tag%% *}
    case ",${EXISTING:-}," in *",$tag,"*) echo '{}' ;; *) exit 1 ;; esac ;;
  *check-runs*) jq -r "$jqexpr" "$STUB_DIR/checks.json" ;;
  */status*) jq -r "$jqexpr" "$STUB_DIR/status.json" ;;
  *generate-notes*) echo "- a change" ;;
  *git/tags*) echo objsha ;;
  *git/refs*) echo '{}' ;;
  *) exit 2 ;;
esac
"""

needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(TEMPLATE.read_text())


def step(doc, name):
    steps = doc["jobs"]["release"]["steps"]
    return next(s for s in steps if s["name"] == name)


def test_triggers_and_settings(doc):
    on = doc[True]  # YAML 1.1: the key `on` loads as boolean True
    assert list(on) == ["workflow_dispatch"]
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"version", "bump", "prerelease", "dry_run", "skip_checks"}
    assert inputs["dry_run"]["default"] is True, "a release must start as a dry run"
    assert inputs["prerelease"]["default"] is False and inputs["skip_checks"]["default"] is False
    assert inputs["bump"]["options"] == ["patch", "minor", "major"] and inputs["bump"]["default"] == "patch"
    assert doc["concurrency"] == {"group": "tld-release", "cancel-in-progress": False}
    assert doc["permissions"] == {"contents": "write", "checks": "read", "statuses": "read"}
    job = doc["jobs"]["release"]
    assert job["environment"] == "release", "every run waits for the reviewers of the release environment"
    assert job["if"] == "github.ref == 'refs/heads/__MAIN_BRANCH__'"
    assert [s["name"] for s in job["steps"]] == [
        "Decide the tag", "Check that the commit is green", "Show the release notes", "Publish the tag and the release"]
    assert step(doc, "Publish the tag and the release")["if"] == "inputs.dry_run == false"
    assert step(doc, "Check that the commit is green")["if"] == "inputs.skip_checks == false"


def test_no_third_party_action_and_no_expression_in_scripts(doc):
    for s in doc["jobs"]["release"]["steps"]:
        assert "uses" not in s
        assert "${{" not in s["run"], f"{s['name']}: an expression inside a script is a shell injection"


def test_only_known_placeholders():
    assert set(re.findall(r"__([A-Z_]+)__", TEMPLATE.read_text())) == {"MAIN_BRANCH", "TAG_PREFIX"}


def test_tokens_fall_back_to_the_default(doc):
    for s in doc["jobs"]["release"]["steps"]:
        assert s["env"]["GH_TOKEN"] == "${{ secrets.TLD_RELEASE_TOKEN || github.token }}"


def test_scripts_have_valid_syntax(doc, tmp_path):
    for i, s in enumerate(doc["jobs"]["release"]["steps"]):
        f = tmp_path / f"s{i}.sh"
        f.write_text(s["run"])
        subprocess.run(["bash", "-n", str(f)], check=True)


def test_no_forbidden_words():
    assert FORBIDDEN.search(TEMPLATE.read_text()) is None


@pytest.mark.parametrize("prefix", ["v", "", "release-"])
def test_renders_to_valid_yaml(ra, prefix):
    text = ra.render_template(TEMPLATE.read_text(), {"main_branch": "trunk", "tag_prefix": prefix})
    rendered = yaml.safe_load(text)
    assert rendered["jobs"]["release"]["if"] == "github.ref == 'refs/heads/trunk'"
    assert rendered["jobs"]["release"]["steps"][0]["env"]["PREFIX"] == prefix


def stub_env(tmp_path, refs=(), checks=None, status="success", statuses=1, **extra):
    d = tmp_path / "stub"
    d.mkdir(exist_ok=True)
    (d / "refs.json").write_text(json.dumps([{"ref": r} for r in refs]))
    (d / "checks.json").write_text(json.dumps({"check_runs": checks or []}))
    (d / "status.json").write_text(json.dumps({"state": status, "total_count": statuses}))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(STUB)
    gh.chmod(0o755)
    out, summary = tmp_path / "output", tmp_path / "summary"
    out.write_text("")
    summary.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "STUB_DIR": str(d), "GH_TOKEN": "t", "REPO": "o/r",
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary), **extra}
    return env, d, out, summary


def run_step(doc, name, env, tmp_path):
    f = tmp_path / "step.sh"
    f.write_text(step(doc, name)["run"])
    return subprocess.run(["bash", str(f)], env=env, capture_output=True, text=True)


def decide(doc, tmp_path, refs=(), version="", bump="patch", prefix="v", existing=""):
    env, d, out, _ = stub_env(tmp_path, refs, EXISTING=existing, VERSION=version, BUMP=bump, PREFIX=prefix)
    p = run_step(doc, "Decide the tag", env, tmp_path)
    return p, out.read_text().strip()


@needs_jq
@pytest.mark.parametrize("bump,expected", [("patch", "v1.10.1"), ("minor", "v1.11.0"), ("major", "v2.0.0")])
def test_bump_uses_the_highest_version_not_the_last_one_listed(doc, tmp_path, bump, expected):
    refs = ["refs/tags/v1.9.0", "refs/tags/v1.10.0", "refs/tags/v1.2.3", "refs/tags/v2.0.0-rc.1", "refs/tags/vnext", "refs/tags/v1.10"]
    p, out = decide(doc, tmp_path, refs, bump=bump)
    assert p.returncode == 0, p.stdout + p.stderr
    assert out == f"tag={expected}"


@needs_jq
def test_prefix_is_matched_literally(doc, tmp_path):
    refs = ["refs/tags/release-1.4.0", "refs/tags/release-1.3.0", "refs/tags/v9.9.9"]
    p, out = decide(doc, tmp_path, refs, prefix="release-")
    assert p.returncode == 0 and out == "tag=release-1.4.1"


@needs_jq
def test_empty_prefix(doc, tmp_path):
    p, out = decide(doc, tmp_path, ["refs/tags/1.0.0", "refs/tags/0.9.0"], prefix="", bump="minor")
    assert p.returncode == 0 and out == "tag=1.1.0"


@needs_jq
def test_explicit_version_wins(doc, tmp_path):
    p, out = decide(doc, tmp_path, ["refs/tags/v1.0.0"], version="3.0.0-rc.1")
    assert p.returncode == 0 and out == "tag=v3.0.0-rc.1"


@needs_jq
@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "01.2.3", "1.2.3; rm -rf /", "$(id)", "1.2.3\n4"])
def test_bad_version_is_rejected(doc, tmp_path, bad):
    p, out = decide(doc, tmp_path, ["refs/tags/v1.0.0"], version=bad)
    assert p.returncode == 1 and out == ""
    assert "::error::version must look like" in p.stdout


@needs_jq
def test_no_tag_and_no_version_asks_for_one(doc, tmp_path):
    p, out = decide(doc, tmp_path, ["refs/tags/v1.0.0-rc.1"])
    assert p.returncode == 1 and "explicit version" in p.stdout


@needs_jq
def test_existing_tag_stops(doc, tmp_path):
    p, out = decide(doc, tmp_path, ["refs/tags/v1.0.0"], version="1.0.1", existing="v1.0.1")
    assert p.returncode == 1 and "tag v1.0.1 already exists" in p.stdout and out == ""


def run_check(doc, tmp_path, checks, status="success", statuses=1):
    env, *_ = stub_env(tmp_path, checks=checks, status=status, statuses=statuses, SHA="abc", SELF="tld-release")
    return run_step(doc, "Check that the commit is green", env, tmp_path)


def run_(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


@needs_jq
def test_green_commit_passes_and_ignores_its_own_run(doc, tmp_path):
    p = run_check(doc, tmp_path, [run_("test"), run_("lint", conclusion="skipped"), run_("tld-release", "in_progress", None)])
    assert p.returncode == 0, p.stdout + p.stderr


@needs_jq
@pytest.mark.parametrize("bad", [run_("test", conclusion="failure"), run_("test", "in_progress", None),
                                 run_("test", conclusion="cancelled"), run_("test", conclusion="timed_out")])
def test_red_or_running_check_blocks(doc, tmp_path, bad):
    p = run_check(doc, tmp_path, [run_("lint"), bad])
    assert p.returncode == 1 and "not all green" in p.stdout and "test:" in p.stdout


@needs_jq
@pytest.mark.parametrize("state,statuses,code", [("failure", 1, 1), ("error", 1, 1), ("success", 1, 0), ("pending", 1, 1),
                                                  ("pending", 0, 0)])  # "pending" with no status at all is just "none yet"
def test_commit_status(doc, tmp_path, state, statuses, code):
    assert run_check(doc, tmp_path, [run_("test")], status=state, statuses=statuses).returncode == code


def publish(doc, tmp_path, prerelease="false", fail=False):
    env, d, *_ = stub_env(tmp_path, SHA="abc", TAG="v1.2.3", PRERELEASE=prerelease, FAIL_RELEASE="1" if fail else "")
    p = run_step(doc, "Publish the tag and the release", env, tmp_path)
    return p, (d / "calls.log").read_text().splitlines()


@needs_jq
def test_publish_creates_annotated_tag_then_release(doc, tmp_path):
    p, calls = publish(doc, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert calls[0].startswith("api -X POST repos/o/r/git/tags -f tag=v1.2.3 -f message=Release v1.2.3 -f object=abc -f type=commit")
    assert calls[1] == "api -X POST repos/o/r/git/refs -f ref=refs/tags/v1.2.3 -f sha=objsha"
    assert calls[2] == "release create v1.2.3 --verify-tag --generate-notes --title v1.2.3 --repo o/r"
    assert "https://example.test/releases/v1.2.3" in p.stdout


@needs_jq
def test_publish_prerelease_flag(doc, tmp_path):
    p, calls = publish(doc, tmp_path, prerelease="true")
    assert calls[2].endswith("--prerelease --repo o/r")


@needs_jq
def test_publish_tells_how_to_finish_when_the_release_fails(doc, tmp_path):
    p, calls = publish(doc, tmp_path, fail=True)
    assert p.returncode == 1
    assert "tag v1.2.3 was created but the release was not" in p.stdout and "gh release create v1.2.3" in p.stdout
