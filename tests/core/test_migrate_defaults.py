"""tld migrate --defaults: files off their default path (plan 90, section 3.7, p11)."""
from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from conftest import _load, tld_cmd

md = _load("tld.ops.migrate_defaults")

PROFILE = """\
# the project's own profile
tld:
  version: ">=1.0,<2"

project:
  name: demo

docs:
  must_read:
    - README.md   # read first
  plan_dir: docs/

git:
  main_branch: main
  branch_pattern: "<type>/<kebab-case>"

verify:
  fast:
    - "true"
  dod:
    - "true"
"""


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
                          capture_output=True, text=True, check=True).stdout


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def repo(tmp_path, profile=PROFILE, files=None, tracked=False):
    root = tmp_path / "r"
    write(root, ".tld/toolkit.yaml", profile)
    write(root, "README.md", "# Demo\n")
    for rel, text in (files or {}).items():
        write(root, rel, text)
    if tracked:
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
    return root


def migrate(root, *args):
    return subprocess.run([*tld_cmd("migrate"), str(root), "--defaults", *args], capture_output=True, text=True,
                          timeout=120)


def answers(tmp_path, data):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(data))
    return str(path)


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git/" not in p.as_posix()}


def keys(root):
    return [c.key for c in md.plan(root, yaml.safe_load((root / ".tld/toolkit.yaml").read_text()))]


def test_off_default_changelog(tmp_path):
    root = repo(tmp_path, files={"CHANGES.md": "# Changes\n\n## Unreleased\n\n- a\n"})
    found = md.plan(root, yaml.safe_load(PROFILE))
    asked = {c.key: c for c in md.questions(found)}
    assert set(asked) == {"docs.changelog", "docs.changelog.section"}
    assert asked["docs.changelog"].path == "CHANGES.md" and asked["docs.changelog"].default_path == "CHANGELOG.md"
    assert asked["docs.changelog"].choices == ("rename", "keep")
    r = migrate(root)
    assert r.returncode == 0
    assert "[docs.changelog] CHANGES.md (default: CHANGELOG.md): rename | keep" in r.stdout


def test_nothing_off_the_default(tmp_path):
    root = repo(tmp_path, files={"docs/README.md": "# Docs\n"})
    r = migrate(root)
    assert r.returncode == 0 and "nothing is off its default path" in r.stdout
    assert "rename | keep" not in r.stdout  # nothing is asked
    assert md.questions(md.plan(root, yaml.safe_load(PROFILE))) == []


def test_defaults_without_write_changes_nothing(tmp_path):
    root = repo(tmp_path, tracked=True, files={"docs/index.md": "# Index\n", "docs/adrs/0001-a.md": "# A\n",
                                              "CHANGES.md": "## Unreleased\n"})
    before = tree(root)
    r = migrate(root)
    assert r.returncode == 0 and "docs.index" in r.stdout and "docs.adr_dir" in r.stdout
    assert tree(root) == before
    assert git(root, "status", "--porcelain") == ""


def test_write_without_answers_refused(tmp_path):
    root = repo(tmp_path, files={"docs/index.md": "# Index\n"})
    before = tree(root)
    r = migrate(root, "--write")
    assert r.returncode == 2 and "--answers" in r.stderr
    assert tree(root) == before


def test_unknown_answer_refused(tmp_path):
    root = repo(tmp_path, files={"docs/index.md": "# Index\n"})
    before = tree(root)
    for data, text in (({"docs.index": "copy"}, "unknown answer 'copy'"),
                       ({"docs.index": "keep", "docs.nothing": "keep"}, "unknown answer 'docs.nothing'"),
                       ({}, "no answer for: docs.index")):
        r = migrate(root, "--write", "--answers", answers(tmp_path, data))
        assert r.returncode == 2 and text in r.stderr
        assert tree(root) == before


