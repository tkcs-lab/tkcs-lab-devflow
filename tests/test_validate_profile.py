import copy
import json
import subprocess
import sys

import pytest
import yaml

from conftest import DEVFLOW, FIXTURES, ROOT

MINIMAL = {
    "docs": {"must_read": []},
    "git": {"main_branch": "main", "branch_pattern": "<type>/<kebab-case>"},
    "verify": {"fast": ["make lint"], "dod": ["make test"]},
    "stacks": [],
}


def errs(vp, profile, root=None):
    return vp.validate(profile, root)[0]


def test_minimal_profile_is_valid(vp):
    assert errs(vp, MINIMAL) == []


@pytest.mark.parametrize("path,message", [
    (("docs",), "missing required key 'docs'"),
    (("docs", "must_read"), "missing required key 'docs.must_read'"),
    (("git",), "missing required key 'git'"),
    (("git", "main_branch"), "missing required key 'git.main_branch'"),
    (("git", "branch_pattern"), "missing required key 'git.branch_pattern'"),
    (("verify",), "missing required key 'verify'"),
    (("verify", "fast"), "missing required key 'verify.fast'"),
    (("verify", "dod"), "missing required key 'verify.dod'"),
    (("stacks",), "missing required key 'stacks'"),
])
def test_missing_required_key_is_named(vp, path, message):
    p = copy.deepcopy(MINIMAL)
    node = p
    for k in path[:-1]:
        node = node[k]
    del node[path[-1]]
    assert message in errs(vp, p)


def test_unknown_key_is_an_error(vp):
    p = copy.deepcopy(MINIMAL)
    p["verfy"] = {}
    p["git"]["main"] = "x"
    e = errs(vp, p)
    assert any("unknown key 'verfy'" in x for x in e)
    assert any("unknown key 'git.main'" in x for x in e)


@pytest.mark.parametrize("mutate,fragment", [
    (lambda p: p["stacks"].append(3), "'stacks[0]': must be a string"),
    (lambda p: p["verify"].update(fast="make lint"), "'verify.fast': must be a list"),
    (lambda p: p["verify"].update(dod=[]), "'verify.dod': needs at least 1 item"),
    (lambda p: p["verify"].update(dod=[{"cwd": "x"}]), "missing required key 'verify.dod[0].run'"),
    (lambda p: p["git"].update(merge_style="rebase"), "'git.merge_style': must be one of"),
    (lambda p: p.update(models={"worker": "gpt"}), "'models.worker': must be one of"),
    (lambda p: p["docs"].update(changelog={"file": "C.md"}), "missing required key 'docs.changelog.section'"),
    (lambda p: p.update(ci={"dispatchable": [{"workflow": "a.yml"}]}), "missing required key 'ci.dispatchable[0].use_when'"),
    (lambda p: p["git"].update(main_branch=""), "'git.main_branch': must not be empty"),
])
def test_type_errors(vp, mutate, fragment):
    p = copy.deepcopy(MINIMAL)
    mutate(p)
    assert any(fragment in e for e in errs(vp, p)), errs(vp, p)


def test_defaults_are_the_only_defaults(vp):
    _, _, resolved = vp.validate(MINIMAL)
    assert resolved["docs"]["plan_dir"] == "docs"
    assert resolved["models"] == {"planner": "opus", "orchestrator": "sonnet", "worker": "sonnet", "reviewer": "opus"}
    assert "adr_dir" not in resolved["docs"]
    assert "ci" not in resolved and "project_steward" not in resolved


