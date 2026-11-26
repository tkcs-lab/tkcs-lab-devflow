"""repo_admin_detect.py: the pure detection functions (plan 93, section 3.9)."""
import subprocess
import sys

from conftest import ROOT

from tld.ops import repo_admin_detect as d


def sample(number, **runs):
    return d.Sample(number, tuple(d.Run(n, c) for n, c in runs.items()))


def three(**runs):
    return [sample(i, **runs) for i in (1, 2, 3)]


def test_checks_from_merged_pull_requests():
    names, excluded = d.status_checks(three(test="success", lint="success"))
    assert names == ["lint", "test"] and excluded == {}


def test_too_few_pull_requests():
    names, excluded = d.status_checks([sample(1, test="success"), sample(2, test="success")])
    assert names == [] and excluded == {"": "too few merged pull requests (2)"}
    assert d.status_checks([]) == ([], {"": "too few merged pull requests (0)"})


def test_flaky_failed_skipped_and_partial_checks_are_excluded():
    samples = [
        d.Sample(4, (d.Run("ok", "success"), d.Run("flaky", "success"), d.Run("flaky", "failure"),
                     d.Run("red", "failure"), d.Run("skip", "skipped"), d.Run("wait", None),
                     d.Run("part", "success"), d.Run("late", "timed_out"))),
        sample(5, ok="success", flaky="success", red="success", skip="success", wait="success", late="success"),
        sample(6, ok="success", flaky="success", red="success", skip="success", wait="success", late="success"),
    ]
    names, excluded = d.status_checks(samples)
    assert names == ["ok"]
    assert excluded == {
        "flaky": "flaky: success and failure on the same commit in #4",
        "red": "failed on #4",
        "skip": "skipped on #4",
        "wait": "pending on #4",
        "late": "failed on #4",
        "part": "seen on 1 of 3 pull requests (path filter or new)",
    }
    for conclusion, reason in (("neutral", "skipped"), ("cancelled", "skipped"), ("stale", "skipped"),
                               ("startup_failure", "failed"), ("action_required", "failed")):
        got = d.status_checks([sample(7, x=conclusion), sample(8, x="success"), sample(9, x="success")])[1]
        assert got == {"x": f"{reason} on #7"}


def test_release_parameters():
    params, notes = d.release_params(["v1.0.0", "v1.1.0", "v2.0.0", "nightly"], ["package.json"], False)
    assert (params, notes) == ({"tag_prefix": "v", "version_style": "semver"}, [])
    params, _ = d.release_params(["1.0.0", "1.1.0"], ["pyproject.toml"], True)
    assert params == {"tag_prefix": "", "version_style": "pep440", "create_release": "false"}
    assert d.release_params(["nightly", "latest"], [], False) == ({}, ["no version-like tags"])
    assert "check_script" not in d.release_params(["v1.0.0"], [], False)[0]


def test_version_style_rules():
    def style(tags, manifests=()):
        return d.release_params(tags, list(manifests), False)[0]["version_style"]

    assert style(["v1.0.0-rc.1", "v1.0.0"], ["pyproject.toml"]) == "semver"
    assert style(["v1.0.0rc1", "v1.0.0"]) == "pep440"
    assert style(["v1.0.0a2"]) == "pep440"
    assert style(["v1.0.0b2"]) == "pep440"
    assert style(["v1.0.0"], ["pyproject.toml"]) == "pep440"
    assert style(["v1.0.0"], ["package.json"]) == "semver"
    assert style(["v1.0.0"]) == "semver"
    assert style(["v1.0.0.post1"]) == "semver"


def test_tag_prefix_tie():
    assert d.release_params(["v1.0.0", "rel-1.0.0"], [], False)[0]["tag_prefix"] == "rel-"
    assert d.release_params(["v1.0.0", "v1.1.0", "rel-1.0.0"], [], False)[0]["tag_prefix"] == "v"
    assert d.release_params(["a1.0.0", "b1.0.0", "b1.1.0", "a1.1.0"], [], False)[0]["tag_prefix"] == "a"


