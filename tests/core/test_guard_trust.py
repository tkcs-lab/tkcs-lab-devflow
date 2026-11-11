"""The trusted copy of the profile (src/tld/guard/trust.py): which branch is trusted, and what may not move it.

Each test builds a repository with a bare origin, runs the guards through the Claude adapter and checks that a
working tree, a local ref, a replace object or a repointed origin cannot switch a guard off."""
import json
import tarfile
import zipfile

from hooks_helpers import PROFILE, bash, git, make_repo_with_origin, run

from tld.guard import trust

EVIL = PROFILE + "hooks:\n  disable: [no-merge, no-force-push, no-git-tag, protect-paths, secret-scan]\n"
EVIL_MAIN = EVIL.replace("main_branch: main", "main_branch: evil")
DISABLE_MERGE = PROFILE + "hooks:\n  disable: [no-merge]\n"


def _commit_branch(repo, name, profile):
    git(repo, "checkout", "-q", "-b", name)
    (repo / ".tld" / "toolkit.yaml").write_text(profile)
    git(repo, "commit", "-qam", name)
    sha = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "feature/demo")
    return sha


def _stamp(repo):
    return json.loads((repo / ".git" / "tld" / "trusted.json").read_text())


def _expire(repo):
    stamp = _stamp(repo)
    stamp["at"] = 0
    (repo / ".git" / "tld" / "trusted.json").write_text(json.dumps(stamp))


def test_the_trusted_branch_is_the_remote_default_not_the_working_tree(tmp_path):
    # F1: a pushed branch that names itself the main branch and disables every hook is not its own trust anchor.
    repo = make_repo_with_origin(tmp_path / "r")
    _commit_branch(repo, "evil", EVIL_MAIN)
    git(repo, "push", "-q", "origin", "evil")
    git(repo, "checkout", "-q", "evil")
    assert run("no-merge", bash("git push origin HEAD:main", repo)).code == 2
    assert run("no-merge", bash("git push origin HEAD:evil", repo)).code == 2  # the working tree's name too
    assert run("no-force-push", bash("git push --force origin HEAD:x", repo)).code == 2
    assert run("no-git-tag", bash("git tag v9", repo)).code == 2
    assert run("protect-paths", bash("echo x > .env", repo)).code == 2
    stamp = _stamp(repo)
    assert stamp["branch"] == "main" and stamp["ok"] and stamp["url"].endswith("-origin.git")
    assert stamp["sha"] == git(repo, "rev-parse", "origin/main").strip()
    assert trust.trusted(str(repo)).branch == "main"


