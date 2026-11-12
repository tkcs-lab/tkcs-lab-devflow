"""deploy/install.sh, run offline under sh against a release directory built here (file:// base, no network)."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import ROOT, need_tool

pytestmark = pytest.mark.slow

INSTALL = ROOT / "deploy" / "install.sh"
COMPOSE = ROOT / "deploy" / "board" / "compose.yaml"
WHEEL = "tld-{v}-py3-none-any.whl"


@pytest.fixture(autouse=True)
def _tools() -> None:
    for name in ("sh", "curl", "sed"):
        need_tool(name)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_wheel(path: Path, version: str, printed: str) -> None:
    files = {
        "tld/__init__.py": "def main():\n    import sys\n    if sys.argv[1:] == ['--version']:\n"
                           f"        print('tld {printed}')\n",
        f"tld-{version}.dist-info/METADATA": f"Metadata-Version: 2.1\nName: tld\nVersion: {version}\n",
        f"tld-{version}.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"tld-{version}.dist-info/entry_points.txt": "[console_scripts]\ntld = tld:main\n",
    }
    record = []
    for name, text in files.items():
        data = text.encode()
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{name},sha256={digest},{len(data)}")
    record.append(f"tld-{version}.dist-info/RECORD,,")
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
        z.writestr(f"tld-{version}.dist-info/RECORD", "\n".join(record) + "\n")


def make_release(root: Path, version: str, printed: str | None = None, stamp_compose: bool = True) -> None:
    d = root / f"v{version}"
    d.mkdir(parents=True)
    wheel = d / WHEEL.format(v=version)
    write_wheel(wheel, version, printed or version)
    stamped = subprocess.run(["sed", f"s/@TLD_VERSION@/{version}/", str(INSTALL)],
                             capture_output=True, text=True, check=True).stdout
    (d / "install.sh").write_text(stamped)
    if stamp_compose:
        compose = subprocess.run(["sed", "s#@TLD_IMAGE@#registry.invalid/tld-board@sha256:abc#", str(COMPOSE)],
                                 capture_output=True, text=True, check=True).stdout
    else:
        compose = COMPOSE.read_text()
    (d / "compose.yaml").write_text(compose)
    sums = "".join(f"{sha(d / n)}  {n}\n" for n in (wheel.name, "install.sh", "compose.yaml"))
    (d / "SHA256SUMS").write_text(sums)


@pytest.fixture(scope="module")
def release(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("release")
    for v in ("9.9.7", "9.9.8", "9.9.9"):
        make_release(root, v)
    return root


def copy_release(release: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "rel"
    shutil.copytree(release, dest)
    return dest


FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$(dirname "$0")/docker.log"
case "$1" in
  compose)
    if [ "$2" = version ]; then exit "${FAKE_COMPOSE_EXIT:-0}"; fi
    if [ "$2" = pull ]; then exit "${FAKE_PULL_EXIT:-0}"; fi
    exit 0 ;;
  inspect)
    printf '%s\\n' "${FAKE_INSPECT_LABEL:-}"
    exit "${FAKE_INSPECT_EXIT:-1}" ;;
esac
exit 0
"""


def tools_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fake-tools"
    if not d.exists():
        d.mkdir()
        docker = d / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
    return d


def docker_log(tmp_path: Path) -> str:
    log = tools_dir(tmp_path) / "docker.log"
    return log.read_text() if log.exists() else ""


def make_env(tmp_path: Path, release_dir: Path, **overrides) -> dict[str, str]:
    env = {
        "PATH": f"{tools_dir(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "TLD_BIN_DIR": str(tmp_path / "bin"),
        "TLD_BOARD_DIR": str(tmp_path / "board"),
        "TMPDIR": str(tmp_path / "tmp"),
        "TLD_PYTHON": sys.executable,
        "TLD_RELEASE_BASE": f"file://{release_dir}",
        "TLD_PIP_ARGS": "--no-index --no-deps",
        "PIP_NO_INDEX": "1",
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
    }
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_installer(tmp_path: Path, args: list[str], release_dir: Path, script: Path | None = None,
                  version: str = "9.9.9", **overrides) -> subprocess.CompletedProcess:
    script = script or release_dir / f"v{version}" / "install.sh"
    env = make_env(tmp_path, release_dir, **overrides)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    return subprocess.run(["sh", str(script), *args], env=env, capture_output=True, text=True, timeout=300)


