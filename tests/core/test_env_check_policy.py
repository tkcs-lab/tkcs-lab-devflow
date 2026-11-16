"""Wording pins for step 5 of "Loading the profile" and the runtime action environment_name() (plan 63).

They check the text, not behaviour: the behaviour of step 5 is the model's.
"""
from __future__ import annotations

import re

from conftest import ROOT

STEP5 = " ".join("""5. **Check the environment.** When the profile has `runtime.environments`, call `environment_name()` ([../runtime.md](../runtime.md)). When it returns a name that is none of the listed names (compared after trimming, ignoring case), call `notify_human("<project>: this session runs in the environment <name>, this repository expects <names>")` once and say the same in your first reply, then carry on: this step never stops a run and never changes what the playbook does. A worker started by another session puts the line in its final report and does not call `notify_human`. When `environment_name()` returns nothing, or the profile has no such key, skip this step without a word. Whenever `environment_name()` returns a name and the shell variable `TLD_ENVIRONMENT` is set and differs from it (also when the name is listed), say in your first reply the line `TLD_ENVIRONMENT says <value> but the session runs in <name>: update the variable in the environment's settings.` and add it to the alert when one is sent.""".split())

PROFILE = ROOT / "playbooks" / "policies" / "profile.md"
RUNTIME = ROOT / "playbooks" / "runtime.md"
SKILL = ROOT / "adapters" / "claude" / "skills" / "runtime" / "SKILL.md"


def _section() -> str:
    text = PROFILE.read_text()
    return text.split("## Loading the profile", 1)[1].split("## Keys", 1)[0]


def test_env_check_step5_text_is_in_the_loading_section():
    assert STEP5 in " ".join(_section().split())


def test_env_check_loading_steps_are_numbered_one_to_five():
    numbers = [int(m.group(1)) for line in _section().splitlines() if (m := re.match(r"(\d+)\.", line))]
    assert numbers == [1, 2, 3, 4, 5]


def test_env_check_key_row_comes_before_project_steward():
    text = PROFILE.read_text()
    assert "| `runtime.environments` |" in text
    assert text.index("| `runtime.environments` |") < text.index("| `project_steward` |")


def test_env_check_runtime_action_is_defined_between_secrets_help_and_time():
    text = RUNTIME.read_text()
    a, b, c = (text.index(h) for h in ("### secrets_help()", "### environment_name()", "## Time"))
    assert a < b < c
    assert "Never an error" in text[b:c]


def test_env_check_skill_maps_the_action():
    rows = [l for l in SKILL.read_text().splitlines() if l.startswith("| `environment_name()`")]
    assert len(rows) == 1
    for word in ("get_environment", "claude-code-remote", "Nothing when"):
        assert word in rows[0]


def test_env_check_every_playbook_links_the_profile_policy():
    missing = [p.name for p in sorted((ROOT / "playbooks").glob("*.md"))
               if p.name not in ("ask.md", "runtime.md") and "policies/profile.md" not in p.read_text()]
    assert missing == []
