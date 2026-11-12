from pathlib import Path

from tld.guard.integrity import PLUGIN_CLI_PATHS, is_tld_cli

ROOT = Path(__file__).resolve().parents[2]


def test_every_plugin_cli_path_exists():
    for entry in PLUGIN_CLI_PATHS:
        path = entry.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT)).replace("$CLAUDE_PLUGIN_ROOT", str(ROOT))
        assert Path(path).is_file(), entry


def test_is_tld_cli_accepts_the_new_path_and_rejects_the_old():
    assert is_tld_cli('"${CLAUDE_PLUGIN_ROOT}/cli/tld"')
    old = '"${CLAUDE_PLUGIN_ROOT}/' + "launcher" + '/tld"'
    assert not is_tld_cli(old)
