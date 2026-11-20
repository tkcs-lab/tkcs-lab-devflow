"""Every `tld ops sysml ...` span of the playbooks runs through the wrapper in a fresh repository."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import ROOT
from tld.ops import sysml

PLAYBOOKS = ROOT / "playbooks"
FILES = ("sysml.md", "make-plan.md", "implement.md")
EXPECTED = {
    "sysml.md": {"check", "render"},
    "make-plan.md": {"new-change", "check", "archive", "render"},
    "implement.md": {"check", "render"},
}
SUBCOMMANDS = {"new-change", "check", "render", "archive"}
FLAGS = {"--profile", "--change", "--file", "--remove", "--check", "--json", "--root"}
SPAN = re.compile(r"`(tld ops sysml [^`]+)`")
API = "package Core {\n  part def Api { doc /* the api */ }\n}\n"
API2 = "package Core {\n  part def Api { doc /* the new api */ }\n}\n"
PROPOSAL = "# x\n\n## Why\n\nBecause.\n\n## What Changes\n\nThe api doc.\n\n## Impact\n\nNone.\n"
ID = "foo"


def extract(name):
    text = " ".join(re.sub(r"^> ?", "", l) for l in (PLAYBOOKS / name).read_text().splitlines()).split()
    text = " ".join(text)
    spans = []
    for m in SPAN.finditer(text):
        span = re.sub(r"<(?:slug|plan slug|sysml_change|id)>", ID, m.group(1))
        span = span.replace("<relpath>", "core/api.sysml")
        spans.append(span)
    return spans


def write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)


def make_repo(root: Path, with_change: bool) -> None:
    write(root, ".tld/toolkit.yaml", "sysml:\n  subset: 1\n")
    write(root, "sysml/model/core/api.sysml", API)
    assert sysml.main(["render", "--root", str(root)]) == 0
    if with_change:
        assert sysml.main(["new-change", ID, "--file", "core/api.sysml", "--root", str(root)]) == 0
        write(root, f"sysml/changes/{ID}/model/core/api.sysml", API2)
        write(root, f"sysml/changes/{ID}/proposal.md", PROPOSAL)


@pytest.mark.parametrize("name", FILES)
def test_the_subcommands_found_per_file(name):
    assert {s.split()[3] for s in extract(name)} == EXPECTED[name]


@pytest.mark.parametrize("name", FILES)
def test_every_tld_ops_sysml_span_runs_through_the_wrapper(name, tmp_path):
    spans = extract(name)
    assert spans
    for i, span in enumerate(spans):
        argv = span.split()[3:]
        assert argv[0] in SUBCOMMANDS, span
        assert {a for a in argv if a.startswith("--")} <= FLAGS, span
        assert argv[argv.index("--profile") + 1] == ".tld/toolkit.yaml", span
        root = tmp_path / f"repo{i}"
        make_repo(root, with_change=argv[0] == "archive" or "--change" in argv)
        argv[argv.index("--profile") + 1] = str(root / ".tld" / "toolkit.yaml")
        assert sysml.main(argv + ["--root", str(root)]) == 0, span


def test_implement_sends_back_sysml_touches_and_final_review_checks_the_archive():
    text = " ".join(re.sub(r"^> ?", "", l) for l in (PLAYBOOKS / "implement.md").read_text().splitlines()).split()
    text = " ".join(text)
    for sentence in (
        "With `sysml_change` in the manifest, a diff that touches `sysml/`, `docs/architecture.md` or "
        "`docs/architecture.svg` in any phase but the last is sent back, with the same revision and fix exception; "
        "with the profile's `sysml` block and no `sysml_change`, any diff that touches them is sent back.",
        "With `sysml_change`, after the merge of `origin/<main>` below run `tld ops sysml check --profile "
        ".tld/toolkit.yaml` and `tld ops sysml render --check --profile .tld/toolkit.yaml`; "
        "a conflict in `docs/architecture.md` or `docs/architecture.svg` is resolved by "
        "`tld ops sysml render --profile .tld/toolkit.yaml`, a conflict in a file under `sysml/` or a failing check "
        "stops the run with a blocking finding",
        "the files under `sysml/changes/<sysml_change>/` were authored by the plan and are not deviations",
        "`sysml/changes/<sysml_change>` must be gone",
        "every part def and port of the archived change under `sysml/changes/archive/` must be named by an "
        "acceptance item or a test",
    ):
        assert sentence in text, sentence


def test_make_plan_manifest_block_has_sysml_change_and_final_check():
    text = (PLAYBOOKS / "make-plan.md").read_text()
    flat = " ".join(text.split())
    assert "sysml_change: <plan slug>   # optional; architecture parts only; the architecture change this plan carries" in text
    assert (
        "  - <`tld ops sysml render --check --profile .tld/toolkit.yaml` and `tld ops sysml check --profile "
        ".tld/toolkit.yaml` exit 0 and `sysml/changes/<sysml_change>` does not exist>   # architecture parts only"
    ) in text
    assert text.index("spec_change: <plan slug>") < text.index("sysml_change: <plan slug>")
    assert "### The architecture change (architecture parts)" in text
    assert "Architecture change (architecture parts):" in text
    assert "Architecture parts: with `sysml_change`" in text
    assert "a `changed since` finding means" in flat and "`status=blocked`" in flat
    assert "must narrow its `touches` or carry `sysml_change`" in flat
