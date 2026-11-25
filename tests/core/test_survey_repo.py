"""survey_repo.scan: CODEOWNERS, the version line, dependency commands, the lock script, the ADR heading."""
from pathlib import Path

from tld.profile import survey_repo as sr  # noqa: E402


def put(root, rel, text=""):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_version_line(tmp_path):
    put(tmp_path, "pyproject.toml", '[project]\nname = "x"\nversion = "1.2.3"\n')
    put(tmp_path, "package.json", '{\n  "name": "x",\n  "version": "0.4.0"\n}\n')
    put(tmp_path, "Cargo.toml", '[dependencies]\nversion = "9"\n[package]\nname = "x"\nversion = "2.0.0"\n')
    found = {v["path"] for v in sr.scan(tmp_path)["version_files"]}
    assert found == {"pyproject.toml", "package.json", "Cargo.toml"}


def test_version_line_outside_cargo_package_is_ignored(tmp_path):
    put(tmp_path, "Cargo.toml", '[dependencies]\nversion = "9"\n')
    assert sr.scan(tmp_path)["version_files"] == []


def test_lock_script(tmp_path):
    put(tmp_path, "pyproject.toml", "")
    put(tmp_path, "requirements/runtime.lock.txt", "")
    assert sr.scan(tmp_path)["lock_freshness"] == []
    put(tmp_path, "scripts/update-lock.sh", "echo hi\n")
    assert sr.scan(tmp_path)["lock_freshness"] == [
        {"when": ["pyproject.toml"], "run": "bash scripts/update-lock.sh",
         "lockfiles": ["requirements/runtime.lock.txt"]}]


def test_decisions_heading(tmp_path):
    put(tmp_path, "CONTRIBUTING.md", "# Contributing\n\n## Tests\n\n## Decisions and ADRs\n\ntext\n")
    assert sr.scan(tmp_path)["adr_bar"] == "CONTRIBUTING.md#decisions-and-adrs"
    put(tmp_path, "CONTRIBUTING.md", "# Contributing\n")
    assert sr.scan(tmp_path)["adr_bar"] is None


def test_dependency_commands(tmp_path):
    put(tmp_path, "requirements/dev.lock.txt", "")
    put(tmp_path, "requirements/runtime.lock.txt", "")
    put(tmp_path, "package-lock.json", "{}")
    put(tmp_path, "web/package-lock.json", "{}")
    put(tmp_path, "go.mod", "module x\n")
    put(tmp_path, "node_modules/p/package-lock.json", "{}")
    assert sr.scan(tmp_path)["deps_audit"] == [
        {"ecosystem": "pip", "run": "pip-audit --strict -r requirements/runtime.lock.txt"},
        {"ecosystem": "go", "run": "govulncheck ./..."},
        {"ecosystem": "npm", "run": "npm audit --omit=dev --audit-level=high"},
        {"ecosystem": "npm", "run": "npm audit --omit=dev --audit-level=high", "cwd": "web"}]


def test_codeowners_skip_teams_emails_and_the_bot(tmp_path):
    put(tmp_path, ".github/CODEOWNERS",
        "# owners\n* @alice @org/team me@example.com @the-bot\n/docs/ @Bob @alice  # note @carol\n")
    assert sr.scan(tmp_path, bot="The-Bot")["codeowners"] == ["alice", "Bob"]
    assert sr.scan(tmp_path)["codeowners"] == ["alice", "the-bot", "Bob"]


def test_no_files_gives_empty_values(tmp_path):
    assert sr.scan(tmp_path) == {"codeowners": [], "version_files": [], "deps_audit": [],
                                 "lock_freshness": [], "adr_bar": None}


def test_oversized_files_are_not_read(tmp_path):
    put(tmp_path, "CODEOWNERS", "* @alice\n" + "x" * (sr.MAX_BYTES + 1))
    assert sr.scan(tmp_path)["codeowners"] == []
