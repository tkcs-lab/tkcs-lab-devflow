import copy
import subprocess
import sys

import pytest
import yaml

from conftest import FIXTURES, tld_cmd

GOOD = yaml.safe_load("""
plan_slug: demo
feature_branch: feature/demo
max_parallel: 2
manual_before:
  - {id: mb1-account, title: Create an account, why: p1 needs it, done_when: the key exists}
manual_after:
  - {id: ma1-check, title: Click through, why: CI cannot}
verify_after_merge: [make test]
final_checks: [the plan is deleted]
phases:
  - id: p1-core
    title: Core
    depends_on: []
    complexity: S
    touches: [src/core.py, tests/test_core.py]
    brief: do it
    acceptance: [make test passes]
  - id: p2-api
    title: API
    depends_on: [p1-core]
    complexity: M
    touches: [src/core.py, src/api.py]
    brief: do it
    acceptance: [make test passes]
  - id: p3-docs
    title: Docs
    depends_on: [p1-core]
    touches: [docs/*.md]
    brief: do it
    acceptance: [a grep matches]
""")


def errors(manifest, vm, profile=None):
    return vm.validate(manifest, profile)[0]


def mutated(fn):
    m = copy.deepcopy(GOOD)
    fn(m)
    return m


def test_good_manifest(vm):
    errs, warns = vm.validate(GOOD)
    assert errs == []
    assert warns == []


@pytest.mark.parametrize("key", ["plan_slug", "feature_branch", "phases"])
def test_missing_top_level_key(vm, key):
    m = mutated(lambda m: m.pop(key))
    assert any(f"missing required key '{key}'" in e for e in errors(m, vm))


@pytest.mark.parametrize("field", ["brief", "acceptance", "title"])
def test_phase_missing_field(vm, field):
    m = mutated(lambda m: m["phases"][0].pop(field))
    assert any(f"phase 'p1-core' is missing '{field}'" in e for e in errors(m, vm))


def test_empty_acceptance_is_missing(vm):
    m = mutated(lambda m: m["phases"][0].update(acceptance=[]))
    assert any("missing 'acceptance'" in e for e in errors(m, vm))


def test_unknown_depends_on(vm):
    m = mutated(lambda m: m["phases"][1].update(depends_on=["p9-nope"]))
    assert any("unknown phase 'p9-nope'" in e for e in errors(m, vm))


def test_duplicate_id(vm):
    m = mutated(lambda m: m["phases"][1].update(id="p1-core"))
    assert any("duplicate phase id 'p1-core'" in e for e in errors(m, vm))


def test_cycle(vm):
    m = mutated(lambda m: m["phases"][0].update(depends_on=["p2-api"]))
    errs = errors(m, vm)
    assert any("dependency cycle" in e and "p1-core" in e and "p2-api" in e for e in errs)


def test_self_dependency(vm):
    m = mutated(lambda m: m["phases"][0].update(depends_on=["p1-core"]))
    assert any("depends on itself" in e for e in errors(m, vm))


def test_parallel_phases_with_overlapping_touches(vm):
    m = mutated(lambda m: m["phases"][2].update(touches=["src/api.py"]))
    errs = errors(m, vm)
    assert any("p2-api" in e and "p3-docs" in e and "src/api.py" in e for e in errs)


def test_glob_overlap_between_parallel_phases(vm):
    m = mutated(lambda m: m["phases"][2].update(touches=["src/*.py"]))
    assert any("p2-api" in e and "p3-docs" in e for e in errors(m, vm))


def test_overlap_allowed_when_one_depends_on_the_other(vm):
    # p1 and p2 both touch src/core.py but p2 depends on p1
    assert errors(GOOD, vm) == []


def test_overlap_allowed_through_transitive_dependency(vm):
    m = mutated(lambda m: m["phases"].append(
        {"id": "p4-last", "title": "Last", "depends_on": ["p3-docs"], "touches": ["src/api.py"],
         "brief": "x", "acceptance": ["y"]}))
    m["phases"][3]["depends_on"] = ["p2-api"]
    assert errors(m, vm) == []


