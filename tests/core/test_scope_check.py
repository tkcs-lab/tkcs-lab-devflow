import json
import re
import subprocess
import sys

import pytest
import yaml

from conftest import ROOT, TLD, CLAUDE, tld_cmd, _load

SCRIPT = TLD / "plan" / "scope.py"
SCRIPT_CMD = tld_cmd("plan", "scope-check")

MANIFEST = {
    "plan_slug": "demo",
    "feature_branch": "feature/demo",
    "phases": [
        {"id": "p1", "title": "One", "touches": ["src/core/**", "tests/test_core.py", "docs/guide.md"]},
        {"id": "p2", "title": "Two", "touches": ["src/api/*.py", "src/shared.py", "assets/"]},
        {"id": "p3", "title": "Three", "depends_on": ["p1"], "touches": ["src/core/extra.py", "README.md"]},
        {"id": "p4", "title": "No touches"},
    ],
}


@pytest.fixture(scope="module")
def sc():
    return _load("tld.plan.scope")


def others_of(phase):
    return {p["id"]: p.get("touches", []) for p in MANIFEST["phases"] if p["id"] != phase}


def classify(sc, paths, phase="p1", ignore=()):
    touches = next(p for p in MANIFEST["phases"] if p["id"] == phase)["touches"]
    return sc.classify(paths, touches, others_of(phase), list(ignore))


# --- the shared matcher (validate_manifest.path_matches) --------------------------------------

@pytest.mark.parametrize("path, pattern, expected", [
    ("src/a.py", "src/a.py", True),                      # literal
    ("./src/a.py", "src/a.py", True),                    # leading ./ is ignored
    ("src/a.py", "src/b.py", False),
    ("src/a/b/c.py", "src/**", True),                    # ** crosses directories
    ("src/a/b/c.py", "src/*", True),                     # so does *: the validator's fnmatch semantics
    ("src/a/b/c.py", "src/**/c.py", True),
    ("src/c.py", "src/**/c.py", False),                  # ... and `**/` needs one directory (pinned)
    ("src/core/deep/x/y.py", "src/core/**", True),
    ("src/corex/y.py", "src/core/**", False),
    ("assets/img/logo.png", "assets/", True),            # directory prefix
    ("assets", "assets/", False),
    ("assetsx/a", "assets/", False),
    ("docs/a.md", "docs/*.md", True),
    ("docs/a.txt", "docs/*.md", False),
    ("src/a1.py", "src/a[0-9].py", True),
    ("src/a.py", "src/?.py", True),
])
def test_path_matches(vm, path, pattern, expected):
    assert vm.path_matches(path, pattern) is expected


def test_overlap_check_still_uses_the_same_matcher(vm):
    assert vm.paths_overlap("src/**", "src/a/b.py")
    assert vm.paths_overlap("assets/", "assets/logo.png")
    assert not vm.paths_overlap("src/a.py", "src/b.py")
    assert vm.paths_overlap("src/*", "lib/*") is False


# --- classification ---------------------------------------------------------------------------

def test_in_scope_nested_and_new_files(sc):
    out = classify(sc, ["src/core/a/b/c.py", "tests/test_core.py", "docs/guide.md"])
    assert out == {"in_scope": 3, "ignored": 0, "out_of_scope": []}


def test_out_of_scope_without_collision(sc):
    out = classify(sc, ["src/core/a.py", "scripts/tool.sh"])
    assert out["in_scope"] == 1
    assert out["out_of_scope"] == [{"path": "scripts/tool.sh", "collides_with": []}]


def test_collision_names_the_owning_phases(sc):
    out = classify(sc, ["src/shared.py", "src/core/extra.py", "README.md"])
    # src/core/extra.py is in p1's own touches (src/core/**) and also in p3's: in scope, not a drift.
    assert out["in_scope"] == 1
    assert out["out_of_scope"] == [
        {"path": "README.md", "collides_with": ["p3"]},
        {"path": "src/shared.py", "collides_with": ["p2"]},
    ]


