import json
import subprocess
import sys

import pytest
import yaml

from conftest import TLD, CLAUDE, FIXTURES, tld_cmd, _load

SCRIPT = TLD / "roles" / "dispatch.py"
SCRIPT_CMD = tld_cmd("roles")
FIXTURE = FIXTURES / "roles-toolkit.yaml"


@pytest.fixture(scope="module")
def ag():
    return _load("tld.roles.dispatch")


@pytest.fixture(scope="module")
def profile():
    return yaml.safe_load(FIXTURE.read_text())


def names(result, key="required"):
    return [i["role"] for i in result[key]]


def item(result, agent):
    return next(i for i in result["required"] if i["role"] == agent)


# --- required ------------------------------------------------------------------------------------

def test_make_plan(ag, profile):
    r = ag.required(profile, "make_plan", None)
    assert r["point"] == "make_plan"
    assert r["posture"] == {"security": "critical"}
    assert r["disabled"] == ["dependency-auditor"]
    assert r["extra_context"] == ["Every outbound request is logged."]
    assert r["required"] == [{"role": "test-architect", "blocking": False, "matched": ["always"], "mode": "review"}]
    assert r["not_applicable"] == []


def test_implement_phase(ag, profile):
    r = ag.required(profile, "implement_phase", [])
    assert r["required"] == [{"role": "security-reviewer", "blocking": True, "matched": ["always"], "mode": "review"}]


def test_implement_final_when_matches(ag, profile):
    r = ag.required(profile, "implement_final", ["app/views/home.py", "README.md"])
    assert names(r) == ["security-reviewer", "ux-reviewer"]
    assert item(r, "ux-reviewer") == {"role": "ux-reviewer", "blocking": False, "matched": ["app/views/**"], "mode": "review"}
    assert r["not_applicable"] == []


def test_implement_final_when_does_not_match(ag, profile):
    r = ag.required(profile, "implement_final", ["README.md"])
    assert names(r) == ["security-reviewer"]
    assert r["not_applicable"] == [{"role": "ux-reviewer", "why": "no changed file matches 'when'"}]


def test_review_has_no_diff(ag, profile):
    r = ag.required(profile, "review", None)
    assert names(r) == ["tech-writer"]


def test_dod_matches_some_globs(ag, profile):
    r = ag.required(profile, "dod", ["docs/guide.md"])
    assert names(r) == ["tech-writer", "website-maintainer"]
    assert item(r, "website-maintainer")["matched"] == ["docs/**"]
    assert item(r, "tech-writer")["matched"] == ["always"]


def test_dod_no_match(ag, profile):
    r = ag.required(profile, "dod", ["src/a.py"])
    assert names(r) == ["tech-writer"]
    assert names(r, "not_applicable") == ["website-maintainer"]


@pytest.mark.parametrize("point", ["make_plan", "review"])
def test_when_at_a_point_without_diff_is_not_applicable(ag, point):
    prof = {"roles": {"required": [{"role": "tech-writer", "at": [point], "when": ["docs/**"]}]}}
    r = ag.required(prof, point, None)
    assert r["required"] == []
    assert r["not_applicable"] == [{"role": "tech-writer", "why": "no diff at this point"}]


def test_blocking_or_merge(ag):
    prof = {"roles": {"required": [
        {"role": "security-reviewer", "at": ["dod"]},
        {"role": "security-reviewer", "at": ["dod", "review"], "blocking": True, "when": ["src/**"]},
    ]}}
    r = ag.required(prof, "dod", ["src/a.py"])
    assert r["required"] == [{"role": "security-reviewer", "blocking": True, "matched": ["always", "src/**"], "mode": "review"}]


def test_profile_without_agents(ag):
    r = ag.required({"stacks": []}, "dod", None)
    assert r["required"] == [] and r["not_applicable"] == []
    assert r["posture"] == {"security": "standard"}
    assert r["disabled"] == [] and r["extra_context"] == []


