"""tld ops spec: the pinned OpenSpec wrapper (fixed argv, checks, install, allowlisted environment)."""
import os
import stat
import subprocess
import sys

import pytest

from conftest import BIN
from tld.ops import spec

VERSION = "2.1.0"
NODE = ["node", "{dir}/node_modules/@fission-ai/openspec/bin/openspec.js"]
NPM = ["npm", "install", "--ignore-scripts", "--no-save", "--no-audit", "--no-fund",
       "--registry", "https://registry.npmjs.org/", "@fission-ai/openspec@2.1.0"]
ALLOWED = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
           "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS"}
FIXED = {"npm_config_ignore_scripts", "npm_config_registry", "OPENSPEC_TELEMETRY", "DO_NOT_TRACK", "CI"}


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / "cache" / "openspec" / VERSION


BASE = "git:\n  main_branch: main\nverify:\n  fast: ['true']\n  dod: ['true']\n"  # the keys no default can supply


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / "toolkit.yaml"
    p.write_text(BASE + f'spec:\n  version: "{VERSION}"\n')
    return p


class Rec:
    def __init__(self, cache):
        self.calls, self.cache, self.code = [], cache, 0
        self.node, self.which_calls, self.node_calls = "22.20.0", [], 0
        self.missing = set()

    def run(self, argv, cwd, env, timeout):
        self.calls.append((list(argv), cwd, env, timeout))
        if argv[0] == "npm":
            pkg = self.cache / "node_modules" / "@fission-ai" / "openspec"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "package.json").write_text(f'{{"version": "{self.installed}"}}')
            return 0
        return self.code

    installed = VERSION

    def which(self, name):
        self.which_calls.append(name)
        return None if name in self.missing else f"/bin/{name}"

    def node_version(self):
        self.node_calls += 1
        return self.node


@pytest.fixture
def rec(monkeypatch, cache):
    r = Rec(cache)
    monkeypatch.setattr(spec, "_run", r.run)
    monkeypatch.setattr(spec, "_which", r.which)
    monkeypatch.setattr(spec, "_node_version", r.node_version)
    return r


def go(profile, root, *args):
    return spec.main([*args, "--profile", str(profile), "--root", str(root)])


def node_argv(cache, *args):
    return ["node", f"{cache}/node_modules/@fission-ai/openspec/bin/openspec.js", *args]


FORMS = [
    (["init"], ["init", "--tools", "none", "--no-animation"]),
    (["new-change", "add-x"], ["new", "change", "add-x"]),
    (["list"], ["list", "--specs"]),
    (["list", "--json"], ["list", "--specs", "--json"]),
    (["validate"], ["validate", "--all", "--strict", "--no-interactive"]),
    (["validate", "--json"], ["validate", "--all", "--strict", "--no-interactive", "--json"]),
    (["validate", "--change", "x"], ["validate", "x", "--type", "change", "--strict", "--no-interactive"]),
    (["validate", "--change", "x", "--json"],
     ["validate", "x", "--type", "change", "--strict", "--no-interactive", "--json"]),
    (["archive", "add-x"], ["archive", "add-x", "--yes"]),
]


@pytest.mark.parametrize("args,expected", FORMS)
def test_every_form_runs_its_fixed_argv(rec, profile, tmp_path, cache, args, expected):
    root = tmp_path / "repo"
    root.mkdir()
    assert go(profile, root, *args) == 0
    last = rec.calls[-1]
    assert last[0] == node_argv(cache, *expected)
    assert last[1] == root and last[3] == 600


def test_profile_and_root_are_accepted_after_the_subcommand(rec, profile, tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    assert spec.main(["validate", "--profile", str(profile), "--change", "x", "--root", str(root)]) == 0
    assert rec.calls[-1][1] == root


def test_usage_lists_exactly_the_five_subcommands(capsys):
    with pytest.raises(SystemExit) as e:
        spec.main([])
    assert e.value.code == 2
    assert "{init,new-change,list,validate,archive}" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["feedback"], ["install"], ["show", "x"], ["archive", "x", "--no-validate"],
                                  ["new-change", "x", "extra"]])
