"""docs/reference/cli.md lists every command that tld.cli registers."""
from conftest import ROOT, _load


def test_cli_reference_lists_every_command():
    text = (ROOT / "docs" / "reference" / "cli.md").read_text(encoding="utf-8")
    cli = _load("tld.cli")
    missing = [f"tld {group} {command}" for group, command in cli.COMMANDS if f"tld {group} {command}" not in text]
    assert missing == []