def link(tmp_path: Path) -> Path:
    return tmp_path / "bin" / "tld"


def venvs(tmp_path: Path) -> set[str]:
    d = tmp_path / "data" / "tld" / "venvs"
    return {p.name for p in d.iterdir()} if d.exists() else set()


def tld_version(tmp_path: Path) -> str:
    return subprocess.run([str(link(tmp_path)), "--version"], capture_output=True, text=True).stdout.strip()


def install(tmp_path: Path, release: Path, version: str) -> None:
    r = run_installer(tmp_path, [], release, version=version)
    assert r.returncode == 0, r.stderr


def test_run_installer_env_is_confined(tmp_path, release) -> None:
    env = make_env(tmp_path, release, EXTRA="1")
    assert set(env) == {"PATH", "HOME", "XDG_DATA_HOME", "TLD_BIN_DIR", "TLD_BOARD_DIR", "TMPDIR", "TLD_PYTHON",
                        "TLD_RELEASE_BASE", "TLD_PIP_ARGS", "PIP_NO_INDEX", "http_proxy", "https_proxy",
                        "HTTPS_PROXY", "EXTRA"}
    for key in ("HOME", "XDG_DATA_HOME", "TLD_BIN_DIR", "TLD_BOARD_DIR", "TMPDIR"):
        assert Path(env[key]).is_relative_to(tmp_path)
    assert env["PATH"] == f"{tmp_path / 'fake-tools'}:/usr/bin:/bin"
    assert "TLD_PYTHON" not in make_env(tmp_path, release, TLD_PYTHON=None)


def test_cli_install_links_a_working_tld(tmp_path, release) -> None:
    r = run_installer(tmp_path, [], release)
    assert r.returncode == 0, r.stderr
    assert tld_version(tmp_path) == "tld 9.9.9"
    assert f"tld 9.9.9 installed: {link(tmp_path)}" in r.stdout


