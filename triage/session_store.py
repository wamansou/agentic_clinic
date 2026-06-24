"""SQLite session metadata store for the dashboard history view."""

import json
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from triage.config import CONFIRMATION_TTL_HOURS
from triage.models import SessionMeta


def effective_confirmation_status(row: dict, now: datetime | None = None) -> str:
    """Derive 'expired' from a pending row past the TTL; otherwise the stored status.
    A NULL/absent stored value is treated as 'none'."""
    status = row.get("confirmation_status") or "none"
    if status == "pending":
        sent = row.get("confirmation_sent_at")
        if sent:
            now = now or datetime.now(timezone.utc)
            try:
                sent_dt = datetime.fromisoformat(sent)
            except ValueError:
                return status
            if now - sent_dt > timedelta(hours=CONFIRMATION_TTL_HOURS):
                return "expired"
    return status


def confirmation_hours_left(row: dict, now: datetime | None = None) -> float | None:
    """Hours remaining in the window for a pending row; None otherwise."""
    if (row.get("confirmation_status") or "none") != "pending":
        return None
    sent = row.get("confirmation_sent_at")
    if not sent:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        sent_dt = datetime.fromisoformat(sent)
    except ValueError:
        return None
    remaining = timedelta(hours=CONFIRMATION_TTL_HOURS) - (now - sent_dt)
    return max(0.0, remaining.total_seconds() / 3600.0)


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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    author      TEXT NOT NULL,
                    body        TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_comments_session ON comments(session_id)"
            )
            self._ensure_session_columns(conn)
            conn.commit()

    def _ensure_session_columns(self, conn):
        """Idempotently add inbox-workflow columns to an existing sessions table."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        migrations = {
            "processing_status": "TEXT DEFAULT 'new'",
            "processed_by": "TEXT",
            "processing_updated_at": "TEXT",
            "urgency": "TEXT",
            "confirmation_status": "TEXT DEFAULT 'none'",
            "confirmation_token": "TEXT",
            "confirmation_sent_at": "TEXT",
            "confirmation_confirmed_at": "TEXT",
            "confirmation_cancelled_at": "TEXT",
        }
        for col, decl in migrations.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {decl}")

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
        result = dict(row)
        result["confirmation"] = effective_confirmation_status(result)
        result["confirmation_hours_left"] = confirmation_hours_left(result)
        return result

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, created_at, patient_name, status, condition_name, result_type "
                "FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_inbox(self) -> list[dict]:
        """Actionable sessions (completed/escalated), urgent-first then newest.
        Each row is enriched with phone, CPR, and doctor parsed from the stored result JSON."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, created_at, patient_name, status, condition_name, "
                "result_type, processing_status, processed_by, processing_updated_at, urgency, "
                "confirmation_status, confirmation_sent_at, confirmation_confirmed_at, "
                "confirmation_cancelled_at, result_json "
                "FROM sessions WHERE status IN ('completed', 'escalated') "
                "ORDER BY CASE urgency "
                "  WHEN 'immediate' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
                "created_at DESC"
            ).fetchall()
        enriched = []
        for r in rows:
            row = dict(r)
            raw = row.pop("result_json", None)
            phone, cpr, doctor = None, None, None
            if raw:
                try:
                    triage = (json.loads(raw) or {}).get("triage") or {}
                    phone = triage.get("phone_number")
                    cpr = triage.get("cpr_number")
                    doctor = triage.get("doctor")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass
            row["phone"] = phone
            row["cpr"] = cpr
            row["doctor"] = doctor
            row["confirmation"] = effective_confirmation_status(row)
            row["confirmation_hours_left"] = confirmation_hours_left(row)
            enriched.append(row)
        return enriched

    def set_processing(self, session_id: str, processing_status: str,
                       processed_by: str | None = None) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "UPDATE sessions SET processing_status = ?, processed_by = ?, "
                "processing_updated_at = ? WHERE session_id = ?",
                (processing_status, processed_by, now, session_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT session_id, processing_status, processed_by, processing_updated_at "
                "FROM sessions WHERE session_id = ?", (session_id,),
            ).fetchone()
        return dict(row)

    def set_urgency(self, session_id: str, urgency: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET urgency = ? WHERE session_id = ?",
                (urgency, session_id),
            )
            conn.commit()

    def save_result(self, session_id: str, result_json: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET result_json = ? WHERE session_id = ?",
                (result_json, session_id),
            )
            conn.commit()

    def mark_booked(self, session_id: str) -> dict:
        """Generate a confirmation token, set status=pending, sent_at=now.
        Returns {ok, token, phone} or {ok: False, error}."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT result_type, result_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "not found"}
            if (row["result_type"] or "") != "booking":
                return {"ok": False, "error": "not a booking"}
            phone = None
            if row["result_json"]:
                try:
                    triage = (json.loads(row["result_json"]) or {}).get("triage") or {}
                    phone = triage.get("phone_number")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    phone = None
            if not phone:
                return {"ok": False, "error": "no phone on file"}
            token = secrets.token_urlsafe(24)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE sessions SET confirmation_status='pending', confirmation_token=?, "
                "confirmation_sent_at=?, confirmation_confirmed_at=NULL, "
                "confirmation_cancelled_at=NULL WHERE session_id=?",
                (token, now, session_id),
            )
            conn.commit()
        return {"ok": True, "token": token, "phone": phone}

    def confirm_by_token(self, token: str) -> dict:
        """Patient confirms via token. Returns
        {status: confirmed|expired|already_confirmed|cancelled|invalid, session_id?}."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sessions WHERE confirmation_token = ?", (token,)
            ).fetchone()
            if row is None:
                return {"status": "invalid"}
            d = dict(row)
            stored = d.get("confirmation_status") or "none"
            if stored == "confirmed":
                return {"status": "already_confirmed", "session_id": d["session_id"]}
            if stored == "cancelled":
                return {"status": "cancelled", "session_id": d["session_id"]}
            if effective_confirmation_status(d) == "expired":
                return {"status": "expired", "session_id": d["session_id"]}
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE sessions SET confirmation_status='confirmed', "
                "confirmation_confirmed_at=? WHERE session_id=?",
                (now, d["session_id"]),
            )
            conn.commit()
            return {"status": "confirmed", "session_id": d["session_id"]}

    def cancel_booking(self, session_id: str) -> dict:
        """Secretary marks a booking cancelled (record-keeping; external slot
        release is manual). Returns {ok, status} or {ok: False, error}."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "not found"}
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE sessions SET confirmation_status='cancelled', "
                "confirmation_cancelled_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.commit()
        return {"ok": True, "status": "cancelled"}

    def get_result(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT result_json FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return None

    def get_conversation(self, session_id: str) -> list[dict]:
        """Read conversation messages from the SDK's triage_sessions.db.
        Returns chronological list of {role, content} dicts for user/assistant messages."""
        sdk_db = str(Path(self.db_path).parent / "triage_sessions.db")
        messages = []
        try:
            with sqlite3.connect(sdk_db) as conn:
                rows = conn.execute(
                    "SELECT message_data FROM agent_messages WHERE session_id = ? ORDER BY created_at ASC",
                    (session_id,),
                ).fetchall()
            for (raw,) in rows:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                role = msg.get("role")
                if role == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        # Skip internal agent inputs (handoff/confirmation prompts)
                        if content.startswith("Triage data collected") or content.startswith("Patient language:"):
                            continue
                        messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    content = msg.get("content")
                    text = None
                    if isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "output_text":
                                text_parts.append(part.get("text", ""))
                        if text_parts:
                            text = "\n".join(text_parts)
                    elif isinstance(content, str) and content.strip():
                        text = content
                    if text:
                        # Skip internal results (JSON handoff/booking outputs)
                        stripped = text.strip()
                        if stripped.startswith("{") and '"triage"' in stripped:
                            continue
                        messages.append({"role": "assistant", "content": text})
        except Exception:
            pass
        return messages

    def add_comment(self, session_id: str, author: str, body: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO comments (session_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (session_id, author, body, now),
            )
            conn.commit()
            comment_id = cur.lastrowid
        return {
            "id": comment_id, "session_id": session_id, "author": author,
            "body": body, "created_at": now, "updated_at": None,
        }

    def list_comments(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, session_id, author, body, created_at, updated_at "
                "FROM comments WHERE session_id = ? ORDER BY created_at ASC, id ASC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_comment(self, comment_id: int, body: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "UPDATE comments SET body = ?, updated_at = ? WHERE id = ?",
                (body, now, comment_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT id, session_id, author, body, created_at, updated_at "
                "FROM comments WHERE id = ?", (comment_id,),
            ).fetchone()
        return dict(row)

    def delete_comment(self, comment_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            conn.commit()
            return cur.rowcount > 0

    def delete_inactive(self) -> int:
        """Delete all sessions with status 'active' and their comments. Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            ids = [r[0] for r in conn.execute(
                "SELECT session_id FROM sessions WHERE status = 'active'"
            ).fetchall()]
            cursor = conn.execute("DELETE FROM sessions WHERE status = 'active'")
            for sid in ids:
                conn.execute("DELETE FROM comments WHERE session_id = ?", (sid,))
            conn.commit()
            return cursor.rowcount
