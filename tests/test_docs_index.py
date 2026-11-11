import json
import os
import subprocess
import sys

import pytest

from conftest import DEVFLOW

SCRIPT = DEVFLOW / "scripts" / "docs_index.py"
ROW = "answers the questions about the thing; read when changing the thing."


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def make_repo(root, *, claude=True, index=True, docs=("docs/guide.md",)):
    """A clean repository: CLAUDE.md links the index, the index lists every doc."""
    if claude:
        write(root, "CLAUDE.md", "# Demo\n\nOpen [docs/README.md](docs/README.md) first.\n")
    if index:
        rows = "".join(f"- [{Path_name(d)}]({d[len('docs/'):]}) - {ROW}\n" for d in docs)
        write(root, "docs/README.md", "# Docs index\n\n" + rows)
    for d in docs:
        write(root, d, f"# {Path_name(d)}\n\nA short summary of the doc.\n")
    return root


def Path_name(rel):
    return rel.rsplit("/", 1)[-1]


def run(root, *args, mode="check", index="docs/README.md"):
    cmd = [sys.executable, str(SCRIPT), mode, "--root", str(root), *args]
    if index:
        cmd += ["--index", index]
    return subprocess.run(cmd, capture_output=True, text=True)


def messages(proc):
    return [l for l in proc.stdout.splitlines() if l.startswith(("error:", "warning:"))]


def git(root, *args, env=None):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, **(env or {})})


def test_clean_repository_exits_zero(tmp_path):
    make_repo(tmp_path)
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[-1] == "docs index: 0 error(s), 0 warning(s)"


def test_missing_claude_md(tmp_path):
    make_repo(tmp_path, claude=False)
    r = run(tmp_path)
    assert r.returncode == 1
    assert "CLAUDE.md: missing (a thin CLAUDE.md that points to the docs index is required)" in r.stdout


def test_claude_md_over_limit(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "CLAUDE.md", "# Demo\n[index](docs/README.md)\n" + "line\n" * 70)
    r = run(tmp_path)
    assert r.returncode == 1
    assert "CLAUDE.md: 72 lines, over 60: it is loaded in every session, move the detail into docs/ and link the index" in r.stdout