def test_a_path_can_collide_with_several_phases(sc):
    others = {"p2": ["lib/**"], "p3": ["lib/x.py"]}
    out = sc.classify(["lib/x.py"], ["src/**"], others, [])
    assert out["out_of_scope"] == [{"path": "lib/x.py", "collides_with": ["p2", "p3"]}]


def test_deletions_and_renames_count_both_paths(sc):
    # A deletion is a changed path like any other; a rename arrives as old path + new path.
    out = classify(sc, ["src/api/old.py", "src/core/new.py"])
    assert out["in_scope"] == 1
    assert [o["path"] for o in out["out_of_scope"]] == ["src/api/old.py"]
    assert out["out_of_scope"][0]["collides_with"] == ["p2"]


def test_ignore_globs_are_not_drift(sc):
    out = classify(sc, ["package-lock.json", "CHANGELOG.md", "vendor/x/y.go", "other.txt"],
                   ignore=["package-lock.json", "CHANGELOG.md", "vendor/**"])
    assert out["ignored"] == 3
    assert [o["path"] for o in out["out_of_scope"]] == ["other.txt"]


def test_touches_win_over_ignore(sc):
    out = classify(sc, ["docs/guide.md"], ignore=["docs/**"])
    assert out["in_scope"] == 1 and out["ignored"] == 0


def test_duplicates_are_counted_once(sc):
    assert classify(sc, ["src/core/a.py", "src/core/a.py"])["in_scope"] == 1


def test_no_changes(sc):
    assert classify(sc, []) == {"in_scope": 0, "ignored": 0, "out_of_scope": []}


# --- records and the pull request section -----------------------------------------------------

def entry(sc, label="p2", n_out=3, collide=1, disposition="accepted"):
    out = [{"path": f"z/f{i}.txt", "collides_with": []} for i in range(n_out)]
    for i in range(collide):
        out[i] = {"path": f"a/c{i}.txt", "collides_with": ["p3"]}
    return {"label": label, "check": "ok", "reason": None, "in_scope": 4, "ignored": 1,
            "out_of_scope": out, "disposition": disposition if n_out else None}


def test_record_field_counts_and_orders_collisions_first(sc):
    field = sc.record_field(entry(sc))
    assert field == {"check": "ok", "in_scope": 4, "out_of_scope_count": 3, "collision_count": 1,
                     "paths": ["a/c0.txt", "z/f1.txt", "z/f2.txt"], "disposition": "accepted"}


def test_record_field_is_capped_but_counts_are_full(sc):
    field = sc.record_field(entry(sc, n_out=45, collide=2))
    assert field["out_of_scope_count"] == 45 and len(field["paths"]) == 20
    assert field["paths"][:2] == ["a/c0.txt", "a/c1.txt"]


def test_record_field_for_unavailable_and_clean(sc):
    gone = sc.record_field(sc.unavailable("p1", "git diff failed"))
    assert gone == {"check": "unavailable", "in_scope": None, "out_of_scope_count": None, "collision_count": None,
                    "paths": [], "disposition": None}
    clean = sc.record_field(entry(sc, n_out=0, collide=0))
    assert clean["out_of_scope_count"] == 0 and clean["paths"] == [] and clean["disposition"] is None


def test_record_field_validates(sc):
    check = _load("tld.board.record")
    base = json.loads((ROOT / "tests/fixtures/status-records/good-run.json").read_text())
    for e in (entry(sc), entry(sc, n_out=45, collide=2), entry(sc, n_out=0, collide=0), sc.unavailable("p1", "x")):
        base["phases"][0]["scope"] = sc.record_field(e)
        assert check.validate(base) == [], e