def test_tag_workflow_creates_release():
    creates = "name: r\non:\n  push:\n    tags:\n      - 'v*'\njobs:\n  r:\n    steps:\n      - run: gh release create $TAG\n"
    assert d.tag_workflow_creates_release([creates])
    for marker in ("uses: softprops/action-gh-release@v1", "uses: ncipollo/create-release@v1"):
        assert d.tag_workflow_creates_release([creates.replace("run: gh release create $TAG", marker)])
    on_branch = creates.replace("    tags:\n      - 'v*'\n", "    branches: [main]\n")
    assert not d.tag_workflow_creates_release([on_branch])
    assert not d.tag_workflow_creates_release([creates.replace("gh release create", "echo")])
    assert not d.tag_workflow_creates_release([])
    assert d.tag_workflow_creates_release(["name: x\n", creates])


def test_tag_workflow_regex_is_linear_and_scoped_to_the_push_block():
    import time

    marker = "      - run: gh release create $TAG\n"
    long_push = "on:\n  push:\n" + "    branches:\n      - main\n" * 100 + "jobs:\n  r:\n    steps:\n" + marker
    start = time.monotonic()
    assert not d.tag_workflow_creates_release([long_push])
    assert time.monotonic() - start < 1
    later = ("on:\n  push:\n    branches: [main]\njobs:\n  r:\n    steps:\n"
             "      - uses: x/y@v1\n        with:\n          tags: latest\n" + marker)
    assert not d.tag_workflow_creates_release([later])
    sibling = "on:\n  push:\n    branches: [main]\n  pull_request:\n    tags: [x]\n" + marker
    assert not d.tag_workflow_creates_release([sibling])
    blank = "on:\n  push:\n\n    tags:\n      - 'v*'\n" + marker
    assert d.tag_workflow_creates_release([blank])


def test_own_release_workflow():
    wf = [{"template": "release"}, {"template": "land"}]
    assert d.own_release_workflow("release.yml", wf) == [{"template": "land"}]
    assert d.own_release_workflow("tld-release.yml", wf) is None
    assert d.own_release_workflow(None, wf) is None
    assert d.own_release_workflow("release.yml", [{"template": "land"}]) is None
    assert d.own_release_workflow("release.yml", None) is None
    assert d.own_release_workflow("release.yml", wf) is not wf


def test_detected_override_shapes():
    assert d.detected_override(None, {}, None) == {}
    assert d.detected_override([], None, None) == {}
    assert d.detected_override(["a", "b"], None, None) == {"rulesets": {"default_branch": {"required_status_checks": ["a", "b"]}}}
    assert d.detected_override(None, {"tag_prefix": "v"}, None) == {"workflow_params": {"release": {"tag_prefix": "v"}}}
    assert d.detected_override(None, None, []) == {"workflows": []}
    full = d.detected_override(["a"], {"tag_prefix": "v"}, [{"template": "land"}])
    assert list(full) == ["rulesets", "workflow_params", "workflows"]


def test_pr_notes():
    assert d.pr_notes(["a", "b"], {}, None, []) == ["required_status_checks: a, b"]
    assert d.pr_notes([], {"": "too few merged pull requests (2)"}, {}, ["no version-like tags"]) == [
        "required_status_checks: none proposed",
        "excluded: (all) (too few merged pull requests (2))",
        "no version-like tags",
    ]
    assert d.pr_notes(["a"], {"x": "failed on #3"}, {"tag_prefix": "v", "version_style": "semver"}, ["n"]) == [
        "required_status_checks: a",
        "excluded: x (failed on #3)",
        "release parameters: tag_prefix=v version_style=semver",
        "n",
    ]


def test_detect_module_does_not_import_repo_admin():
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); import tld.ops.repo_admin_detect; "
            "sys.exit(1 if 'tld.ops.repo_admin' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0