def test_worker_level_strong_needs_reason(vm):
    m = mutated(lambda m: m["phases"][0].update(worker_level="strong"))
    assert any("worker_level_reason" in e for e in errors(m, vm))
    m["phases"][0]["worker_level_reason"] = "subtle locking"
    assert errors(m, vm) == []


def test_worker_level_is_a_level(vm):
    m = mutated(lambda m: m["phases"][0].update(worker_level="opus"))
    assert any("worker_level must be one of strong, standard, fast" in e for e in errors(m, vm))


def test_fast_worker_level_needs_complexity_s(vm):
    m = mutated(lambda m: m["phases"][1].update(worker_level="fast"))
    assert any("phase 'p2-api': worker_level: fast needs complexity S" in e for e in errors(m, vm))
    m = mutated(lambda m: m["phases"][0].update(worker_level="fast"))
    assert errors(m, vm) == []


def test_a_plan_record_in_touches_is_an_error(vm):
    def touching(path, **kw):
        m = mutated(lambda m: (m["phases"][0].update(touches=[path]), m.update(tracking_issue=14)))
        return vm.validate(m, **kw)[0]
    for bad in ("docs/plans/14/plan.md", "docs/plans/14/deviations.md", "./docs/plans/14/plan.md"):
        assert any("is a plan record" in e for e in touching(bad)), bad
    for bad in ("docs/plans/14/*.md", "docs/plans/14/plan.*", "docs/plans/**", "docs/plans/14/",
                " docs/plans/14/plan.md ", "src/../docs/plans/14/plan.md", "docs/plans/*/deviations.md"):
        assert any("is a plan record" in e for e in touching(bad)), bad
    for bad in ("docs/plans/*", "docs/plans/1*", "docs/pl*/14/plan.md", "docs/*/plan.md", "**/plan.md",
                "*", "**", "docs/plans/14/**"):
        assert any("is a plan record" in e for e in touching(bad)), bad
    for bad in ("docs/demo*", "docs/14*", "docs/14**", "**/demo/*", "**/14/*", "*an.md"):
        assert any("is a plan record" in e for e in touching(bad, plan_dir="docs")), bad
    for bad in ("*/demo/*", "**/14/*", "docs/plans/*an.md"):
        assert any("is a plan record" in e for e in touching(bad)), bad
    for ok in ("docs/*.md", "docs/plugin*.md", "*.md"):
        assert touching(ok, plan_dir="docs") == [], ok
    for bad in ("**", "*", "docs/*/plan.md", "docs/demo/", "docs/14/", "docs/14/*", "docs/demo/*"):
        assert any("is a plan record" in e for e in touching(bad, plan_dir="docs")), bad
    assert touching("docs/adr/**", plan_dir="docs") == []
    assert touching("docs/", plan_dir="docs/plans") == []
    for ok in ("docs/plans/", "docs/plans/x-plan.md", "docs/guides/plan.md"):
        assert touching(ok) == [], ok
    assert touching("docs/adr/x.md", plan_dir="docs") == []
    assert touching("docs/adr/x.md", plan_dir="docs/") == []


def _warns(vm, entry, profile=None):
    m = mutated(lambda m: m["phases"][0].update(touches=[entry]))
    return vm.validate(m, profile)


# The profile and ordinary workflows are off the default protect list; a repository that lists them gets the warnings.
LISTED = {"hooks": {"protect_paths": [".tld/toolkit.yaml", ".github/workflows/**"]}}


def test_the_profile_and_ordinary_workflows_are_not_protected_by_default(vm):
    for entry in (".tld/toolkit.yaml", ".github/workflows/ci.yml", ".github/**", ".github/"):
        errs, warns = _warns(vm, entry)
        assert errs == [] and warns == [], entry


def test_a_protected_path_in_touches_is_a_warning(vm):
    for entry in (".tld/toolkit.yaml", ".github/workflows/ci.yml"):
        errs, warns = _warns(vm, entry, LISTED)
        assert errs == [], entry
        assert any(f"touches '{entry}' is a protected path" in w and "protected-changes.md" in w for w in warns), entry


