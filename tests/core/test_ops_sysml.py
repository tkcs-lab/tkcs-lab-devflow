"""tld ops sysml: the four-subcommand wrapper (checks, check, render, archive, new-change; hostile inputs)."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import BIN, FIXTURES
from tld.ops import sysml
from tld.sysml import change as ch
from tld.sysml import files

VALID = FIXTURES / "sysml" / "valid"
API = "package Core {\n  part def Api { doc /* the api */ }\n}\n"
DB = "package Data {\n  part def Db { doc /* the database */ }\n}\n"
API2 = "package Core {\n  part def Api { doc /* the new api */ }\n}\n"
NEW = "package Extra {\n  part def Cache { doc /* a cache */ }\n}\n"
PROPOSAL = "# x\n\n## Why\n\nBecause.\n\n## What Changes\n\nThe api doc.\n\n## Impact\n\nNone.\n"
DATE = datetime.date(2026, 1, 2)
MSG = "tld ops sysml: "


def write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)


def make_repo(root: Path, models: dict[str, str] | None = None, profile: str | None = "sysml:\n  subset: 1\n") -> Path:
    if profile is not None:
        write(root, ".tld/toolkit.yaml", profile)
    for rel, text in (models if models is not None else {"core/api.sysml": API, "core/db.sysml": DB}).items():
        write(root, f"sysml/model/{rel}", text)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo")


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(sysml, "_today", lambda: DATE)


def run(root: Path, *args: str, capsys) -> tuple[int, str, str]:
    capsys.readouterr()
    code = sysml.main([*args, "--root", str(root)])
    out = capsys.readouterr()
    return code, out.out, out.err


def snapshot(root: Path) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    for p in sorted(root.rglob("*")):
        out[str(p.relative_to(root))] = None if p.is_dir() else p.read_bytes()
    return out


def start_change(repo: Path, capsys, id: str = "x") -> None:
    assert run(repo, "new-change", id, "--file", "core/api.sysml", capsys=capsys)[0] == 0
    write(repo, f"sysml/changes/{id}/model/core/api.sysml", API2)
    write(repo, f"sysml/changes/{id}/proposal.md", PROPOSAL)


# ---- the checks before anything runs -------------------------------------------------------------------------

@pytest.mark.parametrize("args,line", [
    (["archive", "archive"], MSG + "'archive' is reserved"),
    (["archive", "Bad"], MSG + "invalid id 'Bad': use lower-case words joined by hyphens"),
    (["new-change", "a--b"], MSG + "invalid id 'a--b': use lower-case words joined by hyphens"),
    (["check", "--change", "x\ny"], MSG + "invalid id 'x\\ny': use lower-case words joined by hyphens"),
    (["check", "--change", "archive"], MSG + "'archive' is reserved"),
    (["new-change", "x", "--file", "A.sysml"], MSG + "invalid file 'A.sysml': use a path like core/api.sysml"),
    (["new-change", "x", "--remove", "a/../b.sysml"],
     MSG + "invalid file 'a/../b.sysml': use a path like core/api.sysml"),
    (["new-change", "x", "--file", "a\x1b[31m.sysml"],
     MSG + "invalid file 'a\\x1b[31m.sysml': use a path like core/api.sysml"),
])
def test_bad_arguments_exit_2(repo, capsys, args, line):
    before = snapshot(repo)
    code, out, err = run(repo, *args, capsys=capsys)
    assert (code, out, err) == (2, "", line + "\n")
    assert snapshot(repo) == before


def test_no_profile(tmp_path, capsys):
    root = make_repo(tmp_path / "r", profile=None)
    code, out, err = run(root, "check", capsys=capsys)
    assert code == 2 and out == ""
    assert err == f"{MSG}profile not found: {root / '.tld/toolkit.yaml'}\n"


def test_explicit_profile_path(tmp_path, capsys):
    root = make_repo(tmp_path / "r", profile=None)
    write(tmp_path, "other.yaml", "sysml:\n  subset: 1\n")
    code, out, _ = run(root, "check", "--profile", str(tmp_path / "other.yaml"), capsys=capsys)
    assert code == 0 and out == "sysml: ok (4 elements)\n"


@pytest.mark.parametrize("profile", ["profile: {}\n", "sysml: {}\n", "sysml: 3\n", ": : :\n\t- [", "", "- a\n"])
def test_no_sysml_block(tmp_path, capsys, profile):
    root = make_repo(tmp_path / "r", profile=profile)
    code, out, err = run(root, "check", capsys=capsys)
    assert (code, out) == (2, "")
    assert err == "toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)\n"


@pytest.mark.parametrize("value,shown", [("2", "2"), ("true", "True"), ("'1'", "'1'"), ("1.0", "1.0"), ("null", "None")])
def test_subset_must_be_the_integer_1(tmp_path, capsys, value, shown):
    root = make_repo(tmp_path / "r", profile=f"sysml:\n  subset: {value}\n")
    code, out, err = run(root, "check", capsys=capsys)
    assert (code, out, err) == (2, "", f"{MSG}sysml.subset must be 1 (got {shown})\n")


def test_subset_value_is_escaped_and_bounded(tmp_path, capsys):
    root = make_repo(tmp_path / "r", profile='sysml:\n  subset: "\\e[31m' + "x" * 900 + '"\n')
    code, _, err = run(root, "check", capsys=capsys)
    assert code == 2 and "\x1b" not in err and err.count("\n") == 1 and len(err) < 500


@pytest.mark.parametrize("sub", [["check"], ["render"], ["new-change", "x"], ["archive", "x"], ["render", "--check"]])
def test_no_model_files_exit_2(tmp_path, capsys, sub):
    root = make_repo(tmp_path / "r", models={})
    code, out, err = run(root, *sub, capsys=capsys)
    assert (code, out) == (2, "")
    assert err == f"{MSG}no model files under sysml/model (run the sysml command's init first)\n"


@pytest.mark.parametrize("args", [["feedback"], ["init"], ["archive", "x", "--force"], ["check", "extra"], ["render", "x"],
                                  ["new-change"], [], ["check", "--bogus"], ["check", "--bogus\x1b[31m"]])
def test_usage_errors_exit_2_and_run_nothing(repo, capsys, args):
    before = snapshot(repo)
    with pytest.raises(SystemExit) as exc:
        sysml.main([*args, "--root", str(repo)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "\x1b" not in err
    assert snapshot(repo) == before


# ---- check ----------------------------------------------------------------------------------------------------

def test_check_ok(repo, capsys):
    assert run(repo, "check", capsys=capsys) == (0, "sysml: ok (4 elements)\n", "")


def test_check_json_ok(repo, capsys):
    code, out, _ = run(repo, "check", "--json", capsys=capsys)
    assert code == 0 and json.loads(out) == {"ok": True, "findings": [], "changes": []}


def test_check_findings_exit_1_and_json_shape(repo, capsys):
    write(repo, "sysml/model/core/api.sysml", "package Core {\n  part def Api { }\n}\n")
    code, out, err = run(repo, "check", capsys=capsys)
    assert (code, err) == (1, "")
    assert out == "sysml/model/core/api.sysml:2: part def 'Core::Api' needs a doc\n"
    code, out, _ = run(repo, "check", "--json", capsys=capsys)
    assert code == 1 and json.loads(out) == {
        "ok": False, "changes": [],
        "findings": [{"file": "sysml/model/core/api.sysml", "line": 2, "message": "part def 'Core::Api' needs a doc"}]}


def test_check_findings_with_hostile_text_are_one_line(repo, capsys):
    write(repo, "sysml/model/core/api.sysml", "package Core {\n  part def A\x1b[31m { }\n}\n")
    code, out, err = run(repo, "check", capsys=capsys)
    assert code == 1 and "\x1b" not in out and err == ""


def test_check_change_prints_findings_then_the_diff(repo, capsys):
    start_change(repo, capsys)
    code, out, err = run(repo, "check", "--change", "x", capsys=capsys)
    assert (code, err) == (0, "")
    assert out == "changed part def Core::Api\nsysml: ok (4 elements)\n"
    code, out, _ = run(repo, "check", "--change", "x", "--json", capsys=capsys)
    assert json.loads(out) == {"ok": True, "findings": [],
                               "changes": [{"op": "changed", "kind": "part def", "qname": "Core::Api"}]}


def test_check_change_findings_exit_1(repo, capsys):
    start_change(repo, capsys)
    write(repo, "sysml/changes/x/proposal.md", "# x\n")
    code, out, _ = run(repo, "check", "--change", "x", capsys=capsys)
    assert code == 1
    assert out.splitlines()[:3] == [f"sysml/changes/x/proposal.md:1: missing section '{h}'"
                                    for h in ("## Impact", "## What Changes", "## Why")]
    assert "sysml: ok" not in out


def test_check_change_missing_change(repo, capsys):
    assert run(repo, "check", "--change", "nope", capsys=capsys) == (2, "", f"{MSG}change 'nope' does not exist\n")


def test_check_change_with_bad_base_json(repo, capsys):
    start_change(repo, capsys)
    write(repo, "sysml/changes/x/base.json", "[1]")
    code, out, _ = run(repo, "check", "--change", "x", capsys=capsys)
    assert code == 1 and out == "sysml/changes/x/base.json:1: base.json is missing or invalid\n"


# ---- new-change -----------------------------------------------------------------------------------------------

def test_new_change_created_then_updated(repo, capsys):
    assert run(repo, "new-change", "x", "--file", "core/api.sysml", capsys=capsys) == (
        0, "created sysml/changes/x\n", "")
    assert (repo / "sysml/changes/x/model/core/api.sysml").read_text() == API
    assert (repo / "sysml/changes/x/proposal.md").read_text() == ch.skeleton("x")
    base = json.loads((repo / "sysml/changes/x/base.json").read_text())
    assert base["files"] == {"core/api.sysml": hashlib.sha256(API.encode()).hexdigest()}
    assert run(repo, "new-change", "x", "--remove", "core/db.sysml", capsys=capsys) == (
        0, "updated sysml/changes/x\n", "")
    base = json.loads((repo / "sysml/changes/x/base.json").read_text())
    assert base["removed"] == {"core/db.sysml": hashlib.sha256(DB.encode()).hexdigest()}


def test_new_change_missing_file_and_conflict(repo, capsys):
    assert run(repo, "new-change", "x", "--file", "core/zzz.sysml", capsys=capsys) == (
        2, "", f"{MSG}model file core/zzz.sysml does not exist\n")
    assert run(repo, "new-change", "x", "--file", "core/api.sysml", "--remove", "core/api.sysml", capsys=capsys) == (
        2, "", f"{MSG}core/api.sysml cannot be both replaced and removed\n")
    assert not (repo / "sysml/changes").exists()


# ---- render ---------------------------------------------------------------------------------------------------

def test_render_writes_both_files_and_check_follows(repo, capsys):
    assert run(repo, "render", capsys=capsys) == (0, "wrote docs/architecture.svg\nwrote docs/architecture.md\n", "")
    assert (repo / "docs/architecture.svg").read_text().startswith(sysml.svg.STAMP + "\n")
    assert (repo / "docs/architecture.md").read_text().startswith("# Architecture\n")
    assert run(repo, "render", "--check", capsys=capsys) == (0, "sysml: docs up to date\n", "")


def test_render_check_out_of_date_missing_and_other_layout(repo, capsys):
    run(repo, "render", capsys=capsys)
    with (repo / "docs/architecture.md").open("a") as fh:
        fh.write("edited\n")
    (repo / "docs/architecture.svg").unlink()
    code, out, _ = run(repo, "render", "--check", capsys=capsys)
    assert code == 1 and out == ("docs/architecture.svg is missing: run tld ops sysml render\n"
                                 "docs/architecture.md is out of date: run tld ops sysml render\n")
    run(repo, "render", capsys=capsys)
    for rel in ("docs/architecture.svg", "docs/architecture.md"):
        p = repo / rel
        p.write_text(p.read_text().replace("layout 1;", "layout 7;"))
    code, out, _ = run(repo, "render", "--check", capsys=capsys)
    assert code == 1 and out == (
        "docs/architecture.svg was rendered by layout 7, this tld renders layout 1: run tld ops sysml render\n"
        "docs/architecture.md was rendered by layout 7, this tld renders layout 1: run tld ops sysml render\n")


def test_render_check_without_stamp_is_out_of_date(repo, capsys):
    run(repo, "render", capsys=capsys)
    (repo / "docs/architecture.svg").write_text("<svg/>")
    code, out, _ = run(repo, "render", "--check", capsys=capsys)
    assert code == 1 and out == "docs/architecture.svg is out of date: run tld ops sysml render\n"


def test_render_with_a_finding_writes_nothing(repo, capsys):
    write(repo, "sysml/model/core/api.sysml", "package Core {\n  part def Api { }\n}\n")
    code, out, _ = run(repo, "render", capsys=capsys)
    assert code == 1 and "needs a doc" in out
    assert not (repo / "docs").exists()
    code, out, _ = run(repo, "render", "--check", capsys=capsys)
    assert code == 1 and "needs a doc" in out and "docs/architecture" not in out


def test_render_over_the_element_limit_is_a_finding_and_draws_nothing(tmp_path, capsys):
    many = "package P {\n" + "".join(f"  part def D{i} {{ doc /* d */ }}\n" for i in range(301)) + "}\n"
    root = make_repo(tmp_path / "r", models={"p.sysml": many})
    code, out, _ = run(root, "render", capsys=capsys)
    assert code == 1 and out == "sysml/model:0: too many elements (limit 300)\n"
    assert not (root / "docs").exists()


def test_render_with_symlinked_docs_writes_nothing(repo, tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary"
    canary.write_text("keep")
    (repo / "docs").symlink_to(outside)
    code, out, err = run(repo, "render", capsys=capsys)
    assert (code, out, err) == (2, "", f"{MSG}path 'docs' is a symbolic link\n")
    assert sorted(p.name for p in outside.iterdir()) == ["canary"] and canary.read_text() == "keep"
    code, _, err = run(repo, "render", "--check", capsys=capsys)
    assert (code, err) == (2, f"{MSG}path 'docs' is a symbolic link\n")


def test_render_with_symlinked_output_writes_nothing(repo, tmp_path, capsys):
    (tmp_path / "victim").write_text("keep")
    (repo / "docs").mkdir()
    (repo / "docs/architecture.svg").symlink_to(tmp_path / "victim")
    code, _, err = run(repo, "render", capsys=capsys)
    assert (code, err) == (2, f"{MSG}path 'docs/architecture.svg' is a symbolic link\n")
    assert (tmp_path / "victim").read_text() == "keep" and not (repo / "docs/architecture.md").exists()


def test_render_with_symlinked_sysml_dir_exits_2(tmp_path, capsys):
    real = make_repo(tmp_path / "real")
    root = tmp_path / "r"
    root.mkdir()
    write(root, ".tld/toolkit.yaml", "sysml:\n  subset: 1\n")
    (root / "sysml").symlink_to(real / "sysml")
    for sub in (["check"], ["render"], ["new-change", "x"], ["archive", "x"]):
        code, out, err = run(root, *sub, capsys=capsys)
        assert (code, out, err) == (2, "", f"{MSG}path 'sysml' is a symbolic link\n")
    assert not (real / "docs").exists()


def test_symlinked_model_file_exits_2(repo, tmp_path, capsys):
    (tmp_path / "evil.sysml").write_text(API)
    (repo / "sysml/model/core/db.sysml").unlink()
    (repo / "sysml/model/core/db.sysml").symlink_to(tmp_path / "evil.sysml")
    code, _, err = run(repo, "check", capsys=capsys)
    assert (code, err) == (2, f"{MSG}path 'sysml/model/core/db.sysml' is a symbolic link\n")


# ---- OSError from the real file system ------------------------------------------------------------------------

def test_oserror_reading_the_model_exits_2(repo, capsys, monkeypatch):
    def boom(*a, **k):
        raise OSError(5, "Input/output error", "sysml/model/core/api.sysml")
    monkeypatch.setattr(files.os, "open", boom)
    for sub in (["check"], ["render"], ["render", "--check"], ["new-change", "x"], ["archive", "x"]):
        code, out, err = run(repo, *sub, capsys=capsys)
        assert code == 2 and out == ""
        assert err == f"{MSG}[Errno 5] Input/output error: 'sysml/model/core/api.sysml'\n"


def test_oserror_listing_the_model_exits_2(repo, capsys, monkeypatch):
    def boom(*a, **k):
        raise PermissionError(13, "Permission denied", "sysml/model")
    monkeypatch.setattr(files.os, "scandir", boom)
    code, out, err = run(repo, "check", capsys=capsys)
    assert (code, out) == (2, "") and err.startswith(MSG) and err.count("\n") == 1 and "Traceback" not in err


def test_oserror_reading_an_existing_output_exits_2(repo, capsys, monkeypatch):
    run(repo, "render", capsys=capsys)
    real = files.read_text

    def boom(root, rel, *a, **k):
        if rel == "docs/architecture.md":
            raise PermissionError(13, "Permission denied", rel)
        return real(root, rel, *a, **k)
    monkeypatch.setattr(sysml.files, "read_text", boom)
    code, out, err = run(repo, "render", "--check", capsys=capsys)
    assert (code, out) == (2, "") and err == f"{MSG}[Errno 13] Permission denied: 'docs/architecture.md'\n"


def test_oserror_message_is_escaped_and_one_line(repo, capsys, monkeypatch):
    def boom(*a, **k):
        raise OSError("bad\nname \x1b[31m" + "y" * 900)
    monkeypatch.setattr(files.os, "scandir", boom)
    code, _, err = run(repo, "check", capsys=capsys)
    assert code == 2 and err.count("\n") == 1 and "\x1b" not in err and len(err) < 500


def test_oserror_in_render_write_exits_2(repo, capsys, monkeypatch):
    def boom(root, rel, text):
        raise PermissionError(13, "Permission denied", rel)
    monkeypatch.setattr(sysml.files, "write_text", boom)
    code, _, err = run(repo, "render", capsys=capsys)
    assert code == 2 and err == f"{MSG}[Errno 13] Permission denied: 'docs/architecture.svg'\n"


# ---- hash seeds and the clock ---------------------------------------------------------------------------------

def generated_model() -> dict[str, str]:
    a = "package Alpha {\n  port def P;\n" + "".join(
        f"  part def A{i} {{ doc /* a{i} */ port p : P; }}\n" for i in range(31)) + "}\n"
    b = "package Beta {\n" + "".join(f"  part def B{i} {{ doc /* b{i} */ }}\n" for i in range(30)) + (
        "  dependency from B0 to Alpha::A0;\n  dependency from B1 to Alpha::A1;\n  dependency from B2 to B3;\n") + "}\n"
    return {"alpha.sysml": a, "beta.sysml": b}


def cli_render(root: Path, seed: str) -> tuple[bytes, bytes]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    r = subprocess.run([sys.executable, str(BIN), "ops", "sysml", "render", "--root", str(root),
                        "--profile", str(root / ".tld/toolkit.yaml")], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return (root / "docs/architecture.svg").read_bytes(), (root / "docs/architecture.md").read_bytes()


@pytest.mark.parametrize("name", ["valid", "generated"])
def test_render_bytes_identical_across_hash_seeds(tmp_path, capsys, name):
    models = ({p.name: p.read_text() for p in sorted(VALID.glob("*.sysml"))} if name == "valid"
              else generated_model())
    root = make_repo(tmp_path / "r", models=models)
    code, _, err = run(root, "check", capsys=capsys)
    assert code == 0, err
    if name == "generated":
        run(root, "render", capsys=capsys)
        assert "The diagram shows packages only" in (root / "docs/architecture.md").read_text()
    run(root, "render", capsys=capsys)
    in_process = ((root / "docs/architecture.svg").read_bytes(), (root / "docs/architecture.md").read_bytes())
    for seed in ("0", "1", "12345"):
        assert cli_render(root, seed) == in_process


def test_render_does_not_depend_on_the_clock(repo, capsys, monkeypatch):
    run(repo, "render", capsys=capsys)
    first = snapshot(repo / "docs")
    for d in (datetime.date(2020, 2, 3), datetime.date(2031, 12, 30)):
        monkeypatch.setattr(sysml, "_today", lambda d=d: d)
        run(repo, "render", capsys=capsys)
        assert snapshot(repo / "docs") == first


# ---- archive --------------------------------------------------------------------------------------------------

def test_full_cycle(repo, capsys):
    run(repo, "render", capsys=capsys)
    start_change(repo, capsys)
    write(repo, "sysml/changes/x/model/extra.sysml", NEW)
    assert run(repo, "check", "--change", "x", capsys=capsys)[0] == 0
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, err) == (0, "")
    assert out == "archived sysml/changes/x to sysml/changes/archive/2026-01-02-x\n"
    assert not (repo / "sysml/changes/x").exists()
    assert (repo / "sysml/changes/archive/2026-01-02-x/proposal.md").read_text() == PROPOSAL
    assert (repo / "sysml/model/core/api.sysml").read_text() == API2
    assert (repo / "sysml/model/extra.sysml").read_text() == NEW
    assert run(repo, "render", "--check", capsys=capsys) == (0, "sysml: docs up to date\n", "")
    assert run(repo, "check", capsys=capsys)[0] == 0
    assert "Cache" in (repo / "docs/architecture.md").read_text()


def test_archive_removes_a_model_file(repo, capsys):
    assert run(repo, "new-change", "gone", "--remove", "core/db.sysml", capsys=capsys)[0] == 0
    write(repo, "sysml/changes/gone/proposal.md", PROPOSAL)
    assert run(repo, "archive", "gone", capsys=capsys)[0] == 0
    assert not (repo / "sysml/model/core/db.sysml").exists() and (repo / "sysml/model/core/api.sysml").exists()
    assert run(repo, "render", "--check", capsys=capsys)[0] == 0


def test_archive_with_findings_writes_nothing(repo, capsys):
    start_change(repo, capsys)
    write(repo, "sysml/changes/x/proposal.md", "# x\n")
    before = snapshot(repo)
    code, out, _ = run(repo, "archive", "x", capsys=capsys)
    assert code == 1 and "missing section" in out
    assert snapshot(repo) == before


def test_archive_missing_change_exit_2(repo, capsys):
    assert run(repo, "archive", "nope", capsys=capsys) == (2, "", f"{MSG}change 'nope' does not exist\n")


def test_archive_with_symlinked_docs_writes_nothing(repo, tmp_path, capsys):
    start_change(repo, capsys)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "docs").symlink_to(outside)
    before = snapshot(repo / "sysml")
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out, err) == (2, "", f"{MSG}path 'docs' is a symbolic link\n")
    assert snapshot(repo / "sysml") == before and list(outside.iterdir()) == []


def test_archive_with_symlinked_changes_archive_writes_nothing(repo, tmp_path, capsys):
    start_change(repo, capsys)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "sysml/changes/archive").symlink_to(outside)
    before = snapshot(repo / "sysml")
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out) == (2, "") and "is a symbolic link" in err and err.startswith(MSG)
    assert snapshot(repo / "sysml") == before and list(outside.iterdir()) == [] and not (repo / "docs").exists()


def test_archive_with_hard_linked_output_writes_nothing(repo, tmp_path, capsys):
    start_change(repo, capsys)
    outside = tmp_path / "outside.md"
    outside.write_text("keep")
    (repo / "docs").mkdir()
    os.link(outside, repo / "docs/architecture.md")
    before = snapshot(repo / "sysml")
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out, err) == (2, "", f"{MSG}path 'docs/architecture.md' has more than one hard link\n")
    assert snapshot(repo / "sysml") == before and outside.read_text() == "keep"
    assert not (repo / "sysml/changes/archive").exists()


def test_archive_with_hard_linked_model_file_writes_nothing(repo, tmp_path, capsys):
    start_change(repo, capsys)
    outside = tmp_path / "outside.sysml"
    outside.write_text(API)
    (repo / "sysml/model/core/api.sysml").unlink()
    os.link(outside, repo / "sysml/model/core/api.sysml")
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out, err) == (2, "", f"{MSG}path 'sysml/model/core/api.sysml' has more than one hard link\n")
    assert outside.read_text() == API and (repo / "sysml/changes/x").is_dir()


def test_archive_oserror_on_output_exits_2_and_rolls_back(repo, capsys, monkeypatch):
    run(repo, "render", capsys=capsys)
    start_change(repo, capsys)
    write(repo, "sysml/changes/x/model/extra.sysml", NEW)
    assert run(repo, "new-change", "x", "--remove", "core/db.sysml", capsys=capsys)[0] == 0
    before = snapshot(repo)
    real = files.write_text

    def boom(root, rel, text):
        if rel == "docs/architecture.svg":
            raise PermissionError(13, "Permission denied", rel)
        return real(root, rel, text)
    monkeypatch.setattr(sysml.files, "write_text", boom)
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out) == (2, "")
    assert err == f"{MSG}[Errno 13] Permission denied: 'docs/architecture.svg'\n"
    after = snapshot(repo)
    # the model and the change folder are exactly as before; only directories made on the way may remain
    assert {k: v for k, v in after.items() if v is not None} == {k: v for k, v in before.items() if v is not None}


def test_archive_failing_move_rolls_the_model_back(repo, capsys, monkeypatch):
    start_change(repo, capsys)
    before = snapshot(repo)

    def boom(root, src, dst):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(sysml.files, "move_dir", boom)
    code, _, err = run(repo, "archive", "x", capsys=capsys)
    assert code == 2 and err == f"{MSG}[Errno 28] No space left on device\n"
    assert snapshot(repo) == before


def test_archive_refuses_bad_base_json_keys_and_leaves_canary(repo, tmp_path, capsys):
    start_change(repo, capsys)
    canary = repo / "README.md"
    canary.write_text("keep")
    base = json.loads((repo / "sysml/changes/x/base.json").read_text())
    base["removed"] = {"../../README.md": "0" * 64}
    write(repo, "sysml/changes/x/base.json", json.dumps(base))
    code, out, _ = run(repo, "archive", "x", capsys=capsys)
    assert code == 1 and out == "sysml/changes/x/base.json:1: base.json is missing or invalid\n"
    assert canary.read_text() == "keep" and (repo / "sysml/model/core/api.sysml").read_text() == API


def test_archive_stale_base_exits_1_and_writes_nothing(repo, capsys):
    start_change(repo, capsys)
    write(repo, "sysml/model/core/api.sysml", API + "// another plan\n")
    before = snapshot(repo)
    code, out, _ = run(repo, "archive", "x", capsys=capsys)
    assert code == 1 and "core/api.sysml changed since the change was written" in out
    assert snapshot(repo) == before and not (repo / "docs").exists()


def test_archive_stale_removed_base_and_deleted_base_file(repo, capsys):
    assert run(repo, "new-change", "x", "--remove", "core/db.sysml", "--file", "core/api.sysml", capsys=capsys)[0] == 0
    write(repo, "sysml/changes/x/proposal.md", PROPOSAL)
    write(repo, "sysml/model/core/db.sysml", DB + "// edited\n")
    before = snapshot(repo)
    code, out, _ = run(repo, "archive", "x", capsys=capsys)
    assert code == 1 and "core/db.sysml changed since the change was written; delete its entry in base.json" in out
    assert snapshot(repo) == before
    write(repo, "sysml/model/core/db.sysml", DB)
    (repo / "sysml/model/core/api.sysml").unlink()
    before = snapshot(repo)
    code, out, _ = run(repo, "archive", "x", capsys=capsys)
    assert code == 1 and "core/api.sysml changed since the change was written" in out
    assert snapshot(repo) == before


def test_archive_destination_exists_exit_2(repo, capsys):
    start_change(repo, capsys)
    (repo / "sysml/changes/archive/2026-01-02-x").mkdir(parents=True)
    before = snapshot(repo)
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out) == (2, "")
    assert err == f"{MSG}path 'sysml/changes/archive/2026-01-02-x' already exists\n"
    assert snapshot(repo) == before


def test_two_plans_changing_one_file_second_archive_is_refused(repo, capsys):
    start_change(repo, capsys, "a")
    start_change(repo, capsys, "b")
    write(repo, "sysml/changes/b/model/core/api.sysml", API2.replace("new api", "other api"))
    assert run(repo, "archive", "a", capsys=capsys)[0] == 0
    code, out, _ = run(repo, "archive", "b", capsys=capsys)
    assert code == 1 and "changed since the change was written" in out
    assert (repo / "sysml/model/core/api.sysml").read_text() == API2


def test_archive_symlink_inside_the_change_is_exit_2(repo, tmp_path, capsys):
    start_change(repo, capsys)
    (tmp_path / "e.sysml").write_text(NEW)
    (repo / "sysml/changes/x/model/extra.sysml").symlink_to(tmp_path / "e.sysml")
    before = snapshot(repo)
    code, out, err = run(repo, "archive", "x", capsys=capsys)
    assert (code, out) == (2, "") and "is a symbolic link" in err
    assert snapshot(repo) == before


def test_archive_never_lays_out_an_over_limit_model(tmp_path, capsys, monkeypatch):
    many = "package P {\n" + "".join(f"  part def D{i} {{ doc /* d */ }}\n" for i in range(150)) + "}\n"
    more = "package Q {\n" + "".join(f"  part def E{i} {{ doc /* d */ }}\n" for i in range(160)) + "}\n"
    root = make_repo(tmp_path / "r", models={"p.sysml": many})
    assert run(root, "new-change", "big", "--file", "p.sysml", capsys=capsys)[0] == 0
    write(root, "sysml/changes/big/proposal.md", PROPOSAL)
    write(root, "sysml/changes/big/model/q.sysml", more)
    monkeypatch.setattr(sysml.layout_mod, "layout", lambda m: pytest.fail("laid out a model with findings"))
    before = snapshot(root)
    code, out, _ = run(root, "archive", "big", capsys=capsys)
    assert code == 1 and "too many elements (limit 300)" in out
    assert snapshot(root) == before


# ---- registration ---------------------------------------------------------------------------------------------

def test_registered_in_the_cli(repo):
    r = subprocess.run([sys.executable, str(BIN), "ops", "sysml", "check", "--root", str(repo),
                        "--profile", str(repo / ".tld/toolkit.yaml")], capture_output=True, text=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, "sysml: ok (4 elements)\n", "")


def test_help_lists_the_four_subcommands_and_the_honesty_sentence():
    r = subprocess.run([sys.executable, str(BIN), "ops", "sysml", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    for word in ("new-change", "check", "render", "archive"):
        assert word in r.stdout
    flat = " ".join(r.stdout.split())
    assert "a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; " \
           "tld does not check it against one" in flat


def test_module_docstring_has_the_honesty_sentence():
    assert "a documented subset of the SysML v2 textual notation, intended to parse in SysML v2 tools; " \
           "tld does not check it against one" in " ".join(sysml.__doc__.split())
