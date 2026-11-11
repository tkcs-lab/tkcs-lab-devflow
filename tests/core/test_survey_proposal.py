"""survey_proposal.build on the four /setup fixture repositories (through profile_survey.survey)."""
import sys

import pytest


from tld.profile import survey as ps  # noqa: E402
from tld.profile import survey_proposal as sp  # noqa: E402
from tld.profile import validate as vp  # noqa: E402
from evals.fixtures.setup_repos import REPOS, build  # noqa: E402


@pytest.fixture(params=REPOS)
def case(request, tmp_path):
    expected = build(tmp_path, request.param)
    return expected, ps.survey(tmp_path)["proposal"]


def test_matches_expected(case):
    expected, proposal = case
    profile = proposal["profile"]
    assert profile["roles"] == expected["roles"]
    assert profile["stacks"] == expected["stacks"]
    assert profile["docs"].get("website") == expected["website"]
    names = [d["workflow"] for d in profile.get("ci", {}).get("dispatchable", [])]
    assert names == expected["dispatchable"]
    for key in ("adr_dir", "adr_index", "changelog"):
        assert profile["docs"].get(key) == expected[key]
    assert list(profile) == [k for k in ("stacks", "git", "docs", "ci", "roles") if k in profile]
    assert profile["git"] == {"main_branch": "main"}


def test_validates(case):
    profile = case[1]["profile"]
    full = {"docs": {"must_read": profile["docs"]["must_read"],
                     **{k: v for k, v in profile["docs"].items() if k != "must_read"}},
            "git": {**profile["git"], "branch_pattern": "<type>/<kebab-case>"},
            "verify": {"fast": ['echo "fast"'], "dod": ['echo "dod"']},
            "stacks": profile["stacks"], "roles": profile["roles"]}
    if "ci" in profile:
        full["ci"] = profile["ci"]
    errors, _, _ = vp.validate(full, root_dir=None)
    assert errors == []


def test_rationale(case):
    proposal = case[1]
    keys = [r["key"] for r in proposal["rationale"]]
    assert "roles.posture.security" in keys
    for entry in proposal["profile"]["roles"].get("required", []):
        assert "roles.required." + entry["role"] in keys
    assert all(r["evidence"] for r in proposal["rationale"] if r["key"] != "stacks")


def test_blocking_only_critical_security(case):
    for entry in case[1]["profile"]["roles"].get("required", []):
        expect = entry["role"] == "security-reviewer" and \
            case[1]["profile"]["roles"]["posture"]["security"] == "critical"
        assert entry["blocking"] is expect


def test_no_source_files_no_required():
    ev = {"stacks": [], "docs": {"must_read": ["README.md"]}, "git": {"main_branch": "main"},
          "ci": {"dispatchable": []},
          "signals": {"source_files": 0, "markdown_files": 20, "security": {"score": 5, "firing": [], "categories": {}},
                      "ui": {"globs": ["a/**"]}, "tests": {"levels": {}}}}
    agents = sp.build(ev)["profile"]["roles"]
    assert "required" not in agents
    assert agents["posture"]["security"] == "critical"


def test_cli_prints_proposal(tmp_path, capsys):
    build(tmp_path, "bare")
    assert ps.main([str(tmp_path)]) == 0
    assert '"proposal": {' in capsys.readouterr().out


def test_index_is_proposed_and_must_read_capped():
    """C5: a docs index is proposed, and with it at most three must-read files."""
    ev = {"stacks": [], "docs": {"must_read": ["README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "SECURITY.md"],
                                 "index": "docs/README.md"},
          "git": {"main_branch": "main"}, "ci": {}, "signals": {"source_files": 0}}
    docs = sp.build(ev)["profile"]["docs"]
    assert docs["index"] == "docs/README.md"
    assert docs["must_read"] == ["README.md", "CONTRIBUTING.md", "ARCHITECTURE.md"]
    ev["docs"].pop("index")
    assert "index" not in sp.build(ev)["profile"]["docs"]
