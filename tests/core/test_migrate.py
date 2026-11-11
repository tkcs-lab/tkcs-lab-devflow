"""tld migrate: a claude-toolkit era repository becomes a tld one (plan §7, WP8).

The fixtures in tests/fixtures/legacy/ are the claude-toolkit files at the import commit 4c14071: the first
consumer's profile and a manifest of one of its plans, the legacy starter profile, the agents fixture and the three
installed devflow workflows.
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from conftest import FIXTURES, TLD, _load, tld_cmd

LEGACY = FIXTURES / "legacy"
mig = _load("tld.ops.migrate")
ra = _load("tld.ops.repo_admin")

MUST_READ = ["CLAUDE.md", "CONTRIBUTING.md", "docs/releasing.md", "docs/coding-and-testing-guidelines.md",
             "docs/testing-policy.md", "docs/adr/README.md", ".claude/skills/steward/SKILL.md"]
CLAUDE_MD = """# Project

Run `/devflow:make-plan`, then `/devflow:implement <url>`; the skill `devflow:project-profile` reads
`.claude/toolkit.yaml`. The board needs DEVFLOW_BOARD_URL and ${DEVFLOW_BOARD_TOKEN}.
The devflow plugin and devflow-land.yml stay as they are in prose, and so do mydevflow:x and NODEVFLOW_X.
"""


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def migrate(root, *args):
    return subprocess.run([*tld_cmd("migrate"), str(root), *args], capture_output=True, text=True, timeout=120)


def legacy_repo(root, profile="privacyfence-toolkit.yaml", git_repo=True):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".claude").mkdir()
    (root / ".claude" / "toolkit.yaml").write_text((LEGACY / profile).read_text())
    for rel in MUST_READ:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# doc\n")
    (root / "CLAUDE.md").write_text(CLAUDE_MD)
    (root / "README.md").write_text("Install the `devflow` plugin; see `.claude/toolkit.yaml`.\n")
    (root / "docs" / "guides").mkdir(parents=True)
    (root / "docs" / "guides" / "x.md").write_text("Use `/devflow:dod`.\n")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "pull_request_template.md").write_text("Ran /devflow:dod\n")
    for name in mig.WORKFLOWS:
        (root / ".github" / "workflows" / f"devflow-{name}.yml").write_text((LEGACY / f"devflow-{name}.yml").read_text())
    (root / ".github" / "workflows" / "ci.yml").write_text("env:\n  T: ${{ secrets.DEVFLOW_AGENT_TOKEN }}\n")
    manifest = (LEGACY / "plugin-framework-manifest.yaml").read_text()
    (root / "docs" / "plugin-framework-plan.md").write_text(
        f"# Plan\n\nKeep worker_model: opus in prose.\n\n## Implementation manifest\n\n```yaml\n{manifest}```\n")
    (root / ".claude" / "admin-policy.yaml").write_text("org: x\n")
    if git_repo:
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "legacy")
    return root


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


@pytest.fixture()
def pf(tmp_path):
    return legacy_repo(tmp_path / "pf")


def test_dry_run_prints_the_plan_and_changes_nothing(pf):
    before = tree(pf)
    r = migrate(pf)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "(dry run; --write applies it)" in out
    for needle in (".claude/toolkit.yaml -> .tld/toolkit.yaml (git mv)", "'models.planner' removed",
                   "'models.worker': sonnet -> standard", "'models.reviewer': opus -> strong",
                   "'tld.version: \">=1.0,<2\"' added", ".github/workflows/devflow-land.yml -> .github/workflows/tld-land.yml",
                   "docs/plugin-framework-plan.md: 12 legacy manifest key(s)", "CLAUDE.md: devflow: -> tld: (3)",
                   "Validation of .tld/toolkit.yaml (as it will be):\n  OK", "Owner checklist"):
        assert needle in out, needle
    assert tree(pf) == before and git(pf, "status", "--porcelain") == ""


def test_write_migrates_profile_workflows_texts_and_manifests(pf):
    r = migrate(pf, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (pf / ".claude" / "toolkit.yaml").exists()
    status = git(pf, "status", "--porcelain")
    assert "R  .claude/toolkit.yaml -> .tld/toolkit.yaml" in status  # git mv, staged
    staged = git(pf, "diff", "--cached", "--name-status", "--no-renames").split("\n")
    assert "D\t.github/workflows/devflow-land.yml" in staged and "A\t.github/workflows/tld-land.yml" in staged

    text = (pf / ".tld" / "toolkit.yaml").read_text()
    assert "# verify.* mirrors docs/coding-and-testing-guidelines.md" in text  # comments kept
    data = yaml.safe_load(text)
    assert data["models"] == {"worker": "standard", "reviewer": "strong"}
    assert data["tld"] == {"version": ">=1.0,<2"}
    v = subprocess.run([*tld_cmd("profile", "validate"), str(pf / ".tld" / "toolkit.yaml")], capture_output=True, text=True)
    assert v.returncode == 0, v.stderr

    wf = pf / ".github" / "workflows"
    assert sorted(p.name for p in wf.iterdir()) == ["ci.yml", "tld-git-ops.yml", "tld-land.yml", "tld-release.yml"]
    land = ra.render_template((TLD / "templates" / "tld-land.yml").read_text(), {"main_branch": "main"})
    assert (wf / "tld-land.yml").read_text() == land
    release = (wf / "tld-release.yml").read_text()
    assert "environment: tld-release" in release and 'PREFIX: "v"' in release and "__" not in release
    assert "secrets.TLD_RELEASE_TOKEN" in release and "DEVFLOW" not in release
    assert "git/tags" not in (wf / "tld-git-ops.yml").read_text()  # git-ops cannot tag

    claude = (pf / "CLAUDE.md").read_text()
    assert "`/tld:make-plan`" in claude and "`/tld:implement <url>`" in claude and "`tld:project-profile`" in claude
    assert "`.tld/toolkit.yaml`" in claude and "TLD_BOARD_URL" in claude and "${TLD_BOARD_TOKEN}" in claude
    assert "The devflow plugin and devflow-land.yml" in claude and "mydevflow:x and NODEVFLOW_X" in claude
    assert (pf / "docs" / "guides" / "x.md").read_text() == "Use `/tld:dod`.\n"
    assert (pf / ".github" / "pull_request_template.md").read_text() == "Ran /tld:dod\n"
    assert (pf / "README.md").read_text() == "Install the `devflow` plugin; see `.tld/toolkit.yaml`.\n"
    assert "DEVFLOW_AGENT_TOKEN" in (wf / "ci.yml").read_text()  # other workflows: listed, not rewritten

    plan = (pf / "docs" / "plugin-framework-plan.md").read_text()
    assert "Keep worker_model: opus in prose." in plan
    assert "worker_model" not in plan.split("## Implementation manifest")[1] and "manual_steps_" not in plan
    assert "worker_level: strong" in plan and "worker_level_reason:" in plan
    m = subprocess.run([*tld_cmd("plan", "validate-manifest"), str(pf / "docs" / "plugin-framework-plan.md"),
                        "--profile", str(pf / ".tld" / "toolkit.yaml")], capture_output=True, text=True)
    assert m.returncode == 0, m.stderr


def test_second_run_is_a_no_op(pf):
    assert migrate(pf, "--write").returncode == 0
    git(pf, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "migrated")
    before = tree(pf)
    for args in ((), ("--write",)):
        r = migrate(pf, *args)
        assert r.returncode == 0, r.stderr
        assert "Nothing to migrate: the repository already uses tld." in r.stdout
    assert tree(pf) == before and git(pf, "status", "--porcelain") == ""


def test_checklist_lists_what_only_the_owner_can_do(pf):
    out = migrate(pf).stdout.split("Owner checklist")[1]
    for needle in ("remove the marketplace claude-toolkit", "add the marketplace tkcs-lab/tkcs-lab-devflow",
                   "enable the plugin tld", "DEVFLOW_* to TLD_*", "TLD_AGENT_TOKEN into the environment tld-agent",
                   "TLD_RELEASE_TOKEN into the environment tld-release", "TLD_BOARD_URL and TLD_BOARD_TOKEN",
                   "network settings", "tld ops repo-admin apply --policy <policy> --yes",
                   ".claude/admin-policy.yaml (move it to .tld/admin-policy.yaml",
                   "workflows that still read DEVFLOW_* secrets: ci.yml", "a session never merges"):
        assert needle in out, needle
    assert out.count("  [ ] ") == 6


def test_the_legacy_starter_migrates_outside_git(tmp_path):
    root = tmp_path / "s"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "toolkit.yaml").write_text((LEGACY / "starter-toolkit.yaml").read_text())
    (root / "README.md").write_text("x\n")
    r = migrate(root, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert ".tld/toolkit.yaml: .claude/toolkit.yaml -> .tld/toolkit.yaml\n" in r.stdout and "(git mv)" not in r.stdout
    text = (root / ".tld" / "toolkit.yaml").read_text()
    assert text.startswith("# .tld/toolkit.yaml — the project profile") and "comments are lost" not in r.stdout
    assert text.count("\n#") >= (LEGACY / "starter-toolkit.yaml").read_text().count("\n#")  # every comment kept
    assert yaml.safe_load(text)["tld"] == {"version": ">=1.0,<2"}
    assert not (root / ".claude" / "toolkit.yaml").exists()


def test_agents_become_roles(tmp_path):
    root = tmp_path / "a"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "toolkit.yaml").write_text((LEGACY / "agents-toolkit.yaml").read_text())
    r = migrate(root, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "'agents' renamed to 'roles'" in r.stdout
    data = yaml.safe_load((root / ".tld" / "toolkit.yaml").read_text())
    assert "agents" not in data and data["roles"]["disable"] == ["dependency-auditor"]
    assert [e["role"] for e in data["roles"]["required"]] == [
        "security-reviewer", "ux-reviewer", "test-architect", "tech-writer", "website-maintainer"]
    assert all("agent" not in e for e in data["roles"]["required"])


def test_an_existing_destination_is_never_overwritten(tmp_path):
    root = tmp_path / "b"
    (root / ".claude").mkdir(parents=True)
    (root / ".tld").mkdir()
    legacy = (LEGACY / "starter-toolkit.yaml").read_text()
    (root / ".claude" / "toolkit.yaml").write_text(legacy)
    current = 'tld:\n  version: ">=1.0,<2"\ndocs:\n  must_read: []\ngit:\n  main_branch: trunk\n  branch_pattern: x\n' \
              'verify:\n  fast: []\n  dod: ["true"]\nstacks: []\n'
    (root / ".tld" / "toolkit.yaml").write_text(current)
    r = migrate(root, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "both .claude/toolkit.yaml and .tld/toolkit.yaml exist" in r.stdout
    assert (root / ".tld" / "toolkit.yaml").read_text() == current
    assert (root / ".claude" / "toolkit.yaml").read_text() == legacy
    assert ".claude/toolkit.yaml (both profiles exist; delete the old one)" in r.stdout


def test_flow_style_models_fall_back_to_the_data(tmp_path):
    root = tmp_path / "f"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "toolkit.yaml").write_text(
        "# mine\ndocs: {must_read: []}\ngit: {main_branch: main, branch_pattern: x}\nverify: {fast: [], dod: [x]}\n"
        "stacks: []\nmodels: {planner: opus, worker: haiku}\ntoolkit: {ref: v0.1.0}\n")
    r = migrate(root, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "its comments are lost" in r.stdout and "'toolkit' removed" in r.stdout
    data = yaml.safe_load((root / ".tld" / "toolkit.yaml").read_text())
    assert data["models"] == {"worker": "fast"} and "toolkit" not in data


def test_models_left_empty_are_removed():
    text = "docs:\n  must_read: []\nmodels:\n  planner: opus   # the planner\n  orchestrator: sonnet\nstacks: []\n"
    data = yaml.safe_load(text)
    target, notes = mig.migrate_profile_data(data)
    new, kept = mig.migrate_profile_text(text, data, target)
    assert kept and "models" not in yaml.safe_load(new) and "planner" not in new


def test_a_profile_that_does_not_validate_exits_1(tmp_path):
    root = legacy_repo(tmp_path / "v", git_repo=False)
    (root / "docs" / "releasing.md").unlink()
    r = migrate(root)
    assert r.returncode == 1
    assert "error: file not found: 'docs/releasing.md'" in r.stdout


def test_no_profile_exits_1(tmp_path):
    r = migrate(tmp_path)
    assert r.returncode == 1 and "no profile" in r.stderr
    assert subprocess.run([*tld_cmd("migrate"), str(tmp_path / "missing")], capture_output=True).returncode == 2


def test_release_keeps_the_installed_tag_prefix(tmp_path):
    root = legacy_repo(tmp_path / "p", git_repo=False)
    old = root / ".github" / "workflows" / "devflow-release.yml"
    old.write_text(old.read_text().replace('PREFIX: "v"', 'PREFIX: "rel-"'))
    assert migrate(root, "--write").returncode == 0
    assert 'PREFIX: "rel-"' in (root / ".github" / "workflows" / "tld-release.yml").read_text()


def test_an_existing_tld_workflow_is_kept(tmp_path):
    root = legacy_repo(tmp_path / "w", git_repo=False)
    (root / ".github" / "workflows" / "tld-land.yml").write_text("# mine\n")
    r = migrate(root, "--write")
    assert "remove .github/workflows/devflow-land.yml (.github/workflows/tld-land.yml already exists, kept)" in r.stdout
    assert (root / ".github" / "workflows" / "tld-land.yml").read_text() == "# mine\n"
    assert not (root / ".github" / "workflows" / "devflow-land.yml").exists()


def test_cli_lists_migrate():
    r = subprocess.run(tld_cmd("--help"), capture_output=True, text=True)
    assert "migrate" in r.stdout
    h = subprocess.run(tld_cmd("migrate", "--help"), capture_output=True, text=True)
    assert h.returncode == 0 and "--write" in h.stdout


def test_a_legacy_profile_without_plan_dir_keeps_the_old_default_docs(tmp_path):
    root = tmp_path / "pd"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "toolkit.yaml").write_text((LEGACY / "agents-toolkit.yaml").read_text())
    (root / "docs").mkdir()
    (root / "docs" / "x-plan.md").write_text("# Plan\n\n## Implementation manifest\n\n```yaml\nworker_model: opus\n```\n")
    r = migrate(root, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "'docs.plan_dir: docs/' added" in r.stdout and "comments are lost" not in r.stdout
    text = (root / ".tld" / "toolkit.yaml").read_text()
    assert yaml.safe_load(text)["docs"]["plan_dir"] == "docs/" and "# Fixture:" in text
    assert "worker_level: strong" in (root / "docs" / "x-plan.md").read_text()  # the plans there are migrated
    assert "Nothing to migrate" in migrate(root).stdout  # and a second run adds nothing


def test_plan_dir_is_added_when_the_profile_has_no_docs_section():
    text = "git:\n  main_branch: main\n"
    data = yaml.safe_load(text)
    target, _ = mig.migrate_profile_data(data)
    new, kept = mig.migrate_profile_text(text, data, target)
    assert kept and yaml.safe_load(new)["docs"] == {"plan_dir": "docs/"}
    tld_text = 'tld:\n  version: ">=1.0,<2"\ngit:\n  main_branch: main\n'  # a tld profile keeps tld's default
    assert "docs" not in mig.migrate_profile_data(yaml.safe_load(tld_text))[0]


def test_the_project_steward_file_is_rewritten(pf):
    steward = pf / ".claude" / "skills" / "steward" / "SKILL.md"
    steward.write_text("Run /devflow:dod and read .claude/toolkit.yaml.\n")
    r = migrate(pf, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert ".claude/skills/steward/SKILL.md: devflow: -> tld: (1)" in r.stdout
    assert steward.read_text() == "Run /tld:dod and read .tld/toolkit.yaml.\n"


def test_a_steward_outside_the_repository_is_not_touched(tmp_path):
    root = legacy_repo(tmp_path / "o", git_repo=False)
    outside = tmp_path / "outside.md"
    outside.write_text("/devflow:dod\n")
    (root / ".claude" / "toolkit.yaml").write_text(
        (root / ".claude" / "toolkit.yaml").read_text().replace(".claude/skills/steward/SKILL.md", "../outside.md"))
    r = migrate(root, "--write")
    assert "refused, left as it is: project_steward ../outside.md: outside the repository" in r.stdout
    assert outside.read_text() == "/devflow:dod\n"


def test_legacy_script_commands_are_left_alone_and_listed(tmp_path):
    root = tmp_path / "ctk"
    (root / ".claude").mkdir(parents=True)
    profile = (LEGACY / "agents-toolkit.yaml").read_text().replace(
        "verify:\n", "verify:\n  # keep\n", 1)
    data = yaml.safe_load(profile)
    data["verify"]["dod"] = ["python3 plugins/devflow/scripts/validate_profile.py .claude/toolkit.yaml",
                             "tld profile validate .claude/toolkit.yaml"]
    (root / ".claude" / "toolkit.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    r = migrate(root, "--write")
    dod = yaml.safe_load((root / ".tld" / "toolkit.yaml").read_text())["verify"]["dod"]
    assert dod == ["python3 plugins/devflow/scripts/validate_profile.py .claude/toolkit.yaml",
                   "tld profile validate .tld/toolkit.yaml"]
    assert "profile commands that still run claude-toolkit scripts" in r.stdout
    assert "verify.dod[0]: python3 plugins/devflow/scripts/validate_profile.py" in r.stdout


def test_symbolic_links_are_refused_and_reported(tmp_path):
    root = legacy_repo(tmp_path / "s", git_repo=False)
    secret = tmp_path / "secret.md"
    secret.write_text("/devflow:dod\n")
    (root / "docs" / "linked.md").symlink_to(secret)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "y.md").write_text("/devflow:dod\n")
    (root / ".github" / "linkdir").symlink_to(elsewhere, target_is_directory=True)
    wf = root / ".github" / "workflows" / "devflow-git-ops.yml"
    wf_target = tmp_path / "wf.yml"
    wf_target.write_text(wf.read_text())
    wf.unlink()
    wf.symlink_to(wf_target)
    r = migrate(root, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    for needle in ("refused, left as it is: docs/linked.md: docs/linked.md is a symbolic link",
                   "refused, left as it is: .github/linkdir: .github/linkdir is a symbolic link",
                   "refused, left as it is: .github/workflows/devflow-git-ops.yml: "):
        assert needle in r.stdout, needle
    assert secret.read_text() == "/devflow:dod\n" and (elsewhere / "y.md").read_text() == "/devflow:dod\n"
    assert wf.is_symlink() and wf_target.exists() and not (root / ".github" / "workflows" / "tld-git-ops.yml").exists()


@pytest.mark.parametrize("link", [".claude/toolkit.yaml", ".tld"])
def test_a_linked_profile_or_tld_directory_is_an_error(tmp_path, link):
    root = legacy_repo(tmp_path / "l", git_repo=False)
    target = tmp_path / "t"
    if link == ".tld":
        target.mkdir()
        (root / ".tld").symlink_to(target, target_is_directory=True)
    else:
        target.write_text((root / link).read_text())
        (root / link).unlink()
        (root / link).symlink_to(target)
    r = migrate(root, "--write")
    assert r.returncode == 1 and "is a symbolic link" in r.stderr and "never follows a symbolic link" in r.stderr
    assert list(target.iterdir()) == [] if link == ".tld" else target.exists()