def test_preserve_plan_dir_written_when_plans_exist(tmp_path):
    profile = PROFILE.replace("  plan_dir: docs/\n", "")
    root = repo(tmp_path, profile=profile, files={"docs/plans/7/plan.md": "# Plan\n"})
    assert "docs.plan_dir" in keys(root)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {}))
    assert r.returncode == 0, r.stdout + r.stderr
    data = yaml.safe_load((root / ".tld/toolkit.yaml").read_text())
    assert data["docs"]["plan_dir"] == "docs/plans/"
    assert "# read first" in (root / ".tld/toolkit.yaml").read_text()  # comments stay
    assert "OK" in r.stdout


def test_branch_types_from_existing_manifests(tmp_path):
    manifest = "# Plan\n\n```yaml\nplan_slug: x\nfeature_branch: docs/x-y\nphases: []\n```\n"
    root = repo(tmp_path, files={"docs/plans/3/plan.md": manifest, "docs/x-plan.md": manifest.replace("docs/", "feat/")})
    found = [c for c in md.plan(root, yaml.safe_load(PROFILE)) if c.key == "git.branch_types"]
    assert len(found) == 1 and found[0].value == ["feature", "fix", "chore", "docs", "feat"]
    r = migrate(root, "--write", "--answers", answers(tmp_path, {}))
    assert r.returncode == 0, r.stdout + r.stderr
    data = yaml.safe_load((root / ".tld/toolkit.yaml").read_text())
    assert data["git"]["branch_types"] == ["feature", "fix", "chore", "docs", "feat"]
    # a profile that already writes the types is left alone
    root2 = repo(tmp_path / "b", profile=PROFILE.replace("  main_branch: main\n", "  main_branch: main\n  branch_types: [feature]\n"),
                 files={"docs/plans/3/plan.md": manifest})
    assert "git.branch_types" not in keys(root2)


def test_moot_protect_paths_allow_listed(tmp_path):
    profile = PROFILE + ("hooks:\n  protect_paths_allow:\n    - .github/workflows/ci.yml\n"
                         "    - .github/workflows/tld-land.yml\n    - .env.example\n")
    root = repo(tmp_path, profile=profile)
    moot = [c for c in md.plan(root, yaml.safe_load(profile)) if c.kind == "moot"]
    assert [c.path for c in moot] == [".github/workflows/ci.yml"]  # the land workflow stays protected in code
    r = migrate(root)
    assert "hooks.protect_paths_allow entries made moot" in r.stdout and ".github/workflows/ci.yml" in r.stdout
    # an entry the repository's own list still protects is not moot
    own = PROFILE + "hooks:\n  protect_paths: ['.github/workflows/**']\n  protect_paths_allow: [.github/workflows/ci.yml]\n"
    assert [c for c in md.plan(root, yaml.safe_load(own)) if c.kind == "moot"] == []


def test_keys_equal_to_default_listed(tmp_path):
    profile = PROFILE.replace("  branch_pattern", "  merge_style: merge-commit\n  branch_pattern") + \
        "land:\n  max_prs: 5\ndocs_extra: {}\n"
    profile = profile.replace("docs_extra: {}\n", "")
    root = repo(tmp_path, profile=profile)
    equal = {c.key for c in md.plan(root, yaml.safe_load(profile)) if c.kind == "equal"}
    assert {"git.merge_style", "git.branch_pattern"} <= equal
    assert "land.max_prs" not in equal  # 5 is not the default
    r = migrate(root)
    assert "git.merge_style: same as the built-in default" in r.stdout
    assert yaml.safe_load((root / ".tld/toolkit.yaml").read_text())["git"]["merge_style"] == "merge-commit"  # listed only


def test_rename_rewrites_a_link(tmp_path):
    root = repo(tmp_path, tracked=True, files={"docs/index.md": "# Index\n\nSee [guide](guide.md).\n",
                                              "docs/guide.md": "# Guide\n\nBack to [the index](index.md).\n",
                                              "CLAUDE.md": "Read [docs/index.md](docs/index.md) first.\n"})
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.index": "rename"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (root / "docs/index.md").exists() and (root / "docs/README.md").read_text().startswith("# Index")
    assert "(README.md)" in (root / "docs/guide.md").read_text()
    assert "docs/README.md" in (root / "CLAUDE.md").read_text()
    assert "docs.index" not in (root / ".tld/toolkit.yaml").read_text()  # the default applies now
    assert "docs/README.md" in git(root, "status", "--porcelain")  # git mv: staged