def test_plan_dir_trailing_slash_normalised(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["plan_dir"] = "plans/"
    assert vp.validate(p)[2]["docs"]["plan_dir"] == "plans"


def test_adr_keys_need_adr_dir(vp):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["adr_index"] = "docs/adr/README.md"
    assert any("adr_dir" in e for e in errs(vp, p))


def test_swift_without_dispatchable_warns(vp):
    p = copy.deepcopy(MINIMAL)
    p["stacks"] = ["swift"]
    e, w, _ = vp.validate(p)
    assert e == [] and any("macOS workflow" in x for x in w)
    p["ci"] = {"dispatchable": [{"workflow": "apple.yml", "use_when": "iOS tests"}]}
    assert vp.validate(p)[1] == []


def test_ipados_needs_swift_and_a_macos_workflow(vp):
    p = copy.deepcopy(MINIMAL)
    p["stacks"] = ["ipados"]
    e, w, _ = vp.validate(p)
    assert e == []
    assert any("macOS workflow" in x for x in w)
    assert any("stacks: [swift, ipados]" in x for x in w)
    p["stacks"] = ["swift", "ipados"]
    p["ci"] = {"dispatchable": [{"workflow": "ipad-tests.yml", "use_when": "iPad simulator tests"}]}
    assert vp.validate(p)[1] == []


def test_listed_files_must_exist(vp, tmp_path):
    p = copy.deepcopy(MINIMAL)
    p["docs"]["must_read"] = ["README.md", "docs/missing.md"]
    p["project_steward"] = ".claude/skills/x/SKILL.md"
    (tmp_path / "README.md").write_text("x")
    e = errs(vp, p, tmp_path)
    assert any("'docs/missing.md'" in x for x in e)
    assert any("'.claude/skills/x/SKILL.md'" in x for x in e)
    assert not any("'README.md'" in x for x in e)


def run_cli(*args):
    return subprocess.run([sys.executable, str(DEVFLOW / "scripts" / "validate_profile.py"), *args],
                          capture_output=True, text=True)


def test_cli_missing_profile():
    out = run_cli("/nonexistent/toolkit.yaml")
    assert out.returncode == 1 and "no profile at" in out.stderr


def test_cli_names_missing_key(tmp_path):
    f = tmp_path / "toolkit.yaml"
    bad = copy.deepcopy(MINIMAL)
    del bad["verify"]["fast"]
    f.write_text(yaml.safe_dump(bad))
    out = run_cli(str(f), "--no-file-checks")
    assert out.returncode == 1
    assert "toolkit.yaml: missing required key 'verify.fast'" in out.stderr


def test_cli_bad_yaml(tmp_path):
    f = tmp_path / "toolkit.yaml"
    f.write_text("a: [unclosed")
    assert run_cli(str(f)).returncode == 1


def test_cli_resolved_json(tmp_path):
    f = tmp_path / "toolkit.yaml"
    f.write_text(yaml.safe_dump(MINIMAL))
    out = run_cli(str(f), "--no-file-checks", "--resolved")
    assert out.returncode == 0
    assert json.loads(out.stdout)["docs"]["plan_dir"] == "docs"


def test_privacyfence_profile_is_valid(vp):
    profile = yaml.safe_load((FIXTURES / "privacyfence-toolkit.yaml").read_text())
    e, w, resolved = vp.validate(profile)  # no file checks: PrivacyFence's files are not in this repo
    assert e == [] and w == []
    assert [c if isinstance(c, str) else c["run"] for c in resolved["verify"]["fast"]] == [
        "ruff check .", "python3 -m pytest tests/unit -q"]
    assert len(resolved["ci"]["dispatchable"]) == 7


def test_starter_template_is_valid(vp):
    profile = yaml.safe_load((ROOT / "templates" / "toolkit.yaml").read_text())
    assert vp.validate(profile)[0] == []


def test_schema_file_matches_the_validator(vp):
    schema = json.loads(vp.SCHEMA.read_text())
    assert set(schema["required"]) == {"docs", "git", "verify", "stacks"}
    assert schema["additionalProperties"] is False
    for key in ("project", "docs", "git", "verify", "ci", "stacks", "models", "project_steward"):
        assert key in schema["properties"]


def test_toolkit_section_is_rejected_with_a_migration_message(vp):
    p = copy.deepcopy(MINIMAL)
    p["toolkit"] = {"ref": "v1"}
    assert errs(vp, p) == [
        "'toolkit' was removed: the toolkit is delivered only as plugins (docs/delivery.md); "
        "delete the 'toolkit' section"
    ]
