"""SQLite session metadata store for the dashboard history view."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from triage.models import SessionMeta


class SessionStore:
    """Manages session metadata in a separate SQLite database (not the SDK's session DB)."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    patient_name TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    condition_name TEXT,
                    result_type TEXT,
                    result_json TEXT
                )
            """)
            conn.commit()

    def create_session(self, session_id: str) -> SessionMeta:
        now = datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, status) VALUES (?, ?, ?)",
                (session_id, now.isoformat(), "active"),
            )
            conn.commit()
        return SessionMeta(session_id=session_id, created_at=now)

    def update_session(
        self,
        session_id: str,
        patient_name: str | None = None,
        status: str | None = None,
        condition_name: str | None = None,
        result_type: str | None = None,
    ):
        updates = []
        values = []
        if patient_name is not None:
            updates.append("patient_name = ?")
            values.append(patient_name)
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if condition_name is not None:
            updates.append("condition_name = ?")
            values.append(condition_name)
        if result_type is not None:
            updates.append("result_type = ?")
            values.append(result_type)
        if not updates:
            return
        values.append(session_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?",
                values,
            )
            conn.commit()

    def get_session(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, created_at, patient_name, status, condition_name, result_type "
                "FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_result(self, session_id: str, result_json: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET result_json = ? WHERE session_id = ?",
                (result_json, session_id),
            )
            conn.commit()

    def get_result(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT result_json FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return None

    def delete_inactive(self) -> int:
        """Delete all sessions with status 'active' (started but never completed). Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE status = 'active'")
            conn.commit()
            return cursor.rowcount
