"""tld roles reflektor-prepare: the pin, the .reflektor.json allow-list, the archive checks. No network, no Node."""
import gzip
import hashlib
import http.client
import io
import json
import os
import subprocess
import tarfile
import urllib.error

import pytest

from conftest import BIN, _load

reflektor = _load("tld.roles.reflektor")
PrepareError = reflektor.PrepareError

SKILL = (b"# Skill\n\n## 4. Before\nx\n\n## 5. Write report.json\nline one\nline two\n\n## 6. Build\nrun build\n")
GOOD = {
    "scripts/collect.mjs": b"// collect\n",
    "scripts/build.mjs": b"// build\n",
    "assets/viewer.html": b"<html></html>",
    "schema/types.ts": b"export type Report = {}\n",
    "style-guide.md": b"style\n",
    "SKILL.md": SKILL,
}


def make_tar(files=None, extra=None, prefix="./"):
    """A gzip tarball with a `.` directory member, ./-prefixed names and the optional extra members."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        d = tarfile.TarInfo(".")
        d.type = tarfile.DIRTYPE
        tar.addfile(d)
        for name, content in (GOOD if files is None else files).items():
            ti = tarfile.TarInfo(prefix + name)
            ti.size = len(content)
            tar.addfile(ti, io.BytesIO(content))
        for ti, content in extra or []:
            tar.addfile(ti, io.BytesIO(content) if content is not None else None)
    return buf.getvalue()


def pin_for(data):
    return {**reflektor.PIN, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def member(name, typ=tarfile.REGTYPE, content=b"x", linkname=""):
    ti = tarfile.TarInfo(name)
    ti.type = typ
    ti.size = len(content) if typ == tarfile.REGTYPE else 0
    ti.linkname = linkname
    return ti, (content if typ == tarfile.REGTYPE else None)


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t.t", "-c", "user.name=t", "-C", str(repo), *args],
                   check=True, capture_output=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    node = bindir / "node"
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("a")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    (repo / "a.txt").write_text("b")
    git(repo, "commit", "-q", "-am", "two")
    dest = tmp_path / "s"
    dest.mkdir()
    return {"repo": repo, "base": base, "dest": dest, "node": node, "tmp": tmp_path}


def run(env, data=None, major=22, fetch=None):
    data = make_tar() if data is None else data
    return reflektor.prepare(env["dest"], env["repo"], env["base"], pin=pin_for(data),
                             fetch=fetch or (lambda url, limit: data), node_major=lambda node: major)


def code_of(env, **kw):
    with pytest.raises(PrepareError) as exc:
        run(env, **kw)
    return exc.value.code


def test_success_returns_path_and_writes_files(env):
    out = run(env)
    assert out == env["dest"].resolve() / "reflektor"
    for name, content in GOOD.items():
        assert (out / name).read_bytes() == content
    guide = (out / "report-guide.md").read_text()
    assert guide == "## 5. Write report.json\nline one\nline two\n\n"
    assert "## 6. Build" not in guide


def test_config_unchanged_and_absent_pass(env):
    run(env)


def test_config_unchanged_between_base_and_head_passes(env):
    (env["repo"] / ".reflektor.json").write_text('{"base": "main"}')
    git(env["repo"], "add", ".")
    git(env["repo"], "commit", "-q", "-m", "cfg")
    env["base"] = subprocess.run(["git", "-C", str(env["repo"]), "rev-parse", "HEAD"], capture_output=True,
                                 text=True, check=True).stdout.strip()
    run(env)


def test_config_changed_in_branch_is_refused(env):
    (env["repo"] / ".reflektor.json").write_text('{"base": "main"}')
    git(env["repo"], "add", ".")
    git(env["repo"], "commit", "-q", "-m", "cfg")
    assert code_of(env) == 3


def test_bad_base_is_refused(env):
    env["base"] = "no-such-ref"
    assert code_of(env) == 3


def _config(env, text):
    p = env["repo"] / ".reflektor.json"
    p.write_text(text)
    return p


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    '{"hooks": {"preRun": "x"}}',
    '{"coverage": {}}',
    '{"base": 5}',
    '{"base": "a\\u0007b"}',
    '{"targets": []}',
    '{"targets": {"foo": ["a"]}}',
    '{"targets": {"backend": "a"}}',
    '{"generated": "a"}',
    '{"generated": [1]}',
    '{"generated": ["a b"]}',
    '{"generated": ["' + "a" * 201 + '"]}',
    '{"generated": ["a/**/**/**"]}',
    '{"generated": ["a*b*c*d*e*"]}',
    json.dumps({"generated": [f"g{i}" for i in range(51)]}),
    "[" * 100000,
])
def test_config_refused(env, text):
    _config(env, text)
    assert code_of(env) == 3


def test_config_symlink_refused(env):
    (env["tmp"] / "real.json").write_text("{}")
    os.symlink(env["tmp"] / "real.json", env["repo"] / ".reflektor.json")
    assert code_of(env) == 3


def test_config_directory_refused(env):
    (env["repo"] / ".reflektor.json").mkdir()
    assert code_of(env) == 3


def test_config_too_large_refused(env):
    _config(env, '{"base": "' + "a" * 100001 + '"}')
    assert code_of(env) == 3


def test_config_plain_accepted(env):
    _config(env, '{"base": "main", "targets": {"backend": ["src/**"]}, "generated": ["x/**"]}')
    env["base"] = "HEAD"
    run(env)


def test_hooks_refused_before_any_download(env):
    _config(env, '{"hooks": {"preRun": "x"}}')

    def boom(url, limit):
        raise AssertionError("fetch called")

    assert code_of(env, fetch=boom) == 3


@pytest.mark.parametrize("major,ok", [(16, False), (17, False), (18, True)])
def test_node_version(env, major, ok):
    def boom(url, limit):
        raise AssertionError("fetch called")

    if ok:
        run(env, major=major)
    else:
        assert code_of(env, major=major, fetch=boom) == 3


def test_node_missing_refused(env, monkeypatch):
    env["node"].unlink()
    monkeypatch.setattr(reflektor.shutil, "which", lambda name: None)
    assert code_of(env) == 3


def test_node_unparsable_version_refused(env):
    with pytest.raises(PrepareError) as exc:
        reflektor.prepare(env["dest"], env["repo"], env["base"], pin=pin_for(make_tar()),
                          fetch=lambda u, n: make_tar(), node_major=lambda node: None)
    assert exc.value.code == 3


def test_path_with_empty_entry_refused(env, monkeypatch):
    monkeypatch.setenv("PATH", f"{env['node'].parent}{os.pathsep}/usr/bin{os.pathsep}")
    assert code_of(env) == 3


def test_path_with_relative_entry_refused(env, monkeypatch):
    monkeypatch.setenv("PATH", f"{env['node'].parent}{os.pathsep}/usr/bin{os.pathsep}bin")
    assert code_of(env) == 3


def _fake_run(monkeypatch, result=None, exc=None):
    def fake(cmd, **kw):
        if exc:
            raise exc
        return result

    monkeypatch.setattr(reflektor.subprocess, "run", fake)


def test_node_major_success(monkeypatch):
    _fake_run(monkeypatch, subprocess.CompletedProcess([], 0, "v22.3.1\n", ""))
    assert reflektor._node_major("node") == 22


def test_node_major_not_found(monkeypatch):
    _fake_run(monkeypatch, exc=FileNotFoundError())
    assert reflektor._node_major("node") is None


def test_node_major_timeout(monkeypatch):
    _fake_run(monkeypatch, exc=subprocess.TimeoutExpired("node", 20))
    assert reflektor._node_major("node") is None


def test_node_major_nonzero_exit(monkeypatch):
    _fake_run(monkeypatch, subprocess.CompletedProcess([], 1, "v22.3.1\n", ""))
    assert reflektor._node_major("node") is None


def test_node_major_unparsable(monkeypatch):
    _fake_run(monkeypatch, subprocess.CompletedProcess([], 0, "hello\n", ""))
    assert reflektor._node_major("node") is None


def test_fetch_failure_code_is_kept(env):
    def failing(url, limit):
        raise PrepareError(3, "download failed: x")

    assert code_of(env, fetch=failing) == 3


def test_download_longer_than_pin_refused(env):
    data = make_tar()
    pin = {**pin_for(data), "size": len(data) - 1}
    with pytest.raises(PrepareError) as exc:
        reflektor.prepare(env["dest"], env["repo"], env["base"], pin=pin, fetch=lambda u, n: data,
                          node_major=lambda n: 22)
    assert exc.value.code == 1


def test_download_shorter_than_pin_refused(env):
    data = make_tar()
    pin = {**pin_for(data), "size": len(data) + 1}
    with pytest.raises(PrepareError) as exc:
        reflektor.prepare(env["dest"], env["repo"], env["base"], pin=pin, fetch=lambda u, n: data,
                          node_major=lambda n: 22)
    assert exc.value.code == 1


def test_wrong_sha256_refused(env):
    data = make_tar()
    pin = {**pin_for(data), "sha256": "0" * 64}
    with pytest.raises(PrepareError) as exc:
        reflektor.prepare(env["dest"], env["repo"], env["base"], pin=pin, fetch=lambda u, n: data,
                          node_major=lambda n: 22)
    assert exc.value.code == 1


def test_not_gzip_refused(env):
    assert code_of(env, data=b"not gzip") == 1


def test_gzip_but_not_tar_refused(env):
    assert code_of(env, data=gzip.compress(b"hello world, not a tar" * 50)) == 1


@pytest.mark.parametrize("name", ["../x", "/x", "a\\b", "a//b", "a/./b"])
def test_bad_member_names_refused(env, name):
    assert code_of(env, data=make_tar(extra=[member(name)])) == 1


@pytest.mark.parametrize("typ,kw", [
    (tarfile.SYMTYPE, {"linkname": "scripts/build.mjs"}),
    (tarfile.LNKTYPE, {"linkname": "scripts/build.mjs"}),
    (tarfile.CHRTYPE, {}),
    (tarfile.FIFOTYPE, {}),
])
def test_special_members_refused(env, typ, kw):
    assert code_of(env, data=make_tar(extra=[member("./evil", typ, **kw)])) == 1


def test_duplicate_member_refused(env):
    assert code_of(env, data=make_tar(extra=[member("./scripts/build.mjs")])) == 1


def test_file_followed_by_path_below_it_refused(env):
    files = {"scripts": b"x", **GOOD}
    assert code_of(env, data=make_tar(files=files)) == 1


def test_member_name_unit():
    assert reflektor._member_name("./a", False) == "a"
    assert reflektor._member_name("././a", False) == "a"
    assert reflektor._member_name(".", True) == ""
    with pytest.raises(PrepareError) as exc:
        reflektor._member_name("a\0b", False)
    assert exc.value.code == 1
    with pytest.raises(PrepareError):
        reflektor._member_name(".", False)


def test_bad_last_member_writes_nothing(env):
    assert code_of(env, data=make_tar(extra=[member("../x")])) == 1
    assert not (env["dest"] / "reflektor").exists()
    assert not (env["dest"].parent / "x").exists()


def test_existing_destination_refused(env):
    (env["dest"] / "reflektor").mkdir()
    assert code_of(env) == 1


@pytest.mark.parametrize("missing", ["assets/viewer.html", "SKILL.md", "scripts/collect.mjs", "scripts/build.mjs"])
def test_missing_required_file_refused(env, missing):
    files = {k: v for k, v in GOOD.items() if k != missing}
    assert code_of(env, data=make_tar(files=files)) == 1


def test_skill_without_build_section_refused(env):
    files = {**GOOD, "SKILL.md": b"## 5. Write report.json\nx\n"}
    assert code_of(env, data=make_tar(files=files)) == 1


def test_skill_without_report_section_refused(env):
    files = {**GOOD, "SKILL.md": b"## 6. Build\nx\n"}
    assert code_of(env, data=make_tar(files=files)) == 1


@pytest.mark.parametrize("url", [
    "http://example.invalid/x",
    "https://example.invalid/x",
    "https://github.com.example.invalid/x",
    "https://github.com@example.invalid/x",
])
def test_fetch_refuses_other_urls(url):
    with pytest.raises(PrepareError) as exc:
        reflektor._fetch(url, 10)
    assert exc.value.code == 1


class FakeResponse:
    def __init__(self, payload=b"", exc=None):
        self.payload, self.exc, self.pos = payload, exc, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        if self.exc:
            raise self.exc
        chunk = self.payload[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk


class FakeOpener:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.timeout = response, exc, None

    def open(self, url, timeout=None):
        self.timeout = timeout
        if self.exc:
            raise self.exc
        return self.response


def test_fetch_reads_at_most_limit_plus_one(monkeypatch):
    fake = FakeOpener(FakeResponse(b"x" * 1000))
    monkeypatch.setattr(reflektor.net, "opener", lambda: fake)
    got = reflektor._fetch(reflektor.PIN["url"], 100)
    assert got == b"x" * 101
    assert fake.timeout == 30


def test_fetch_small_payload_complete(monkeypatch):
    monkeypatch.setattr(reflektor.net, "opener", lambda: FakeOpener(FakeResponse(b"abc")))
    assert reflektor._fetch(reflektor.PIN["url"], 100) == b"abc"


@pytest.mark.parametrize("exc", [
    urllib.error.URLError("x"), OSError("x"), http.client.HTTPException("x"), TimeoutError("x"),
])
def test_fetch_maps_errors_on_open(monkeypatch, exc):
    monkeypatch.setattr(reflektor.net, "opener", lambda: FakeOpener(exc=exc))
    with pytest.raises(PrepareError) as e:
        reflektor._fetch(reflektor.PIN["url"], 10)
    assert e.value.code == 3


@pytest.mark.parametrize("exc", [
    urllib.error.URLError("x"), OSError("x"), http.client.HTTPException("x"), TimeoutError("x"),
])
def test_fetch_maps_errors_on_read(monkeypatch, exc):
    monkeypatch.setattr(reflektor.net, "opener", lambda: FakeOpener(FakeResponse(exc=exc)))
    with pytest.raises(PrepareError) as e:
        reflektor._fetch(reflektor.PIN["url"], 10)
    assert e.value.code == 3


def test_fetch_deadline(monkeypatch):
    monkeypatch.setattr(reflektor.net, "opener", lambda: FakeOpener(FakeResponse(b"x" * 1000)))
    clock = iter([0.0, 1000.0, 2000.0, 3000.0])
    monkeypatch.setattr(reflektor.time, "monotonic", lambda: next(clock))
    with pytest.raises(PrepareError) as e:
        reflektor._fetch(reflektor.PIN["url"], 500)
    assert e.value.code == 3
    assert "timed out" in e.value.message


def test_main_success_prints_paths(env, monkeypatch, capsys):
    data = make_tar()
    monkeypatch.setattr(reflektor, "_fetch", lambda url, limit: data)
    monkeypatch.setattr(reflektor, "_node_major", lambda node: 22)
    monkeypatch.setattr(reflektor, "PIN", pin_for(data))
    rc = reflektor.main(["prepare", "--dest", str(env["dest"]), "--repo", str(env["repo"]), "--base", env["base"]])
    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == str(env["dest"].resolve() / "reflektor")
    assert lines[1] == str(env["node"])


def test_main_refuses_hooks_with_prefix(env, monkeypatch, capsys):
    _config(env, '{"hooks": {}}')
    rc = reflektor.main(["prepare", "--dest", str(env["dest"]), "--repo", str(env["repo"]), "--base", env["base"]])
    assert rc == 3
    assert capsys.readouterr().err.startswith("tld roles: reflektor: ")


def test_pin_shape():
    assert reflektor.PIN["url"].startswith("https://github.com/bashovski/reflektor/releases/download/v0.9.1/")
    for key in ("sha256", "release_key_sha256"):
        assert len(reflektor.PIN[key]) == 64 and int(reflektor.PIN[key], 16) >= 0


def test_cli_refuses_hooks_without_network(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".reflektor.json").write_text('{"hooks": {"preRun": "x"}}')
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    done = subprocess.run([str(BIN), "roles", "reflektor-prepare", "--dest", "d", "--repo", str(repo), "--base", "HEAD"],
                          capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 3, done.stderr
    assert done.stderr.startswith("tld roles: reflektor: ")


def test_git_stub_in_cwd_never_runs_with_empty_path_entry(env, monkeypatch):
    cwd = env["tmp"] / "cwd"
    cwd.mkdir()
    marker = cwd / "marker"
    stub = cwd / "git"
    stub.write_text(f"#!/bin/sh\ntouch {marker}\n")
    stub.chmod(0o755)
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("PATH", f"{env['node'].parent}{os.pathsep}/usr/bin{os.pathsep}")
    assert code_of(env) == 3
    assert not marker.exists()


def test_git_missing_refused(env, monkeypatch):
    monkeypatch.setattr(reflektor.shutil, "which", lambda name: None)
    assert code_of(env) == 3
