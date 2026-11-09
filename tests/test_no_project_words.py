"""The generic plugin must not carry any one project's words."""
import re

from conftest import ROOT

FORBIDDEN = re.compile(r"privacyfence|ruff|pytest|src/privacyfence|connector", re.I)
# stack-python names its tools on purpose; docs/ and tests/ use PrivacyFence as the worked example.
CHECKED = ["plugins/devflow", "plugins/stack-swift", "plugins/stack-ipados", "plugins/stack-go", "templates", ".claude-plugin"]
SUFFIXES = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt"}


def test_no_project_specific_strings():
    hits = []
    for rel in CHECKED:
        for path in sorted((ROOT / rel).rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert hits == [], "project-specific words in the generic plugin:\n" + "\n".join(hits)


def test_checked_paths_exist():
    for rel in CHECKED:
        assert (ROOT / rel).is_dir(), rel


def test_install_directory_is_gone():
    assert not (ROOT / "install").exists()
