"""The ask example of runtime.md and the record examples of land.md stay valid (behaviour, not wording)."""
import json
import re
from pathlib import Path

from tld.board import ask, record

ROOT = Path(__file__).resolve().parents[2]
REPLACE = {
    "<project slug>": "example-project",
    "<owner>/<repo>": "example-org/example-project",
    "<the status record's document id>": "example-project",
    "<this session's id, else the playbook's name>": "session_x",
    "<optional https link: the review, the plan, the pull request>": "https://example.com/x",
    "<one line>": "A title",
    "<question>": "A question?",
    "<label> (recommended)": "A (recommended)",
    "<label>": "A",
}


def _json_blocks(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    return re.findall(r"```json\n(.*?)```", text, re.S)


def _ask_example():
    for block in _json_blocks("playbooks/runtime.md"):
        if '"kind": "ask"' in block:
            return block
    raise AssertionError("no ask example in runtime.md")


def test_the_ask_example_with_a_record_validates():
    text = _ask_example()
    for old, new in REPLACE.items():
        text = text.replace(old, new)
    ids = iter(["q1", "q2", "q3"])
    text = re.sub(r'"id": "<id>"', lambda _m: f'"id": "{next(ids)}"', text)
    values = iter(["a", "b"])
    text = re.sub(r'"value": "<value>"', lambda _m: f'"value": "{next(values)}"', text)
    data = json.loads(text)
    assert data["record"] == "example-project"
    assert ask.validate_new(data) == []


def test_land_json_examples_are_valid_and_never_pr_open_with_needs_you():
    for block in _json_blocks("playbooks/land.md"):
        rec = json.loads(block)
        assert record.validate(rec, "example-project--land") == []
        assert not (rec.get("status") == "pr_open" and rec.get("needs_you") is True)