def test_a_wildcard_over_protected_paths_is_a_warning(vm):
    errs, warns = _warns(vm, ".github/**", LISTED)
    assert errs == []
    assert any("touches '.github/**' could name a protected path" in w for w in warns)


def test_a_directory_entry_is_checked_like_its_glob(vm):
    errs, warns = _warns(vm, ".github/", LISTED)
    assert errs == []
    assert any("touches '.github/' could name a protected path" in w for w in warns)


def test_lockfiles_and_env_files_in_touches_give_no_warning(vm):
    for entry in ("uv.lock", "package-lock.json", ".env.example"):
        errs, warns = _warns(vm, entry)
        assert errs == [] and warns == [], entry


def test_a_wildcard_away_from_protected_paths_does_not_warn(vm):
    m = mutated(lambda m: m["phases"][0].update(touches=["src/**", "docs/*.md"]))
    m["phases"][0]["depends_on"] = []
    errs, warns = vm.validate(m)
    assert warns == []
    assert vm.validate(GOOD)[1] == []


def test_the_profile_protect_list_replaces_the_default(vm):
    profile = {"hooks": {"protect_paths": ["secrets/x/**"]}}
    errs, warns = _warns(vm, ".tld/toolkit.yaml", profile)
    assert errs == [] and warns == []
    errs, warns = _warns(vm, "secrets/x/a.txt", profile)
    assert errs == []
    assert any("touches 'secrets/x/a.txt' is a protected path" in w for w in warns)


def test_a_profile_without_hooks_gives_the_default_check(vm):
    errs, warns = _warns(vm, ".tld/toolkit.yaml", {"git": {}})
    assert errs == [] and warns == []  # the default list has no path with a slash
    errs, warns = _warns(vm, ".tld/toolkit.yaml", {"git": {}, **LISTED})
    assert errs == []
    assert any("is a protected path" in w for w in warns)


def test_ref_must_be_main_or_the_feature_branch_or_the_legacy_plan_branch(vm, tmp_path, capsys):
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(GOOD))
    for ref in ("main", "feature/demo", "plan/demo"):
        assert vm.main([str(f), "--ref", ref]) == 0, ref
    assert "old-layout plan on 'plan/demo' (deprecated)" in capsys.readouterr().err
    for empty in ("", "  "):
        assert vm.main([str(f), "--ref", empty]) == 1
    assert "--ref is empty" in capsys.readouterr().err
    assert vm.main([str(f), "--ref", "plan/other"]) == 1
    assert "the plan is on 'plan/other', but it may only be on 'main' or on its own feature branch 'feature/demo'" in capsys.readouterr().err


def test_complexity_must_be_s_or_m(vm):
    m = mutated(lambda m: m["phases"][0].update(complexity="L"))
    assert any("complexity must be S or M" in e for e in errors(m, vm))


def test_manual_item_fields(vm):
    m = mutated(lambda m: m["manual_before"][0].pop("done_when"))
    assert any("manual_before[0]" in e and "done_when" in e for e in errors(m, vm))


def test_legacy_manual_key_means_manual_after(vm):
    m = mutated(lambda m: m.update(manual=m.pop("manual_after")))
    assert errors(m, vm) == []


def test_tracking_issue_is_optional(vm):
    """C13: a manifest without tracking_issue is valid."""
    m = mutated(lambda m: m.pop("tracking_issue", None))
    assert errors(m, vm) == []


@pytest.mark.parametrize("value", [0, -1, "7", True, 1.5])
def test_tracking_issue_must_be_positive_integer(vm, value):
    m = mutated(lambda m: m.update(tracking_issue=value))
    assert "tracking_issue must be a positive integer" in errors(m, vm)


@pytest.mark.parametrize("value", [5, [0], ["1"], [True], [1, 2.5]])
def test_closes_must_be_list_of_positive_integers(vm, value):
    m = mutated(lambda m: m.update(closes=value))
    assert "closes must be a list of positive integers" in errors(m, vm)


def test_closes_containing_tracking_issue_warns(vm):
    m = mutated(lambda m: m.update(tracking_issue=7, closes=[7, 8]))
    errs, warns = vm.validate(m)
    assert errs == [] and "closes contains tracking_issue" in warns


