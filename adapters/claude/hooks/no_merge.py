#!/usr/bin/env python3
"""Claude Code hook entry for `no-merge`: the adapter (claude_adapter.py) turns the event into a tld.guard Action."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_adapter import main  # noqa: E402

if __name__ == "__main__":
    main("no-merge")