def test_keep_writes_the_explicit_key(tmp_path):
    root = repo(tmp_path, files={"docs/index.md": "# Index\n", "docs/adrs/README.md": "# ADRs\n",
                                 "docs/adrs/0001-a.md": "# A\n", "CHANGES.md": "## [unreleased]\n\n- x\n"})
    r = migrate(root, "--write", "--answers", answers(
        tmp_path, {"docs.index": "keep", "docs.adr_dir": "keep", "docs.changelog": "keep",
                   "docs.changelog.section": "keep"}))
    assert r.returncode == 0, r.stdout + r.stderr
    text = (root / ".tld/toolkit.yaml").read_text()
    data = yaml.safe_load(text)
    assert data["docs"]["index"] == "docs/index.md"
    assert data["docs"]["adr_dir"] == "docs/adrs" and data["docs"]["adr_index"] == "docs/adrs/README.md"
    assert data["docs"]["changelog"] == {"file": "CHANGES.md", "section": "## [unreleased]", "policy": "unreleased"}
    assert "# the project's own profile" in text and "# read first" in text
    assert (root / "docs/index.md").exists() and (root / "CHANGES.md").exists()  # nothing moved
    assert "OK" in r.stdout


def test_adr_directory_rename_moves_every_file(tmp_path):
    root = repo(tmp_path, tracked=True, files={"docs/adrs/README.md": "# ADRs\n", "docs/adrs/0001-a.md": "# A\n",
                                               "docs/design.md": "See [A](adrs/0001-a.md).\n"})
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "docs/adr/0001-a.md").exists() and (root / "docs/adr/README.md").exists()
    assert not (root / "docs/adrs").exists()
    assert "(adr/0001-a.md)" in (root / "docs/design.md").read_text()


def test_heading_rename_and_file_rename(tmp_path):
    root = repo(tmp_path, tracked=True, files={"CHANGES.md": "# Changes\n\n## Unreleased\n\n- a\n"})
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename",
                                                                 "docs.changelog.section": "rename"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "CHANGELOG.md").read_text() == "# Changes\n\n## [Unreleased]\n\n- a\n"
    assert not (root / "CHANGES.md").exists()
    assert "changelog" not in yaml.safe_load((root / ".tld/toolkit.yaml").read_text())["docs"]


def test_rename_never_overwrites(tmp_path):
    # the default file exists: the off-default one is not even a find
    root = repo(tmp_path, files={"docs/index.md": "# Old\n", "docs/README.md": "# New\n"})
    assert "docs.index" not in keys(root)