def test_the_remote_default_branch_disables_what_it_says(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", committed=DISABLE_MERGE)
    assert run("no-merge", bash("gh pr merge 1", repo)).code == 0
    assert run("no-force-push", bash("git push -f origin x", repo)).code == 2


def test_a_remote_without_a_default_branch_disables_nothing_and_protects_main_and_master(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", committed=DISABLE_MERGE)
    git(tmp_path / "r-origin.git", "symbolic-ref", "HEAD", "refs/heads/nosuch")  # HEAD dangles: no default
    (repo / ".tld" / "toolkit.yaml").write_text(DISABLE_MERGE.replace("main_branch: main", "main_branch: trunk"))
    assert run("no-merge", bash("gh pr merge 1", repo)).code == 2
    for target in ("HEAD:main", "HEAD:master", "HEAD:trunk"):
        assert run("no-merge", bash(f"git push origin {target}", repo)).code == 2, target
    assert run("no-merge", bash("git push -u origin feature/x", repo)).code == 0
    t = trust.trusted(str(repo))
    assert not t.available and t.branch is None and "default branch" in t.problem


def test_a_moved_trusted_ref_makes_the_copy_unavailable(tmp_path):
    # F2: a write to refs/tld/trusted the hooks did not see (e.g. from a script) does not change what is trusted.
    repo = make_repo_with_origin(tmp_path / "r", committed=DISABLE_MERGE)
    evil = _commit_branch(repo, "evil", EVIL)
    assert run("no-merge", bash("gh pr merge 1", repo)).code == 0  # trusted: main disables no-merge
    git(repo, "update-ref", "refs/tld/trusted", evil)
    assert run("no-force-push", bash("git push -f origin x", repo)).code == 2  # evil's disable is not applied
    assert run("no-merge", bash("gh pr merge 1", repo)).code == 2  # and main's own disable is no longer trusted
    t = trust.trusted(str(repo))
    assert not t.available and "refs/tld/trusted" in t.problem


def test_replace_objects_do_not_change_the_trusted_profile(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    _commit_branch(repo, "evil", EVIL)
    run("no-merge", bash("true", repo))  # first lookup fills refs/tld/trusted
    old = git(repo, "rev-parse", "refs/tld/trusted:.tld/toolkit.yaml").strip()
    new = git(repo, "rev-parse", "evil:.tld/toolkit.yaml").strip()
    git(repo, "replace", old, new)
    assert "disable" in git(repo, "show", "refs/tld/trusted:.tld/toolkit.yaml")  # git itself sees the swap
    assert run("no-merge", bash("git push origin HEAD:main", repo)).code == 2
    assert run("no-force-push", bash("git push -f origin x", repo)).code == 2


def test_a_repointed_origin_makes_the_copy_unavailable(tmp_path):
    # F3: origin changed behind the hooks' back (a script, a person) to a remote whose main disables every hook.
    repo = make_repo_with_origin(tmp_path / "r")
    run("no-merge", bash("true", repo))  # records origin's URL
    bad = tmp_path / "evil.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bad))
    _commit_branch(repo, "evil", EVIL)
    git(repo, "push", "-q", str(bad), "evil:main")
    git(repo, "config", "remote.origin.url", str(bad))
    _expire(repo)
    assert run("no-force-push", bash("git push -f origin x", repo)).code == 2
    t = trust.trusted(str(repo))
    assert not t.available and "another URL" in t.problem and t.branch == "main"


def test_an_insteadof_rewrite_of_origin_makes_the_copy_unavailable(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    run("no-merge", bash("true", repo))
    bad = tmp_path / "evil.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bad))
    _commit_branch(repo, "evil", EVIL)
    git(repo, "push", "-q", str(bad), "evil:main")
    git(repo, "config", f"url.{bad}.insteadOf", str(tmp_path / "r-origin.git"))
    _expire(repo)
    assert run("no-merge", bash("git push origin HEAD:main", repo)).code == 2
    assert not trust.trusted(str(repo)).available


def test_a_renamed_remote_swap_makes_the_copy_unavailable(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    run("no-merge", bash("true", repo))
    bad = tmp_path / "evil.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bad))
    git(repo, "remote", "add", "o2", str(bad))
    git(repo, "remote", "rename", "origin", "z")
    git(repo, "remote", "rename", "o2", "origin")
    _expire(repo)
    assert not trust.trusted(str(repo)).available


def test_the_trusted_commit_is_fetched_when_it_is_missing_locally(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "r-origin.git"), str(other))
    (other / ".tld" / "toolkit.yaml").write_text(DISABLE_MERGE)
    git(other, "-c", "user.email=t@e.test", "-c", "user.name=t", "commit", "-qam", "disable merge")
    git(other, "push", "-q", "origin", "main")
    assert run("no-merge", bash("gh pr merge 1", repo)).code == 0  # read from the newly fetched commit
    assert _stamp(repo)["sha"] == git(other, "rev-parse", "HEAD").strip()


def test_no_origin_and_no_repository(tmp_path):
    plain = tmp_path / "p"
    plain.mkdir()
    assert trust.trusted(str(plain)).problem == "not a git repository"
    git(plain, "init", "-q", "-b", "main")
    t = trust.trusted(str(plain))
    assert t.problem == "no origin remote" and not t.origin


def test_an_unreachable_origin_is_retried_after_the_failure_ttl(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    git(repo, "config", "remote.origin.url", str(tmp_path / "gone.git"))
    t = trust.trusted(str(repo), now=1000.0)
    assert not t.available and _stamp(repo)["ok"] is False
    assert not trust.trusted(str(repo), now=1000.0 + trust.FAIL_TTL_SECONDS - 1).available  # cached failure
    git(repo, "config", "remote.origin.url", str(tmp_path / "r-origin.git"))
    assert not trust.trusted(str(repo), now=1000.0 + trust.FAIL_TTL_SECONDS + 1).available  # URL differs: recorded


# ---- F9: whole-directory writes with real source trees and archives ---------------------------------------

def test_recursive_copies_and_archives_are_checked_file_by_file(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    src = tmp_path / "gh"
    (src / "workflows").mkdir(parents=True)
    (src / "workflows" / "ci.yml").write_text("on: push\n")
    harmless = tmp_path / "docs-src"
    harmless.mkdir()
    (harmless / "a.md").write_text("a\n")
    assert run("protect-paths", bash(f"cp -r {src} .github", repo)).code == 2
    assert run("protect-paths", bash(f"cp -a {src}/. .github/", repo)).code == 2
    tree = tmp_path / "tree"
    (tree / ".github").mkdir(parents=True)
    (tree / ".github" / "workflows").symlink_to(src / "workflows")
    assert run("protect-paths", bash(f"rsync -a {tree}/ .", repo)).code == 2  # .github/workflows lands in the root
    assert run("protect-paths", bash(f"rsync -a {tree} .", repo)).code == 0  # ... or under tree/
    assert run("protect-paths", bash(f"cp -r {harmless} docs", repo)).code == 0
    assert run("protect-paths", bash(f"rsync -a {harmless}/ .", repo)).code == 0  # only a.md lands in the root
    (repo / "docs").mkdir()
    assert run("protect-paths", bash(f"cp -r {harmless} docs/", repo)).code == 0
    tgz = tmp_path / "a.tgz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(src, arcname="pkg/.github")
    assert run("protect-paths", bash(f"tar --strip-components=1 -xzf {tgz}", repo)).code == 2
    assert run("protect-paths", bash(f"tar xzf {tgz}", repo)).code == 0  # lands under pkg/
    zpath = tmp_path / "a.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(".env", "X=1\n")
        zf.writestr("docs/b.md", "b\n")
    assert run("protect-paths", bash(f"unzip -o {zpath}", repo)).code == 2
    assert run("protect-paths", bash(f"unzip {zpath} -d sub", repo)).code == 2  # sub/.env matches `.env`
    ok = tmp_path / "ok.zip"
    with zipfile.ZipFile(ok, "w") as zf:
        zf.writestr("docs/b.md", "b\n")
    assert run("protect-paths", bash(f"unzip {ok}", repo)).code == 0


def test_an_existing_protected_file_under_a_checked_out_directory(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    (repo / "web").mkdir()
    (repo / "web" / "yarn.lock").write_text("x\n")
    (repo / "web" / "a.js").write_text("x\n")
    assert run("protect-paths", bash("git checkout main -- web", repo)).code == 2
    assert run("protect-paths", bash("git checkout main -- web/a.js", repo)).code == 0


def test_a_patch_read_from_stdin_or_input_is_checked(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r")
    (repo / "x.diff").write_text("--- a/.env\n+++ b/.env\n@@ -0,0 +1 @@\n+X=1\n")
    (repo / "ok.diff").write_text("--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-demo\n+demo2\n")
    assert run("protect-paths", bash("patch -p1 < x.diff", repo)).code == 2
    assert run("protect-paths", bash("patch -p1 -i x.diff", repo)).code == 2
    assert run("protect-paths", bash("git apply < x.diff", repo)).code == 2
    assert run("protect-paths", bash("patch -p1 < ok.diff", repo)).code == 0