def test_claude_md_without_index_link(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "CLAUDE.md", "# Demo\n\nNo link here.\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "CLAUDE.md: does not link to the docs index (docs/README.md)" in r.stdout


def test_missing_index(tmp_path):
    make_repo(tmp_path, index=False)
    r = run(tmp_path)
    assert r.returncode == 1
    assert "docs/README.md: the docs index is missing" in r.stdout


def test_index_over_limit(tmp_path):
    make_repo(tmp_path)
    text = (tmp_path / "docs/README.md").read_text() + "\n" * 160
    write(tmp_path, "docs/README.md", text)
    r = run(tmp_path)
    assert r.returncode == 1
    assert "docs/README.md: 163 lines, over 150: split the long sections into a README.md per directory and link them from the index" in r.stdout


def test_broken_link_in_index_is_an_error(tmp_path):
    make_repo(tmp_path)
    with open(tmp_path / "docs/README.md", "a") as f:
        f.write(f"- [gone](gone.md) - {ROW}\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "error: docs/README.md:4: broken link 'gone.md'" in r.stdout


def test_broken_link_in_other_doc_is_a_warning(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/guide.md", "# Guide\n\nSee [nothing](nothing.md).\n")
    r = run(tmp_path)
    assert r.returncode == 0
    assert "warning: docs/guide.md:3: broken link 'nothing.md'" in r.stdout


def test_unlisted_doc_is_an_error(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/orphan.md", "# Orphan\n\nNobody links me.\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "docs/orphan.md: not listed in the docs index (add a row, or move it to archive/)" in r.stdout


def test_plan_review_and_archive_are_not_reported(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/x-plan.md", "# Plan\n")
    write(tmp_path, "docs/x-review.md", "# Review\n")
    write(tmp_path, "docs/x-plan-manual-steps.md", "# Steps\n")
    write(tmp_path, "docs/archive/old.md", "# Old\n\nSee [x](missing.md).\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert messages(r) == []


def test_doc_listed_by_a_linked_section_readme_counts_as_listed(tmp_path):
    make_repo(tmp_path, docs=())
    write(tmp_path, "docs/README.md", f"# Docs index\n\n- [api/README.md](api/README.md) - the API docs, {ROW}\n")
    write(tmp_path, "docs/api/README.md", f"# API\n\n- [calls.md](calls.md) - {ROW}\n")
    write(tmp_path, "docs/api/calls.md", "# Calls\n\nThe calls.\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert messages(r) == []


def test_adr_missing_from_adr_index(tmp_path):
    make_repo(tmp_path, docs=())
    write(tmp_path, "docs/README.md", f"# Docs index\n\n- [adr/README.md](adr/README.md) - the decisions, {ROW}\n")
    write(tmp_path, "docs/adr/README.md", f"# ADRs\n\n- [0001-a.md](0001-a.md) - {ROW}\n")
    write(tmp_path, "docs/adr/0001-a.md", "# A\n\nDecided.\n")
    write(tmp_path, "docs/adr/0002-b.md", "# B\n\nDecided.\n")
    write(tmp_path, ".claude/toolkit.yaml",
          "docs:\n  index: docs/README.md\n  adr_dir: docs/adr\n  adr_index: docs/adr/README.md\n")
    r = run(tmp_path, "--profile", str(tmp_path / ".claude/toolkit.yaml"), index=None)
    assert r.returncode == 1
    assert "docs/adr/0002-b.md: not listed in the ADR index (docs/adr/README.md)" in r.stdout
    assert "0001-a.md: not listed" not in r.stdout


def test_row_without_description_is_a_warning(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/README.md", "# Docs index\n\n- [guide.md](guide.md)\n")
    r = run(tmp_path)
    assert r.returncode == 0
    assert "warning: docs/README.md:3: 'guide.md' has no description (say what it answers and when to read it)" in r.stdout


def test_doubly_listed_doc_is_a_warning(tmp_path):
    make_repo(tmp_path)
    with open(tmp_path / "docs/README.md", "a") as f:
        f.write(f"- [guide again](guide.md) - {ROW}\n")
    r = run(tmp_path)
    assert r.returncode == 0
    assert "warning: docs/README.md:4: 'guide.md' is listed twice in this file" in r.stdout


def test_long_doc_is_a_warning(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/guide.md", "# Guide\n" + "text\n" * 20)
    r = run(tmp_path, "--max-doc-lines", "10")
    assert r.returncode == 0
    assert "docs/guide.md: 21 lines, over 10: split it so a reader can open only the part they need" in r.stdout


def test_stale_days_reports_old_docs_and_ignores_plans(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/x-plan.md", "# Plan\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    old = "2020-01-01T00:00:00"
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init",
        env={"GIT_COMMITTER_DATE": old, "GIT_AUTHOR_DATE": old})
    r = run(tmp_path, "--stale-days", "30")
    assert "docs/guide.md: not changed for " in r.stdout
    assert "days: confirm it is current, or move it to archive/" in r.stdout
    assert "x-plan.md" not in r.stdout
    assert r.returncode == 0
    assert "not changed" not in run(tmp_path).stdout


def test_strict_turns_a_warning_into_exit_one(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/guide.md", "# Guide\n\nSee [nothing](nothing.md).\n")
    assert run(tmp_path).returncode == 0
    r = run(tmp_path, "--strict")
    assert r.returncode == 1
    assert "docs index: 0 error(s), 1 warning(s)" in r.stdout


def test_missing_index_key_exits_two(tmp_path):
    make_repo(tmp_path)
    for args in ([], ["--profile", str(tmp_path / "nope.yaml")]):
        r = run(tmp_path, *args, index=None)
        assert r.returncode == 2
        assert "toolkit.yaml: missing required key 'docs.index' (or pass --index)" in r.stderr
    write(tmp_path, ".claude/toolkit.yaml", "docs:\n  must_read: [README.md]\n")
    assert run(tmp_path, index=None).returncode == 2


def test_profile_names_the_index(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, ".claude/toolkit.yaml", "docs:\n  index: docs/README.md\n")
    r = run(tmp_path, index=None)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_json(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/orphan.md", "# Orphan\n")
    r = run(tmp_path, "--json")
    data = json.loads(r.stdout)
    assert set(data) == {"errors", "warnings"}
    assert data["errors"] == ["docs/orphan.md: not listed in the docs index (add a row, or move it to archive/)"]
    assert data["warnings"] == []
    assert r.returncode == 1


def test_inventory_json(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/other.md", "# Other\n\nNot linked from the index.\n")
    write(tmp_path, "docs/x-plan.md", "# Plan\n\nA plan.\n")
    r = run(tmp_path, "--json", mode="inventory")
    assert r.returncode == 0
    items = {i["path"]: i for i in json.loads(r.stdout)}
    keys = {"path", "title", "lines", "summary", "age_days", "linked_from", "in_index", "plan"}
    assert all(set(i) == keys for i in items.values())
    assert items["docs/guide.md"]["in_index"] is True
    assert items["docs/guide.md"]["linked_from"] == ["docs/README.md"]
    assert items["docs/guide.md"]["title"] == "guide.md"
    assert items["docs/other.md"]["in_index"] is False
    assert items["docs/other.md"]["linked_from"] == []
    assert items["docs/x-plan.md"]["plan"] is True


def test_inventory_lists_claude_md_as_a_linker(tmp_path):
    make_repo(tmp_path)
    items = {i["path"]: i for i in json.loads(run(tmp_path, "--json", mode="inventory").stdout)}
    assert items["docs/README.md"]["linked_from"] == ["CLAUDE.md"]


def test_inventory_text_marks_docs_not_in_the_index(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, "docs/other.md", "# Other\n\nNot linked from the index.\n")
    r = run(tmp_path, mode="inventory")
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    other = next(l for l in lines if l.startswith("docs/other.md"))
    assert "[NOT IN INDEX]" in other
    assert "[NOT IN INDEX]" not in next(l for l in lines if l.startswith("docs/guide.md"))
