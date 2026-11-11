#!/usr/bin/env python3
"""SQLite storage for the status board records. Imported by board_server.py; it has no command line.

    from board_store import Store, Conflict, Invalid

One table, `records(id, version, data)`. `Store.set` validates the record with
validate_status_record.py and enforces optimistic concurrency with `if_version`.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_status_record  # noqa: E402

MAX_RECORD = 262144
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


class Conflict(Exception):
    """The stored version is not the one the caller read. `current` is the stored record or None."""

    def __init__(self, current: dict | None) -> None:
        super().__init__("version conflict")
        self.current = current


class Invalid(Exception):
    """The id or the record is not acceptable. `errors` lists the reasons."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class Store:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS records("
                "id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL)")
            self._db.commit()

    @staticmethod
    def _row(row: tuple) -> dict:
        return {"id": row[0], "version": row[1], "data": json.loads(row[2])}

    def _get(self, doc_id: str) -> dict | None:
        row = self._db.execute("SELECT id, version, data FROM records WHERE id = ?", (doc_id,)).fetchone()
        return self._row(row) if row else None

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            return self._get(doc_id)

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, version, data FROM records ORDER BY id").fetchall()
        return [self._row(row) for row in rows]

    def set(self, doc_id: str, data: object, if_version: int | None) -> dict:
        if not isinstance(doc_id, str) or not ID_RE.match(doc_id):
            raise Invalid([f"document id '{doc_id}' is not valid"])
        errors = validate_status_record.validate(data, doc_id)
        if errors:
            raise Invalid(errors)
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_RECORD:
            raise Invalid([f"the record is larger than {MAX_RECORD} bytes"])
        with self._lock:
            current = self._get(doc_id)
            if if_version is None:
                if current is not None:
                    raise Conflict(current)
                version = 1
                self._db.execute("INSERT INTO records(id, version, data) VALUES (?, ?, ?)",
                                 (doc_id, version, text))
            else:
                if current is None or current["version"] != if_version:
                    raise Conflict(current)
                version = if_version + 1
                self._db.execute("UPDATE records SET version = ?, data = ? WHERE id = ?",
                                 (version, text, doc_id))
            self._db.commit()
        return {"id": doc_id, "version": version}

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM records WHERE id = ?", (doc_id,))
            self._db.commit()
            return cur.rowcount > 0

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
