"""The spec playbook, its command file and the stop message its eval expects."""
from __future__ import annotations

import re

from conftest import ROOT, CLAUDE, _load

PLAYBOOK = ROOT / "playbooks" / "spec.md"
STEPS = ("1. Survey", "2. Confirm", "3. Draft", "4. Validate and archive", "5. Deliver")


def test_playbook_has_usage_record_and_the_five_steps():
    text = PLAYBOOK.read_text()
    assert "\nUsage: spec [check | init]\n" in text
    assert "attended: true" in text
    headings = [l[4:] for l in text.splitlines() if l.startswith("### ")]
    assert headings == list(STEPS)


def test_command_file_names_the_playbook_path():
    text = (CLAUDE / "commands" / "spec.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/playbooks/spec.md" in text
    assert len(text.encode()) < 1500


def test_spec_playbook_names_the_stop_message_of_its_eval(tmp_path, capsys):
    text = (ROOT / "evals" / "fixtures" / "commands.py").read_text()
    m = re.search(r'command == "spec":.*?expected\["stop_message"\] = "([^"]+)"', text, re.S)
    assert m, "no spec stop_message in evals/fixtures/commands.py"
    message = m.group(1)
    assert message in PLAYBOOK.read_text()
    profile = tmp_path / "toolkit.yaml"
    profile.write_text("tld:\n  version: '>=1.0'\ngit:\n  main_branch: main\nverify:\n  fast: ['true']\n  dod: ['true']\n")
    assert _load("tld.ops.spec").main(["validate", "--profile", str(profile), "--root", str(tmp_path)]) == 2
    assert capsys.readouterr().err.strip() == message


def test_init_stops_on_a_dirty_tree_before_it_branches():
    text = PLAYBOOK.read_text()
    msg = "The working tree has changes; commit or stash them first. Nothing was changed."
    assert msg in " ".join(text.split())
    assert text.index("git status --porcelain") < text.index("git checkout -b chore/spec-init-")
