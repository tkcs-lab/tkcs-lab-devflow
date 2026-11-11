"""The shell tokenizer behind the Bash hooks."""
import pytest

import hooks_helpers  # noqa: F401  (puts the hooks directory on sys.path)

from hooks_helpers import BASH_GUARDS, bash, make_repo, run
from tld.guard._shell import DYN, ParseError, split_commands, walk


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
    ("echo $'a\\nb' c", [["echo", "a\nb", "c"]]),
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


@pytest.mark.parametrize("command", [
    "env -S 'git push -f origin feature'",
    "time -p git push -f origin feature",
    "flock /tmp/l git push -f origin feature",
    "script -qc 'git push -f origin feature' /dev/null",
])
def test_wrapper_forms_denied(command, tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    assert run("no-force-push", bash(command, repo)).code == 2


def test_ansi_c_quoting_is_decoded(tmp_path):
    from tld.guard._ansi import ansi_c_decode
    assert ansi_c_decode(r"\x2d\x2dforce") == "--force"
    assert ansi_c_decode(r"a\nb") == "a\nb"
    assert ansi_c_decode(r"\q") == "\\q"
    repo = make_repo(tmp_path / "r", "feature/demo")
    for command in ["git push $'--force' origin feature", "git push origin $'+feature'",
                    "bash -c $'git push -f origin feature'"]:
        assert run("no-force-push", bash(command, repo)).code == 2, command
    assert run("no-merge", bash("git push origin $'HEAD:main'", repo)).code == 2


DENY, ALLOW = 2, 0


@pytest.mark.parametrize("command, code, merge", [
    ("git push $'--force' origin feature", DENY, False),
    ("git push origin $'+feature'", DENY, False),
    ("git push origin $'HEAD:main'", DENY, True),
    ("bash -c $'git push -f origin feature'", DENY, False),
    ("echo 'git push -f origin feature' | bash", DENY, False),
    ("bash <<< 'git push -f origin feature'", DENY, False),
    ("bash <<'EOF'\ngit push -f origin feature\nEOF", DENY, False),
    ("sh <<EOF\ngit push origin HEAD:main\nEOF", DENY, True),
    ("bash -s <<-EOF\n\tgit push -f origin feature\n\tEOF", DENY, False),
    ("bash -o errexit < script.sh", DENY, False),
    ("cat <<EOF | bash\ngit push -f x\nEOF", DENY, False),
    ("bash script.sh", ALLOW, False),
    ("bash -c 'echo hi'", ALLOW, False),
    ("cat <<EOF\ngit push -f x\nEOF", ALLOW, False),
    ("echo hi | cat", ALLOW, False),
    ("bash --version", ALLOW, False),
    ("bash -x script.sh <<< 'git push -f x'", ALLOW, False),
    ("bash <<< 'echo hi'", ALLOW, False),
])
def test_stdin_fed_shells_and_ansi_c_are_denied(command, code, merge, tmp_path):
    """`merge` rows push to main without forcing: no-merge is the hook that denies them."""
    repo = make_repo(tmp_path / "r", "feature/demo")
    hooks = ("no-merge",) if merge else ("no-force-push",) if code == DENY else BASH_GUARDS
    for hook in hooks:
        assert run(hook, bash(command, repo)).code == code, hook


def test_heredoc_body_is_kept_on_its_command():
    cmds = split_commands("cat <<A | bash <<-'B'\nx\nA\n\tgit push\n\tB\nls <<< 'y z'")
    assert [(c.words, c.stdin_text) for c in cmds] == [(["cat"], "x\n"), (["bash"], "git push\n"), (["ls"], "y z")]
