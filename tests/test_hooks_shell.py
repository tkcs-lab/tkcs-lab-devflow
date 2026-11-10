"""The shell tokenizer behind the Bash hooks."""
import pytest

import hooks_helpers  # noqa: F401  (puts the hooks directory on sys.path)

from _shell import DYN, ParseError, split_commands, walk


def words(command):
    return [c.words for c in split_commands(command)]


@pytest.mark.parametrize("command, expected", [
    ("git status", [["git", "status"]]),
    ("a && b || c; d | e & f", [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]),
    ("echo 'a && b' \"c; d\"", [["echo", "a && b", "c; d"]]),
    ("a\nb", [["a"], ["b"]]),
    ("a \\\n  b", [["a", "b"]]),
    ("(cd x; git push)", [["cd", "x"], ["git", "push"]]),
    ("{ a; b; }", [["{", "a"], ["b"], ["}"]]),
    ("a # git push -f\nb", [["a"], ["b"]]),
    ("echo a#b", [["echo", "a#b"]]),
    ("echo $# ${#x}", [["echo", "$#", "${#x}"]]),
    ("echo $(git tag -d x) tail", [["git", "tag", "-d", "x"], ["echo", DYN, "tail"]]),
    ("echo \"$(git tag -d x)\"", [["git", "tag", "-d", "x"], ["echo", DYN]]),
    ("echo `git tag -d x`", [["git", "tag", "-d", "x"], ["echo", DYN]]),
    ("echo '$(git tag -d x)'", [["echo", "$(git tag -d x)"]]),
    ("diff <(git tag) b", [["git", "tag"], ["diff", DYN, "b"]]),
    ("echo $((1+2))", [["1+2"], ["echo", DYN]]),
    ("echo $'a\\nb' c", [["echo", DYN, "c"]]),
    ("echo \"it's\" 'say \"hi\"'", [["echo", "it's", 'say "hi"']]),
    ("x=1 y=2 cmd", [["x=1", "y=2", "cmd"]]),
])
def test_split(command, expected):
    assert words(command) == expected


def test_heredoc_body_is_not_a_command():
    cmd = "git commit -m \"$(cat <<'EOF'\nfix: never git push --force\n\nit's a ) odd body\nEOF\n)\" && git push -u origin x"
    assert words(cmd) == [["cat"], ["git", "commit", "-m", DYN], ["git", "push", "-u", "origin", "x"]]


def test_unquoted_heredoc_body_still_runs_substitutions():
    assert ["git", "tag", "v1"] in words("cat <<EOF\n$(git tag v1)\nEOF\n")
    assert ["git", "tag", "v1"] not in words("cat <<'EOF'\n$(git tag v1)\nEOF\n")
    assert words("cat <<-EOF\n\tx\n\tEOF\nls") == [["cat"], ["ls"]]


def test_redirections():
    cmd = split_commands("echo hi 2>&1 >> out.txt > b.txt &> c.txt 2> d.txt < in.txt")[0]
    assert cmd.words == ["echo", "hi"]
    assert cmd.redirects == [(">&", "1"), (">>", "out.txt"), (">", "b.txt"), ("&>", "c.txt"), (">", "d.txt"),
                             ("<", "in.txt")]
    assert split_commands("echo \"> not.txt\"")[0].redirects == []


@pytest.mark.parametrize("command", ["echo \"abc", "echo 'abc", "echo $(ls", "echo `ls", "git push 'origin",
                                     "cat <<", "echo $'a"])
def test_unparseable_commands_raise(command):
    with pytest.raises(ParseError):
        split_commands(command)


def test_nesting_is_bounded():
    with pytest.raises(ParseError):
        split_commands("echo " + "$(" * 20 + "x" + ")" * 20)


@pytest.mark.parametrize("command, expected", [
    ("FOO=1 git push", ["git", "push"]),
    ("env -u X A=b git push", ["git", "push"]),
    ("sudo -u me git push", ["git", "push"]),
    ("nice -n 5 timeout 10 git push", ["git", "push"]),
    ("command git push", ["git", "push"]),
    ("exec git push", ["git", "push"]),
    ("time git push", ["git", "push"]),
    ("if true; then git push; fi", ["git", "push"]),
    ("/usr/bin/git push", ["/usr/bin/git", "push"]),
])
def test_wrappers_are_stripped(command, expected):
    assert expected in [w for _, w, _ in walk(command)]


@pytest.mark.parametrize("command", [
    "bash -c 'git push -f'", "sh -c \"git push -f\"", "bash -lc 'git push -f'", "eval git push -f",
    "eval 'git push -f'", "sudo bash -c 'git push -f'", "xargs -n1 git push -f", "find . -exec git push -f \\;",
])
def test_indirect_execution_is_unpacked(command):
    assert ["git", "push", "-f"] in [w[:3] for _, w, _ in walk(command)]


def test_cd_is_tracked():
    seen = [(cwd, w) for cwd, w, _ in walk("cd a && cd b && git push; cd /x; git tag")]
    assert seen[2] == ("a/b", ["git", "push"])
    assert seen[4] == ("/x", ["git", "tag"])