def test_valid_tracking_issue_and_closes(vm):
    m = mutated(lambda m: m.update(tracking_issue=7, closes=[8, 9]))
    assert vm.validate(m) == ([], [])


def test_feature_branch_checked_against_profile_types(vm):
    profile = {"git": {"branch_types": ["feature", "fix"], "branch_pattern": "<type>/<kebab-case>"}}
    m = mutated(lambda m: m.update(feature_branch="feat/demo"))
    assert any("feat/demo" in e and "feature/" in e for e in errors(m, vm, profile))
    assert errors(GOOD, vm, profile) == []


def test_not_a_mapping(vm):
    assert vm.validate(["x"])[0] == ["the manifest must be a YAML mapping"]


@pytest.mark.parametrize("a,b,expected", [
    ("src/a.py", "src/a.py", True),
    ("src/a.py", "src/b.py", False),
    ("src/", "src/a.py", True),
    ("src/a.py", "src/*.py", True),
    ("src/**/*.py", "tests/*.py", False),
    ("src/**", "src/x/y.py", True),
    ("docs/*.md", "src/*.py", False),
    ("src/*", "src/x/*", True),
])
def test_paths_overlap(vm, a, b, expected):
    assert vm.paths_overlap(a, b) is expected
    assert vm.paths_overlap(b, a) is expected


def run_cli(*args):
    return subprocess.run([*tld_cmd("plan", "validate-manifest"), *args],
                          capture_output=True, text=True)


def test_cli_plan_markdown(tmp_path):
    plan = tmp_path / "x-plan.md"
    plan.write_text("# Plan\n\n## Implementation manifest\n\n```yaml\n" + yaml.safe_dump(GOOD) + "```\n")
    out = run_cli(str(plan))
    assert out.returncode == 0, out.stderr
    assert "OK (demo, 3 phases)" in out.stdout


def test_cli_plan_without_manifest(tmp_path):
    plan = tmp_path / "x-plan.md"
    plan.write_text("# Plan\n\nno manifest here\n")
    out = run_cli(str(plan))
    assert out.returncode == 1
    assert "only runs plans that have a manifest" in out.stderr


def test_cli_reports_every_error(tmp_path):
    m = copy.deepcopy(GOOD)
    m["phases"][1]["depends_on"] = ["nope"]
    m["phases"][0].pop("brief")
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(m))
    out = run_cli(str(f))
    assert out.returncode == 1
    assert out.stderr.count("manifest:") >= 2


