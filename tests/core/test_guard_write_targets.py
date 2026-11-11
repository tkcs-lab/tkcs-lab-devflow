"""write_targets: the paths a Bash command writes."""
import pytest

from tld.guard import _common, _writes
from tld.guard.action import Action, Settings


def targets(tmp_path, command):
    ctx = _common.make_ctx(Action("shell", str(tmp_path), str(tmp_path), command=command), Settings())
    return [p for p, _ in _writes.write_targets(ctx, command)]


def test_redirect_target(tmp_path):
    assert targets(tmp_path, "echo x > a.txt") == ["a.txt"]


def test_tee_and_sed_in_place(tmp_path):
    assert targets(tmp_path, "echo x | tee b.txt") == ["b.txt"]
    assert targets(tmp_path, "sed -i 's/a/b/' c.txt") == ["c.txt"]


def test_cp_and_mv_destinations(tmp_path):
    assert targets(tmp_path, "cp src.txt dst.txt") == ["dst.txt"]
    assert set(targets(tmp_path, "mv old.txt new.txt")) == {"new.txt", "old.txt"}


def test_variable_set_in_the_same_command_is_resolved(tmp_path):
    assert targets(tmp_path, "F=a.txt; echo x > $F") == ["a.txt"]


def test_brace_and_glob_expansion(tmp_path):
    assert targets(tmp_path, "touch {a,b}.txt") == ["a.txt", "b.txt"]
    (tmp_path / "one.log").write_text("")
    (tmp_path / "two.log").write_text("")
    found = targets(tmp_path, "rm *.log")
    assert "*.log" in found
    assert {str(tmp_path / "one.log"), str(tmp_path / "two.log")} <= set(found)


def test_dynamic_path_is_skipped(tmp_path):
    assert targets(tmp_path, "echo x > $(date)") == []


@pytest.mark.parametrize("command", ["ls -l", "cat a", "git status", "python3 -c 'print(1)'"])
def test_read_only_commands_yield_nothing(tmp_path, command):
    assert targets(tmp_path, command) == []


def test_unparseable_command_yields_nothing(tmp_path):
    assert targets(tmp_path, "echo 'unterminated > a.txt") == []


def test_too_many_paths_raises(tmp_path):
    with pytest.raises(_writes.TooManyPaths):
        targets(tmp_path, "touch " + "{a,b}" * 7)