def test_paths_are_made_safe(sc):
    assert sc.safe_path("a\nb\x00c") == "a?b?c"
    assert len(sc.safe_path("x" * 500)) == 300
    weird = {"label": "p1", "check": "ok", "in_scope": 0, "out_of_scope": [{"path": "a\nb", "collides_with": []}],
             "disposition": "accepted"}
    assert sc.record_field(weird)["paths"] == ["a?b"]


def test_section_from_a_sample_result(sc):
    entries = [
        entry(sc, "p1-core", n_out=0, collide=0),
        entry(sc, "p2-api", n_out=3, collide=1),
        sc.unavailable("p3-ui", "git diff failed"),
        {"label": "p4-docs", "check": "skipped", "reason": "merged before this run resumed", "out_of_scope": []},
    ]
    text = sc.build_section(entries)
    lines = text.splitlines()
    assert lines[0] == "## Scope"
    assert "- **p1-core**: none" in lines
    assert "- **p2-api**: 3 out of scope, 1 collision, accepted (merged as is)" in lines
    assert "  - `a/c0.txt` (collides with `p3`)" in lines
    assert "  - `z/f1.txt`" in lines
    assert "- **p3-ui**: scope check unavailable (git diff failed)" in lines
    assert "- **p4-docs**: not checked (merged before this run resumed)" in lines
    assert "nothing was blocked" in text


def test_section_caps_paths_per_phase(sc):
    text = sc.build_section([entry(sc, n_out=27, collide=0)], cap=20)
    assert text.count("\n  - `") == 20
    assert "  - and 7 more" in text.splitlines()


def test_section_with_nothing_recorded(sc):
    assert "none recorded" in sc.build_section([])


def test_section_quotes_backticks_and_reverted_words(sc):
    e = entry(sc, n_out=1, collide=0, disposition="reverted")
    e["out_of_scope"][0]["path"] = "we`ird.txt"
    text = sc.build_section([e])
    assert "``we`ird.txt``" in text and "reverted by a later commit" in text


def test_dispositions_from_the_final_diff(sc):
    entries = [entry(sc, "a", n_out=2, collide=0), entry(sc, "b", n_out=2, collide=0),
               entry(sc, "c", n_out=2, collide=0), entry(sc, "d", n_out=0, collide=0), sc.unavailable("e", "x")]
    final = {"z/f0.txt", "z/f1.txt"}
    entries[1]["out_of_scope"] = [{"path": "gone/1", "collides_with": []}, {"path": "z/f0.txt", "collides_with": []}]
    entries[2]["out_of_scope"] = [{"path": "gone/1", "collides_with": []}, {"path": "gone/2", "collides_with": []}]
    sc.update_dispositions(entries, final)
    assert [e["disposition"] for e in entries] == ["accepted", "partly_reverted", "reverted", None, None]


# --- the CLI against a real repository -------------------------------------------------------

def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def commit(repo, message, files=None, remove=(), move=()):
    for name, text in (files or {}).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for name in remove:
        git(repo, "rm", "-q", name)
    for old, new in move:
        (repo / new).parent.mkdir(parents=True, exist_ok=True)
        git(repo, "mv", old, new)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    commit(r, "base", {"src/core/a.py": "a\n", "src/api/old.py": "old\n", "CHANGELOG.md": "# c\n", "lock.json": "{}\n",
                       "docs/guide.md": "g\n", "README.md": "r\n"})
    git(r, "checkout", "-q", "-b", "feature/demo")
    git(r, "checkout", "-q", "-b", "feature/demo--p1")
    return r


@pytest.fixture()
def files(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(MANIFEST) + "```\n")
    profile = tmp_path / "toolkit.yaml"
    profile.write_text(yaml.safe_dump({"docs": {"must_read": [], "changelog": {"file": "CHANGELOG.md", "section": "## [Unreleased]"}},
                                       "scope": {"ignore": ["lock.json"]}}))
    return plan, profile, tmp_path / "results.json"