@pytest.mark.parametrize("fixture,phases", [
    ("privacyfence-atlassian-user-names-manifest.yaml", 7),
    ("privacyfence-plugin-framework-manifest.yaml", 21),
])
def test_real_privacyfence_manifests(vm, fixture, phases):
    manifest = yaml.safe_load((FIXTURES / fixture).read_text())
    profile = yaml.safe_load((FIXTURES / "privacyfence-toolkit.yaml").read_text())
    errs, warns = vm.validate(manifest, profile)
    assert errs == []
    assert len(manifest["phases"]) == phases
    out = run_cli(str(FIXTURES / fixture), "--profile", str(FIXTURES / "privacyfence-toolkit.yaml"))
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("manifest", sorted(FIXTURES.glob("privacyfence-*-manifest.yaml")), ids=lambda p: p.name)
def test_privacyfence_manifests_still_validate(manifest):
    """Regression fixtures: two real manifests validate against the real profile they were written for."""
    out = subprocess.run(
        [*tld_cmd("plan", "validate-manifest"), str(manifest),
         "--profile", str(FIXTURES / "privacyfence-toolkit.yaml")],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


# ---- the type checks (mutation survivors of the review: each case fails when its check is removed) -------------
def _set(path, value):
    def fn(m):
        target = m
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return fn


@pytest.mark.parametrize("path, value, message", [
    (("max_parallel",), 0, "max_parallel must be a positive integer"),
    (("max_parallel",), -1, "max_parallel must be a positive integer"),
    (("max_parallel",), "2", "max_parallel must be a positive integer"),
    (("max_parallel",), True, "max_parallel must be a positive integer"),
    (("verify_after_merge",), "make test", "'verify_after_merge' must be a list of strings"),
    (("verify_after_merge",), ["make test", 3], "'verify_after_merge' must be a list of strings"),
    (("final_checks",), "done", "'final_checks' must be a list of strings"),
    (("phases", 0, "acceptance"), "make test passes", "phase 'p1-core': 'acceptance' must be a list"),
    (("phases", 1, "depends_on"), "p1-core", "phase 'p2-api': depends_on must be a list"),
    (("phases", 0, "touches"), "src/core.py", "phase 'p1-core': touches must be a list of paths"),
    (("phases", 0, "touches"), ["src/core.py", 7], "phase 'p1-core': touches must be a list of paths"),
    (("phases", 0, "human_gate"), "yes", "phase 'p1-core': human_gate must be true or false"),
    (("phases", 0, "human_gate"), 1, "phase 'p1-core': human_gate must be true or false"),
])
def test_type_checks(vm, path, value, message):
    assert message in errors(mutated(_set(path, value)), vm)


@pytest.mark.parametrize("path, value", [(("max_parallel",), 1), (("phases", 0, "human_gate"), True),
                                         (("phases", 0, "human_gate"), False), (("verify_after_merge",), [])])
def test_type_checks_accept_the_right_types(vm, path, value):
    assert errors(mutated(_set(path, value)), vm) == []


# ---- unknown keys (C3): a typo or a claude-toolkit key is an error, not silently ignored -----------------------
@pytest.mark.parametrize("path, value, message", [
    (("worker_model",), "opus", "unknown key 'worker_model': use worker_level"),
    (("manual_steps_artifact",), "x.html", "unknown key 'manual_steps_artifact': manual steps now reach the owner as asks"),
    (("manual_steps_page",), "x.html", "unknown key 'manual_steps_page': manual steps now reach the owner as asks"),
    (("max_paralel",), 2, "unknown key 'max_paralel': known keys: plan_slug"),
    (("phases", 0, "worker_model"), "opus", "phase 'p1-core': unknown key 'worker_model': use worker_level"),
    (("phases", 0, "worker_model_reason"), "x", "phase 'p1-core': unknown key 'worker_model_reason': use worker_level_reason"),
    (("phases", 1, "touch"), ["a"], "phase 'p2-api': unknown key 'touch': known keys: id, title"),
])
def test_unknown_keys_are_errors_with_a_hint(vm, path, value, message):
    assert any(message in e for e in errors(mutated(_set(path, value)), vm)), errors(mutated(_set(path, value)), vm)


SPEC_PROFILE = {"spec": {"version": "2.1.0"}}
ID_ERR = "spec_change must be lower-case words joined by hyphens"


def _spec_manifest(**over):
    """GOOD as a spec plan: spec_change equals the slug, the last phase archives and depends on every phase."""
    m = copy.deepcopy(GOOD)
    m["spec_change"] = "demo"
    m["phases"][2]["depends_on"] = ["p1-core", "p2-api"]
    m["phases"][2]["touches"] = ["docs/*.md", "openspec/**"]
    m.update(over)
    return m


def test_every_documented_key_is_known(vm):
    m = mutated(lambda m: m.update(tracking_issue=3, closes=[4], screenshots_after_merge="make shots"))
    m["phases"][0].update(human_gate=True, worker_level="strong", worker_level_reason="r")
    assert errors(m, vm) == []
    m = _spec_manifest(tracking_issue=3, closes=[4], screenshots_after_merge="make shots")
    m["phases"][0].update(human_gate=True, worker_level="strong", worker_level_reason="r")
    assert errors(m, vm, SPEC_PROFILE) == []


# ---- spec_change (plan 3.6) -----------------------------------------------------------------------------------
def test_spec_change_valid_with_a_spec_profile(vm):
    assert vm.validate(_spec_manifest(), SPEC_PROFILE) == ([], [])


@pytest.mark.parametrize("value", ["abc\n", "-x", "../x", "A", "a--b", "", "a_b", 7, ["x"]])
def test_spec_change_id_is_checked(vm, value):
    assert ID_ERR in errors(_spec_manifest(spec_change=value), vm, SPEC_PROFILE)


def test_spec_change_needs_the_profile_spec_block(vm):
    msg = "spec_change needs the profile's spec block"
    assert msg in errors(_spec_manifest(), vm, {"git": {}})
    assert msg not in errors(_spec_manifest(), vm, None)


@pytest.mark.parametrize("entry", ["openspec/specs/auth/spec.md", "openspec/changes/x/specs/auth/spec.md",
                                   "openspec/project.md", "openspec/changes/other/", "openspec/", "openspec/**",
                                   "**/*.md"])
@pytest.mark.parametrize("profile", [SPEC_PROFILE, None])
def test_spec_change_fence_for_a_middle_phase(vm, entry, profile):
    m = _spec_manifest()
    m["phases"][1]["touches"] = [entry]
    m["phases"][1]["depends_on"] = ["p1-core"]
    msg = "phase 'p2-api': touches openspec/ but only the last phase may when spec_change is set"
    assert msg in errors(m, vm, profile)


@pytest.mark.parametrize("entry", ["docs/**", "src/**"])
def test_spec_change_fence_ignores_other_paths(vm, entry):
    m = _spec_manifest()
    m["phases"][1]["touches"] = [entry]
    assert not any("only the last phase may" in e for e in errors(m, vm, SPEC_PROFILE))


def test_spec_change_last_phase_may_touch_openspec(vm):
    assert not any("openspec" in e for e in errors(_spec_manifest(), vm, SPEC_PROFILE))


def test_spec_change_last_phase_must_touch_openspec(vm):
    m = _spec_manifest()
    m["phases"][2]["touches"] = ["docs/*.md"]
    assert "last phase 'p3-docs' must touch openspec/ when spec_change is set" in errors(m, vm, SPEC_PROFILE)


def test_without_spec_change_a_middle_phase_may_touch_openspec(vm):
    m = mutated(lambda m: m["phases"][1].update(touches=["openspec/"]))
    assert not any("openspec" in e for e in errors(m, vm))


def test_spec_change_last_phase_must_depend_on_all_phases(vm):
    m = _spec_manifest()
    m["phases"][2]["depends_on"] = ["p1-core"]
    msg = "last phase 'p3-docs' must depend on every other phase when spec_change is set (missing: p2-api)"
    assert msg in errors(m, vm, SPEC_PROFILE)
    m["phases"][2]["depends_on"] = []
    assert "(missing: p1-core, p2-api)" in " ".join(errors(m, vm))
    m["phases"][2]["depends_on"] = ["p2-api"]  # p2 depends on p1: through another phase counts
    assert not any("must depend on every other" in e for e in errors(m, vm))


def test_spec_change_differing_from_the_slug_warns(vm):
    assert "spec_change differs from plan_slug" in vm.validate(_spec_manifest(spec_change="other"), SPEC_PROFILE)[1]
    assert "spec_change differs from plan_slug" not in vm.validate(_spec_manifest(), SPEC_PROFILE)[1]


def test_cli_spec_change_with_a_spec_profile(tmp_path):
    profile = tmp_path / "toolkit.yaml"
    profile.write_text(yaml.safe_dump(SPEC_PROFILE))
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(_spec_manifest(spec_change="A")))
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump(_spec_manifest()))
    out = run_cli(str(good), "--profile", str(profile))
    assert out.returncode == 0, out.stdout + out.stderr
    out = run_cli(str(bad), "--profile", str(profile))
    assert out.returncode != 0
    assert ID_ERR in out.stdout + out.stderr
    no_spec = tmp_path / "plain.yaml"
    no_spec.write_text("git: {}\n")
    out = run_cli(str(good), "--profile", str(no_spec))
    assert "spec_change needs the profile's spec block" in out.stdout + out.stderr


