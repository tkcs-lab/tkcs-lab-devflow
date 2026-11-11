"""Tests that pin the mutation survivors from the review and the low-coverage helper tables
(_ansi escape decoding, _wrappers env -S / script -c)."""
import json
import random
import string
import time

import pytest

from hooks_helpers import bash, event, make_repo, make_repo_with_origin, run
from tld.guard import secret_scan
from tld.guard._ansi import ansi_c_decode
from tld.guard._shell import candidates, split_commands
from tld.guard._wrappers import script_command, strip_wrapper
from tld.dod.gate import state_dir


def _rand(n, alphabet=string.ascii_letters + string.digits):
    return "".join(random.choices(alphabet, k=n))


# ---- no-merge: DELETE / POST to the contents API on the main branch ------------------------------
@pytest.mark.parametrize("command", [
    "gh api -X DELETE repos/o/r/contents/README.md -f branch=main",
    "gh api -X POST repos/o/r/contents/README.md -f branch=main",
    "gh api -X PUT repos/o/r/contents/README.md",  # no branch field means the default branch
])
def test_contents_api_write_to_main_is_denied(feature_repo, command):
    assert run("no-merge", bash(command, feature_repo)).code == 2


def test_contents_api_write_to_a_feature_branch_is_allowed(feature_repo):
    assert run("no-merge", bash("gh api -X PUT repos/o/r/contents/a -f branch=feature/demo", feature_repo)).code == 0


# ---- no-merge: the -c branch. prefix guard on a push --------------------------------------------
@pytest.mark.parametrize("key", ["remote.origin.url", "push.default", "branch.main.remote"])
def test_c_config_prefixes_on_a_push_are_denied(feature_repo, key):
    assert run("no-merge", bash(f"git -c {key}=x push origin HEAD:feature/other", feature_repo)).code == 2


# ---- secret-scan pattern survivors --------------------------------------------------------------
@pytest.mark.parametrize("secret", [
    "xoxp-" + _rand(20, string.digits), "xoxr-" + _rand(20, string.digits), "xoxs-" + _rand(20, string.digits),
    "rk_live_" + _rand(24), "eyJ" + _rand(12) + ".eyJ" + _rand(12) + "." + _rand(16),
])
def test_specific_patterns_that_survived_mutation(feature_repo, secret):
    assert run("secret-scan", event("Write", feature_repo, file_path="a.txt", content=f"x = '{secret}'\n")).code == 2


def test_a_name_containing_pub_is_exempt(feature_repo):
    content = "PUBLIC_KEY = '" + _rand(40) + "'\n"
    assert run("secret-scan", event("Write", feature_repo, file_path="a.py", content=content)).code == 0


def test_password_needs_only_twelve_characters(feature_repo):
    assert not secret_scan.password_literal("Tr0ub4dor3x")  # 11 chars: below the password minimum
    twelve = "Tr0ub4dor3xy"  # 12 chars with a digit and a letter
    assert secret_scan.password_literal(twelve)
    r = run("secret-scan", event("Write", feature_repo, file_path="c.cfg", content=f"DB_PASSWORD={twelve}QX\n"))
    assert r.code == 2


# ---- protect-paths: a trailing dir/ means a directory, future-dated marker --------------------
def test_trailing_slash_pattern_matches_the_directory(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r",
                                 committed="git:\n  main_branch: main\nhooks:\n  protect_paths: ['secrets/']\n")
    assert run("protect-paths", event("Write", repo, file_path="secrets/a/b.txt", content="x")).code == 2
    assert run("protect-paths", event("Write", repo, file_path="secrets", content="x")).code == 0


def test_a_future_dated_allow_marker_does_not_exempt_the_profile(tmp_path):
    from tld.guard import protect_paths
    repo = make_repo(tmp_path / "r", "feature/demo")
    marker = state_dir(str(repo)) / protect_paths.PROFILE_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 10000))
    marker.write_text(json.dumps({"written_at": future}))
    assert run("protect-paths", event("Write", repo, file_path=".tld/toolkit.yaml", content="x")).code == 2


# ---- _ansi: escape decoding ---------------------------------------------------------------------
@pytest.mark.parametrize("body, expect", [
    (r"\x2d\x2dforce", "--force"), (r"\055\055", "--"), (r"\n\t", "\n\t"), (r"-", "-"),
    (r"\e", "\x1b"), (r"\\", "\\"), (r"\q", "\\q"), (r"a\x00b", "a"), ("plain", "plain"),
    (r"\cA", "\x01"),
])
def test_ansi_c_decode_table(body, expect):
    assert ansi_c_decode(body) == expect


def test_ansi_c_quoting_decodes_a_hidden_force(feature_repo):
    assert run("no-force-push", bash(r"git push $'\x2d\x2dforce' origin x", feature_repo)).code == 2


# ---- _wrappers: env -S and script -c ------------------------------------------------------------
@pytest.mark.parametrize("rest, expect", [
    (["-S", "git push -f", "ignored"], ["git", "push", "-f", "ignored"]),
    (["--split-string=git push -f"], ["git", "push", "-f"]),
    (["-S", "git push"], ["git", "push"]),
    (["FOO=1", "git", "push"], ["git", "push"]),
    (["-u", "NAME", "git", "push"], ["git", "push"]),
])
def test_env_wrapper_split_string(rest, expect):
    assert strip_wrapper("env", rest) == expect


@pytest.mark.parametrize("rest, expect", [
    (["-c", "git push -f", "out.log"], "git push -f"),
    (["--command=git push", "out.log"], "git push"),
    (["-qc", "git push", "out.log"], "git push"),
    (["out.log"], None),
])
def test_script_command_extraction(rest, expect):
    assert script_command(rest) == expect


def test_env_dash_s_reaches_the_guard(feature_repo):
    assert run("no-force-push", bash("env -S 'git push --force origin x'", feature_repo)).code == 2


def test_script_minus_c_reaches_the_guard(feature_repo):
    assert run("no-force-push", bash("script -c 'git push --force origin x' /dev/null", feature_repo)).code == 2
