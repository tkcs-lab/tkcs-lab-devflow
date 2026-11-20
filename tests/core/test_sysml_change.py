"""The architecture change overlay, its semantic diff and the archive plan (tld.sysml.change, tld.sysml.diff)."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import pytest

from tld.sysml import change as ch
from tld.sysml.diff import Change, diff
from tld.sysml.files import load_tree, sha256_text
from tld.sysml.model import build
from tld.sysml.types import Finding, ModelError

API = "package Core {\n  part def Api { doc /* the api */ }\n}\n"
DB = "package Data {\n  part def Db { doc /* the database */ }\n}\n"
API2 = "package Core {\n  part def Api { doc /* the new api */ }\n}\n"
NEW = "package Extra {\n  part def Cache { doc /* a cache */ }\n}\n"
GOOD_PROPOSAL = "# x\n\n## Why\n\nBecause.\n\n## What Changes\n\nThe api doc.\n\n## Impact\n\nNone.\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "sysml/model/core").mkdir(parents=True)
    (tmp_path / "sysml/model/core/api.sysml").write_text(API)
    (tmp_path / "sysml/model/core/db.sysml").write_text(DB)
    return tmp_path


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            out[rel] = "link" if p.is_symlink() else ("dir" if p.is_dir() else p.read_text())
    return out


def base_json(files: dict | None = None, removed: dict | None = None, **extra) -> str:
    data = {"schema": 1, "files": files or {}, "removed": removed or {}}
    data.update(extra)
    return json.dumps(data)


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def make_change(root: Path, cid: str = "x", overlay: dict | None = None, files: dict | None = None,
                removed: dict | None = None, proposal: str | None = GOOD_PROPOSAL) -> None:
    c = f"sysml/changes/{cid}"
    for rel, text in (overlay or {}).items():
        write(root, f"{c}/model/{rel}", text)
    if proposal is not None:
        write(root, f"{c}/proposal.md", proposal)
    write(root, f"{c}/base.json", base_json(files, removed))
    (root / c).mkdir(parents=True, exist_ok=True)


def check(root: Path, cid: str = "x"):
    return ch.check_change(root, cid, load_tree(root))


# --- ids -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["A", "a--b", "-a", "a_b", "", "a b", "a/b", "x" * 101, "a\n"])
def test_valid_id_refuses(bad):
    with pytest.raises(ModelError, match="invalid id .*: use lower-case words joined by hyphens"):
        ch.valid_id(bad)


def test_valid_id_archive_is_reserved():
    with pytest.raises(ModelError, match="^'archive' is reserved$"):
        ch.valid_id("archive")


def test_valid_id_accepts():
    assert ch.valid_id("add-cache-2") == "add-cache-2"


def test_invalid_id_message_is_escaped():
    with pytest.raises(ModelError) as exc:
        ch.valid_id("a\x1b[31m")
    assert "\x1b" not in str(exc.value)


# --- new_change ------------------------------------------------------------------------------------------


def test_new_change_creates_skeleton_copy_and_hash(repo):
    assert ch.new_change(repo, "x", ["core/api.sysml"], []) == "created"
    assert (repo / "sysml/changes/x/proposal.md").read_text() == (
        "# x\n\n## Why\n\nTODO\n\n## What Changes\n\nTODO\n\n## Impact\n\nTODO\n\n")
    assert (repo / "sysml/changes/x/model/core/api.sysml").read_text() == API
    assert json.loads((repo / "sysml/changes/x/base.json").read_text()) == {
        "schema": 1, "files": {"core/api.sysml": sha256_text(API)}, "removed": {}}


def test_new_change_is_repeatable_and_only_adds(repo):
    ch.new_change(repo, "x", ["core/api.sysml"], [])
    (repo / "sysml/changes/x/model/core/api.sysml").write_text(API2)
    (repo / "sysml/changes/x/proposal.md").write_text(GOOD_PROPOSAL)
    assert ch.new_change(repo, "x", ["core/api.sysml", "core/db.sysml"], []) == "updated"
    assert (repo / "sysml/changes/x/model/core/api.sysml").read_text() == API2
    assert (repo / "sysml/changes/x/proposal.md").read_text() == GOOD_PROPOSAL
    assert (repo / "sysml/changes/x/model/core/db.sysml").read_text() == DB
    files = json.loads((repo / "sysml/changes/x/base.json").read_text())["files"]
    assert files == {"core/api.sysml": sha256_text(API), "core/db.sysml": sha256_text(DB)}


def test_new_change_records_a_removal(repo):
    ch.new_change(repo, "x", [], ["core/db.sysml"])
    data = json.loads((repo / "sysml/changes/x/base.json").read_text())
    assert data["removed"] == {"core/db.sysml": sha256_text(DB)}
    assert not (repo / "sysml/changes/x/model").exists()


def test_new_change_refuses_unknown_file(repo):
    with pytest.raises(ModelError, match="^model file core/nope.sysml does not exist$"):
        ch.new_change(repo, "x", ["core/nope.sysml"], [])
    with pytest.raises(ModelError, match="^model file core/nope.sysml does not exist$"):
        ch.new_change(repo, "x", [], ["core/nope.sysml"])
    assert not (repo / "sysml/changes").exists()


def test_new_change_refuses_replace_and_remove_of_one_file(repo):
    with pytest.raises(ModelError, match="^core/api.sysml cannot be both replaced and removed$"):
        ch.new_change(repo, "x", ["core/api.sysml"], ["core/api.sysml"])
    ch.new_change(repo, "x", ["core/api.sysml"], [])
    with pytest.raises(ModelError, match="cannot be both replaced and removed"):
        ch.new_change(repo, "x", [], ["core/api.sysml"])
    assert "core/api.sysml" not in json.loads((repo / "sysml/changes/x/base.json").read_text())["removed"]


def test_new_change_refuses_invalid_names_and_ids(repo):
    with pytest.raises(ModelError, match="invalid file"):
        ch.new_change(repo, "x", ["../x.sysml"], [])
    with pytest.raises(ModelError, match="invalid id"):
        ch.new_change(repo, "A", [], [])
    with pytest.raises(ModelError, match="reserved"):
        ch.new_change(repo, "archive", [], [])
    assert not (repo / "sysml/changes").exists()


def test_new_change_needs_model_files(tmp_path):
    with pytest.raises(ModelError, match=r"^no model files under sysml/model \(run the sysml command's init first\)$"):
        ch.new_change(tmp_path, "x", [], [])


def test_new_change_refuses_a_preexisting_symlink_copy(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "target.sysml"
    outside.write_text("untouched")
    (repo / "sysml/changes/x/model/core").mkdir(parents=True)
    (repo / "sysml/changes/x/model/core/api.sysml").symlink_to(outside)
    before = snapshot(repo)
    with pytest.raises(ModelError, match="path 'sysml/changes/x/model/core/api.sysml' is a symbolic link"):
        ch.new_change(repo, "x", ["core/api.sysml"], [])
    assert outside.read_text() == "untouched"
    assert snapshot(repo) == before
    assert not (repo / "sysml/changes/x/base.json").exists()


def test_new_change_refuses_symlinked_changes_dir(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (repo / "sysml/changes").symlink_to(outside)
    with pytest.raises(ModelError, match="path 'sysml/changes' is a symbolic link"):
        ch.new_change(repo, "x", ["core/api.sysml"], [])
    assert list(outside.iterdir()) == []


def test_new_change_partial_failure_checks_before_writing(repo, tmp_path_factory):
    # the second file's copy is a link: nothing of the first may be written
    outside = tmp_path_factory.mktemp("outside") / "t.sysml"
    outside.write_text("untouched")
    (repo / "sysml/changes/x/model/core").mkdir(parents=True)
    (repo / "sysml/changes/x/model/core/db.sysml").symlink_to(outside)
    before = snapshot(repo)
    with pytest.raises(ModelError, match="symbolic link"):
        ch.new_change(repo, "x", ["core/api.sysml", "core/db.sysml"], [])
    assert snapshot(repo) == before


def test_new_change_refuses_invalid_base_json(repo):
    write(repo, "sysml/changes/x/base.json", "{not json")
    with pytest.raises(ModelError, match="base.json is invalid"):
        ch.new_change(repo, "x", ["core/api.sysml"], [])


# --- check_change: change-level findings -----------------------------------------------------------------


C = "sysml/changes/x"


def test_clean_change_has_no_findings(repo):
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)})
    composed, model, findings = check(repo)
    assert findings == []
    assert composed["core/api.sysml"] == API2 and composed["core/db.sysml"] == DB
    assert model is not None and "Core::Api" in model.index


def test_missing_and_todo_sections(repo):
    proposal = "# x\n\n## Why\n\nTODO\n\n## Impact\n\n\n"
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)}, proposal=proposal)
    _, _, findings = check(repo)
    assert findings == [
        Finding(f"{C}/proposal.md", 1, "missing section '## What Changes'"),
        Finding(f"{C}/proposal.md", 3, "section '## Why' is empty or still TODO"),
        Finding(f"{C}/proposal.md", 7, "section '## Impact' is empty or still TODO"),
    ]


def test_missing_proposal_gives_one_finding_per_heading(repo):
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)}, proposal=None)
    _, _, findings = check(repo)
    assert findings == [Finding(f"{C}/proposal.md", 1, f"missing section '{h}'") for h in
                        ("## Impact", "## What Changes", "## Why")]


def test_subheading_belongs_to_its_section(repo):
    proposal = "## Why\n\n### Detail\n\ntext\n\n## What Changes\n\nx\n\n## Impact\n\ny\n"
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)}, proposal=proposal)
    assert check(repo)[2] == []


def test_changes_nothing(repo):
    make_change(repo)
    _, _, findings = check(repo)
    assert findings == [Finding(f"{C}/base.json", 1, "change 'x' changes nothing")]


def test_overlay_file_that_exists_must_be_listed(repo):
    make_change(repo, overlay={"core/api.sysml": API2})
    _, _, findings = check(repo)
    assert findings == [Finding(
        f"{C}/base.json", 1,
        "core/api.sysml is in the change but exists in the model; list it with new-change --file")]


def test_new_overlay_file_needs_no_base_entry(repo):
    make_change(repo, overlay={"extra.sysml": NEW})
    composed, model, findings = check(repo)
    assert findings == [] and "extra.sysml" in composed and "Extra::Cache" in model.index


def test_listed_file_missing_from_change(repo):
    make_change(repo, files={"core/api.sysml": sha256_text(API)}, removed={"core/db.sysml": sha256_text(DB)})
    _, _, findings = check(repo)
    assert findings == [Finding(f"{C}/base.json", 1, "core/api.sysml is listed in base.json but missing from the change")]


def test_replaced_base_changed_gives_changed_since(repo):
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text("old")})
    _, _, findings = check(repo)
    assert findings == [Finding(
        f"{C}/base.json", 1,
        f"core/api.sysml changed since the change was written; delete {C}/model/core/api.sysml and its entry in "
        "base.json, run new-change --file core/api.sysml and apply your edit again")]


def test_replaced_base_deleted_from_model_gives_changed_since(repo):
    make_change(repo, overlay={"core/gone.sysml": NEW}, files={"core/gone.sysml": sha256_text("old")})
    _, _, findings = check(repo)
    assert [f.message.split(" changed since")[0] for f in findings] == ["core/gone.sysml"]
    assert all(f.file == f"{C}/base.json" and f.line == 1 for f in findings)


def test_removed_base_changed_gives_changed_since(repo):
    make_change(repo, removed={"core/db.sysml": sha256_text("old")})
    _, _, findings = check(repo)
    assert findings == [Finding(
        f"{C}/base.json", 1,
        "core/db.sysml changed since the change was written; delete its entry in base.json and run "
        "new-change --remove core/db.sysml again")]


def test_removed_base_deleted_from_model_gives_changed_since(repo):
    make_change(repo, removed={"core/gone.sysml": sha256_text("old")})
    _, _, findings = check(repo)
    assert findings == [Finding(
        f"{C}/base.json", 1,
        "core/gone.sysml changed since the change was written; delete its entry in base.json and run "
        "new-change --remove core/gone.sysml again")]


def test_base_json_replace_and_remove_same_file(repo):
    make_change(repo, overlay={"core/api.sysml": API2},
                files={"core/api.sysml": sha256_text(API)}, removed={"core/api.sysml": sha256_text(API)})
    _, _, findings = check(repo)
    assert Finding(f"{C}/base.json", 1, "core/api.sysml cannot be both replaced and removed") in findings
    assert [f for f in findings if "cannot be both" in f.message] == [
        Finding(f"{C}/base.json", 1, "core/api.sysml cannot be both replaced and removed")]


def test_removed_file_with_overlay_copy_is_both(repo):
    make_change(repo, overlay={"core/db.sysml": DB}, removed={"core/db.sysml": sha256_text(DB)})
    _, _, findings = check(repo)
    assert Finding(f"{C}/base.json", 1, "core/db.sysml cannot be both replaced and removed") in findings


HEX = "a" * 64


@pytest.mark.parametrize("section", ["files", "removed"])
@pytest.mark.parametrize("entry", [
    {"../x.sysml": HEX}, {"/abs.sysml": HEX}, {"A.sysml": HEX}, {"a/../b.sysml": HEX}, {"x.txt": HEX},
    {"core/api.sysml": "abc"}, {"core/api.sysml": "A" * 64}, {"core/api.sysml": "a" * 63},
    {"core/api.sysml": 1}, ["core/api.sysml"],
])
def test_base_json_rejects_bad_keys_and_shapes(repo, section, entry):
    data = {"schema": 1, "files": {}, "removed": {}}
    data[section] = entry
    write(repo, f"{C}/base.json", json.dumps(data))
    write(repo, f"{C}/proposal.md", GOOD_PROPOSAL)
    before = snapshot(repo)
    composed, model, findings = check(repo)
    assert findings == [Finding(f"{C}/base.json", 1, "base.json is missing or invalid")]
    assert model is None
    assert snapshot(repo) == before


@pytest.mark.parametrize("text", [
    "{not json", "[]", "null", '{"files": {}, "removed": {}}', '{"schema": 2, "files": {}, "removed": {}}',
    '{"schema": true, "files": {}, "removed": {}}', '{"schema": "1", "files": {}, "removed": {}}',
    '{"schema": 1, "removed": {}}', '{"schema": 1, "files": {}}', "[" * 5000,
])
def test_base_json_rejects_bad_documents(repo, text):
    write(repo, f"{C}/base.json", text)
    write(repo, f"{C}/proposal.md", GOOD_PROPOSAL)
    before = snapshot(repo)
    _, model, findings = check(repo)
    assert findings == [Finding(f"{C}/base.json", 1, "base.json is missing or invalid")]
    assert model is None
    assert snapshot(repo) == before


def test_base_json_missing(repo):
    write(repo, f"{C}/proposal.md", GOOD_PROPOSAL)
    _, model, findings = check(repo)
    assert findings == [Finding(f"{C}/base.json", 1, "base.json is missing or invalid")] and model is None


def test_invalid_base_json_gives_only_base_and_proposal_findings(repo):
    write(repo, f"{C}/base.json", "x")
    write(repo, f"{C}/model/core/api.sysml", "this is not sysml")
    write(repo, f"{C}/proposal.md", "# x\n")
    _, model, findings = check(repo)
    assert model is None
    assert {f.file for f in findings} == {f"{C}/base.json", f"{C}/proposal.md"}
    assert len(findings) == 4


@pytest.mark.parametrize("name", ["Evil.sysml", "notes.txt", "a b.sysml"])
def test_overlay_file_with_invalid_name_is_refused(repo, name):
    make_change(repo, overlay={name: API2}, files={})
    with pytest.raises(ModelError, match="invalid file"):
        check(repo)


def test_missing_change_is_a_model_error(repo):
    with pytest.raises(ModelError, match="^change 'nope' does not exist$"):
        check(repo, "nope")
    with pytest.raises(ModelError, match="invalid id"):
        check(repo, "../x")
    with pytest.raises(ModelError, match="reserved"):
        check(repo, "archive")


@pytest.mark.parametrize("victim", ["overlay", "base.json", "proposal.md", "model", "change"])
def test_check_change_refuses_any_symlink_under_change(repo, tmp_path_factory, victim):
    canary = tmp_path_factory.mktemp("outside")
    (canary / "f").write_text("canary")
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)})
    c = repo / C
    if victim == "overlay":
        (c / "model/core/api.sysml").unlink()
        (c / "model/core/api.sysml").symlink_to(canary / "f")
    elif victim == "change":
        (repo / "moved").mkdir()
        os.rename(c, repo / "moved/x")
        c.symlink_to(repo / "moved/x")
    elif victim == "model":
        os.rename(c / "model", repo / "moved-model")
        (c / "model").symlink_to(repo / "moved-model")
    else:
        (c / victim).unlink()
        (c / victim).symlink_to(canary / "f")
    with pytest.raises(ModelError, match="symbolic link"):
        check(repo)
    assert (canary / "f").read_text() == "canary"


def test_oversize_overlay_file_is_refused(repo):
    make_change(repo, overlay={"big.sysml": "x" * 100001})
    with pytest.raises(ModelError, match="is longer than 100000 bytes"):
        check(repo)


# --- check_change: the composed model --------------------------------------------------------------------


def test_composed_model_of_replace_add_and_remove(repo):
    make_change(
        repo, overlay={"core/api.sysml": API2, "extra.sysml": NEW},
        files={"core/api.sysml": sha256_text(API)}, removed={"core/db.sysml": sha256_text(DB)})
    composed, model, findings = check(repo)
    assert findings == []
    assert sorted(composed) == ["core/api.sysml", "extra.sysml"]
    assert set(model.index) == {"Core", "Core::Api", "Extra", "Extra::Cache"}
    old, _ = build(load_tree(repo))
    assert [str(c) for c in diff(old, model)] == [
        "changed part def Core::Api", "removed package Data", "removed part def Data::Db",
        "added package Extra", "added part def Extra::Cache"]


def test_composed_findings_carry_the_right_prefix(repo):
    bad = "package Core {\n  part def Api { }\n}\n"
    other = "package Extra {\n  part def Other { doc /* x */ }\n  part def Api2 { }\n}\n"
    make_change(repo, overlay={"core/api.sysml": bad, "extra.sysml": other},
                files={"core/api.sysml": sha256_text(API)}, removed={"core/db.sysml": sha256_text(DB)})
    _, _, findings = check(repo)
    assert findings == [
        Finding(f"{C}/model/core/api.sysml", 2, "part def 'Core::Api' needs a doc"),
        Finding(f"{C}/model/extra.sysml", 3, "part def 'Extra::Api2' needs a doc"),
    ]


def test_composed_findings_of_untouched_files_use_the_model_prefix(repo):
    write(repo, "sysml/model/core/db.sysml", "package Data {\n  part def Db { }\n}\n")  # invalid doc, kept as is
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)})
    _, _, findings = check(repo)
    assert findings == [Finding("sysml/model/core/db.sysml", 2, "part def 'Data::Db' needs a doc")]


def test_check_change_writes_nothing(repo):
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)})
    before = snapshot(repo)
    check(repo)
    assert snapshot(repo) == before


# --- diff ------------------------------------------------------------------------------------------------


def model_of(text: str, rel: str = "m.sysml"):
    model, findings = build({rel: text})
    assert findings == []
    return model


BASE_M = """package P {
  port def Pd;
  part def A { doc /* a */ port p : Pd; }
  part def B { doc /* b */ }
}
"""


def test_diff_of_equal_models_is_empty():
    assert diff(model_of(BASE_M), model_of(BASE_M)) == []


def test_diff_added_removed_changed_ordered_by_qname():
    new = """package P {
  port def Pd;
  part def A { doc /* a changed */ port p : Pd; }
  part def C { doc /* c */ }
}
"""
    assert diff(model_of(BASE_M), model_of(new)) == [
        Change("changed", "part def", "P::A"),
        Change("removed", "part def", "P::B"),
        Change("added", "part def", "P::C"),
    ]
    assert str(diff(model_of(BASE_M), model_of(new))[0]) == "changed part def P::A"


def test_diff_type_edit_is_a_change():
    old = "package P {\n  port def X;\n  port def Y;\n  part def A { doc /* a */ port p : X; }\n}\n"
    new = old.replace("p : X", "p : Y")
    assert diff(model_of(old), model_of(new)) == [Change("changed", "port", "P::A::p")]


def test_diff_owner_move_is_removed_plus_added():
    old = "package P {\n  part def A { doc /* a */ }\n}\npackage Q { }\n"
    new = "package P { }\npackage Q {\n  part def A { doc /* a */ }\n}\n"
    assert diff(model_of(old), model_of(new)) == [
        Change("removed", "part def", "P::A"), Change("added", "part def", "Q::A")]


def test_diff_dependency_and_connect_end_edits_are_remove_plus_add():
    old = """package P {
  port def Pd;
  part def A { doc /* a */ port p : Pd; }
  part def B { doc /* b */ port q : Pd; }
  part def C { doc /* c */ part a : A; part b : B; connect a.p to b.q; }
  dependency from A to B;
}
"""
    new = old.replace("dependency from A to B;", "dependency from A to C;").replace(
        "connect a.p to b.q;", "connect b.q to a.p;")
    assert diff(model_of(old), model_of(new)) == [
        Change("removed", "connect", "P::C::connect(a.p-b.q)"),
        Change("added", "connect", "P::C::connect(b.q-a.p)"),
        Change("removed", "dependency", "P::dependency(A->B)"),
        Change("added", "dependency", "P::dependency(A->C)"),
    ]


# --- archive_plan ----------------------------------------------------------------------------------------

TODAY = datetime.date(2026, 11, 20)


def test_archive_plan_lists_writes_deletes_and_destination(repo):
    make_change(repo, overlay={"core/api.sysml": API2, "extra.sysml": NEW},
                files={"core/api.sysml": sha256_text(API)}, removed={"core/db.sysml": sha256_text(DB)})
    base = load_tree(repo)
    composed, _, findings = ch.check_change(repo, "x", base)
    assert findings == []
    plan = ch.archive_plan(repo, "x", TODAY, composed, base)
    assert plan == ch.ArchivePlan(composed, ("core/api.sysml", "extra.sysml"), ("core/db.sysml",),
                                  "sysml/changes/archive/2026-11-20-x")


def test_archive_plan_skips_unchanged_files(repo):
    base = load_tree(repo)
    plan = ch.archive_plan(repo, "x", TODAY, dict(base), base)
    assert plan.write == () and plan.delete == ()


def test_archive_plan_refuses_an_existing_destination(repo):
    (repo / "sysml/changes/archive/2026-11-20-x").mkdir(parents=True)
    base = load_tree(repo)
    with pytest.raises(ModelError, match="^path 'sysml/changes/archive/2026-11-20-x' already exists$"):
        ch.archive_plan(repo, "x", TODAY, dict(base), base)


def test_archive_plan_refuses_a_symlinked_archive_dir(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (repo / "sysml/changes").mkdir()
    (repo / "sysml/changes/archive").symlink_to(outside)
    base = load_tree(repo)
    with pytest.raises(ModelError, match="path 'sysml/changes/archive' is a symbolic link"):
        ch.archive_plan(repo, "x", TODAY, dict(base), base)


def test_archive_plan_refuses_bad_id_and_names(repo):
    base = load_tree(repo)
    with pytest.raises(ModelError, match="reserved"):
        ch.archive_plan(repo, "archive", TODAY, dict(base), base)
    with pytest.raises(ModelError, match="invalid file"):
        ch.archive_plan(repo, "x", TODAY, {"../evil.sysml": ""}, base)


def test_archive_plan_writes_nothing(repo):
    make_change(repo, overlay={"core/api.sysml": API2}, files={"core/api.sysml": sha256_text(API)})
    base = load_tree(repo)
    before = snapshot(repo)
    composed, _, _ = ch.check_change(repo, "x", base)
    ch.archive_plan(repo, "x", TODAY, composed, base)
    assert snapshot(repo) == before
