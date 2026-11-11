"""survey_proposal.build on the four /setup fixture repositories (through profile_survey.survey)."""
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "plugins" / "devflow" / "scripts"))
import profile_survey as ps  # noqa: E402
import survey_proposal as sp  # noqa: E402
import validate_profile as vp  # noqa: E402
from evals.fixtures.setup_repos import REPOS, build  # noqa: E402


@pytest.fixture(params=REPOS)
def case(request, tmp_path):
    expected = build(tmp_path, request.param)
    return expected, ps.survey(tmp_path)["proposal"]


def test_matches_expected(case):
    expected, proposal = case
    profile = proposal["profile"]
    assert profile["agents"] == expected["agents"]
    assert profile["stacks"] == expected["stacks"]
    assert profile["docs"].get("website") == expected["website"]
    names = [d["workflow"] for d in profile.get("ci", {}).get("dispatchable", [])]
    assert names == expected["dispatchable"]
    for key in ("adr_dir", "adr_index", "changelog"):
        assert profile["docs"].get(key) == expected[key]
    assert list(profile) == [k for k in ("stacks", "git", "docs", "ci", "agents") if k in profile]
    assert profile["git"] == {"main_branch": "main"}


def test_validates(case):
    profile = case[1]["profile"]
    full = {"docs": {"must_read": profile["docs"]["must_read"],
                     **{k: v for k, v in profile["docs"].items() if k != "must_read"}},
            "git": {**profile["git"], "branch_pattern": "<type>/<kebab-case>"},
            "verify": {"fast": ['echo "fast"'], "dod": ['echo "dod"']},
            "stacks": profile["stacks"], "agents": profile["agents"]}
    if "ci" in profile:
        full["ci"] = profile["ci"]
    errors, _, _ = vp.validate(full, root_dir=None)
    assert errors == []


def test_rationale(case):
    proposal = case[1]
    keys = [r["key"] for r in proposal["rationale"]]
    assert "agents.posture.security" in keys
    for entry in proposal["profile"]["agents"].get("required", []):
        assert "agents.required." + entry["agent"] in keys
    assert all(r["evidence"] for r in proposal["rationale"] if r["key"] != "stacks")


def test_blocking_only_critical_security(case):
    for entry in case[1]["profile"]["agents"].get("required", []):
        expect = entry["agent"] == "security-reviewer" and \
            case[1]["profile"]["agents"]["posture"]["security"] == "critical"
        assert entry["blocking"] is expect


def test_no_source_files_no_required():
    ev = {"stacks": [], "docs": {"must_read": ["README.md"]}, "git": {"main_branch": "main"},
          "ci": {"dispatchable": []},
          "signals": {"source_files": 0, "markdown_files": 20, "security": {"score": 5, "firing": [], "categories": {}},
                      "ui": {"globs": ["a/**"]}, "tests": {"levels": {}}}}
    agents = sp.build(ev)["profile"]["agents"]
    assert "required" not in agents
    assert agents["posture"]["security"] == "critical"


def test_cli_prints_proposal(tmp_path, capsys):
    build(tmp_path, "bare")
    assert ps.main([str(tmp_path)]) == 0
    assert '"proposal": {' in capsys.readouterr().out
