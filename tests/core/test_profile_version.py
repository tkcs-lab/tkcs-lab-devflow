"""tld.version (D9): the profile's version specifier, checked against the running tld."""
import re
import subprocess

import pytest

import tld
from conftest import ROOT, tld_cmd, _load

tv = _load("tld.profile.version")
MINIMAL = {"docs": {"must_read": []}, "git": {"main_branch": "main", "branch_pattern": "x"},
           "verify": {"fast": [], "dod": ["true"]}, "stacks": []}


def test_the_version_agrees_with_the_package():
    package = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert tld.__version__ == package


def test_cli_prints_the_version():
    for args in (["--version"], ["version", "show"]):
        r = subprocess.run(tld_cmd(*args), capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout == f"tld {tld.__version__}\n"


@pytest.mark.parametrize("version, spec, ok", [
    ("1.0.0", ">=1.0,<2", True),
    ("1.4.2", ">=1.0,<2", True),
    ("2.0.0", ">=1.0,<2", False),
    ("0.9.9", ">=1.0,<2", False),
    ("1.0.0.dev0", ">=1.0,<2", True),   # a development build counts as the release it leads to
    ("1.0.0rc1", ">=1.0", True),
    ("1.2", "==1.2.0", True),
    ("1.2.1", "!=1.2.1", False),
    ("1.3", ">1.2,<=1.3", True),
    ("1.3", " >= 1.3 , < 1.4 ", True),
])
def test_satisfies(version, spec, ok):
    assert tv.satisfies(version, spec) is ok


@pytest.mark.parametrize("spec", ["", "1.0", ">=one", ">=1.0,,<2", "~=1.0", ">=1.0;<2"])
def test_bad_specifiers(spec):
    with pytest.raises(tv.SpecifierError):
        tv.parse(spec)


def test_validate_checks_the_running_version(vp, monkeypatch):
    ok = {**MINIMAL, "tld": {"version": ">=1.0,<2"}}
    assert vp.validate(ok)[0] == []
    monkeypatch.setattr(tld, "__version__", "2.1.0")
    errors = vp.validate(ok)[0]
    assert errors and errors[0].startswith("'tld.version': this profile needs tld >=1.0,<2, but tld 2.1.0 is running")


def test_validate_rejects_a_malformed_specifier(vp):
    errors = vp.validate({**MINIMAL, "tld": {"version": "latest"}})[0]
    assert errors and "'tld.version'" in errors[0]
    assert vp.validate({**MINIMAL, "tld": {"versoin": ">=1"}})[0]  # unknown key


def test_repo_profile_and_template_carry_a_satisfied_version():
    for path in (ROOT / ".tld" / "toolkit.yaml", ROOT / "src" / "tld" / "templates" / "toolkit.yaml"):
        assert "version: \">=1.0,<2\"" in path.read_text(), path
        r = subprocess.run([*tld_cmd("profile", "validate"), str(path), "--no-file-checks"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_old_agents_key_is_rejected_with_the_new_name(vp):
    errors = vp.validate({**MINIMAL, "agents": {}})[0]
    assert errors == ["'agents' was renamed to 'roles' (and each entry's 'agent' to 'role'): rename the section"]


def test_doc_help_does_not_run_the_command(tmp_path):
    """`tld dod exempt --help` prints help and writes no marker (the contract tests call --help on every command)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for args in (["dod", "exempt", "--help"], ["guard", "allow-profile", "--help"], ["profile", "survey", "--help"]):
        r = subprocess.run(tld_cmd(*args), capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode == 0 and r.stdout.startswith(f"usage: tld {args[0]} {args[1]}")
    assert not (tmp_path / ".git" / "tld").exists()
