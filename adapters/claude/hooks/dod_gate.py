#!/usr/bin/env python3
"""Claude Code hook entry: runs tld.dod.gate on the hook event JSON from stdin.

A thin shim: the policy lives in the core package (src/tld/dod/gate.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from tld.dod import gate as hook  # noqa: E402

if __name__ == "__main__":
    hook.main()