def cli(repo, *args):
    done = subprocess.run([*SCRIPT_CMD, *args, "--repo", str(repo)] if args[0] in ("check", "disposition")
                          else [*SCRIPT_CMD, *args], capture_output=True, text=True)
    return done


def check(repo, files, phase="p1", **extra):
    plan, profile, results = files
    args = ["check", "--plan", str(plan), "--phase", phase, "--base", "feature/demo", "--head", "feature/demo--p1",
            "--profile", str(profile), "--results", str(results)]
    for k, v in extra.items():
        args += [f"--{k.replace('_', '-')}", v]
    done = cli(repo, *args)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_cli_end_to_end(repo, files):
    commit(repo, "phase work", {"src/core/b.py": "b\n", "docs/guide.md": "g2\n", "CHANGELOG.md": "# c2\n", "lock.json": "{1}\n",
                                "src/api/new.py": "n\n", "stray.txt": "s\n", "README.md": "r2\n"},
           remove=["src/api/old.py"], move=[("src/core/a.py", "src/core/renamed.py")])
    got = check(repo, files)
    assert got["check"] == "ok" and got["disposition"] == "accepted"
    assert got["in_scope"] == 4        # src/core/a.py (rename source), src/core/renamed.py, src/core/b.py, docs/guide.md
    assert got["ignored"] == 2         # lock.json (scope.ignore) and CHANGELOG.md (docs.changelog.file)
    assert {(o["path"], tuple(o["collides_with"])) for o in got["out_of_scope"]} == {
        ("README.md", ("p3",)), ("src/api/new.py", ("p2",)), ("src/api/old.py", ("p2",)), ("stray.txt", ())}


def test_cli_record_section_and_disposition(repo, files):
    commit(repo, "phase work", {"src/core/b.py": "b\n", "stray.txt": "s\n", "README.md": "r2\n"})
    check(repo, files)
    plan, profile, results = files
    rec = json.loads(cli(repo, "record", "--results", str(results), "--label", "p1").stdout)
    assert rec["out_of_scope_count"] == 2 and rec["collision_count"] == 1 and rec["paths"] == ["README.md", "stray.txt"]
    # Merge the phase, then a later commit reverts one stray file: the final diff decides the disposition.
    git(repo, "checkout", "-q", "feature/demo")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge demo p1\n\nPlan-Phase: demo/p1", "feature/demo--p1")
    commit(repo, "revert stray", remove=["stray.txt"])
    done = cli(repo, "disposition", "--results", str(results), "--base", "main", "--head", "feature/demo")
    assert done.returncode == 0, done.stderr
    assert json.loads(results.read_text())[0]["disposition"] == "partly_reverted"
    section = cli(repo, "section", "--results", str(results)).stdout
    assert "- **p1**: 2 out of scope, 1 collision, partly reverted by a later commit" in section
    assert "  - `README.md` (collides with `p3`)" in section and "`stray.txt`" in section


def test_cli_label_for_a_fix_session_uses_the_original_touches(repo, files):
    commit(repo, "fix work", {"src/core/c.py": "c\n"})
    got = check(repo, files, label="fix-1")
    assert got["label"] == "fix-1" and got["out_of_scope"] == [] and got["disposition"] is None
    assert [e["label"] for e in json.loads(files[2].read_text())] == ["fix-1"]


def test_cli_replaces_the_entry_of_the_same_label(repo, files):
    commit(repo, "w", {"src/core/c.py": "c\n"})
    check(repo, files)
    check(repo, files)
    assert len(json.loads(files[2].read_text())) == 1


def test_resumed_run_does_not_recheck_a_merged_phase(repo, files):
    commit(repo, "phase work", {"stray.txt": "s\n"})
    git(repo, "checkout", "-q", "feature/demo")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge demo p1\n\nPlan-Phase: demo/p1", "feature/demo--p1")
    got = check(repo, files, plan_slug="demo", feature="feature/demo")
    assert got["check"] == "skipped"
    assert cli(repo, "record", "--results", str(files[2]), "--label", "p1").stdout.strip() == "null"
    # p1 is not p10: a longer id sharing the prefix is a different phase.
    assert check(repo, files, phase="p4", plan_slug="demo", feature="feature/demo")["reason"] != "merged before this run resumed"