# ---- sysml_change (plan 3.7) ----------------------------------------------------------------------------------
SYSML_PROFILE = {"sysml": {"subset": 1}}
SYSML_ID_ERR = "sysml_change must be lower-case words joined by hyphens"
SYSML_BLOCK_ERR = "sysml_change needs the profile's sysml block"
SYSML_MIDDLE = "phase 'p2-api': touches sysml/ or the architecture docs but only the last phase may when sysml_change is set"
SYSML_FENCE = ["sysml/model/core.sysml", "sysml/changes/x/model/a.sysml", "sysml/", "sysml/**", "docs/architecture.md",
               "docs/architecture.svg", "docs/**", "**/*.md"]


def _sysml_manifest(**over):
    """GOOD as a sysml plan: sysml_change equals the slug, the last phase archives and depends on every phase."""
    m = copy.deepcopy(GOOD)
    m["sysml_change"] = "demo"
    m["phases"][2]["depends_on"] = ["p1-core", "p2-api"]
    m["phases"][2]["touches"] = ["docs/*.md", "sysml/**"]
    m.update(over)
    return m


def test_sysml_change_id_of_100_characters_is_valid_and_101_is_refused(vm):
    assert vm.validate(_sysml_manifest(sysml_change="a" * 100), SYSML_PROFILE)[0] == []
    assert SYSML_ID_ERR in errors(_sysml_manifest(sysml_change="a" * 101), vm, SYSML_PROFILE)


