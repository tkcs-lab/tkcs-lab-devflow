"""The tld-land workflow template: structure, and the script run against a stub gh."""
import json
import os
import shutil
import subprocess

import pytest
import yaml

from conftest import TLD, FORBIDDEN
from conftest import FORBIDDEN

TEMPLATE = TLD / "templates" / "tld-land.yml"

STUB = r"""#!/usr/bin/env bash
# Stub gh: serves JSON from $STUB_DIR and logs every call to $STUB_DIR/calls.log.
echo "$*" >> "$STUB_DIR/calls.log"
[ "$1" = api ] || exit 2
shift
method=GET; path=""; jqexpr=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method=$2; shift 2 ;;
    -f) shift 2 ;;
    --jq) jqexpr=$2; shift 2 ;;
    *) path=$1; shift ;;
  esac
done
[ "$method" = PUT ] && { echo '{}'; exit 0; }
case "$path" in
  */pulls\?*) file="$STUB_DIR/list.json" ;;
  */pulls/*)
    n=${path##*/}
    k=$(cat "$STUB_DIR/count_$n" 2>/dev/null || echo 0)
    echo $((k + 1)) > "$STUB_DIR/count_$n"
    file="$STUB_DIR/pr_${n}_$k.json"
    [ -f "$file" ] || file=$(ls "$STUB_DIR"/pr_${n}_*.json | sort -V | tail -1)
    ;;
  *) exit 2 ;;
esac
if [ -n "$jqexpr" ]; then jq -r "$jqexpr" "$file"; else cat "$file"; fi
"""

needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(TEMPLATE.read_text())


@pytest.fixture(scope="module")
def script(doc):
    steps = doc["jobs"]["update-next"]["steps"]
    assert len(steps) == 1
    return steps[0]["run"]


def test_triggers_and_settings(doc):
    on = doc[True]  # YAML 1.1: the key `on` loads as boolean True
    assert on["pull_request"] == {"types": ["closed"], "branches": ["__MAIN_BRANCH__"]}
    assert "workflow_dispatch" in on
    assert doc["concurrency"] == {"group": "tld-land", "cancel-in-progress": False}
    assert doc["permissions"] == {"contents": "read"}
    jobs = doc["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert job["if"] == "github.event_name == 'workflow_dispatch' || github.event.pull_request.merged == true"
    env = job["steps"][0]["env"]
    assert env == {
        "GH_TOKEN": "${{ secrets.TLD_AGENT_TOKEN }}",
        "REPO": "${{ github.repository }}",
        "BASE": "__MAIN_BRANCH__",
        "RETRIES": "6",
        "SLEEP": "10",
    }


def test_script_syntax(script, tmp_path):
    f = tmp_path / "s.sh"
    f.write_text(script)
    subprocess.run(["bash", "-n", str(f)], check=True)


def test_no_forbidden_words():
    assert FORBIDDEN.search(TEMPLATE.read_text()) is None


def pr(number, state, auto=True, sha=None):
    return {
        "number": number,
        "mergeable_state": state,
        "auto_merge": {"merge_method": "squash"} if auto else None,
        "head": {"sha": sha or f"sha{number}"},
    }


def run(script, tmp_path, prs, token="tok", extra=None):
    """prs: {number: [pr json per successive call]}"""
    d = tmp_path / "stub"
    d.mkdir()
    (d / "list.json").write_text(json.dumps([{"number": n} for n in sorted(prs)]))
    for n, seq in prs.items():
        for k, body in enumerate(seq):
            (d / f"pr_{n}_{k}.json").write_text(json.dumps(body))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(STUB)
    gh.chmod(0o755)
    s = tmp_path / "script.sh"
    s.write_text(script)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "STUB_DIR": str(d),
        "GH_TOKEN": token,
        "REPO": "o/r",
        "BASE": "main",
        "RETRIES": "6",
        "SLEEP": "0",
        **(extra or {}),
    }
    p = subprocess.run(["bash", str(s)], env=env, capture_output=True, text=True)
    log = (d / "calls.log").read_text().splitlines() if (d / "calls.log").exists() else []
    puts = [c for c in log if "-X PUT" in c]
    return p, puts


@needs_jq
def test_behind_updates_lowest(script, tmp_path):
    p, puts = run(script, tmp_path, {7: [pr(7, "behind", sha="abc")], 3: [pr(3, "behind", sha="def")]})
    assert p.returncode == 0, p.stderr
    assert puts == ["api -X PUT repos/o/r/pulls/3/update-branch -f expected_head_sha=def"]
    assert "updated #3" in p.stdout


@needs_jq
def test_blocked_first_no_put(script, tmp_path):
    p, puts = run(script, tmp_path, {3: [pr(3, "blocked")], 7: [pr(7, "behind")]})
    assert p.returncode == 0
    assert puts == []
    assert "#3 is blocked; nothing to update" in p.stdout


@needs_jq
def test_skips_pr_without_auto_merge(script, tmp_path):
    p, puts = run(script, tmp_path, {3: [pr(3, "behind", auto=False)], 7: [pr(7, "behind", sha="x7")]})
    assert len(puts) == 1 and "pulls/7/update-branch" in puts[0]


@needs_jq
def test_dirty_warns(script, tmp_path):
    p, puts = run(script, tmp_path, {3: [pr(3, "dirty")]})
    assert p.returncode == 0
    assert puts == []
    assert "::warning::#3 has a merge conflict" in p.stdout


@needs_jq
def test_unknown_retries_then_behind(script, tmp_path):
    p, puts = run(script, tmp_path, {3: [pr(3, "unknown"), pr(3, "unknown"), pr(3, "behind", sha="s3")]})
    assert p.returncode == 0, p.stderr
    assert puts == ["api -X PUT repos/o/r/pulls/3/update-branch -f expected_head_sha=s3"]


@needs_jq
def test_no_auto_merge_pr(script, tmp_path):
    p, puts = run(script, tmp_path, {3: [pr(3, "behind", auto=False)]})
    assert p.returncode == 0
    assert puts == []
    assert "no pull request with auto-merge enabled" in p.stdout


@needs_jq
def test_empty_token_fails(script, tmp_path):
    p, puts = run(script, tmp_path, {3: [pr(3, "behind")]}, token="")
    assert p.returncode == 1
    assert "::error::secret TLD_AGENT_TOKEN is not set" in p.stdout
    assert puts == []
