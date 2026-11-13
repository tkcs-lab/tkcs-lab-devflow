import tld.board.stale as stale

NOW = stale.parse("2026-11-09T12:00:00Z")


def doc(doc_id, **changes):
    data = {"kind": "run", "command": None, "project": "p", "attended": True, "status": "running",
            "needs_you": True, "updated_at": "2026-11-06T12:00:00Z"}
    data.update(changes)
    return {"id": doc_id, "data": data}


def test_a_record_with_needs_you_is_never_hidden_by_age_alone():
    assert stale.section(doc("p--run--some-plan")["data"], NOW) == "needs_you"


def test_an_unattended_record_is_not_hidden_after_24_hours():
    entry = doc("p--deps", kind="command", command="deps", attended=False, needs_you=False,
                updated_at="2026-11-08T08:00:00Z")
    assert stale.section(entry["data"], NOW) != "hidden"
