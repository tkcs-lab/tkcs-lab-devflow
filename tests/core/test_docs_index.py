import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, TLD, CLAUDE, tld_cmd

SCRIPT = TLD / "ops" / "docs_index.py"
SCRIPT_CMD = tld_cmd("ops", "docs-index")
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
    cmd = [*SCRIPT_CMD, mode, "--root", str(root), *args]
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
    write(tmp_path, ".tld/toolkit.yaml",
          "docs:\n  index: docs/README.md\n  adr_dir: docs/adr\n  adr_index: docs/adr/README.md\n")
    r = run(tmp_path, "--profile", str(tmp_path / ".tld/toolkit.yaml"), index=None)
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
    write(tmp_path, ".tld/toolkit.yaml", "docs:\n  must_read: [README.md]\n")
    assert run(tmp_path, index=None).returncode == 2


def test_profile_names_the_index(tmp_path):
    make_repo(tmp_path)
    write(tmp_path, ".tld/toolkit.yaml", "docs:\n  index: docs/README.md\n")
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


# --------------------------------------------------------------------------------------------- move

def move_repo(root, files, commit=True):
    """A git repository with the given files, all committed."""
    for rel_path, text in files.items():
        write(root, rel_path, text)
    if commit:
        git(root, "init", "-q")
        git(root, "add", "-A")
        git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
    return root


def mv(root, src, dst, *args):
    return subprocess.run([*SCRIPT_CMD, "move", src, dst, "--root", str(root), *args],
                          capture_output=True, text=True)


def read(root, rel_path):
    return (root / rel_path).read_text()


def test_move_rewrites_link_in_another_doc_and_keeps_anchor(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# Hooks\n", "docs/other.md": "See [hooks](hooks.md#top) now.\n"})
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert r.returncode == 0, r.stderr
    assert read(tmp_path, "docs/other.md") == "See [hooks](architecture/hooks.md#top) now.\n"


def test_move_rebases_links_inside_the_moved_file(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# Hooks\n\n[up](../README.md) [peer](other.md#x) [web](https://e.com/a)\n",
                         "docs/other.md": "# O\n", "README.md": "# R\n"})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert read(tmp_path, "docs/architecture/hooks.md") == (
        "# Hooks\n\n[up](../../README.md) [peer](../other.md#x) [web](https://e.com/a)\n")


def test_move_rewrites_root_mentions_in_readme_and_py_even_in_code_spans(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "README.md": "Read `docs/hooks.md`, then docs/hooks.md.\n",
                         "tool.py": "NAME = 'docs/hooks.md'\n"})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert read(tmp_path, "README.md") == "Read `docs/architecture/hooks.md`, then docs/architecture/hooks.md.\n"
    assert read(tmp_path, "tool.py") == "NAME = 'docs/architecture/hooks.md'\n"


def test_move_rewrites_path_expression_and_keeps_the_root_prefix(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n",
                         "t.py": 'a = ROOT / "docs" / "hooks.md"\nb = ("docs"/"hooks.md")\nc = "x" / "docs" / "hooks.md"\n'})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    out = read(tmp_path, "t.py").splitlines()
    assert out[0] == 'a = ROOT / "docs" / "architecture" / "hooks.md"'
    assert out[1] == 'b = ("docs"/"architecture"/"hooks.md")'
    assert out[2] == 'c = "x" / "docs" / "hooks.md"'


def test_move_leaves_other_directories_and_longer_names_alone(tmp_path):
    text = "see plugins/docs/hooks.md and docs/hooks.md.bak\n"
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "README.md": text})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert read(tmp_path, "README.md") == text


def test_move_does_not_touch_fixture_files(tmp_path):
    text = "docs/hooks.md\n"
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "tests/fixtures/a.md": text, "evals/fixtures/b.py": text})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert read(tmp_path, "tests/fixtures/a.md") == text
    assert read(tmp_path, "evals/fixtures/b.py") == text


