"""The safe file layer of the SysML subset (src/tld/sysml/files.py)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tld.sysml import files
from tld.sysml.types import ModelError


def _mk(root: Path, rel: str, text: str = "package P {}\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _outside(tmp_path: Path) -> Path:
    out = tmp_path / "outside"
    out.mkdir()
    (out / "f.sysml").write_text("outside\n")
    return out


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    return r


@pytest.mark.parametrize("link", ["sysml", "sysml/model", "sysml/model/a.sysml", "sysml/model/sub"])
@pytest.mark.parametrize("op", ["load_tree", "write_text", "read_text"])
def test_symlinked_component_is_refused(tmp_path: Path, root: Path, link: str, op: str) -> None:
    out = _outside(tmp_path)
    parent = (root / link).parent
    parent.mkdir(parents=True, exist_ok=True)
    (root / link).symlink_to(out if not link.endswith(".sysml") else out / "f.sysml")
    if op == "load_tree":
        with pytest.raises(ModelError, match=f"path '{link}' is a symbolic link"):
            files.load_tree(root)
        return
    target = "sysml/model/a.sysml" if link != "sysml/model/sub" else "sysml/model/sub/a.sysml"
    call = (lambda: files.write_text(root, target, "x")) if op == "write_text" else (lambda: files.read_text(root, target))
    with pytest.raises(ModelError, match="is a symbolic link"):
        call()
    assert (out / "f.sysml").read_text() == "outside\n"


@pytest.mark.parametrize("op", ["write_text", "check_writable"])
def test_symlinked_docs_dir_and_file_are_refused(tmp_path: Path, root: Path, op: str) -> None:
    out = _outside(tmp_path)
    (root / "docs").symlink_to(out)
    fn = getattr(files, op)
    args = ("docs/architecture.svg",) if op == "check_writable" else ("docs/architecture.svg", "x")
    with pytest.raises(ModelError, match="path 'docs' is a symbolic link"):
        fn(root, *args)
    (root / "docs").unlink()
    (root / "docs").mkdir()
    (root / "docs/architecture.svg").symlink_to(out / "f.sysml")
    with pytest.raises(ModelError, match="path 'docs/architecture.svg' is a symbolic link"):
        fn(root, *args)
    assert (out / "f.sysml").read_text() == "outside\n"


def test_dangling_symlink_target_is_refused(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "docs/architecture.svg").symlink_to(root / "nowhere")
    with pytest.raises(ModelError, match="is a symbolic link"):
        files.write_text(root, "docs/architecture.svg", "x")
    assert not (root / "nowhere").exists()


def test_write_text_open_refuses_final_symlink_even_if_component_check_is_skipped(
    tmp_path: Path, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _outside(tmp_path)
    (root / "docs").mkdir()
    (root / "docs/a.svg").symlink_to(out / "f.sysml")
    monkeypatch.setattr(files, "_check_components", lambda *a, **k: None)
    with pytest.raises(ModelError, match="is a symbolic link"):
        files.write_text(root, "docs/a.svg", "changed")
    assert (out / "f.sysml").read_text() == "outside\n"


def test_write_text_creates_parents_and_file(root: Path) -> None:
    files.write_text(root, "sysml/model/core/api.sysml", "package A {}\n")
    assert (root / "sysml/model/core/api.sysml").read_text() == "package A {}\n"
    assert files.read_text(root, "sysml/model/core/api.sysml") == "package A {}\n"
    assert files.read_text(root, "sysml/model/none.sysml") is None
    files.write_text(root, "sysml/model/core/api.sysml", "package B {}\n")
    assert files.read_text(root, "sysml/model/core/api.sysml") == "package B {}\n"


def test_write_text_refuses_hard_linked_target(tmp_path: Path, root: Path) -> None:
    out = _outside(tmp_path)
    (root / "docs").mkdir()
    os.link(out / "f.sysml", root / "docs/a.svg")
    with pytest.raises(ModelError, match="path 'docs/a.svg' has more than one hard link"):
        files.write_text(root, "docs/a.svg", "x")
    assert (out / "f.sysml").read_text() == "outside\n"


def test_check_writable_refuses_hard_linked_target(tmp_path: Path, root: Path) -> None:
    out = _outside(tmp_path)
    (root / "docs").mkdir()
    os.link(out / "f.sysml", root / "docs/a.svg")
    with pytest.raises(ModelError, match="path 'docs/a.svg' has more than one hard link"):
        files.check_writable(root, "docs/a.svg")
    assert (out / "f.sysml").read_text() == "outside\n"


def test_check_writable_refuses_an_existing_directory_target(root: Path) -> None:
    (root / "docs/a.svg").mkdir(parents=True)
    with pytest.raises(ModelError, match="path 'docs/a.svg' is not a regular file or directory"):
        files.check_writable(root, "docs/a.svg")
    with pytest.raises(ModelError, match="path 'docs/a.svg' is not a regular file or directory"):
        files.write_text(root, "docs/a.svg", "x")
    assert list((root / "docs/a.svg").iterdir()) == []


def test_check_writable_writes_nothing(root: Path) -> None:
    files.check_writable(root, "sysml/model/new/dir/a.sysml")
    assert list(root.iterdir()) == []


def test_file_as_parent_directory_is_refused(root: Path) -> None:
    _mk(root, "docs", "i am a file")
    with pytest.raises(ModelError, match="path 'docs' is not a regular file or directory"):
        files.write_text(root, "docs/a.svg", "x")


def test_fifo_is_refused(root: Path) -> None:
    (root / "docs").mkdir()
    os.mkfifo(root / "docs/a.svg")
    with pytest.raises(ModelError, match="is not a regular file or directory"):
        files.write_text(root, "docs/a.svg", "x")
    (root / "sysml/model").mkdir(parents=True)
    os.mkfifo(root / "sysml/model/p.sysml")
    with pytest.raises(ModelError, match="path 'sysml/model/p.sysml' is not a regular file or directory"):
        files.load_tree(root)


@pytest.mark.parametrize("rel", ["A.sysml", "a/../b.sysml", "/a.sysml", "a.txt", "a\n.sysml", "a b.sysml"])
def test_invalid_relpaths(rel: str) -> None:
    with pytest.raises(ModelError) as exc:
        files.check_relpath(rel)
    assert str(exc.value) == f"invalid file '{rel}': use a path like core/api.sysml"


def test_valid_relpath() -> None:
    assert files.check_relpath("core/api_2.sysml") == "core/api_2.sysml"


@pytest.mark.parametrize("name", ["A.sysml", "a b.sysml"])
def test_load_tree_refuses_stray_names(root: Path, name: str) -> None:
    _mk(root, "sysml/model/ok.sysml")
    _mk(root, f"sysml/model/{name}")
    with pytest.raises(ModelError, match="invalid file"):
        files.load_tree(root)


def test_load_tree_absent_and_sorted(root: Path) -> None:
    assert files.load_tree(root) == {}
    _mk(root, "sysml/model/b.sysml", "b")
    _mk(root, "sysml/model/a/z.sysml", "z")
    _mk(root, "sysml/model/a.sysml", "a")
    assert list(files.load_tree(root)) == ["a.sysml", "a/z.sysml", "b.sysml"]


def test_load_tree_file_limit(root: Path) -> None:
    _mk(root, "sysml/model/big.sysml", "x" * 100000)
    assert "big.sysml" in files.load_tree(root)
    _mk(root, "sysml/model/big.sysml", "x" * 100001)
    with pytest.raises(ModelError, match=r"^sysml/model/big.sysml is longer than 100000 bytes$"):
        files.load_tree(root)


def test_load_tree_count_limit(root: Path) -> None:
    for i in range(51):
        _mk(root, f"sysml/model/f{i:02}.sysml", "x")
    with pytest.raises(ModelError, match=r"^more than 50 model files$"):
        files.load_tree(root)


def test_load_tree_total_limit(root: Path) -> None:
    for i in range(11):
        _mk(root, f"sysml/model/f{i:02}.sysml", "x" * 100000)
    with pytest.raises(ModelError, match=r"^the model is larger than 1000000 bytes$"):
        files.load_tree(root)


def test_load_tree_refuses_non_utf8(root: Path) -> None:
    p = _mk(root, "sysml/model/a.sysml")
    p.write_bytes(b"\xff\xfe")
    with pytest.raises(ModelError, match=r"^sysml/model/a.sysml is not valid UTF-8$"):
        files.load_tree(root)


def test_remove_file_removes(root: Path) -> None:
    _mk(root, "sysml/model/a.sysml")
    files.remove_file(root, "sysml/model/a.sysml")
    assert not (root / "sysml/model/a.sysml").exists()
    with pytest.raises(ModelError, match="does not exist"):
        files.remove_file(root, "sysml/model/a.sysml")


def test_remove_file_refuses_symlinked_parent_and_symlinked_target(tmp_path: Path, root: Path) -> None:
    out = _outside(tmp_path)
    (root / "sysml").symlink_to(out)
    with pytest.raises(ModelError, match="path 'sysml' is a symbolic link"):
        files.remove_file(root, "sysml/f.sysml")
    (root / "sysml").unlink()
    (root / "sysml/model").mkdir(parents=True)
    (root / "sysml/model/a.sysml").symlink_to(out / "f.sysml")
    with pytest.raises(ModelError, match="is a symbolic link"):
        files.remove_file(root, "sysml/model/a.sysml")
    assert (out / "f.sysml").read_text() == "outside\n"


def test_move_dir_moves(root: Path) -> None:
    _mk(root, "sysml/changes/x/proposal.md", "p")
    files.move_dir(root, "sysml/changes/x", "sysml/changes/archive/2026-01-01-x")
    assert (root / "sysml/changes/archive/2026-01-01-x/proposal.md").read_text() == "p"
    assert not (root / "sysml/changes/x").exists()


def test_move_dir_refuses_existing_destination(root: Path) -> None:
    _mk(root, "sysml/changes/x/proposal.md", "p")
    (root / "sysml/changes/archive/d").mkdir(parents=True)
    with pytest.raises(ModelError, match="path 'sysml/changes/archive/d' already exists"):
        files.move_dir(root, "sysml/changes/x", "sysml/changes/archive/d")
    assert (root / "sysml/changes/x/proposal.md").exists()


def test_move_dir_refuses_symlink_in_src_or_dst_components(tmp_path: Path, root: Path) -> None:
    out = _outside(tmp_path)
    (root / "sysml").mkdir()
    (root / "sysml/changes").symlink_to(out)
    with pytest.raises(ModelError, match="path 'sysml/changes' is a symbolic link"):
        files.move_dir(root, "sysml/changes/x", "sysml/changes/archive/d")
    (root / "sysml/changes").unlink()
    _mk(root, "sysml/changes/x/proposal.md", "p")
    (root / "sysml/changes/archive").symlink_to(out)
    with pytest.raises(ModelError, match="path 'sysml/changes/archive' is a symbolic link"):
        files.move_dir(root, "sysml/changes/x", "sysml/changes/archive/d")
    assert (root / "sysml/changes/x/proposal.md").exists()
    assert sorted(p.name for p in out.iterdir()) == ["f.sysml"]


def test_move_dir_refuses_missing_or_file_source(root: Path) -> None:
    with pytest.raises(ModelError, match="does not exist"):
        files.move_dir(root, "sysml/changes/x", "sysml/changes/archive/d")
    _mk(root, "sysml/changes/x", "file")
    with pytest.raises(ModelError, match="is not a regular file or directory"):
        files.move_dir(root, "sysml/changes/x", "sysml/changes/archive/d")


def test_sha256_text() -> None:
    assert files.sha256_text("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.parametrize("rel", ["", "/a", "a//b", "a/../b", "./a"])
def test_bad_paths_are_refused(root: Path, rel: str) -> None:
    with pytest.raises(ModelError, match="invalid path"):
        files.check_writable(root, rel)


def test_o_nofollow_expression_once() -> None:
    src = Path(files.__file__).read_text()
    assert src.count("os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW") == 1
