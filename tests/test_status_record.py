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


@pytest.mark.parametrize("name", ["good-run", "good-run-scope", "good-maintenance"])
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


# --- the optional per-phase `scope` field (scope-drift monitoring) -------------------------------

OK_SCOPE = {"check": "ok", "in_scope": 5, "out_of_scope_count": 2, "collision_count": 1,
            "paths": ["src/core.py", "docs/extra.md"], "disposition": "accepted"}


def with_scope(scope, kind="run"):
    rec = json.loads((RECORDS / ("good-run.json" if kind == "run" else "good-maintenance.json")).read_text())
    rec["phases"][0]["scope"] = scope
    return run("-", stdin=json.dumps(rec))


def test_scope_is_optional():
    # good-run.json has no scope at all: records written before the field existed stay valid.
    assert run(RECORDS / "good-run.json").returncode == 0


def test_valid_scope_passes():
    assert with_scope(OK_SCOPE).returncode == 0
    assert with_scope({**OK_SCOPE, "out_of_scope_count": 0, "collision_count": 0, "paths": [], "disposition": None}).returncode == 0
    gone = {"check": "unavailable", "in_scope": None, "out_of_scope_count": None, "collision_count": None, "paths": [], "disposition": None}
    assert with_scope(gone).returncode == 0
    assert with_scope({**OK_SCOPE, "disposition": "reverted"}).returncode == 0


@pytest.mark.parametrize("change, needle", [
    ({"check": None}, "'check'"),
    ({"in_scope": -1}, "'in_scope'"),
    ({"out_of_scope_count": True}, "'out_of_scope_count'"),
    ({"collision_count": 3}, "'collision_count'"),
    ({"paths": ["a"] * 21, "out_of_scope_count": 30}, "at most 20"),
    ({"paths": ["a", "b", "c"]}, "more paths"),
    ({"paths": ["/etc/passwd"]}, "repository-relative"),
    ({"paths": ["../outside"]}, "repository-relative"),
    ({"paths": ["bad\nname"]}, "repository-relative"),
    ({"paths": ["x" * 301]}, "repository-relative"),
    ({"paths": [""]}, "non-empty strings"),
    ({"paths": [{"path": "a"}]}, "non-empty strings"),
    ({"disposition": "ignored"}, "'disposition'"),
    ({"disposition": None}, "'disposition'"),
    ({"extra": 1}, "unknown field 'extra'"),
])
def test_bad_scope_is_rejected(change, needle):
    result = with_scope({**OK_SCOPE, **change})
    assert result.returncode == 1, result.stdout
    assert any("'scope'" in line and needle in line for line in result.stdout.splitlines()), result.stdout


def test_missing_scope_key_is_rejected():
    scope = {k: v for k, v in OK_SCOPE.items() if k != "paths"}
    result = with_scope(scope)
    assert result.returncode == 1 and "missing 'paths'" in result.stdout


def test_unavailable_scope_must_be_empty():
    result = with_scope({**OK_SCOPE, "check": "unavailable"})
    assert result.returncode == 1 and "unavailable" in result.stdout


def test_scope_is_not_for_maintenance_records():
    result = with_scope(OK_SCOPE, kind="maintenance")
    assert result.returncode == 1 and "only allowed in a run record" in result.stdout


def test_scope_must_be_an_object():
    assert with_scope("3 files").returncode == 1


def test_scope_schema_matches_validator():
    schema = json.loads(SCHEMA.read_text())
    module = _load("validate_status_record")
    scope = schema["$defs"]["scope"]
    assert scope["additionalProperties"] is False
    assert set(scope["properties"]) == set(module.SCOPE_FIELDS) == set(scope["required"])
    assert scope["properties"]["paths"]["maxItems"] == module.SCOPE_PATHS_MAX
    assert scope["properties"]["paths"]["items"]["maxLength"] == module.SCOPE_PATH_MAX_LEN
    assert "scope" in schema["$defs"]["item"]["properties"] and "scope" not in schema["$defs"]["item"]["required"]
    assert schema["properties"]["schema"]["const"] == 1  # additive change: no version bump
    assert set(scope["properties"]["disposition"]["enum"]) == set(module.SCOPE_DISPOSITIONS) | {None}