def test_unknown_or_extra_arguments_are_rejected_and_nothing_runs(rec, profile, tmp_path, args):
    with pytest.raises(SystemExit) as e:
        go(profile, tmp_path, *args)
    assert e.value.code == 2
    assert not rec.calls and not rec.which_calls and rec.node_calls == 0


@pytest.mark.parametrize("bad", ["abc\n", "-x", "../x", "A", "a--b", "", "a_b"])
def test_invalid_ids_exit_2(rec, profile, tmp_path, capsys, bad):
    opts = ["--profile", str(profile), "--root", str(tmp_path)]
    args = ["new-change", *opts, "--", bad] if bad.startswith("-") else ["new-change", bad, *opts]
    assert spec.main(args) == 2
    assert capsys.readouterr().err == f"tld ops spec: invalid id '{bad}': use lower-case words joined by hyphens\n"
    assert not rec.calls and not rec.which_calls


def test_invalid_change_id_on_validate_exits_2(rec, profile, tmp_path, capsys):
    assert go(profile, tmp_path, "validate", "--change", "A") == 2
    assert "invalid id 'A'" in capsys.readouterr().err and not rec.calls


@pytest.mark.parametrize("version", ['"latest"', '"^2.1.0"', '"2.1"', "2.1", '"2.1.0\\n"', '"2.1.0 --registry=x"', "null"])
def test_invalid_versions_exit_2(rec, tmp_path, capsys, version):
    p = tmp_path / "p.yaml"
    p.write_text(BASE + f"spec:\n  version: {version}\n")
    code = go(p, tmp_path, "list")
    err = capsys.readouterr().err
    # the resolver's schema check says it first; the command's own exact-release check catches the rest
    assert code == 2 and err.startswith(("toolkit.yaml: 'spec.version': ", "tld ops spec: spec.version must be"))
    assert not rec.calls and not rec.which_calls


def test_missing_profile_file(rec, tmp_path, capsys):
    p = tmp_path / "nope.yaml"
    assert go(p, tmp_path, "list") == 2
    assert capsys.readouterr().err == f"tld ops spec: profile not found: {p}\n"
    assert not rec.calls


def test_default_profile_is_under_root(rec, tmp_path, capsys):
    assert spec.main(["list", "--root", str(tmp_path)]) == 2
    assert f"profile not found: {tmp_path / '.tld' / 'toolkit.yaml'}" in capsys.readouterr().err


def test_absent_spec_section_message(rec, tmp_path, capsys):
    p = tmp_path / "p.yaml"
    p.write_text(BASE)
    assert go(p, tmp_path, "list") == 2
    assert capsys.readouterr().err == ("toolkit.yaml: /spec needs a 'spec' section (an empty 'spec:' uses version "
                                       "2.1.0; see docs/guides/spec.md)\n")
    assert not rec.calls


@pytest.mark.parametrize("text", ['spec: "2.1.0"\n', "project: {}\n", ""])
def test_an_unusable_profile_is_reported(rec, tmp_path, capsys, text):
    p = tmp_path / "p.yaml"
    p.write_text(text)
    assert go(p, tmp_path, "list") == 2
    assert capsys.readouterr().err.startswith("toolkit.yaml: ")
    assert not rec.calls


@pytest.mark.parametrize("spec", ["spec:\n", "spec: {}\n"])
def test_an_empty_spec_section_pins_the_default_version(rec, cache, tmp_path, spec):
    assert cache.name == "2.1.0"  # the version of the default
    p = tmp_path / "p.yaml"
    p.write_text(BASE + spec)
    assert go(p, tmp_path, "list") == 0
    assert rec.calls[-1][0] == node_argv(cache, "list", "--specs")


@pytest.mark.parametrize("missing", ["node", "npm"])
def test_node_or_npm_missing(rec, profile, tmp_path, capsys, missing):
    rec.missing.add(missing)
    assert go(profile, tmp_path, "list") == 2
    assert capsys.readouterr().err == ("tld ops spec: node and npm are required "
                                       "(OpenSpec 2.1.0 needs Node.js 22.20.0 or newer)\n")
    assert not rec.calls


def test_unreadable_node_version(rec, profile, tmp_path, capsys):
    rec.node = None
    assert go(profile, tmp_path, "list") == 2
    assert "node and npm are required" in capsys.readouterr().err and not rec.calls