def test_move_honours_a_second_exclude(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "a/one.md": "docs/hooks.md\n", "b/two.md": "docs/hooks.md\n",
                         "c/three.md": "docs/hooks.md\n"})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply", "--exclude", "a/**", "--exclude", "b/**")
    assert read(tmp_path, "a/one.md") == "docs/hooks.md\n"
    assert read(tmp_path, "b/two.md") == "docs/hooks.md\n"
    assert read(tmp_path, "c/three.md") == "docs/architecture/hooks.md\n"


def test_move_does_not_touch_plan_documents(tmp_path):
    text = "mentions docs/hooks.md and [h](hooks.md)\n"
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "docs/x-plan.md": text, "docs/x-plan-manual-steps.html": text})
    mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert read(tmp_path, "docs/x-plan.md") == text
    assert read(tmp_path, "docs/x-plan-manual-steps.html") == text


def test_move_dry_run_changes_nothing_and_prints_the_plan(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "README.md": "docs/hooks.md\n"})
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md")
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert lines[0] == "move docs/hooks.md -> docs/architecture/hooks.md"
    assert "would rewrite README.md:1: docs/hooks.md -> docs/architecture/hooks.md" in lines
    assert lines[-1] == "move: 1 reference(s) in 1 file(s) would change, 0 unresolved"
    assert read(tmp_path, "README.md") == "docs/hooks.md\n"
    assert (tmp_path / "docs/hooks.md").is_file()
    assert not (tmp_path / "docs/architecture").exists()


def test_move_apply_uses_git_mv_and_removes_the_emptied_directory(tmp_path):
    move_repo(tmp_path, {"docs/design/spike.md": "# S\n", "README.md": "docs/design/spike.md\n"})
    r = mv(tmp_path, "docs/design/spike.md", "docs/architecture/spike.md", "--apply")
    assert r.stdout.splitlines()[-1] == (
        "move: moved docs/design/spike.md -> docs/architecture/spike.md, rewrote 1 reference(s) in 1 file(s), 0 unresolved")
    status = subprocess.run(["git", "-C", str(tmp_path), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert any(l.startswith("R") and "docs/design/spike.md -> docs/architecture/spike.md" in l for l in status.splitlines())
    assert not (tmp_path / "docs/design").exists()


def test_move_fails_when_destination_exists(tmp_path):
    move_repo(tmp_path, {"docs/a.md": "# A\n", "docs/b.md": "# B\n"})
    r = mv(tmp_path, "docs/a.md", "docs/b.md", "--apply")
    assert r.returncode == 1
    assert "move: 'docs/b.md' already exists" in r.stderr


def test_move_fails_when_destination_is_a_dangling_symlink(tmp_path):
    move_repo(tmp_path, {"docs/a.md": "# A\n", "README.md": "docs/a.md\n"})
    os.symlink("nowhere.md", tmp_path / "docs/dangling.md")
    r = mv(tmp_path, "docs/a.md", "docs/dangling.md", "--apply")
    assert r.returncode == 1
    assert "move: 'docs/dangling.md' already exists" in r.stderr
    assert os.readlink(tmp_path / "docs/dangling.md") == "nowhere.md"
    assert read(tmp_path, "docs/a.md") == "# A\n"
    assert read(tmp_path, "README.md") == "docs/a.md\n"


def test_move_does_not_fall_back_to_rename_when_git_mv_fails(tmp_path, monkeypatch):
    move_repo(tmp_path, {"docs/a.md": "# A\n", "README.md": "docs/a.md\n"})
    real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
    fake = tmp_path.parent / (tmp_path.name + "-bin")
    fake.mkdir()
    (fake / "git").write_text(f'#!/bin/sh\ncase "$*" in *" mv "*) echo boom >&2; exit 1;; esac\nexec {real} "$@"\n')
    (fake / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    r = mv(tmp_path, "docs/a.md", "docs/new/a.md", "--apply")
    assert r.returncode == 1
    assert "move: git mv failed: boom" in r.stderr
    assert read(tmp_path, "docs/a.md") == "# A\n"
    assert read(tmp_path, "README.md") == "docs/a.md\n"
    assert not (tmp_path / "docs/new").exists()


def test_move_fails_when_source_is_not_a_file(tmp_path):
    move_repo(tmp_path, {"docs/a.md": "# A\n"})
    r = mv(tmp_path, "docs/missing.md", "docs/b.md")
    assert r.returncode == 1
    assert "move: 'docs/missing.md' is not a file" in r.stderr
    assert mv(tmp_path, "docs", "x").returncode == 1


def test_move_reports_a_bare_mention_as_unresolved_without_rewriting(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "docs/n.md": "Read hooks.md for details.\n"})
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert "unresolved: docs/n.md:1: mentions 'hooks.md' without its directory" in r.stdout
    assert read(tmp_path, "docs/n.md") == "Read hooks.md for details.\n"


def test_move_does_not_report_the_text_of_a_rewritten_link(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "docs/n.md": "[hooks.md](hooks.md)\n"})
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md")
    assert "unresolved:" not in r.stdout


def test_move_reports_a_url_mention_as_unresolved(tmp_path):
    line = "See https://example.com/docs/hooks.md for it.\n"
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "README.md": line})
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert "unresolved: README.md:1: URL mentions 'docs/hooks.md'" in r.stdout
    assert read(tmp_path, "README.md") == line


def test_move_composes_over_two_calls(tmp_path):
    move_repo(tmp_path, {"docs/a.md": "# A\n\n[b](b.md)\n", "docs/b.md": "# B\n\n[a](a.md)\n", "README.md": "docs/a.md docs/b.md\n"})
    assert mv(tmp_path, "docs/a.md", "docs/architecture/a.md", "--apply").returncode == 0
    assert mv(tmp_path, "docs/b.md", "docs/guides/b.md", "--apply").returncode == 0
    assert read(tmp_path, "README.md") == "docs/architecture/a.md docs/guides/b.md\n"
    assert read(tmp_path, "docs/architecture/a.md") == "# A\n\n[b](../guides/b.md)\n"
    assert read(tmp_path, "docs/guides/b.md") == "# B\n\n[a](../architecture/a.md)\n"


def test_move_without_git_uses_rename(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "docs/o.md": "[h](hooks.md)\n"}, commit=False)
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--apply")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "docs/architecture/hooks.md").is_file() and not (tmp_path / "docs/hooks.md").exists()
    assert read(tmp_path, "docs/o.md") == "[h](architecture/hooks.md)\n"


def test_move_json_output_parses(tmp_path):
    move_repo(tmp_path, {"docs/hooks.md": "# H\n", "README.md": "docs/hooks.md and hooks.md\n"})
    r = mv(tmp_path, "docs/hooks.md", "docs/architecture/hooks.md", "--json")
    data = json.loads(r.stdout)
    assert data["changes"] == [{"file": "README.md", "line": 1, "old": "docs/hooks.md", "new": "docs/architecture/hooks.md"}]
    assert data["unresolved"][0]["kind"] == "bare"


def test_move_help_mentions_apply():
    r = subprocess.run([*SCRIPT_CMD, "move", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--apply" in r.stdout


def test_move_rule_functions_work_without_a_repository():
    from tld.ops import docs_index as mod
    assert mod.rewrite_root_mentions("a docs/x.md b", "docs/x.md", "docs/y/x.md")[0] == "a docs/y/x.md b"
    assert mod.rewrite_path_expressions('"docs" / "x.md"', "docs/x.md", "docs/y/x.md")[0] == '"docs" / "y" / "x.md"'
    text = "[x](x.md#a)\n```\n[x](x.md)\n```\n"
    assert mod.rewrite_links(text, "docs/i.md", "docs/i.md", "docs/x.md", "docs/y/x.md")[0].startswith("[x](y/x.md#a)")
    assert mod.find_unresolved("see x.md\n", "docs/x.md") == [(1, "bare", "mentions 'x.md' without its directory")]


REPO_ROOT = SCRIPT.parents[3]


def test_this_repository_docs_index_is_clean():
    r = subprocess.run([*SCRIPT_CMD, "check", "--index", "docs/README.md", "--root", str(REPO_ROOT)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "error:" not in r.stdout


def test_claude_md_is_thin():
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert len(text.splitlines()) <= 60
    assert "docs/README.md" in text
    assert "(AGENTS.md)" in text, "CLAUDE.md points to AGENTS.md, the agent entry"
    agents = (REPO_ROOT / "AGENTS.md").read_text()
    assert len(agents.splitlines()) <= 60 and "docs/README.md" in agents


def test_the_one_plugin_is_1_0_0_dev0():
    manifests = sorted(REPO_ROOT.glob("**/.claude-plugin/plugin.json"))
    assert manifests == [REPO_ROOT / ".claude-plugin" / "plugin.json"]
    assert json.loads(manifests[0].read_text())["version"] == "1.0.0-dev0"
