#!/usr/bin/env python3
"""SQLite storage for the board: status records and asks. Imported by the server; it has no command line.

    from tld.board.store import Store, Conflict, Invalid

Four tables. `records(id, version, data)`: `Store.set` validates a status record (tld.board.record) and
enforces optimistic concurrency with `if_version`. `asks(id, state, created_at, data)`: `Store.create_ask`
validates an ask (tld.board.ask) and assigns its id; `answer_ask` and `cancel_ask` move an open ask to its
final state. `revoked_sessions(nonce, expires)` keeps the owner sessions a logout ended, so a logout survives a
restart of the server. `dismissals(doc_id, version, dismissed_at)` keeps the owner's dismissal of a record
next to it (never inside it); it counts only while the record is still at that version. The schema version is SQLite's `user_version`; opening an older database adds what is missing
and keeps every record. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

from tld.board import ask as ask_model
from tld.board import record as validate_status_record

MAX_RECORD = 262144
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
SCHEMA_VERSION = 4
MAX_OPEN_ASKS = 200


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


class NotFound(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str, clock=utc_now) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._migrate()

    def _migrate(self) -> None:
        """Bring an empty or older database to SCHEMA_VERSION; every step is idempotent."""
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"the database has schema {version}; this board knows {SCHEMA_VERSION}")
        # 1: the status records (a database of the first board has this table and user_version 0).
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS records("
            "id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL)")
        # 2: the asks.
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS asks("
            "id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL)")
        self._db.execute("CREATE INDEX IF NOT EXISTS asks_state ON asks(state, created_at)")
        # 3: the owner sessions a logout revoked (until their cookie would have expired anyway).
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS revoked_sessions(nonce TEXT PRIMARY KEY, expires INTEGER NOT NULL)")
        # 4: the owner's dismissals of records; a record's data and version are never touched.
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS dismissals("
            "doc_id TEXT PRIMARY KEY, version INTEGER NOT NULL, dismissed_at TEXT NOT NULL)")
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.commit()

    def schema_version(self) -> int:
        with self._lock:
            return self._db.execute("PRAGMA user_version").fetchone()[0]

    @staticmethod
    def _row(row: tuple) -> dict:
        return {"id": row[0], "version": row[1], "dismissed_at": row[3], "data": json.loads(row[2])}

    _SELECT = ("SELECT r.id, r.version, r.data, CASE WHEN d.version = r.version THEN d.dismissed_at END "
               "FROM records r LEFT JOIN dismissals d ON d.doc_id = r.id")

    def _get(self, doc_id: str) -> dict | None:
        row = self._db.execute(self._SELECT + " WHERE r.id = ?", (doc_id,)).fetchone()
        return self._row(row) if row else None

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            return self._get(doc_id)

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(self._SELECT + " ORDER BY r.id").fetchall()
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
            self._db.execute("DELETE FROM dismissals WHERE doc_id = ?", (doc_id,))
            self._db.commit()
            return cur.rowcount > 0

    def dismiss(self, doc_id: str, version: int) -> dict:
        """The owner dismisses a record (any state) on `version`. Raises NotFound or Conflict (the stored
        version differs). The record itself is not changed."""
        with self._lock:
            current = self._get(doc_id)
            if current is None:
                raise NotFound(doc_id)
            if current["version"] != version:
                raise Conflict(current)
            stamp = self._clock()
            self._db.execute("INSERT OR REPLACE INTO dismissals(doc_id, version, dismissed_at) VALUES (?, ?, ?)",
                             (doc_id, version, stamp))
            self._db.commit()
        return {"id": doc_id, "version": version, "dismissed_at": stamp}

    def restore(self, doc_id: str) -> dict:
        """Undo a dismissal (a no-op when there is none). Raises NotFound when there is no such record."""
        with self._lock:
            if self._get(doc_id) is None:
                raise NotFound(doc_id)
            self._db.execute("DELETE FROM dismissals WHERE doc_id = ?", (doc_id,))
            self._db.commit()
        return {"id": doc_id, "dismissed_at": None}

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    # -- owner sessions --------------------------------------------------------------------------

    def revoke_session(self, nonce: str, expires: int, now: int) -> None:
        """Remember a logged-out session until `expires`; drops the entries that have expired by `now`."""
        with self._lock:
            self._db.execute("DELETE FROM revoked_sessions WHERE expires <= ?", (now,))
            self._db.execute("INSERT OR REPLACE INTO revoked_sessions(nonce, expires) VALUES (?, ?)",
                             (nonce, int(expires)))
            self._db.commit()

    def session_revoked(self, nonce: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM revoked_sessions WHERE nonce = ?", (nonce,)).fetchone() is not None

    # -- asks -----------------------------------------------------------------------------------

    def _get_ask(self, ask_id: str) -> dict | None:
        row = self._db.execute("SELECT data FROM asks WHERE id = ?", (ask_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _put_ask(self, ask: dict) -> None:
        self._db.execute("UPDATE asks SET state = ?, data = ? WHERE id = ?",
                         (ask["state"], json.dumps(ask, ensure_ascii=False, separators=(",", ":")), ask["id"]))
        self._db.commit()

    def create_ask(self, data: object) -> dict:
        """Store a new ask; returns it with its id, state 'open', empty answers and created_at."""
        errors = ask_model.validate_new(data)
        if errors:
            raise Invalid(errors)
        assert isinstance(data, dict)
        ask = {k: v for k, v in data.items() if k not in ("state", "answers") and v is not None}
        ask.update(id="a-" + secrets.token_hex(8), state="open", answers={}, created_at=self._clock(),
                   answered_at=None)
        ask.setdefault("context_url", None)
        ask.setdefault("fallback_issue", None)
        with self._lock:
            open_count = self._db.execute("SELECT COUNT(*) FROM asks WHERE state = 'open'").fetchone()[0]
            if open_count >= MAX_OPEN_ASKS:
                raise Invalid([f"the board already holds {MAX_OPEN_ASKS} open asks; cancel some first"])
            self._db.execute("INSERT INTO asks(id, state, created_at, data) VALUES (?, ?, ?, ?)",
                             (ask["id"], ask["state"], ask["created_at"],
                              json.dumps(ask, ensure_ascii=False, separators=(",", ":"))))
            self._db.commit()
        return ask

    def get_ask(self, ask_id: str) -> dict | None:
        if not isinstance(ask_id, str) or not ask_model.ID_RE.match(ask_id):
            return None
        with self._lock:
            return self._get_ask(ask_id)

    def list_asks(self, state: str | None = None, limit: int = 200) -> list[dict]:
        """Asks, open ones first (oldest first), then the others (newest first)."""
        query = "SELECT data FROM asks"
        params: tuple = ()
        if state is not None:
            query += " WHERE state = ?"
            params = (state,)
        query += (" ORDER BY CASE state WHEN 'open' THEN 0 ELSE 1 END,"
                  " CASE state WHEN 'open' THEN created_at END ASC, created_at DESC LIMIT ?")
        with self._lock:
            rows = self._db.execute(query, (*params, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def answer_ask(self, ask_id: str, answers: object) -> dict:
        """Record the owner's answers. Raises NotFound, Conflict (not open) or Invalid."""
        with self._lock:
            ask = self._get_ask(ask_id) if ask_model.ID_RE.match(ask_id or "") else None
            if ask is None:
                raise NotFound(ask_id)
            if ask["state"] != "open":
                raise Conflict(ask)
            clean, errors = ask_model.validate_answers(ask, answers)
            if errors:
                raise Invalid(errors)
            ask.update(state="answered", answers=clean, answered_at=self._clock())
            self._put_ask(ask)
            return ask

    def cancel_ask(self, ask_id: str) -> dict:
        """Cancel an open ask; cancelling a cancelled one is a no-op. Raises NotFound or Conflict (answered)."""
        with self._lock:
            ask = self._get_ask(ask_id) if ask_model.ID_RE.match(ask_id or "") else None
            if ask is None:
                raise NotFound(ask_id)
            if ask["state"] == "answered":
                raise Conflict(ask)
            if ask["state"] == "open":
                ask["state"] = "cancelled"
                self._put_ask(ask)
            return ask