@pytest.mark.parametrize("what", ["bad-ref", "bad-plan", "unknown-phase", "no-touches", "bad-profile"])
def test_check_failure_is_recorded_not_raised(repo, files, what, tmp_path):
    commit(repo, "w", {"stray.txt": "s\n"})
    plan, profile, results = files
    args = {"plan": plan, "phase": "p1", "base": "feature/demo", "head": "feature/demo--p1", "profile": profile}
    if what == "bad-ref":
        args["head"] = "no-such-ref"
    elif what == "bad-plan":
        args["plan"] = tmp_path / "missing.md"
    elif what == "unknown-phase":
        args["phase"] = "p99"
    elif what == "no-touches":
        args["phase"] = "p4"
    else:
        args["profile"] = tmp_path / "missing.yaml"
    done = cli(repo, "check", *sum(([f"--{k}", str(v)] for k, v in args.items()), []), "--results", str(results))
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert got["check"] == "unavailable" and got["reason"]
    field = json.loads(cli(repo, "record", "--results", str(results), "--label", args["phase"]).stdout)
    assert field["check"] == "unavailable" and field["paths"] == []
    assert "scope check unavailable" in cli(repo, "section", "--results", str(results)).stdout


def test_unreadable_results_file_never_fails(repo, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    section = cli(repo, "section", "--results", str(bad))
    assert section.returncode == 0 and "scope check unavailable" in section.stdout
    assert cli(repo, "disposition", "--results", str(bad), "--base", "main", "--head", "main").returncode == 0


def test_disposition_failure_leaves_results_unchanged(repo, files):
    commit(repo, "w", {"stray.txt": "s\n"})
    check(repo, files)
    before = files[2].read_text()
    done = cli(repo, "disposition", "--results", str(files[2]), "--base", "main", "--head", "no-such-ref")
    assert done.returncode == 0 and files[2].read_text() == before


def test_results_hold_paths_only(repo, files):
    commit(repo, "SECRET-COMMIT-MESSAGE", {"stray.txt": "SECRET-FILE-CONTENT\n"})
    check(repo, files)
    saved = files[2].read_text()
    assert "SECRET" not in saved and "stray.txt" in saved


# --- profile key, command text and docs ------------------------------------------------------

MINIMAL_PROFILE = {"docs": {"must_read": []}, "git": {"main_branch": "main", "branch_pattern": "<type>/<kebab-case>"},
                   "verify": {"fast": ["make lint"], "dod": ["make test"]}, "stacks": []}


def test_profile_accepts_scope_ignore(vp):
    assert vp.validate({**MINIMAL_PROFILE, "scope": {"ignore": ["package-lock.json", "**/gen/**"]}}, None)[0] == []
    assert vp.validate({**MINIMAL_PROFILE, "scope": {}}, None)[0] == []
    assert vp.validate(MINIMAL_PROFILE, None)[0] == []  # default: none, key absent


@pytest.mark.parametrize("bad", [{"ignore": "package-lock.json"}, {"ignore": [""]}, {"ignore": [3]}, {"ignroe": []}])
def test_profile_rejects_bad_scope_ignore(vp, bad):
    errors = vp.validate({**MINIMAL_PROFILE, "scope": bad}, None)[0]
    assert errors and all("scope" in e for e in errors)


def test_starter_template_documents_the_key():
    text = (TLD / "templates" / "toolkit.yaml").read_text()
    assert "# scope:" in text and "#   ignore:" in text


def test_implement_command_calls_the_script_with_real_flags():
    text = (CLAUDE / "commands" / "implement.md").read_text()
    block = text[text.index("plan scope-check check"):]
    block = block[:block.index("```")]
    flags = {w for w in block.split() if w.startswith("--")}
    helptext = subprocess.run([*SCRIPT_CMD, "check", "--help"], capture_output=True, text=True).stdout
    assert flags and all(f in helptext for f in flags), flags
    for needle in ("plan scope-check disposition", "plan scope-check section", "plan scope-check record",
                   "never a reason to hold the merge back", "`unavailable`", "guardrail hooks",
                   "`docs.changelog.file`", "**Scope** section", "at most 20"):
        assert needle in text, needle
    # the scope check runs before the merge command
    assert text.index("plan scope-check check") < text.index("git merge --no-ff origin/<phase branch>")


def test_docs_describe_the_decisions():
    doc = (ROOT / "docs" / "architecture" / "scope-drift.md").read_text()
    for needle in ("optional property in schema version 1", "pull request description", "scope.ignore",
                   "never blocks", "are not ignored by default", "partly_reverted", "rejected"):
        assert needle in doc, needle


# --- fix and rework sessions, section hardening (DOC-2, SEC-E8, TST-5) -------------------------

def _merge_p1_then_branch_on(repo, trailer="Plan-Phase: demo/p1"):
    """p1 merged into feature/demo with its trailer; the phase branch then moves on from there."""
    commit(repo, "phase work", {"src/core/b.py": "b\n"})
    git(repo, "checkout", "-q", "feature/demo")
    git(repo, "merge", "-q", "--no-ff", "-m", f"Merge demo p1\n\n{trailer}", "feature/demo--p1")
    git(repo, "checkout", "-q", "feature/demo--p1")
    git(repo, "merge", "-q", "--ff-only", "feature/demo")
    commit(repo, "later work", {"other.py": "o\n"})


@pytest.mark.parametrize("label", ["fix-1", "p1-rev1"])
def test_rev_and_fix_sessions_are_checked(repo, files, label):
    _merge_p1_then_branch_on(repo)
    got = check(repo, files, label=label, plan_slug="demo", feature="feature/demo")
    assert got["check"] == "ok" and got["label"] == label
    assert got["out_of_scope"] == [{"path": "other.py", "collides_with": []}]


def test_run_without_label_is_skipped_when_the_phase_trailer_is_on_the_feature_branch(repo, files):
    _merge_p1_then_branch_on(repo)
    got = check(repo, files, plan_slug="demo", feature="feature/demo")
    assert got["check"] == "skipped"


def test_section_code_span_cannot_be_escaped(sc):
    path = "a``b @someone [x](http://e)``c"
    e = {"label": "p1", "check": "ok", "in_scope": 0, "disposition": None,
         "out_of_scope": [{"path": path, "collides_with": []}]}
    line = sc.build_section([e]).splitlines()[-1]
    body = line.strip()[2:]  # drop "- "
    fence = len(body) - len(body.lstrip("`"))
    assert body.endswith("`" * fence) and not body.endswith("`" * (fence + 1))
    assert fence > 2  # longer than the longest backtick run in the path
    inner = body[fence:-fence]
    assert not re.search(r"@[A-Za-z]", inner)
    assert "@​someone" in inner


def test_resumed_p1_is_not_p10(repo, files, tmp_path):
    manifest = {**MANIFEST, "phases": MANIFEST["phases"] + [{"id": "p10", "title": "Ten", "touches": ["x/**"]}]}
    plan = tmp_path / "plan10.md"
    plan.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(manifest) + "```\n")
    commit(repo, "phase work", {"src/core/b.py": "b\n"})
    git(repo, "checkout", "-q", "feature/demo")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge demo p10\n\nPlan-Phase: demo/p10", "feature/demo--p1")
    got = check(repo, (plan, files[1], files[2]), phase="p1", plan_slug="demo", feature="feature/demo")
    assert got["check"] == "ok"
    assert "resumed" not in (got["reason"] or "")
