"""tiny_app plus two planted flaws: a shell-injection in an export helper and an untested auth check."""
from __future__ import annotations

from pathlib import Path

from . import commit_all, tiny_app, write_files
from evals.fixtures.tiny_app import FILES as APP_FILES
from evals.harness.common import git

EXPORT = '''\
"""Export notes to an archive."""
import os


def export(name: str, directory: str = ".") -> int:
    # name comes from the command line of the caller
    return os.system("tar czf " + name + ".tgz " + directory)
'''

AUTH = '''\
"""Token check used by `notes sync`."""
import hmac

EXPECTED = "change-me-in-config"


def check_token(given: str) -> bool:
    return hmac.compare_digest(given, EXPECTED)
'''

# Tests exist for the store; `notes sync` reaches check_token and nothing tests it: a gap in a security-relevant path.


def build(dest: Path, **params) -> dict:
    tiny_app.build(dest)
    cli = APP_FILES["notes/cli.py"]
    cli = cli.replace("from notes import store", "from notes import auth, store")
    cli = cli.replace('    sub.add_parser("list")\n', '    sub.add_parser("list")\n    s = sub.add_parser("sync")\n    s.add_argument("--token", required=True)\n')
    cli = cli.replace('    elif args.cmd == "list":', '    elif args.cmd == "sync":\n        return 0 if auth.check_token(args.token) else 1\n    elif args.cmd == "list":')
    write_files(dest, {"notes/export.py": EXPORT, "notes/auth.py": AUTH, "notes/cli.py": cli})
    commit_all(dest, "Add export helper and the sync token check")
    return {
        "main_branch": "main",
        "seeded": [
            {"id": "injection", "file": "notes/export.py", "class": "injection",
             "class_words": ["injection", "shell", "command execution", "os.system"]},
            {"id": "missing-test", "file": "notes/auth.py", "class": "missing-test",
             "class_words": ["missing test", "missing: test", "no test", "untested", "not tested", "test coverage", "without a test", "not covered"]},
        ],
        # real but minor facts the fixture accepts as non-noise (matched by file)
        "acceptable_files": ["notes/store.py", "notes/cli.py", "README.md", "docs/design.md"],
    }