def test_old_node_is_rejected(rec, profile, tmp_path, capsys):
    rec.node = "22.19.9"
    assert go(profile, tmp_path, "list") == 2
    assert capsys.readouterr().err == ("tld ops spec: Node.js 22.19.9 is too old; "
                                       "OpenSpec 2.1.0 needs 22.20.0 or newer\n")
    assert not rec.calls


@pytest.mark.parametrize("v", ["22.20.0", "23.0.0", "100.0.0"])
def test_new_enough_node_is_accepted(rec, profile, tmp_path, v):
    rec.node = v
    assert go(profile, tmp_path, "list") == 0


def test_fresh_cache_installs_then_runs_and_second_call_skips_install(rec, profile, tmp_path, cache):
    assert go(profile, tmp_path, "list") == 0
    assert [c[0] for c in rec.calls] == [NPM, node_argv(cache, "list", "--specs")]
    assert rec.calls[0][1] == cache and rec.calls[0][3] == 600
    assert (cache / "package.json").read_text().strip() == '{"private": true}'
    assert go(profile, tmp_path, "list") == 0
    assert [c[0][0] for c in rec.calls] == ["npm", "node", "node"]


def test_installed_version_mismatch_exits_2(rec, profile, tmp_path, capsys):
    rec.installed = "2.0.9"
    assert go(profile, tmp_path, "list") == 2
    assert capsys.readouterr().err == "tld ops spec: installed version 2.0.9 is not 2.1.0\n"
    assert [c[0][0] for c in rec.calls] == ["npm"]


def test_failed_install_exits_2(monkeypatch, profile, tmp_path, capsys):
    monkeypatch.setattr(spec, "_which", lambda n: "/bin/" + n)
    monkeypatch.setattr(spec, "_node_version", lambda: "22.20.0")
    calls = []
    monkeypatch.setattr(spec, "_run", lambda a, c, e, t: calls.append(a) or 3)
    assert go(profile, tmp_path, "list") == 2
    assert capsys.readouterr().err == "tld ops spec: installing @fission-ai/openspec@2.1.0 failed (exit 3)\n"
    assert len(calls) == 1


def test_environment_is_an_allowlist(rec, profile, tmp_path, monkeypatch):
    for k, v in {"GITHUB_TOKEN": "x", "TLD_BOARD_TOKEN": "x", "NPM_TOKEN": "x", "NODE_OPTIONS": "--inspect",
                 "npm_config_userconfig": "/x", "http_proxy": "http://p:1", "OPENSPEC_TELEMETRY": "1"}.items():
        monkeypatch.setenv(k, v)
    assert go(profile, tmp_path, "list") == 0
    assert len(rec.calls) == 2
    for _, _, env, _ in rec.calls:
        assert set(env) <= ALLOWED | FIXED
        assert env["http_proxy"] == "http://p:1"
        for dropped in ("GITHUB_TOKEN", "TLD_BOARD_TOKEN", "NPM_TOKEN", "NODE_OPTIONS", "npm_config_userconfig"):
            assert dropped not in env
        assert env["OPENSPEC_TELEMETRY"] == "0" and env["DO_NOT_TRACK"] == "1" and env["CI"] == "1"
        assert env["npm_config_ignore_scripts"] == "true"
        assert env["npm_config_registry"] == "https://registry.npmjs.org/"


def test_cache_defaults_to_home_cache_tld(rec, profile, tmp_path, monkeypatch):
    monkeypatch.delenv("TLD_CACHE_DIR")
    rec.cache = tmp_path / ".cache" / "tld" / "openspec" / VERSION
    assert go(profile, tmp_path, "list") == 0
    assert rec.calls[0][1] == tmp_path / ".cache" / "tld" / "openspec" / "2.1.0"


