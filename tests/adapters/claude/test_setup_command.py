import json
import subprocess
import sys

import yaml

from conftest import TLD, CLAUDE, tld_cmd
from evals.fixtures import setup_repos

COMMAND = CLAUDE / "commands" / "setup.md"
SKILL = CLAUDE / "skills" / "profile-setup" / "SKILL.md"

HEADINGS = ["## Profile", "## Guardrail hooks", "## 1. Survey", "## 2. Decide", "## 3. Ask", "## 4. Write",
            "## 5. Check", "## 6. Deliver", "## Status board"]
SKILL_HEADINGS = ["## Choosing verify commands", "## Mapping evidence to keys", "## Questions",
                  "## Pull request body", "## Never"]
STRINGS = ["project-profile", "never substitute", "profile survey", "profile patch diff",
           "profile patch set-block", "profile validate", 'bin/tld" dod exempt',
           'bin/tld" guard allow-profile', 'bin/tld" guard end-allow', "chore/toolkit-profile",
           "AskUserQuestion", "never merges", "stop after the commit"]


def flat(path):
    return " ".join(path.read_text().split())


def in_order(text, headings):
    pos = -1
    for h in headings:
        nxt = text.find("\n" + h + "\n", pos + 1)
        assert nxt > pos, f"missing or out of order: {h}"
        pos = nxt


def front(path):
    return yaml.safe_load(path.read_text().split("---")[1])


def test_command_front_matter():
    fm = front(COMMAND)
    assert fm["model"] == "sonnet"
    assert fm["description"] and fm["argument-hint"]


def test_command_headings_and_strings():
    in_order(COMMAND.read_text(), HEADINGS)
    text = flat(COMMAND)
    for s in STRINGS:
        assert s in text, s


def test_skill():
    fm = front(SKILL)
    assert fm["name"] == "profile-setup" and fm["user-invocable"] is False
    in_order(SKILL.read_text(), SKILL_HEADINGS)
    text = flat(SKILL)
    for s in ("Decisions for a human", "blocking: true", "--accept-proposals", "Never"):
        assert s in text, s


def test_starter_exists():
    assert (TLD / "templates" / "toolkit.yaml").is_file()


def test_survey_then_set_block_validates(tmp_path):
    repo = tmp_path / "repo"
    setup_repos.build(repo, repo="security_heavy", with_profile=True)
    survey = subprocess.run([*tld_cmd("profile", "survey"), str(repo)],
                            capture_output=True, text=True)
    assert survey.returncode == 0, survey.stderr
    survey_file = tmp_path / "survey.json"
    survey_file.write_text(survey.stdout)
    assert "agents" in json.loads(survey.stdout)["proposal"]["profile"]
    profile = repo / ".tld" / "toolkit.yaml"
    patched = subprocess.run([*tld_cmd("profile", "patch"), "set-block", str(profile),
                              "agents", str(survey_file), "--write"], capture_output=True, text=True)
    assert patched.returncode == 0, patched.stderr
    assert "agents:" in profile.read_text()
    check = subprocess.run([*tld_cmd("profile", "validate"), str(profile),
                            "--no-file-checks"], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
