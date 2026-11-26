"""The generic product must not carry any one project's words."""
from conftest import ROOT, FORBIDDEN

# The python stack guide names its tools on purpose; docs/ and tests/ use the first project as the worked example.
CHECKED = ["src", "cli", "adapters", ".claude-plugin", "playbooks", "roles", "checklists", "stacks"]
OPTIONAL: list[str] = []  # directories checked only when they exist
EXEMPT = ["stacks/python.md"]
# The owner mandated this literal as the default `docs.website.links` (plan 90, risk 9); it is removed from the text
# of that one file before the scan, and nothing else is.
MANDATED = {"src/tld/profile/defaults.py": "python3 -m pytest tests/unit/test_website_links.py -q"}
SUFFIXES = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt", ".html", ".js", ".toml", ""}


def scan_text(path) -> str:
    text = path.read_text()
    literal = MANDATED.get(path.relative_to(ROOT).as_posix())
    return text.replace(literal, "") if literal else text


def test_no_project_specific_strings():
    hits = []
    for rel in [d for d in CHECKED if (ROOT / d).is_dir()]:
        for path in sorted((ROOT / rel).rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                continue
            if path.relative_to(ROOT).as_posix() in EXEMPT:
                continue
            for n, line in enumerate(scan_text(path).splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert hits == [], "project-specific words in the generic product:\n" + "\n".join(hits)


def test_checked_paths_exist():
    for rel in CHECKED:
        assert rel in OPTIONAL or (ROOT / rel).is_dir(), rel


def test_the_word_list_catches_the_known_words():
    for word in ("PrivacyFence", "the approval gate", "Gemini", "Google AI Studio", "feature/org-mode-mobile",
                 "src/privacyfence", "a connector"):
        assert FORBIDDEN.search(word), word


def test_install_directory_is_gone():
    assert not (ROOT / "install").exists()


def test_the_spike_record_names_no_login_trigger_or_session():
    """C14: docs/architecture/maintenance-spike.md keeps placeholders for logins, task and session ids."""
    import re
    text = (ROOT / "docs" / "architecture" / "maintenance-spike.md").read_text()
    for pattern in (r"\btrig_[A-Za-z0-9]{8,}", r"\b(session|cse)_[A-Za-z0-9]{8,}", r"andras", r"comments/\d{6,}"):
        assert not re.search(pattern, text), pattern


def test_exemption_removes_only_the_mandated_literal(tmp_path):
    defaults = ROOT / "src/tld/profile/defaults.py"
    assert FORBIDDEN.search(defaults.read_text()), "the exemption is no longer needed: remove it"
    assert not FORBIDDEN.search(scan_text(defaults))
    other = tmp_path / "other.py"
    other.write_text("links = 'python3 -m pytest tests/unit/test_website_links.py -q'\n")
    assert MANDATED.keys() == {"src/tld/profile/defaults.py"}
    assert FORBIDDEN.search(other.read_text())
    # a second use of a forbidden word in the exempt file is still found
    assert FORBIDDEN.search(defaults.read_text().replace(MANDATED["src/tld/profile/defaults.py"], "") + " ruff")
