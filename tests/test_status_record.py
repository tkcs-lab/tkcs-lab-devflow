import json
import subprocess
import sys

import pytest

from conftest import DEVFLOW, FIXTURES, ROOT, _load

SCRIPT = DEVFLOW / "scripts" / "validate_status_record.py"
SCHEMA = DEVFLOW / "schema" / "status-record.schema.json"
RECORDS = FIXTURES / "status-records"


def run(*args, stdin=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], input=stdin, capture_output=True, text=True)


@pytest.mark.parametrize("name", ["good-run", "good-maintenance"])
def test_good_fixture_passes(name):
    result = run(RECORDS / f"{name}.json")
    assert result.returncode == 0, result.stdout
    assert result.stdout.strip() == "status-record: OK"


@pytest.mark.parametrize("name, needle", [
    ("bad-needs-you-no-reason", "'needs_you_reason'"),
    ("bad-unknown-status", "'status'"),
    ("bad-missing-updated-at", "'updated_at'"),
    ("bad-done-no-finished", "'finished_at'"),
    ("bad-running-with-finished", "'finished_at'"),
    ("bad-maintenance-with-timer", "'next_check_at'"),
    ("bad-kind-command-mismatch", "'command'"),
])
def test_bad_fixture_fails(name, needle):
    result = run(RECORDS / f"{name}.json")
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines and all(line.startswith("status-record: ") for line in lines)
    assert any(needle in line for line in lines), result.stdout


def test_doc_id_for_maintenance():
    assert run(RECORDS / "good-maintenance.json", "--doc-id", "claude-toolkit--deps").returncode == 0
    wrong = run(RECORDS / "good-maintenance.json", "--doc-id", "claude-toolkit")
    assert wrong.returncode == 1 and "--doc-id" in wrong.stdout


def test_doc_id_for_run():
    assert run(RECORDS / "good-run.json", "--doc-id", "claude-toolkit").returncode == 0
    assert run(RECORDS / "good-run.json", "--doc-id", "claude-toolkit--deps").returncode == 1


def test_stdin_and_bad_json():
    assert run("-", stdin=(RECORDS / "good-run.json").read_text()).returncode == 0
    broken = run("-", stdin="{not json")
    assert broken.returncode == 1 and broken.stdout.startswith("status-record: ")


def test_impossible_date_is_rejected():
    rec = json.loads((RECORDS / "good-run.json").read_text())
    rec["updated_at"] = "2026-02-30T10:00:00Z"
    result = run("-", stdin=json.dumps(rec))
    assert result.returncode == 1 and "'updated_at'" in result.stdout


def test_unknown_field_is_rejected():
    rec = json.loads((RECORDS / "good-run.json").read_text())
    rec["extra"] = 1
    result = run("-", stdin=json.dumps(rec))
    assert result.returncode == 1 and "'extra'" in result.stdout


def test_fields_match_schema():
    schema = json.loads(SCHEMA.read_text())
    module = _load("validate_status_record")
    assert set(module.FIELDS) == set(schema["properties"])
    assert set(schema["required"]) == set(module.FIELDS)
    assert schema["additionalProperties"] is False


def test_schema_examples_validate():
    schema = json.loads(SCHEMA.read_text())
    assert schema["examples"]
    for example in schema["examples"]:
        result = run("-", stdin=json.dumps(example))
        assert result.returncode == 0, result.stdout


def test_no_plan_name_in_fixtures_or_schema():
    paths = [SCHEMA, *RECORDS.glob("*.json")]
    assert len(paths) > 2
    for path in paths:
        assert "devflow-" "v2" not in path.read_text(), path.relative_to(ROOT)
