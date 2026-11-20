#!/usr/bin/env python3
"""Run the pinned OpenSpec CLI through five fixed subcommands; no other OpenSpec argument is passed through.

    spec.py init                              [--profile .tld/toolkit.yaml] [--root .]
    spec.py new-change ID                     [--profile .tld/toolkit.yaml] [--root .]
    spec.py list [--json]                     [--profile .tld/toolkit.yaml] [--root .]
    spec.py validate [--change ID] [--json]   [--profile .tld/toolkit.yaml] [--root .]
    spec.py archive ID                        [--profile .tld/toolkit.yaml] [--root .]

The OpenSpec release is `spec.version` in the profile. It is installed once per version into
`$TLD_CACHE_DIR/openspec/<version>` (default `~/.cache/tld/openspec/<version>`), outside the repository, with
`npm install --ignore-scripts`, and run with `node` in `--root`. Both npm and node get an allowlisted environment
(no tokens), stdin is /dev/null, and a run ends after 600 seconds. Usage errors, a bad id, a bad profile, a missing
or too old Node.js and a failed install exit 2; otherwise the exit code is OpenSpec's.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

DEFAULT_PROFILE = ".tld/toolkit.yaml"
MIN_NODE = (22, 20, 0)
TIMEOUT = 600
ID_RE = r"[a-z0-9]+(-[a-z0-9]+)*"
VERSION_RE = r"\d+\.\d+\.\d+"
REGISTRY = "https://registry.npmjs.org/"
ENV_NAMES = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS")
FIXED_ENV = {"npm_config_ignore_scripts": "true", "npm_config_registry": REGISTRY, "OPENSPEC_TELEMETRY": "0",
             "DO_NOT_TRACK": "1", "CI": "1"}


class Fail(Exception):
    """A check failed: the message is the stderr line, the exit code is 2."""


def _which(name: str) -> str | None:
    return shutil.which(name)


def _env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_NAMES if k in os.environ}
    env.update(FIXED_ENV)
    return env


def _node_version() -> str | None:
    try:
        proc = subprocess.run(["node", "--version"], capture_output=True, text=True, env=_env(),
                              stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().removeprefix("v").strip() or None


def _run(argv: list[str], cwd: Path | str, env: dict[str, str], timeout: int) -> int:
    return subprocess.run(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, timeout=timeout).returncode


def build_args(sub: str, ns: argparse.Namespace) -> list[str]:
    if sub == "init":
        return ["init", "--tools", "none", "--no-animation"]
    if sub == "new-change":
        return ["new", "change", ns.id]
    if sub == "list":
        return ["list", "--specs"] + (["--json"] if ns.json else [])
    if sub == "validate":
        base = (["validate", ns.change, "--type", "change", "--strict", "--no-interactive"] if ns.change
                else ["validate", "--all", "--strict", "--no-interactive"])
        return base + (["--json"] if ns.json else [])
    return ["archive", ns.id, "--yes"]


def _version_tuple(text: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", text)
    return tuple(int(x) for x in m.groups()) if m else None


def _check(ns: argparse.Namespace, root: Path) -> str:
    """Run the checks in order; return the pinned version."""
    for ident in (getattr(ns, "id", None), getattr(ns, "change", None)):
        if ident is not None and not re.fullmatch(ID_RE, ident):
            raise Fail(f"tld ops spec: invalid id '{ident}': use lower-case words joined by hyphens")
    profile = Path(ns.profile) if ns.profile else root / DEFAULT_PROFILE
    if not profile.is_file():
        raise Fail(f"tld ops spec: profile not found: {profile}")
    try:
        data = yaml.safe_load(profile.read_text()) or {}
    except yaml.YAMLError:
        data = {}
    block = data.get("spec") if isinstance(data, dict) else None
    if not isinstance(block, dict) or "version" not in block:
        raise Fail("toolkit.yaml: missing required key 'spec.version' (add a spec block; see docs/guides/spec.md)")
    version = block["version"]
    if not isinstance(version, str) or not re.fullmatch(VERSION_RE, version):
        raise Fail(f"tld ops spec: spec.version must be an exact release such as 2.1.0 (got {version!r})")
    need = f"tld ops spec: node and npm are required (OpenSpec {version} needs Node.js 22.20.0 or newer)"
    if not _which("node") or not _which("npm"):
        raise Fail(need)
    found = _node_version()
    parsed = _version_tuple(found) if found else None
    if parsed is None:
        raise Fail(need)
    if parsed < MIN_NODE:
        raise Fail(f"tld ops spec: Node.js {found} is too old; OpenSpec {version} needs 22.20.0 or newer")
    return version


def _cache_root() -> Path:
    cache = os.environ.get("TLD_CACHE_DIR")
    return Path(cache) if cache else Path.home() / ".cache" / "tld"


def _install(version: str, env: dict[str, str]) -> Path:
    d = _cache_root() / "openspec" / version
    pkg = d / "node_modules" / "@fission-ai" / "openspec" / "package.json"
    if not pkg.is_file():
        d.mkdir(parents=True, exist_ok=True)
        (d / "package.json").write_text('{"private": true}\n')
        argv = ["npm", "install", "--ignore-scripts", "--no-save", "--no-audit", "--no-fund",
                "--registry", REGISTRY, f"@fission-ai/openspec@{version}"]
        code = _run(argv, d, env, TIMEOUT)
        if code != 0:
            raise Fail(f"tld ops spec: installing @fission-ai/openspec@{version} failed (exit {code})")
    try:
        installed = json.loads(pkg.read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        installed = None
    if installed != version:
        raise Fail(f"tld ops spec: installed version {installed} is not {version}")
    return d


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help=f"profile path (default {DEFAULT_PROFILE} under --root)")
    common.add_argument("--root", default=".", help="repository root, the working directory of OpenSpec (default: .)")
    ap = argparse.ArgumentParser(prog="tld ops spec", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{init,new-change,list,validate,archive}")
    sub.add_parser("init", parents=[common], help="openspec init, without tool files")
    sub.add_parser("new-change", parents=[common], help="create a change").add_argument("id", metavar="ID")
    sub.add_parser("list", parents=[common], help="list the specs").add_argument("--json", action="store_true")
    v = sub.add_parser("validate", parents=[common], help="validate all changes and specs, or one change")
    v.add_argument("--change", metavar="ID")
    v.add_argument("--json", action="store_true")
    sub.add_parser("archive", parents=[common], help="merge a change into the specs and archive it").add_argument(
        "id", metavar="ID")
    ns = ap.parse_args(argv)
    root = Path(ns.root)
    try:
        version = _check(ns, root)
        env = _env()
        d = _install(version, env)
        cmd = ["node", str(d / "node_modules" / "@fission-ai" / "openspec" / "bin" / "openspec.js"),
               *build_args(ns.cmd, ns)]
        return _run(cmd, root, env, TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"tld ops spec: OpenSpec did not finish within {TIMEOUT} seconds", file=sys.stderr)
        return 2
    except Fail as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
