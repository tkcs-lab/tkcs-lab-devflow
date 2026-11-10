#!/usr/bin/env python3
"""Entry point of the eval harness. See docs/evals.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.harness.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