def test_symbolic_links_are_not_followed(tmp_path):
    root = repo(tmp_path, files={"real/0001.md": "# A\n"})
    (root / "docs").mkdir()
    (root / "docs/adrs").symlink_to(root / "real")
    assert "docs.adr_dir" not in keys(root)
    root2 = repo(tmp_path / "b", files={"docs/adrs/0001.md": "# A\n"})
    (root2 / "docs/adrs/link.md").symlink_to(root2 / "README.md")
    asked = [c for c in md.questions(md.plan(root2, yaml.safe_load(PROFILE)))]
    assert [c.choices for c in asked] == [("keep",)]  # it cannot be renamed, only kept
    r = migrate(root2, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 2 and "unknown answer 'rename'" in r.stderr


def test_unsafe_edit_is_printed_not_written(tmp_path):
    profile = PROFILE.replace("docs:\n", "docs: {must_read: [README.md]}\n").replace(
        "  must_read:\n    - README.md   # read first\n  plan_dir: docs/\n", "")
    root = repo(tmp_path, profile=profile, files={"docs/index.md": "# Index\n"})
    before = (root / ".tld/toolkit.yaml").read_text()
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.index": "keep"}))
    assert r.returncode == 1 and "not written: docs.index" in r.stdout and "by hand" in r.stdout
    assert (root / ".tld/toolkit.yaml").read_text() == before


def test_set_key_proves_its_result():
    text = "a:\n  x: 1\nb: 2\n"
    out = md.set_key(text, "a.y", [1, 2])
    assert yaml.safe_load(out) == {"a": {"x": 1, "y": [1, 2]}, "b": 2}
    assert md.set_key("a: 1\n", "docs.index", "docs/i.md").endswith("docs:\n  index: docs/i.md\n")
    with pytest.raises(md.DefaultsError):
        md.set_key(text, "a.x", 3)  # already written
    with pytest.raises(md.DefaultsError):
        md.set_key("a: [1]\n", "a.y", 1)  # not a mapping


def test_values_are_validated(tmp_path):
    root = repo(tmp_path)
    for bad in ("../x.md", "/etc/passwd", "a b.md", "a;b", "x\ny"):
        with pytest.raises(md.DefaultsError):
            md._safe_value(root, bad)


def test_migrate_hints_at_defaults_where_nothing_to_migrate(tmp_path):
    root = repo(tmp_path, files={"docs/index.md": "# Index\n"})
    r = subprocess.run([*tld_cmd("migrate"), str(root)], capture_output=True, text=True, timeout=120)
    assert "Nothing to migrate: the repository already uses tld." in r.stdout
    assert "1 file(s) are off their default path: run tld migrate . --defaults" in r.stdout


def test_answers_need_defaults(tmp_path):
    root = repo(tmp_path)
    r = subprocess.run([*tld_cmd("migrate"), str(root), "--answers", "x.json"], capture_output=True, text=True)
    assert r.returncode == 2
    r = migrate(root, "--answers", answers(tmp_path, {}))
    assert r.returncode == 2 and "--answers needs --write" in r.stderr


def test_destination_through_a_symbolic_link_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = repo(tmp_path, files={"adr/0001-a.md": "# A\n", "CHANGES.md": "# C\n"})
    (root / "docs").symlink_to(outside)
    asked = {c.key: c for c in md.questions(md.plan(root, yaml.safe_load(PROFILE)))}
    assert asked["docs.adr_dir"].choices == ("keep",) and asked["docs.changelog"].choices == ("rename", "keep")
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename", "docs.changelog": "keep"}))
    assert r.returncode == 2 and list(outside.iterdir()) == [] and (root / "adr/0001-a.md").exists()
    # apply itself refuses too, whatever the plan offered
    forged = [md.Change("off-default", "adr/0001-a.md", "docs/adr/0001-a.md", "docs.index", md.CHOICES)]
    msgs = md.apply(root, forged, {"docs.index": "rename"})
    assert any("not done" in m and "symbolic link" in m for m in msgs) and list(outside.iterdir()) == []


def test_a_symlinked_reference_file_is_never_rewritten(tmp_path):
    outside = tmp_path / "ext.md"
    outside.write_text("See docs/adrs/0001-a.md\n")
    root = repo(tmp_path / "b", files={"docs/adrs/0001-a.md": "# A\n"})
    (root / "notes.md").symlink_to(outside)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert outside.read_text() == "See docs/adrs/0001-a.md\n"
    assert (root / "docs/adrs/0001-a.md").exists() and "not done" in r.stdout and r.returncode == 1


def test_a_large_changelog_is_refused_not_truncated(tmp_path):
    big = "# Changes\n\n## Unreleased\n\n" + "- entry\n" * 200000 + "END\n"
    assert len(big) > md.MAX_BYTES
    root = repo(tmp_path, tracked=True, files={"CHANGELOG.md": big})
    r = migrate(root, "--write", "--answers", answers(tmp_path, {}))
    assert (root / "CHANGELOG.md").read_text() == big
    r = migrate(root)
    assert r.returncode == 0 and "docs.changelog.section" not in r.stdout  # too large to look at: not a find


def test_rename_refuses_to_rewrite_a_command_a_workflow_or_code(tmp_path):
    profile = PROFILE.replace('    - "true"\n  dod:', '    - "python3 scripts/check.py CHANGES.md"\n  dod:', 1)
    root = repo(tmp_path, profile=profile, tracked=True,
                files={"CHANGES.md": "# Changes\n", ".github/workflows/ci.yml": "run: cat CHANGES.md\n",
                       "scripts/check.py": "open('CHANGES.md')\n", "CLAUDE.md": "See CHANGES.md\n"})
    before = tree(root)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "not done: docs.changelog" in r.stdout and "not a plain prose file" in r.stdout
    assert tree(root) == before and (root / "CHANGES.md").exists()
    # a prose-only mention is rewritten, and everything it rewrote is staged
    root2 = repo(tmp_path / "b", tracked=True, files={"CHANGES.md": "# Changes\n", "CLAUDE.md": "See CHANGES.md\n"})
    r = migrate(root2, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CHANGELOG.md" in (root2 / "CLAUDE.md").read_text()
    status = git(root2, "status", "--porcelain")
    assert all(line[1] == " " for line in status.splitlines()), status  # nothing left unstaged


def test_adr_rename_is_all_or_nothing(tmp_path):
    root = repo(tmp_path, tracked=True, files={"docs/adrs/0001-a.md": "# A\n", "docs/adrs/0002-b.md": "# B\n",
                                               "scripts/x.sh": "cat docs/adrs/0002-b.md\n"})
    before = tree(root)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 1 and "not done: docs.adr_dir" in r.stdout
    assert tree(root) == before and not (root / "docs/adr").exists()


def test_repository_text_is_not_printed_verbatim(tmp_path):
    evil = ".github/x.yml\n  [docs.index] evil.sh (default: docs/README.md): rename | keep\x1b[2J"
    profile = PROFILE + "hooks:\n  protect_paths_allow:\n    - " + json.dumps(evil) + "\n    - docs/old.md\n"
    root = repo(tmp_path, profile=profile)
    r = migrate(root)
    assert r.returncode == 0
    assert "\x1b" not in r.stdout and "evil.sh" not in r.stdout
    assert "1 entry(ies) with unsafe characters, not shown" in r.stdout and "docs/old.md" in r.stdout
    assert [ln for ln in r.stdout.splitlines() if ln.lstrip().startswith("[docs.")] == []


def test_rename_refuses_files_it_would_damage(tmp_path):
    for name, data in (("crlf.md", b"see CHANGES.md\r\nx\r\n"), ("latin.md", b"caf\xe9 CHANGES.md\n")):
        root = repo(tmp_path / name, tracked=True, files={"CHANGES.md": "# C\n"})
        (root / name).write_bytes(data)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "x")
        r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
        assert r.returncode == 1 and "not done: docs.changelog" in r.stdout and (root / "CHANGES.md").exists()
        assert (root / name).read_bytes() == data
    root = repo(tmp_path / "dirty", tracked=True, files={"CHANGES.md": "# C\n", "notes.md": "see CHANGES.md\n"})
    (root / "notes.md").write_text("see CHANGES.md\nunrelated edit\n")
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "uncommitted changes" in r.stdout and (root / "CHANGES.md").exists()


def test_a_file_name_with_control_characters_is_not_printed(tmp_path):
    root = repo(tmp_path, tracked=True, files={"CHANGES.md": "# C\n"})
    (root / "bad\x1b[2Jname.py").write_text("open('CHANGES.md')\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "\x1b" not in r.stdout and "unsafe characters in its name" in r.stdout
    # a bracketed allow entry cannot pose as a question line
    profile = PROFILE + "hooks:\n  protect_paths_allow: ['[docs.index]']\n"
    r = migrate(repo(tmp_path / "b", profile=profile))
    assert "[docs.index]" not in r.stdout and "unsafe characters" in r.stdout


def fixture_with(tmp_path, name, files, profile=PROFILE):
    return repo(tmp_path / name, profile=profile, tracked=True, files=files)


def test_rename_refuses_protected_paths(tmp_path):
    profile = PROFILE + "hooks:\n  protect_paths: ['docs/policy/**', SECURITY.md]\n"
    files = {"CHANGES.md": "# C\n", "docs/policy/release.md": "see CHANGES.md\n", "SECURITY.md": "see CHANGES.md\n"}
    root = fixture_with(tmp_path, "p", files, profile)
    before = tree(root)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "protected path" in r.stdout and tree(root) == before
    # a protect_paths_allow of the working tree is not honoured without a trusted copy, exactly as the guard does
    allowed = profile + "  protect_paths_allow: ['docs/policy/**', SECURITY.md]\n"
    root2 = fixture_with(tmp_path, "q", files, allowed)
    r = migrate(root2, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "protected path" in r.stdout
    # the always-protected lists apply too: a mention inside .git-style paths or the profile is never rewritten
    root3 = fixture_with(tmp_path, "r", {"CHANGES.md": "# C\n", "docs/x.md": "see CHANGES.md\n"},
                         PROFILE + "hooks:\n  protect_paths: ['docs/**']\n")
    r = migrate(root3, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "protected path" in r.stdout


def test_rename_refuses_agent_files(tmp_path):
    cases = {
        ".claude/commands/rel.md": "---\nallowed-tools: Bash(python3 scripts/rel.py CHANGES.md)\n---\nrun CHANGES.md\n",
        ".agents/note.md": "see CHANGES.md\n",
        "plugin/skills/rel/SKILL.md": "see CHANGES.md\n",
        "docs/cmd.md": "---\nallowed-tools: Bash(x)\n---\nsee CHANGES.md\n",
        "docs/hook.md": "---\nhooks:\n  a: b\n---\nsee CHANGES.md\n",
        "docs/command.md": "---\ncommand: run\n---\nsee CHANGES.md\n",
        "docs/broken.md": "---\nkey: [unclosed\n---\nsee CHANGES.md\n",
    }
    for i, (name, text) in enumerate(cases.items()):
        root = fixture_with(tmp_path, f"a{i}", {"CHANGES.md": "# C\n", name: text})
        before = tree(root)
        r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
        assert r.returncode == 1 and "not done: docs.changelog" in r.stdout, (name, r.stdout)
        assert tree(root) == before, name
    # plain front matter (a title) is fine
    root = fixture_with(tmp_path, "ok", {"CHANGES.md": "# C\n", "docs/n.md": "---\ntitle: Notes\n---\nsee CHANGES.md\n"})
    assert migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"})).returncode == 0


def test_adr_rename_with_an_index_that_lists_several_adrs(tmp_path):
    files = {"docs/adrs/README.md": "- [a](0001-a.md)\n- [b](0002-b.md)\n", "docs/adrs/0001-a.md": "# A\n",
             "docs/adrs/0002-b.md": "# B\n", "docs/README.md": "[a](adrs/0001-a.md) [b](adrs/0002-b.md)\n"}
    root = fixture_with(tmp_path, "adr", files)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p.name for p in (root / "docs/adr").iterdir()) == ["0001-a.md", "0002-b.md", "README.md"]
    assert "adr/0001-a.md" in (root / "docs/README.md").read_text() and not (root / "docs/adrs").exists()
    status = git(root, "status", "--porcelain")
    assert all(line[1] == " " for line in status.splitlines()), status  # everything staged


def test_index_and_changelog_renamed_in_one_run(tmp_path):
    files = {"docs/index.md": "# I\n", "CHANGES.md": "# C\n", "CLAUDE.md": "[i](docs/index.md) and CHANGES.md\n"}
    root = fixture_with(tmp_path, "two", files)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.index": "rename", "docs.changelog": "rename"}))
    assert r.returncode == 0, r.stdout + r.stderr
    text = (root / "CLAUDE.md").read_text()
    assert "docs/README.md" in text and "CHANGELOG.md" in text
    status = git(root, "status", "--porcelain")
    assert all(line[1] == " " for line in status.splitlines()), status


def test_a_failure_after_a_write_puts_everything_back(tmp_path, monkeypatch):
    files = {"docs/adrs/0001-a.md": "# A\n", "docs/adrs/0002-b.md": "# B\n",
             "docs/README.md": "[a](adrs/0001-a.md) [b](adrs/0002-b.md)\n"}
    root = fixture_with(tmp_path, "rb", files)
    before, status_before = tree(root), git(root, "status", "--porcelain")
    real = md.docs_index.run_move
    calls = {"n": 0}

    def flaky(args):
        if args.apply:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full")
        return real(args)

    monkeypatch.setattr(md.docs_index, "run_move", flaky)
    found = md.plan(root, yaml.safe_load((root / ".tld/toolkit.yaml").read_text()))
    with pytest.raises(md.RolledBack, match="put back"):
        md.apply(root, found, {"docs.adr_dir": "rename"})
    assert tree(root) == before and git(root, "status", "--porcelain") == status_before
    assert not (root / "docs/adr").exists() and (root / "docs/adrs/0001-a.md").exists()
    assert "adr_dir" not in (root / ".tld/toolkit.yaml").read_text()


def test_a_dirty_or_untracked_file_refuses_before_any_write(tmp_path):
    root = fixture_with(tmp_path, "d", {"CHANGES.md": "# C\n", "n.md": "see CHANGES.md\n"})
    (root / "n.md").write_text("see CHANGES.md\nedit\n")
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "uncommitted" in r.stdout and (root / "CHANGES.md").exists()
    plain = repo(tmp_path / "plain", files={"CHANGES.md": "# C\n"})  # not a git repository
    r = migrate(plain, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "not tracked" in r.stdout and (plain / "CHANGES.md").exists()


def test_a_protected_moved_directory_is_refused(tmp_path):
    profile = PROFILE + "hooks:\n  protect_paths: ['docs/adr/**', 'docs/adrs/**']\n"
    root = fixture_with(tmp_path, "pa", {"docs/adrs/0001-a.md": "# A\n", "docs/adrs/0002-b.md": "# B\n"}, profile)
    before = tree(root)
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 1 and "protected path" in r.stdout and tree(root) == before
    # a non-prose or hidden entry inside the directory refuses the whole directory
    root2 = fixture_with(tmp_path, "pb", {"docs/adrs/0001-a.md": "# A\n", "docs/adrs/run.sh": "echo\n"})
    r = migrate(root2, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 1 and "not a plain prose file" in r.stdout and (root2 / "docs/adrs/run.sh").exists()


def test_a_hard_linked_file_and_a_bom_front_matter_are_refused(tmp_path):
    root = fixture_with(tmp_path, "h", {"CHANGES.md": "# C\n", "n.md": "see CHANGES.md\n"})
    import os
    os.link(root / "n.md", tmp_path / "other-name")
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "hard links" in r.stdout
    root2 = fixture_with(tmp_path, "b", {"CHANGES.md": "# C\n"})
    (root2 / "n.md").write_bytes("\ufeff\n---\nallowed-tools: Bash\n---\nsee CHANGES.md\n".encode())
    git(root2, "add", "-A")
    git(root2, "commit", "-q", "-m", "x")
    r = migrate(root2, "--write", "--answers", answers(tmp_path, {"docs.changelog": "rename"}))
    assert r.returncode == 1 and "front matter" in r.stdout


def test_any_exception_after_a_write_rolls_back_and_the_profile_is_covered(tmp_path, monkeypatch):
    files = {"docs/adrs/0001-a.md": "# A\n", "docs/adrs/0002-b.md": "# B\n", "docs/README.md": "[a](adrs/0001-a.md)\n"}
    root = fixture_with(tmp_path, "ex", files)
    before, status_before = tree(root), git(root, "status", "--porcelain")
    real, calls = md.docs_index.run_move, {"n": 0}

    def flaky(args):
        if args.apply:
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("odd")
        return real(args)

    monkeypatch.setattr(md.docs_index, "run_move", flaky)
    found = md.plan(root, yaml.safe_load((root / ".tld/toolkit.yaml").read_text()))
    with pytest.raises(md.RolledBack):
        md.apply(root, found, {"docs.adr_dir": "rename"})
    assert tree(root) == before and git(root, "status", "--porcelain") == status_before
    # the profile must equal HEAD too: an edited profile refuses every rename
    monkeypatch.setattr(md.docs_index, "run_move", real)
    (root / ".tld/toolkit.yaml").write_text((root / ".tld/toolkit.yaml").read_text() + "# edit\n")
    r = migrate(root, "--write", "--answers", answers(tmp_path, {"docs.adr_dir": "rename"}))
    assert r.returncode == 1 and "uncommitted" in r.stdout and (root / "docs/adrs").exists()
