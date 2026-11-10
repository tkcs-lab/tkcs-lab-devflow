"""tiny_app plus two planted flaws: a shell-injection in an export helper and an untested auth check."""
from __future__ import annotations

from pathlib import Path

from . import commit_all, tiny_app, write_files
from evals.harness.common import git

EXPORT = '''\
"""Export notes to an archive."""
import os


def export(name: str, directory: str = ".") -> int:
    # name comes from the command line of the caller
    return os.system("tar czf " + name + ".tgz " + directory)
'''

AUTH = '''\
"""Token check for the (planned) sync endpoint."""
import hmac

EXPECTED = "change-me-in-config"


def check_token(given: str) -> bool:
    return hmac.compare_digest(given, EXPECTED)
'''

# Tests exist for the store, so the missing one for auth is a gap in a security-relevant module.


def build(dest: Path, **params) -> dict:
    tiny_app.build(dest)
    write_files(dest, {"notes/export.py": EXPORT, "notes/auth.py": AUTH})
    commit_all(dest, "Add export helper and token check")
    return {
        "main_branch": "main",
        "seeded": [
            {"id": "injection", "file": "notes/export.py", "class": "injection",
             "class_words": ["injection", "shell", "command execution", "os.system"]},
            {"id": "missing-test", "file": "notes/auth.py", "class": "missing-test",
             "class_words": ["missing test", "no test", "untested", "not tested", "test coverage", "without a test"]},
        ],
        # real but minor facts the fixture accepts as non-noise (matched by file)
        "acceptable_files": ["notes/store.py", "notes/cli.py", "README.md", "docs/design.md"],
    }