def test_rerun_of_the_same_version_keeps_a_working_tld(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.9")
    install(tmp_path, release, "9.9.9")
    assert tld_version(tmp_path) == "tld 9.9.9"
    assert venvs(tmp_path) == {"9.9.9"}


def test_rerun_with_failing_pip_keeps_the_working_link_and_venv(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.9")
    before = os.readlink(link(tmp_path))
    r = run_installer(tmp_path, [], release, TLD_PIP_ARGS="--no-index --no-deps --no-such-option")
    assert r.returncode == 0, r.stderr
    assert "tld 9.9.9 is already installed" in r.stdout
    assert os.readlink(link(tmp_path)) == before
    assert tld_version(tmp_path) == "tld 9.9.9"


def test_rerun_with_a_broken_venv_rebuilds_it(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.9")
    entry = tmp_path / "data" / "tld" / "venvs" / "9.9.9" / "bin" / "tld"
    entry.write_text("#!/bin/sh\necho broken\n")
    r = run_installer(tmp_path, [], release)
    assert r.returncode == 0, r.stderr
    assert "already installed" not in r.stdout
    assert tld_version(tmp_path) == "tld 9.9.9"


def test_second_run_replaces_the_link_and_keeps_one_previous_venv(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.8")
    install(tmp_path, release, "9.9.9")
    assert venvs(tmp_path) == {"9.9.8", "9.9.9"}
    assert os.readlink(link(tmp_path)).startswith(str(tmp_path / "data" / "tld" / "venvs" / "9.9.9"))


def test_install_prunes_all_but_current_and_previous(tmp_path, release) -> None:
    for v in ("9.9.7", "9.9.8", "9.9.9"):
        install(tmp_path, release, v)
    assert venvs(tmp_path) == {"9.9.8", "9.9.9"}


def test_failed_smoke_test_removes_the_venv_and_keeps_the_old_link(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.8")
    bad = tmp_path / "bad"
    make_release(bad, "9.9.9", printed="0.0.0")
    r = run_installer(tmp_path, [], bad)
    assert r.returncode == 1
    assert "expected 'tld 9.9.9'" in r.stderr
    assert "checksum mismatch" not in r.stderr
    assert "9.9.9" not in venvs(tmp_path)
    assert "/venvs/9.9.8/" in os.readlink(link(tmp_path))


def test_checksum_mismatch_is_refused_and_nothing_is_linked(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.8")
    rel = copy_release(release, tmp_path)
    wheel = rel / "v9.9.9" / WHEEL.format(v="9.9.9")
    wheel.write_bytes(wheel.read_bytes() + b"x")
    r = run_installer(tmp_path, [], rel)
    assert r.returncode == 1
    assert "checksum mismatch for tld-9.9.9-py3-none-any.whl: refusing to install" in r.stderr
    assert "/venvs/9.9.8/" in os.readlink(link(tmp_path))
    assert "9.9.9" not in venvs(tmp_path)


def test_missing_checksum_line_is_refused(tmp_path, release) -> None:
    rel = copy_release(release, tmp_path)
    sums = rel / "v9.9.9" / "SHA256SUMS"
    sums.write_text("".join(ln for ln in sums.read_text().splitlines(True) if "whl" not in ln))
    r = run_installer(tmp_path, [], rel)
    assert r.returncode == 1
    assert "no checksum for tld-9.9.9-py3-none-any.whl" in r.stderr


def test_unstamped_copy_refuses(tmp_path, release) -> None:
    r = run_installer(tmp_path, [], release, script=INSTALL)
    assert r.returncode == 1
    assert "not from a release" in r.stderr


def test_unstamped_copy_with_tld_version_installs(tmp_path, release) -> None:
    r = run_installer(tmp_path, [], release, script=INSTALL, TLD_VERSION="9.9.9")
    assert r.returncode == 0, r.stderr
    assert tld_version(tmp_path) == "tld 9.9.9"


def test_leading_v_is_dropped(tmp_path, release) -> None:
    r = run_installer(tmp_path, [], release, script=INSTALL, TLD_VERSION="v9.9.9")
    assert r.returncode == 0, r.stderr
    assert tld_version(tmp_path) == "tld 9.9.9"


@pytest.mark.parametrize("value", ["1.2", "1.2.3-rc1", "../../x", "9.9.9/../..", "9.9.9\nx", " 9.9.9", "1..2",
                                   ".9.9", "9.9.", "vv9.9.9", "9.9.9.9"])
def test_invalid_version_refused(tmp_path, release, value) -> None:
    r = run_installer(tmp_path, [], release, script=INSTALL, TLD_VERSION=value)
    assert r.returncode == 1
    assert "invalid version:" in r.stderr
    assert not (tmp_path / "data").exists()


def test_existing_regular_file_is_not_overwritten(tmp_path, release) -> None:
    (tmp_path / "bin").mkdir()
    link(tmp_path).write_text("mine")
    r = run_installer(tmp_path, [], release)
    assert r.returncode == 1
    assert "was not made by this installer" in r.stderr
    assert link(tmp_path).read_text() == "mine"


def test_uninstall_removes_link_and_data(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.9")
    board = tmp_path / "board"
    board.mkdir()
    (board / "keep").write_text("x")
    r = run_installer(tmp_path, ["uninstall"], release)
    assert r.returncode == 0, r.stderr
    assert not link(tmp_path).exists() and not link(tmp_path).is_symlink()
    assert not (tmp_path / "data" / "tld").exists()
    assert (board / "keep").read_text() == "x"


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_uninstall_leaves_a_foreign_tld(tmp_path, release, kind) -> None:
    (tmp_path / "bin").mkdir()
    if kind == "file":
        link(tmp_path).write_text("mine")
    else:
        link(tmp_path).symlink_to("/usr/bin/true")
    (tmp_path / "data" / "tld").mkdir(parents=True)
    r = run_installer(tmp_path, ["uninstall"], release)
    assert r.returncode == 0, r.stderr
    if kind == "file":
        assert link(tmp_path).read_text() == "mine"
    else:
        assert os.readlink(link(tmp_path)) == "/usr/bin/true"
    assert not (tmp_path / "data" / "tld").exists()


def test_unknown_mode_exits_2(tmp_path, release) -> None:
    r = run_installer(tmp_path, ["bogus"], release)
    assert r.returncode == 2
    assert "usage: install.sh [cli|board|uninstall]" in r.stderr


def test_missing_release_says_no_assets(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run_installer(tmp_path, [], empty, script=INSTALL, TLD_VERSION="9.9.9")
    assert r.returncode == 1
    assert "cannot download" in r.stderr and "has none" in r.stderr


FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
exit 22
"""


def curl_args(tmp_path: Path, base: str) -> str:
    """The arguments the installer gives `curl`, recorded by a fake `curl` that always fails the download."""
    tools = tools_dir(tmp_path)
    curl = tools / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    log = tmp_path / "curl.log"
    r = run_installer(tmp_path, [], tmp_path, script=INSTALL, TLD_VERSION="9.9.9", TLD_RELEASE_BASE=base,
                      CURL_LOG=str(log))
    assert r.returncode == 1 and "cannot download" in r.stderr
    return log.read_text()


def test_https_download_is_pinned_to_https_and_tls_1_2(tmp_path) -> None:
    args = curl_args(tmp_path, "https://example.invalid")
    for flag in ("--proto =https", "--proto-redir =https", "--tlsv1.2"):
        assert flag in args, flag


def test_file_download_has_no_protocol_pins(tmp_path) -> None:
    args = curl_args(tmp_path, f"file://{tmp_path}")
    assert "--proto" not in args and "--tlsv1.2" not in args


def test_old_python3_only_is_refused(tmp_path, release) -> None:
    tools = tools_dir(tmp_path)
    for name in ("python3.13", "python3.12", "python3.11", "python3"):
        fake = tools / name
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
    r = run_installer(tmp_path, [], release, TLD_PYTHON=None)
    assert r.returncode == 1
    assert "need Python 3.11 or newer" in r.stderr
    assert not (tmp_path / "data" / "tld" / "venvs").exists()


def test_venv_failure_names_python3_venv(tmp_path, release) -> None:
    fake = tmp_path / "badpython"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    r = run_installer(tmp_path, [], release, TLD_PYTHON=str(fake))
    assert r.returncode == 1
    assert "python3-venv" in r.stderr


def test_path_hint_only_when_bin_is_not_on_path(tmp_path, release) -> None:
    r = run_installer(tmp_path, [], release)
    assert "export PATH=" in r.stdout
    on_path = make_env(tmp_path, release)["PATH"] + f":{tmp_path / 'bin'}"
    r = run_installer(tmp_path, [], release, PATH=on_path)
    assert r.returncode == 0, r.stderr
    assert "export PATH=" not in r.stdout


def test_temp_dir_is_removed(tmp_path, release) -> None:
    assert run_installer(tmp_path, [], release).returncode == 0
    assert list((tmp_path / "tmp").iterdir()) == []
    rel = copy_release(release, tmp_path)
    (rel / "v9.9.9" / WHEEL.format(v="9.9.9")).write_bytes(b"x")
    assert run_installer(tmp_path, [], rel).returncode == 1
    assert list((tmp_path / "tmp").iterdir()) == []


def test_pip_failure_removes_the_venv(tmp_path, release) -> None:
    install(tmp_path, release, "9.9.8")
    before = os.readlink(link(tmp_path))
    r = run_installer(tmp_path, [], release, TLD_PIP_ARGS="--no-index --no-deps --no-such-option")
    assert r.returncode == 1
    assert "could not install the wheel" in r.stderr
    assert "9.9.9" not in venvs(tmp_path)
    assert os.readlink(link(tmp_path)) == before


# ---- board ----------------------------------------------------------------------------------------
def env_file(tmp_path: Path) -> Path:
    return tmp_path / "board" / ".env"


def seed_env(tmp_path: Path, passphrase: str = "", origin: str = "") -> None:
    (tmp_path / "board").mkdir(exist_ok=True)
    env_file(tmp_path).write_text(
        f"TLD_BOARD_TOKEN={'a' * 64}\nTLD_BOARD_OWNER_PASSPHRASE={passphrase}\n"
        f"TLD_BOARD_PUBLIC_ORIGIN={origin}\nTLD_BOARD_SESSION_URL=https://claude.ai/code/\n")


def test_board_creates_env_once_with_mode_0600_and_does_not_print_the_token(tmp_path, release) -> None:
    r = run_installer(tmp_path, ["board"], release)
    assert r.returncode == 0, r.stderr
    text = env_file(tmp_path).read_text()
    m = re.search(r"^TLD_BOARD_TOKEN=([0-9a-f]{64})$", text, re.M)
    assert m
    token = m.group(1)
    assert token not in r.stdout and token not in r.stderr and token not in docker_log(tmp_path)
    assert stat.S_IMODE(env_file(tmp_path).stat().st_mode) == 0o600
    first = env_file(tmp_path).read_bytes()
    r = run_installer(tmp_path, ["board"], release)
    assert r.returncode == 0, r.stderr
    assert env_file(tmp_path).read_bytes() == first


@pytest.mark.parametrize("passphrase,origin,empty", [
    ("secret", "", ["TLD_BOARD_PUBLIC_ORIGIN"]),
    ("", "https://b.example.org", ["TLD_BOARD_OWNER_PASSPHRASE"]),
    ("", "", ["TLD_BOARD_OWNER_PASSPHRASE", "TLD_BOARD_PUBLIC_ORIGIN"]),
])
def test_board_does_not_start_without_passphrase_and_origin(tmp_path, release, passphrase, origin, empty) -> None:
    seed_env(tmp_path, passphrase, origin)
    r = run_installer(tmp_path, ["board"], release)
    assert r.returncode == 0, r.stderr
    assert " up" not in docker_log(tmp_path)
    for name in empty:
        assert name in r.stdout


def test_board_starts_when_both_are_set(tmp_path, release) -> None:
    seed_env(tmp_path, "secret", "https://b.example.org")
    r = run_installer(tmp_path, ["board"], release)
    assert r.returncode == 0, r.stderr
    log = docker_log(tmp_path)
    assert "compose pull" in log and "compose up -d" in log
    assert log.index("compose pull") < log.index("compose up -d")


@pytest.mark.parametrize("label", ["", "<no value>"])
def test_board_refuses_a_docker_run_container(tmp_path, release, label) -> None:
    r = run_installer(tmp_path, ["board"], release, FAKE_INSPECT_EXIT="0", FAKE_INSPECT_LABEL=label)
    assert r.returncode == 1
    assert "docker rm -f tld-board" in r.stderr


def test_board_upgrade_with_a_compose_container_proceeds(tmp_path, release) -> None:
    r = run_installer(tmp_path, ["board"], release, FAKE_INSPECT_EXIT="0", FAKE_INSPECT_LABEL="tld-board")
    assert r.returncode == 0, r.stderr
    assert "compose pull" in docker_log(tmp_path)


def test_board_denied_pull_prints_the_visibility_hint(tmp_path, release) -> None:
    r = run_installer(tmp_path, ["board"], release, FAKE_PULL_EXIT="1")
    assert r.returncode == 1
    assert "must be made public" in r.stderr
    assert " up" not in docker_log(tmp_path)


def test_board_keeps_compose_override_and_overwrites_compose_yaml(tmp_path, release) -> None:
    board = tmp_path / "board"
    board.mkdir()
    (board / "compose.override.yaml").write_text("mine\n")
    (board / "compose.yaml").write_text("old\n")
    r = run_installer(tmp_path, ["board"], release)
    assert r.returncode == 0, r.stderr
    assert (board / "compose.override.yaml").read_text() == "mine\n"
    assert "registry.invalid/tld-board@sha256:abc" in (board / "compose.yaml").read_text()


def test_board_checksum_mismatch_keeps_the_old_compose_yaml(tmp_path, release) -> None:
    rel = copy_release(release, tmp_path)
    (rel / "v9.9.9" / "compose.yaml").write_text("tampered\n")
    board = tmp_path / "board"
    board.mkdir()
    (board / "compose.yaml").write_text("old\n")
    r = run_installer(tmp_path, ["board"], rel)
    assert r.returncode == 1
    assert "checksum mismatch for compose.yaml" in r.stderr
    assert (board / "compose.yaml").read_text() == "old\n"


def test_board_unstamped_compose_refuses(tmp_path) -> None:
    rel = tmp_path / "rel"
    make_release(rel, "9.9.9", stamp_compose=False)
    r = run_installer(tmp_path, ["board"], rel)
    assert r.returncode == 1
    assert "compose.yaml is not stamped" in r.stderr
    assert "checksum mismatch" not in r.stderr
    assert "pull" not in docker_log(tmp_path)


def test_board_without_compose_plugin_refuses(tmp_path, release) -> None:
    r = run_installer(tmp_path, ["board"], release, FAKE_COMPOSE_EXIT="1")
    assert r.returncode == 1
    assert "Docker with the compose plugin is required" in r.stderr
    assert "pull" not in docker_log(tmp_path)


@pytest.mark.parametrize("dangling", [False, True])
def test_board_symlinked_env_is_refused_and_left_alone(tmp_path, release, dangling) -> None:
    (tmp_path / "board").mkdir()
    target = tmp_path / "elsewhere.env"
    if not dangling:
        target.write_text("TLD_BOARD_TOKEN=x\n")
        target.chmod(0o644)
    env_file(tmp_path).symlink_to(target)
    r = run_installer(tmp_path, ["board"], release)
    assert r.returncode == 1
    assert f"{env_file(tmp_path)} is a symlink: replace it with a regular file" in r.stderr
    assert "chmod" not in r.stderr
    assert "pull" not in docker_log(tmp_path) and " up" not in docker_log(tmp_path)
    if not dangling:
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
        assert target.read_text() == "TLD_BOARD_TOKEN=x\n"
    else:
        assert not target.exists()


def test_foreign_symlink_is_not_replaced(tmp_path, release) -> None:
    (tmp_path / "bin").mkdir()
    link(tmp_path).symlink_to("/usr/bin/true")
    r = run_installer(tmp_path, [], release)
    assert r.returncode == 1
    assert "was not made by this installer" in r.stderr
    assert os.readlink(link(tmp_path)) == "/usr/bin/true"
    assert "9.9.9" not in venvs(tmp_path)


def test_docs_name_every_installer_variable() -> None:
    """Every TLD_* name the installer reads is in the delivery or board-server guide."""
    text = (ROOT / "docs" / "guides" / "delivery.md").read_text() + (ROOT / "docs" / "guides" / "board-server.md").read_text()
    names = set(re.findall(r"TLD_[A-Z_]+", INSTALL.read_text()))
    assert {"TLD_VERSION", "TLD_PYTHON", "TLD_BIN_DIR", "TLD_BOARD_DIR"} <= names
    for name in sorted(names):
        assert name in text, name