def test_sysml_change_valid_with_a_sysml_profile(vm):
    assert vm.validate(_sysml_manifest(), SYSML_PROFILE) == ([], [])


def test_sysml_change_with_only_a_spec_profile_needs_the_sysml_block(vm):
    assert SYSML_BLOCK_ERR in errors(_sysml_manifest(), vm, {"spec": {"version": "2.1.0"}})


@pytest.mark.parametrize("profile", [{"git": {}}, {"sysml": None}])
def test_sysml_change_needs_the_profile_sysml_block(vm, profile):
    assert SYSML_BLOCK_ERR in errors(_sysml_manifest(), vm, profile)
    assert SYSML_BLOCK_ERR not in errors(_sysml_manifest(), vm, None)


@pytest.mark.parametrize("value", ["abc\n", "-x", "../x", "A", "a--b", "", "archive", 7, ["x"], None, True])
def test_sysml_change_id_is_checked(vm, value):
    assert SYSML_ID_ERR in errors(_sysml_manifest(sysml_change=value), vm, SYSML_PROFILE)
    assert SYSML_ID_ERR in errors(_sysml_manifest(sysml_change=value), vm, None)


def test_spec_change_archive_is_still_accepted(vm):
    assert vm.validate(_spec_manifest(spec_change="archive"), SPEC_PROFILE) == ([], ["spec_change differs from plan_slug"])


@pytest.mark.parametrize("entry", SYSML_FENCE)
@pytest.mark.parametrize("profile", [SYSML_PROFILE, None])
def test_sysml_change_fence_for_a_middle_phase(vm, entry, profile):
    m = _sysml_manifest()
    m["phases"][1]["touches"] = [entry]
    m["phases"][1]["depends_on"] = ["p1-core"]
    assert SYSML_MIDDLE in errors(m, vm, profile)
    assert SYSML_BLOCK_ERR not in errors(m, vm, None)


@pytest.mark.parametrize("entry", ["src/**", "docs/README.md"])
def test_sysml_change_fence_ignores_other_paths(vm, entry):
    m = _sysml_manifest()
    m["phases"][1]["touches"] = [entry]
    assert not any("only the last phase may" in e for e in errors(m, vm, SYSML_PROFILE))


def test_sysml_change_fence_is_independent_of_the_openspec_fence(vm):
    m = _sysml_manifest()
    m["phases"][1]["touches"] = ["openspec/specs/a.md"]
    assert not any("only the last phase may" in e for e in errors(m, vm, SYSML_PROFILE))


@pytest.mark.parametrize("entry", ["sysml/model/core.sysml", "docs/architecture.md", "docs/architecture.svg"])
def test_sysml_change_last_phase_touching_one_path_passes(vm, entry):
    m = _sysml_manifest()
    m["phases"][2]["touches"] = [entry]
    assert vm.validate(m, SYSML_PROFILE) == ([], [])