def test_timeout_gives_the_timeout_line(monkeypatch, rec, profile, tmp_path, capsys):
    def boom(argv, cwd, env, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(spec, "_run", boom)
    assert go(profile, tmp_path, "list") == 2
    assert capsys.readouterr().err == "tld ops spec: OpenSpec did not finish within 600 seconds\n"


def test_exit_code_of_openspec_is_returned_unchanged(rec, profile, tmp_path):
    go(profile, tmp_path, "list")
    rec.code = 7
    assert go(profile, tmp_path, "list") == 7


def test_run_wraps_subprocess_without_shell(monkeypatch, tmp_path):
    seen = {}

    def fake(argv, **kw):
        seen.update(kw, argv=argv)
        return subprocess.CompletedProcess(argv, 5)
    monkeypatch.setattr(subprocess, "run", fake)
    assert spec._run(["x"], tmp_path, {"A": "1"}, 9) == 5
    assert seen["stdin"] == subprocess.DEVNULL and seen["timeout"] == 9 and seen["env"] == {"A": "1"}
    assert seen["cwd"] == str(tmp_path) and not seen.get("shell")


def test_node_version_parses_and_fails_to_none(monkeypatch):
    out = {"rc": 0, "out": "v22.20.0\n"}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, out["rc"], out["out"], ""))
    assert spec._node_version() == "22.20.0"
    out["rc"] = 1
    assert spec._node_version() is None

    def oserr(*a, **k):
        raise OSError("no node")
    monkeypatch.setattr(subprocess, "run", oserr)
    assert spec._node_version() is None


def test_node_version_uses_allowlist_env(monkeypatch):
    monkeypatch.setenv("NODE_OPTIONS", "--require=/x.js")
    seen = {}

    def fake(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, "v22.20.0\n", "")
    monkeypatch.setattr(subprocess, "run", fake)
    spec._node_version()
    assert "NODE_OPTIONS" not in seen["env"]


def _script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_cli_runs_node_with_fixed_argv_env_and_cwd(tmp_path):
    bin_dir, out, root = tmp_path / "bin", tmp_path / "out", tmp_path / "repo"
    for d in (bin_dir, out, root):
        d.mkdir()
    _script(bin_dir / "npm", f'''mkdir -p node_modules/@fission-ai/openspec/bin
echo '{{"version": "2.1.0"}}' > node_modules/@fission-ai/openspec/package.json
: > node_modules/@fission-ai/openspec/bin/openspec.js
env > {out}/npm.env
cat > {out}/npm.stdin
exit 0
''')
    _script(bin_dir / "node", f'''if [ "$1" = "--version" ]; then echo v22.20.0; exit 0; fi
echo "$@" > {out}/node.args
pwd > {out}/node.cwd
env > {out}/node.env
cat > {out}/node.stdin
exit 7
''')
    prof = tmp_path / "p.yaml"
    prof.write_text(BASE + 'spec:\n  version: "2.1.0"\n')
    env = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(tmp_path),
           "TLD_CACHE_DIR": str(tmp_path / "c"), "GITHUB_TOKEN": "x", "TLD_BOARD_TOKEN": "x", "NPM_TOKEN": "x",
           "NODE_OPTIONS": "--require=/nonexistent.js", "npm_config_registry": "https://evil.invalid/",
           "OPENSPEC_TELEMETRY": "1"}
    r = subprocess.run([sys.executable, str(BIN), "ops", "spec", "validate", "--root", str(root),
                        "--profile", str(prof)], env=env, input="secret\n", capture_output=True, text=True)
    assert r.returncode == 7, r.stderr
    js = tmp_path / "c" / "openspec" / "2.1.0" / "node_modules" / "@fission-ai" / "openspec" / "bin" / "openspec.js"
    assert (out / "node.args").read_text().strip() == f"{js} validate --all --strict --no-interactive"
    assert (out / "node.cwd").read_text().strip() == str(root.resolve())
    for name in ("npm.env", "node.env"):
        text = (out / name).read_text()
        for bad in ("GITHUB_TOKEN", "TLD_BOARD_TOKEN", "NPM_TOKEN", "NODE_OPTIONS", "evil.invalid"):
            assert bad not in text
        assert "OPENSPEC_TELEMETRY=0" in text.splitlines()
    assert "npm_config_registry=https://registry.npmjs.org/" in (out / "npm.env").read_text().splitlines()
    assert "npm_config_ignore_scripts=true" in (out / "npm.env").read_text().splitlines()
    assert (out / "npm.stdin").read_text() == "" and (out / "node.stdin").read_text() == ""
