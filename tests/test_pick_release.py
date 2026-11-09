import json
import subprocess
import sys

from conftest import DEVFLOW

SCRIPT = DEVFLOW / "scripts" / "pick_release.py"
SEMVER = r"^v?[0-9]+\.[0-9]+\.[0-9]+$"


def run(stdin, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)


def tags(*items):
    return json.dumps([{"tag": t} if isinstance(t, str) else t for t in items])


def test_highest_stable_wins():
    r = run(tags("v1.0.0", "v1.2.0", "v1.1.0"), "--pattern", SEMVER)
    assert (r.returncode, r.stdout.strip()) == (0, "v1.2.0")


def test_prerelease_flag_excluded():
    r = run(tags("v1.0.0", {"tag": "v2.0.0", "prerelease": True}), "--pattern", SEMVER)
    assert r.stdout.strip() == "v1.0.0"


def test_rc_suffix_excluded_even_if_pattern_allows():
    r = run(tags("v1.0.0", "v1.2.0-rc1"), "--pattern", "^v")
    assert r.stdout.strip() == "v1.0.0"


def test_numeric_not_lexical_order():
    r = run(tags("v1.9.0", "v1.10.0"), "--pattern", SEMVER)
    assert r.stdout.strip() == "v1.10.0"


def test_lines_bare_tags():
    r = run("v1.0.0\nv1.3.0\n\nv1.2.0\n", "--lines", "--pattern", SEMVER)
    assert (r.returncode, r.stdout.strip()) == (0, "v1.3.0")


def test_lines_raw_ls_remote_output():
    text = ("a" * 40 + "\trefs/tags/v1.0.0\n" + "b" * 40 + "\trefs/tags/v1.1.0\n"
            + "c" * 40 + "\trefs/tags/v1.1.0^{}\n" + "d" * 40 + "\trefs/tags/v1.2.0-rc1\n")
    r = run(text, "--lines", "--pattern", SEMVER)
    assert (r.returncode, r.stdout.strip()) == (0, "v1.1.0")


def test_no_eligible_release_exit_3():
    r = run(tags("v1.0.0-rc1", {"tag": "v1.0.0", "prerelease": True}), "--pattern", SEMVER)
    assert r.returncode == 3
    assert "pick_release: no eligible release" in r.stderr


def test_bad_pattern_exit_1():
    r = run(tags("v1.0.0"), "--pattern", "(")
    assert r.returncode == 1
    assert r.stderr.startswith("pick_release: ")


def test_bad_json_exit_1():
    r = run("not json", "--pattern", SEMVER)
    assert r.returncode == 1
    assert r.stderr.startswith("pick_release: ")
