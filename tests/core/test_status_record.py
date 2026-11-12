import json
import re
import subprocess
import sys

import pytest

from conftest import ROOT, TLD, FIXTURES, tld_cmd, _load

SCRIPT = TLD / "board" / "record.py"
SCRIPT_CMD = tld_cmd("board", "validate-record")
SCHEMA = TLD / "schema" / "status-record.schema.json"
RECORDS = FIXTURES / "status-records"


def run(*args, stdin=None):
    return subprocess.run([*SCRIPT_CMD, *map(str, args)], input=stdin, capture_output=True, text=True)


@pytest.mark.parametrize("name", ["good-run", "good-run-scope", "good-command", "good-command-docs"])
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
    ("bad-command-with-timer", "'next_check_at'"),
    ("bad-kind-command-mismatch", "'command'"),
])
def test_bad_fixture_fails(name, needle):
    result = run(RECORDS / f"{name}.json")
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines and all(line.startswith("status-record: ") for line in lines)
    assert any(needle in line for line in lines), result.stdout


def test_doc_id_for_a_command_record():
    assert run(RECORDS / "good-command.json", "--doc-id", "tkcs-lab-devflow--deps").returncode == 0
    wrong = run(RECORDS / "good-command.json", "--doc-id", "tkcs-lab-devflow")
    assert wrong.returncode == 1 and "--doc-id" in wrong.stdout


def test_doc_id_for_docs():
    assert run(RECORDS / "good-command-docs.json", "--doc-id", "tkcs-lab-devflow--docs").returncode == 0
    wrong = run(RECORDS / "good-command-docs.json", "--doc-id", "tkcs-lab-devflow--deps")
    assert wrong.returncode == 1 and "--doc-id" in wrong.stdout


def command_record(*args, **changes):
    rec = json.loads((RECORDS / "good-command.json").read_text())
    rec.update(changes)
    return run("-", *args, stdin=json.dumps(rec))


def setup_record(*args, **changes):
    base = json.loads((RECORDS / "good-command.json").read_text())["phases"][0]
    items = [{**base, "id": step, "title": step, "branch": None, "pr": None, "state": "pending"}
             for step in ("survey", "confirm", "write", "verify", "pr")]
    return command_record(*args, **{"command": "setup", "orchestrator_session": "session_01abc", "attended": True,
                                 "phases": items, **changes})


def test_valid_setup_record_passes():
    result = setup_record()
    assert result.returncode == 0, result.stdout


def test_attended_replaces_the_scheduled_literal():
    """C7: `attended` says who is there; `orchestrator_session` is an id or null, never 'scheduled'."""
    bad = setup_record(orchestrator_session="scheduled")
    assert bad.returncode == 1 and "'attended: false' marks an unattended run" in bad.stdout
    assert setup_record(orchestrator_session="").returncode == 1
    assert command_record(orchestrator_session="session_01abc").returncode == 0  # unattended, but it knows its id
    no_id = setup_record(orchestrator_session=None)
    assert no_id.returncode == 1 and "must be the session id when 'attended' is true" in no_id.stdout
    assert command_record(attended="no").returncode == 1
    missing = json.loads((RECORDS / "good-command.json").read_text())
    missing.pop("attended")
    assert "'attended' is required" in run("-", stdin=json.dumps(missing)).stdout


@pytest.mark.parametrize("command", ["review", "make-plan"])
def test_review_and_make_plan_write_records(command):
    # setup_record's session id is "session_01abc": its tail is "ion01abc"
    result = setup_record("--doc-id", f"tkcs-lab-devflow--{command}--ion01abc", command=command)
    assert result.returncode == 0, result.stdout


