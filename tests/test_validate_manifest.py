import copy
import subprocess
import sys

import pytest
import yaml

from conftest import DEVFLOW, FIXTURES

GOOD = yaml.safe_load("""
plan_slug: demo
feature_branch: feature/demo
max_parallel: 2
manual_before:
  - {id: mb1-account, title: Create an account, why: p1 needs it, done_when: the key exists}
manual_after:
  - {id: ma1-check, title: Click through, why: CI cannot}
manual_steps_artifact: https://claude.ai/artifact/abc
manual_steps_source: docs/demo-plan-manual-steps.html
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


def test_worker_model_opus_needs_reason(vm):
    m = mutated(lambda m: m["phases"][0].update(worker_model="opus"))
    assert any("worker_model_reason" in e for e in errors(m, vm))
    m["phases"][0]["worker_model_reason"] = "subtle locking"
    assert errors(m, vm) == []


def test_complexity_must_be_s_or_m(vm):
    m = mutated(lambda m: m["phases"][0].update(complexity="L"))
    assert any("complexity must be S or M" in e for e in errors(m, vm))


def test_manual_item_fields(vm):
    m = mutated(lambda m: m["manual_before"][0].pop("done_when"))
    assert any("manual_before[0]" in e and "done_when" in e for e in errors(m, vm))


def test_legacy_manual_key_means_manual_after(vm):
    m = mutated(lambda m: m.update(manual=m.pop("manual_after")))
    assert errors(m, vm) == []


def test_artifact_without_source_warns(vm):
    m = mutated(lambda m: m.pop("manual_steps_source"))
    errs, warns = vm.validate(m)
    assert errs == [] and any("manual_steps_source" in w for w in warns)


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
    return subprocess.run([sys.executable, str(DEVFLOW / "scripts" / "validate_manifest.py"), *args],
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
