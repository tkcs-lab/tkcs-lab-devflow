"""Every `tld ops spec ...` span of the playbooks runs through the wrapper with fixed OpenSpec arguments."""
from __future__ import annotations

import json
import re

import pytest

from conftest import ROOT, _load

PLAYBOOKS = ROOT / "playbooks"
FILES = ("spec.md", "make-plan.md", "implement.md")
EXPECTED = {
    "spec.md": {"init", "new-change", "list", "validate", "archive"},
    "make-plan.md": {"new-change", "validate", "archive"},
    "implement.md": {"validate"},
}
# The forms of plan section 3.2 with the id "foo".
FORMS = [
    ["init", "--tools", "none", "--no-animation"],
    ["new", "change", "foo"],
    ["list", "--specs"],
    ["list", "--specs", "--json"],
    ["validate", "--all", "--strict", "--no-interactive"],
    ["validate", "foo", "--type", "change", "--strict", "--no-interactive"],
    ["archive", "foo", "--yes"],
]
SPAN = re.compile(r"`(tld ops spec [^`]+)`")


def extract(name):
    text = " ".join((PLAYBOOKS / name).read_text().split())
    return [re.sub(r"<[^>]+>", "foo", m.group(1)).replace("baseline-foo", "foo") for m in SPAN.finditer(text)]


def subcommand(span):
    return span.split()[3]


@pytest.mark.parametrize("name", FILES)
def test_the_subcommands_found_per_file(name):
    assert {subcommand(s) for s in extract(name)} == EXPECTED[name]


@pytest.mark.parametrize("name", FILES)
def test_every_tld_ops_spec_span_runs_through_the_wrapper(name, tmp_path, monkeypatch):
    spec = _load("tld.ops.spec")
    cache = tmp_path / "cache"
    pkg = cache / "openspec" / "2.1.0" / "node_modules" / "@fission-ai" / "openspec" / "package.json"
    pkg.parent.mkdir(parents=True)
    pkg.write_text(json.dumps({"version": "2.1.0"}))
    monkeypatch.setenv("TLD_CACHE_DIR", str(cache))
    profile = tmp_path / "toolkit.yaml"
    profile.write_text('spec:\n  version: "2.1.0"\n')
    calls = []
    monkeypatch.setattr(spec, "_which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(spec, "_node_version", lambda: "22.20.0")
    monkeypatch.setattr(spec, "_run", lambda argv, cwd, env, timeout: calls.append(argv) or 0)
    spans = extract(name)
    assert spans
    for span in spans:
        argv = span.split()[3:]
        if "--profile" not in argv:
            argv += ["--profile", str(profile)]
        else:
            argv[argv.index("--profile") + 1] = str(profile)
        calls.clear()
        assert spec.main(argv + ["--root", str(tmp_path)]) == 0, span
        assert len(calls) == 1, span
        assert calls[0][0] == "node" and calls[0][2:] in FORMS, (span, calls[0])