def test_sysml_change_last_phase_must_touch_the_fence(vm):
    m = _sysml_manifest()
    m["phases"][2]["touches"] = ["docs/README.md"]
    assert "last phase 'p3-docs' must touch sysml/ when sysml_change is set" in errors(m, vm, SYSML_PROFILE)


def test_sysml_change_last_phase_must_depend_on_all_phases(vm):
    m = _sysml_manifest()
    m["phases"][2]["depends_on"] = ["p1-core"]
    msg = "last phase 'p3-docs' must depend on every other phase when sysml_change is set (missing: p2-api)"
    assert msg in errors(m, vm, SYSML_PROFILE)
    m["phases"][2]["depends_on"] = ["p2-api"]
    assert not any("must depend on every other" in e for e in errors(m, vm, SYSML_PROFILE))


def test_sysml_change_differing_from_the_slug_warns(vm):
    assert "sysml_change differs from plan_slug" in vm.validate(_sysml_manifest(sysml_change="other"), SYSML_PROFILE)[1]
    assert "sysml_change differs from plan_slug" not in vm.validate(_sysml_manifest(), SYSML_PROFILE)[1]


@pytest.mark.parametrize("entry", SYSML_FENCE)
@pytest.mark.parametrize("pid_index", [0, 2])
def test_no_change_no_touch(vm, entry, pid_index):
    m = copy.deepcopy(GOOD)
    ph = m["phases"][pid_index]
    ph["touches"] = [entry]
    msg = (f"phase '{ph['id']}': touches sysml/ or the architecture docs but the manifest has no sysml_change; "
           "narrow the touches or set sysml_change")
    assert msg in errors(m, vm, SYSML_PROFILE)
    assert not any("no sysml_change" in e for e in errors(m, vm, None))
    assert not any("no sysml_change" in e for e in errors(m, vm, {"git": {}}))
    assert not any("no sysml_change" in e for e in errors(m, vm, {"sysml": None}))


def test_no_change_no_touch_leaves_other_paths_alone(vm):
    m = copy.deepcopy(GOOD)
    m["phases"][2]["touches"] = ["lib/**", "docs/README.md"]
    assert vm.validate(m, SYSML_PROFILE) == ([], [])


def test_spec_profile_without_spec_change_lets_a_middle_phase_touch_openspec(vm):
    m = mutated(lambda m: m["phases"][1].update(touches=["openspec/"]))
    assert not any("openspec" in e for e in errors(m, vm, SPEC_PROFILE))


def test_both_changes_with_a_last_phase_touching_both_fences_pass(vm):
    m = _sysml_manifest(spec_change="demo")
    m["phases"][2]["touches"] = ["openspec/**", "sysml/**"]
    assert vm.validate(m, {**SPEC_PROFILE, **SYSML_PROFILE}) == ([], [])
    m["phases"][2]["touches"] = ["sysml/**"]
    assert "last phase 'p3-docs' must touch openspec/ when spec_change is set" in errors(m, vm, {**SPEC_PROFILE, **SYSML_PROFILE})


def test_sysml_change_is_a_known_key(vm):
    m = mutated(lambda m: m.update(sysml_change="demo"))
    m["phases"][2]["depends_on"] = ["p1-core", "p2-api"]
    m["phases"][2]["touches"] = ["sysml/**"]
    assert errors(m, vm) == []


def test_cli_sysml_change_with_a_sysml_profile(tmp_path):
    profile = tmp_path / "toolkit.yaml"
    profile.write_text(yaml.safe_dump(SYSML_PROFILE))
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump(_sysml_manifest()))
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(_sysml_manifest(sysml_change="archive")))
    out = run_cli(str(good), "--profile", str(profile))
    assert out.returncode == 0, out.stdout + out.stderr
    out = run_cli(str(bad), "--profile", str(profile))
    assert out.returncode != 0 and SYSML_ID_ERR in out.stdout + out.stderr
    plain = tmp_path / "plain.yaml"
    plain.write_text("git: {}\n")
    out = run_cli(str(good), "--profile", str(plain))
    assert SYSML_BLOCK_ERR in out.stdout + out.stderr
