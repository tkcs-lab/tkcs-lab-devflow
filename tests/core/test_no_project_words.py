"""The generic product must not carry any one project's words."""
from conftest import ROOT, FORBIDDEN

# The stack-python skill names its tools on purpose; docs/ and tests/ use PrivacyFence as the worked example.
CHECKED = ["src", "bin", "adapters", ".claude-plugin"]
OPTIONAL = ["playbooks"]  # checked once it exists
EXEMPT = ["adapters/claude/skills/stack-python"]
SUFFIXES = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt", ""}


def test_no_project_specific_strings():
    hits = []
    for rel in CHECKED + [d for d in OPTIONAL if (ROOT / d).is_dir()]:
        for path in sorted((ROOT / rel).rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                continue
            if any(path.relative_to(ROOT).as_posix().startswith(e + "/") for e in EXEMPT):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert hits == [], "project-specific words in the generic product:\n" + "\n".join(hits)


def test_checked_paths_exist():
    for rel in CHECKED:
        assert (ROOT / rel).is_dir(), rel


def test_install_directory_is_gone():
    assert not (ROOT / "install").exists()
