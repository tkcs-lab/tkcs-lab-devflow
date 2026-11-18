"""The board-gate section of docs/architecture/hooks.md quotes the block messages verbatim."""
from __future__ import annotations

from pathlib import Path

from tld.guard import board_gate

DOC = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "hooks.md"


def test_hooks_doc_quotes_board_gate_messages():
    text = DOC.read_text(encoding="utf-8")
    for message in (board_gate.MESSAGE, board_gate.DIRTY_MESSAGE, board_gate.TIMER_MESSAGE):
        assert message in text
