#!/usr/bin/env python3
"""Claude Code hook entry: runs tld.guard.no_force_push on the hook event JSON from stdin.

A thin shim: the policy lives in the core package (src/tld/guard/no_force_push.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from tld.guard import no_force_push as hook  # noqa: E402

if __name__ == "__main__":
    hook.main()