def test_defaults_applied_here(ag):
    prof = {"roles": {"required": [{"role": "debugger", "at": ["dod"]}]}}
    r = ag.required(prof, "dod", None)
    assert r["posture"] == {"security": "standard"}
    assert item(r, "debugger")["blocking"] is False


def test_unknown_point(ag, profile):
    with pytest.raises(ag.RolesError, match=r"unknown point 'x' \(one of make_plan, implement_phase"):
        ag.required(profile, "x", None)


def test_changed_missing_at_dod(ag, profile):
    with pytest.raises(ag.RolesError, match="--changed is needed: roles.required has entries with 'when'"):
        ag.required(profile, "dod", None)


# --- verify --------------------------------------------------------------------------------------

REQ = {"point": "implement_final", "required": [
    {"role": "security-reviewer", "blocking": True, "matched": ["always"]},
    {"role": "ux-reviewer", "blocking": False, "matched": ["always"]}]}


def line(agent, verdict="pass", b=0, nb=0, at="implement_final"):
    return f"AGENT-REPORT {agent} at={at} verdict={verdict} blocking={b} non_blocking={nb}"


def test_verify_ok(ag):
    out, ok = ag.verify(REQ, "text\n" + line("security-reviewer") + "\n" + line("ux-reviewer") + "\n")
    assert ok
    assert out == ["OK security-reviewer at=implement_final blocking=0",
                   "OK ux-reviewer at=implement_final blocking=0",
                   "roles: ok (2 required)"]


def test_verify_missing_line(ag):
    out, ok = ag.verify(REQ, line("security-reviewer"))
    assert not ok
    assert "MISSING ux-reviewer at=implement_final" in out
    assert out[-1] == "roles: FAILED (1 of 2 required)"


def test_verify_wrong_point_is_missing(ag):
    out, ok = ag.verify(REQ, line("security-reviewer", at="dod") + "\n" + line("ux-reviewer"))
    assert not ok and out[0] == "MISSING security-reviewer at=implement_final"


def test_verify_na_is_missing(ag):
    out, ok = ag.verify(REQ, line("security-reviewer") + "\n" + line("ux-reviewer", "n/a"))
    assert not ok and "MISSING ux-reviewer at=implement_final" in out


def test_verify_blocked(ag):
    out, ok = ag.verify(REQ, line("security-reviewer", "findings", 2, 1) + "\n" + line("ux-reviewer"))
    assert not ok
    assert out[0] == "BLOCKED security-reviewer at=implement_final blocking=2"
    assert out[-1] == "roles: FAILED (1 of 2 required)"


def test_verify_non_blocking_entry_with_findings_is_ok(ag):
    out, ok = ag.verify(REQ, line("security-reviewer") + "\n" + line("ux-reviewer", "findings", 3, 1))
    assert ok and "OK ux-reviewer at=implement_final blocking=3" in out


def test_verify_last_line_wins(ag):
    report = line("security-reviewer", "findings", 1, 0) + "\nfixed\n" + line("security-reviewer") + "\n" + line("ux-reviewer")
    assert ag.verify(REQ, report)[1]
    reverse = line("security-reviewer") + "\n" + line("security-reviewer", "findings", 1, 0) + "\n" + line("ux-reviewer")
    assert not ag.verify(REQ, reverse)[1]


@pytest.mark.parametrize("wrap", ["> {}", "   {}", "`{}`", "> `{}`", "{}  "])
def test_verify_tolerates_quoting(ag, wrap):
    report = wrap.format(line("security-reviewer")) + "\n" + wrap.format(line("ux-reviewer")) + "\n"
    assert ag.verify(REQ, report)[1]


def test_verify_ignores_text_after_the_line(ag):
    out, ok = ag.verify(REQ, line("security-reviewer") + " extra\n" + line("ux-reviewer"))
    assert not ok


def test_verify_empty_required(ag):
    assert ag.verify({"point": "dod", "required": []}, "") == (["roles: ok (0 required)"], True)


