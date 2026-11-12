import tld.board.stale as stale

NOW = stale.parse("2026-11-09T12:00:00Z")


def doc(doc_id, **changes):
    data = {"kind": "run", "command": None, "project": "p", "attended": True, "status": "running",
            "needs_you": True, "updated_at": "2026-11-06T12:00:00Z"}
    data.update(changes)
    return {"id": doc_id, "data": data}


def test_a_legacy_record_with_needs_you_is_listed_after_24_hours():
    assert stale.legacy_stale(doc("p"), NOW)


def test_a_legacy_record_updated_an_hour_ago_is_kept():
    assert not stale.legacy_stale(doc("p", updated_at="2026-11-09T11:00:00Z"), NOW)


def test_a_new_key_record_with_needs_you_is_never_listed():
    assert not stale.legacy_stale(doc("p--run--some-plan"), NOW)


def test_an_unattended_command_with_needs_you_is_never_listed():
    entry = doc("p--deps", kind="command", command="deps", attended=False)
    assert not stale.legacy_stale(entry, NOW)


def test_an_unattended_record_is_not_listed_after_24_hours():
    entry = doc("p--deps", kind="command", command="deps", attended=False, needs_you=False,
                updated_at="2026-11-08T08:00:00Z")
    assert stale.section(entry["data"], NOW) != "hidden"
    assert not stale.legacy_stale(entry, NOW)