def test_project_slug_comes_from_the_repository_name():
    assert command_record(repo="someone/Tkcs_Lab.Devflow").returncode == 0
    wrong = command_record(project="other")
    assert wrong.returncode == 1 and "'project' must be 'tkcs-lab-devflow'" in wrong.stdout
    out = subprocess.run(tld_cmd("board", "project-slug", "Org/My__Repo.js"), capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == "my-repo-js\n"
    bad = subprocess.run(tld_cmd("board", "project-slug", "no-slash"), capture_output=True, text=True)
    assert bad.returncode == 1


def test_pr_open_is_a_final_state():
    """C7: done, failed and pr_open are final; only they may carry finished_at."""
    assert command_record(finished_at="2026-11-09T05:00:00Z").returncode == 0  # status pr_open
    assert command_record(finished_at=None).returncode == 0
    assert command_record(status="running", finished_at="2026-11-09T05:00:00Z").returncode == 1


def test_doc_id_for_setup():
    assert setup_record("--doc-id", "tkcs-lab-devflow--setup--ion01abc").returncode == 0
    wrong = setup_record("--doc-id", "tkcs-lab-devflow--deps")
    assert wrong.returncode == 1 and "--doc-id" in wrong.stdout


def test_doc_id_for_run():
    assert run(RECORDS / "good-run.json", "--doc-id", "tkcs-lab-devflow--run--example-plan").returncode == 0
    assert run(RECORDS / "good-run.json", "--doc-id", "tkcs-lab-devflow--deps").returncode == 1


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
    module = _load("tld.board.record")
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
        assert "tld-" "v2" not in path.read_text(), path.relative_to(ROOT)


# --- the optional per-phase `scope` field (scope-drift monitoring) -------------------------------

OK_SCOPE = {"check": "ok", "in_scope": 5, "out_of_scope_count": 2, "collision_count": 1,
            "paths": ["src/core.py", "docs/extra.md"], "disposition": "accepted"}


def with_scope(scope, kind="run"):
    rec = json.loads((RECORDS / ("good-run.json" if kind == "run" else "good-command.json")).read_text())
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


def test_scope_is_not_for_command_records():
    result = with_scope(OK_SCOPE, kind="command")
    assert result.returncode == 1 and "only allowed in a run record" in result.stdout


def test_scope_must_be_an_object():
    assert with_scope("3 files").returncode == 1


def test_scope_schema_matches_validator():
    schema = json.loads(SCHEMA.read_text())
    module = _load("tld.board.record")
    scope = schema["$defs"]["scope"]
    assert scope["additionalProperties"] is False
    assert set(scope["properties"]) == set(module.SCOPE_FIELDS) == set(scope["required"])
    assert scope["properties"]["paths"]["maxItems"] == module.SCOPE_PATHS_MAX
    assert scope["properties"]["paths"]["items"]["maxLength"] == module.SCOPE_PATH_MAX_LEN
    assert "scope" in schema["$defs"]["item"]["properties"] and "scope" not in schema["$defs"]["item"]["required"]
    assert schema["properties"]["schema"]["const"] == 1  # additive change: no version bump
    assert set(scope["properties"]["disposition"]["enum"]) == set(module.SCOPE_DISPOSITIONS) | {None}


def test_the_old_kind_maintenance_is_refused():
    """The record kind for every command but implement is `command`; nothing reads the old name."""
    result = command_record(kind="maintenance")
    assert result.returncode == 1 and "'kind' must be 'run' or 'command'" in result.stdout


# --- document ids per run and per session (tld board record-id) ----------------------------------

import tld  # noqa: E402

REC = _load("tld.board.record")
LONG_MESSAGE = "'project' is too long for a document id"
SHORT_MESSAGE = "'orchestrator_session' needs at least 6 letters or digits to key an attended command record"
SESSION = "session_01ABcdEFghIJkl"


def rec_of(kind="command", command="make-plan", project="tkcs-lab-devflow", plan_slug=None, attended=True, session=SESSION):
    return {"project": project, "kind": kind, "command": None if kind == "run" else command,
            "plan_slug": plan_slug, "attended": attended, "orchestrator_session": session}


def run_id(plan_slug, project="p"):
    return REC.doc_id(rec_of("run", project=project, plan_slug=plan_slug))


def record_id(*args):
    return subprocess.run([*tld_cmd("board", "record-id"), *args], capture_output=True, text=True)


def test_run_id_uses_the_plan_slug():
    assert REC.doc_id(rec_of("run", plan_slug="stale-needs-you-cards")) == "tkcs-lab-devflow--run--stale-needs-you-cards"


def test_attended_command_id_uses_the_session_tail():
    assert REC.doc_id(rec_of()) == "tkcs-lab-devflow--make-plan--efghijkl"


def test_unattended_command_id_is_unchanged():
    assert REC.doc_id(rec_of(command="deps", attended=False, session=None)) == "tkcs-lab-devflow--deps"
    assert REC.doc_id(rec_of(command="deps", attended=False, session="session_01abc")) == "tkcs-lab-devflow--deps"


def test_plan_slug_is_made_safe():
    assert run_id("Plan_X  y!") == "p--run--plan-x-y"
    assert run_id("") == "p--run--plan"
    assert run_id("---") == "p--run--plan"
    assert run_id(None) == "p--run--plan"


def test_plan_slug_at_the_limit_is_not_cut():
    prefix = "p--run--"
    plan = "a" * (100 - len(prefix))
    assert run_id(plan) == prefix + plan and len(run_id(plan)) == 100


def test_plan_slug_one_over_the_limit_is_cut():
    prefix = "p--run--"
    result = run_id("a" * (101 - len(prefix)))
    assert len(result) == 100 and REC.DOC_ID_RE.match(result)
    assert re.fullmatch(r"p--run--a+-[0-9a-f]{8}", result)


def test_two_long_slugs_with_one_prefix_get_two_ids():
    first, second = run_id("a" * 100 + "x" * 50), run_id("a" * 100 + "y" * 50)
    assert first != second and len(first) == len(second) == 100
    assert REC.DOC_ID_RE.match(first) and REC.DOC_ID_RE.match(second)


def test_long_project_is_an_error():
    project = "a" * 95
    for rec in (rec_of("run", project=project, plan_slug="x"), rec_of(project=project, command="deps", attended=False)):
        with pytest.raises(ValueError, match=re.escape(LONG_MESSAGE)):
            REC.doc_id(rec)
    with pytest.raises(ValueError, match=re.escape(LONG_MESSAGE)):  # no room for a cut plan and its hash
        REC.doc_id(rec_of("run", project="a" * 85, plan_slug="b" * 60))
    assert len(REC.doc_id(rec_of("run", project="a" * 85, plan_slug="b"))) == 93
    with pytest.raises(ValueError, match=re.escape(LONG_MESSAGE)):
        REC.doc_id(rec_of(project="a" * 87))  # 87 + "--make-plan--" + 8 = 108


def test_six_character_tail_is_enough():
    assert REC.doc_id(rec_of(session="ab-cd_ef")) == "tkcs-lab-devflow--make-plan--abcdef"


def test_five_character_tail_is_an_error():
    with pytest.raises(ValueError, match=re.escape(SHORT_MESSAGE)):
        REC.doc_id(rec_of(session="ab-cd_e"))
    with pytest.raises(ValueError, match=re.escape(SHORT_MESSAGE)):
        REC.doc_id(rec_of(session=None))


def test_run_is_not_a_command():
    assert "run" not in REC.COMMANDS


def test_two_runs_get_two_ids():
    assert run_id("first-plan") != run_id("second-plan")


def test_legacy_ids_are_still_accepted():
    assert setup_record("--doc-id", "tkcs-lab-devflow--setup").returncode == 0
    assert run(RECORDS / "good-run.json", "--doc-id", "tkcs-lab-devflow").returncode == 0
    third = setup_record("--doc-id", "tkcs-lab-devflow")
    assert third.returncode == 1 and "'--doc-id'" in third.stdout
    third = run(RECORDS / "good-run.json", "--doc-id", "tkcs-lab-devflow--run")
    assert third.returncode == 1 and "'--doc-id'" in third.stdout


def test_unattended_command_has_no_legacy_id():
    assert REC.legacy_ids(rec_of(command="deps", attended=False, session=None)) == ()
    assert REC.legacy_ids(rec_of()) == ("tkcs-lab-devflow--make-plan",)
    assert REC.legacy_ids(rec_of("run", plan_slug="x")) == ("tkcs-lab-devflow",)
    assert command_record("--doc-id", "tkcs-lab-devflow--deps").returncode == 0


def test_wrong_id_gets_the_message_of_3_1():
    result = run(RECORDS / "good-run.json", "--doc-id", "tkcs-lab-devflow--run--other")
    assert result.returncode == 1
    assert ("status-record: '--doc-id' is 'tkcs-lab-devflow--run--other' but the document id of this record is "
            "'tkcs-lab-devflow--run--example-plan'") in result.stdout
    short = setup_record("--doc-id", "tkcs-lab-devflow--setup--abcdefgh", orchestrator_session="ab")
    assert short.returncode == 1 and f"status-record: {SHORT_MESSAGE}" in short.stdout


def test_broken_record_gets_no_id_error():
    rec = json.loads((RECORDS / "good-run.json").read_text())
    del rec["project"]
    result = run("-", "--doc-id", "x", stdin=json.dumps(rec))
    assert result.returncode == 1 and "'--doc-id'" not in result.stdout
    for change in ({"kind": "maintenance"}, {"project": "A b"}, {"project": "a--b"}):
        result = run("-", "--doc-id", "x", stdin=json.dumps({**json.loads((RECORDS / "good-run.json").read_text()), **change}))
        assert result.returncode == 1 and "'--doc-id'" not in result.stdout
    result = command_record("--doc-id", "x", command="nope")
    assert result.returncode == 1 and "'--doc-id'" not in result.stdout


def test_validate_without_doc_id_ignores_the_tail():
    assert setup_record(orchestrator_session="ab").returncode == 0


def test_attended_record_rewritten_by_a_new_session():
    old = REC.doc_id(rec_of(command="setup", session="session_01abc"))
    assert setup_record("--doc-id", old).returncode == 0
    result = setup_record("--doc-id", old, orchestrator_session="session_01xyzxyz")
    assert result.returncode == 1
    assert (f"status-record: '--doc-id' is '{old}' but the document id of this record is "
            "'tkcs-lab-devflow--setup--01xyzxyz'") in result.stdout


def test_owns_doc_id():
    for good in ("p", "p--run--x", "p--deps", "p--make-plan--abcdefgh"):
        assert REC.owns_doc_id("p", good), good
    for bad in ("p--run--", "p--run", "p--nope--abcdefgh", "q--run--x", "p--deps--a--b", "p--run--a--b", "",
                "P--run--x", "p--run--" + "x" * 93):
        assert not REC.owns_doc_id("p", bad), bad
    assert len("p--run--" + "x" * 93) == 101


def test_record_id_cli():
    repo = ["--repo", "tkcs-lab/tkcs-lab-devflow"]
    ok = record_id(*repo, "--run", "--plan-slug", "stale-needs-you-cards")
    assert (ok.returncode, ok.stdout) == (0, "tkcs-lab-devflow--run--stale-needs-you-cards\n")
    ok = record_id(*repo, "--command", "make-plan", "--session", SESSION)
    assert (ok.returncode, ok.stdout) == (0, "tkcs-lab-devflow--make-plan--efghijkl\n")
    ok = record_id(*repo, "--command", "deps", "--unattended")
    assert (ok.returncode, ok.stdout) == (0, "tkcs-lab-devflow--deps\n")
    for args in (
        [*repo, "--run"],
        [*repo, "--command", "x"],
        [*repo, "--command", "make-plan"],
        [*repo, "--run", "--command", "make-plan"],
        [*repo, "--command", "make-plan", "--session", SESSION, "--unattended"],
        ["--repo", "no-slash", "--command", "deps", "--unattended"],
        [*repo, "--command", "nope", "--unattended"],
        [*repo, "--command", "make-plan", "--session", "abc"],
        [*repo],
    ):
        bad = record_id(*args)
        assert bad.returncode == 1 and bad.stdout == "" and bad.stderr.startswith("status-record: "), (args, bad.stderr)


def window_over(version):
    return tuple(int(x) for x in version.split(".")[:3]) >= (1, 2, 0)


def test_version_compare_reads_two_digit_parts():
    assert window_over("1.10.0") and window_over("1.2.0") and window_over("2.0.0")
    assert not window_over("1.1.9") and not window_over("1.0.0")


def test_legacy_window_ends():
    assert REC.LEGACY_UNTIL == "1.2.0"
    assert not window_over(tld.__version__), "remove LEGACY_UNTIL and legacy_ids from tld.board.record"