# --- CLI -----------------------------------------------------------------------------------------

def run(*args, stdin=None):
    return subprocess.run([*SCRIPT_CMD, *args], capture_output=True, text=True, input=stdin)


def test_cli_round_trip(tmp_path):
    changed = tmp_path / "changed.txt"
    changed.write_text("app/views/a.py\n\n")
    p = run("required", "--profile", str(FIXTURE), "--at", "implement_final", "--changed", str(changed))
    assert p.returncode == 0, p.stderr
    req = json.loads(p.stdout)
    assert names(req) == ["security-reviewer", "ux-reviewer"]
    (tmp_path / "req.json").write_text(p.stdout)
    report = tmp_path / "report.txt"
    report.write_text(line("security-reviewer") + "\n" + line("ux-reviewer") + "\n")
    v = run("verify", "--required", str(tmp_path / "req.json"), "--report", str(report))
    assert v.returncode == 0 and v.stdout.splitlines()[-1] == "roles: ok (2 required)"
    report.write_text(line("security-reviewer", "findings", 1, 0) + "\n")
    v = run("verify", "--required", str(tmp_path / "req.json"), "--report", str(report))
    assert v.returncode == 1
    assert v.stdout.splitlines() == ["BLOCKED security-reviewer at=implement_final blocking=1",
                                     "MISSING ux-reviewer at=implement_final",
                                     "roles: FAILED (2 of 2 required)"]


def test_cli_make_plan_needs_no_changed():
    p = run("required", "--profile", str(FIXTURE), "--at", "make_plan")
    assert p.returncode == 0
    assert "test-architect" in names(json.loads(p.stdout))


def test_cli_changed_from_stdin():
    p = run("required", "--profile", str(FIXTURE), "--at", "dod", "--changed", "-", stdin="site/index.md\n")
    assert p.returncode == 0
    assert names(json.loads(p.stdout)) == ["tech-writer", "website-maintainer"]


def test_cli_errors(tmp_path):
    p = run("required", "--profile", str(FIXTURE), "--at", "nope")
    assert p.returncode == 1 and p.stderr.startswith("tld roles: unknown point 'nope' (one of make_plan")
    p = run("required", "--profile", str(tmp_path / "missing.yaml"), "--at", "dod")
    assert p.returncode == 1 and p.stderr.startswith(f"tld roles: cannot read '{tmp_path / 'missing.yaml'}'")
    p = run("required", "--profile", str(FIXTURE), "--at", "dod")
    assert p.returncode == 1
    assert p.stderr.strip() == "tld roles: --changed is needed: roles.required has entries with 'when'"
    bad = tmp_path / "bad.yaml"
    bad.write_text("stacks: []\n")
    p = run("required", "--profile", str(bad), "--at", "dod")
    assert p.returncode == 1 and p.stderr.startswith("tld roles: ") and "verify" in p.stderr
    p = run("verify", "--required", str(tmp_path / "nope.json"), "--report", str(bad))
    assert p.returncode == 1 and "cannot read" in p.stderr


def test_cli_invalid_agents_block(tmp_path):
    prof = yaml.safe_load(FIXTURE.read_text())
    prof["roles"]["required"].append({"role": "tech-writer", "at": ["nowhere"]})
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(prof))
    p = run("required", "--profile", str(bad), "--at", "make_plan")
    assert p.returncode == 1 and "nowhere" in p.stderr


# --- modes (C2) ----------------------------------------------------------------------------------

@pytest.mark.parametrize("point", ["make_plan", "implement_phase", "implement_final", "dod"])
def test_edit_mode_only_for_edit_roles_in_a_phase(ag, point):
    prof = {"roles": {"required": [{"role": "tech-writer", "at": [point]}, {"role": "code-reviewer", "at": [point]}]}}
    r = ag.required(prof, point, [])
    modes = {i["role"]: i["mode"] for i in r["required"]}
    assert modes == {"tech-writer": "edit" if point == "implement_phase" else "review", "code-reviewer": "review"}
