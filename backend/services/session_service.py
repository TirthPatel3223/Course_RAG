"""
Session Service — SQLite-based conversation persistence.
Manages user sessions and chat message history for multi-turn conversations.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)


class SessionService:
    """
    Manages user sessions and chat history using SQLite.

    Usage:
        sessions = SessionService()
        session_id = sessions.create_session()
        sessions.add_message(session_id, "user", "What is the deadline?")
        history = sessions.get_history(session_id)
    """

    def __init__(self):
        settings = get_settings()
        db_path = settings.get_session_db_path()
        self._db_path = str(db_path)
        self._timeout_hours = settings.session_timeout_hours
        self._init_db()
        logger.info(f"Session service initialized: {self._db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """Get a new database connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_active TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    query_type TEXT,
                    source_chunks TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_last_active
                    ON sessions(last_active);
            """
            )
            conn.commit()
        finally:
            conn.close()

    def create_session(self) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, last_active) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        logger.debug(f"Created session: {session_id}")
        return session_id

    def validate_session(self, session_id: str) -> bool:
        """Check if a session exists and is not expired."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT last_active FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

            if not row:
                return False

            last_active = datetime.fromisoformat(row["last_active"])
            cutoff = datetime.now(timezone.utc) - timedelta(hours=self._timeout_hours)

            return last_active > cutoff
        finally:
            conn.close()

    def touch_session(self, session_id: str):
        """Update the last_active timestamp for a session."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        query_type: Optional[str] = None,
        source_chunks: Optional[list[dict]] = None,
    ):
        """Add a message to a session's history."""
        now = datetime.now(timezone.utc).isoformat()
        chunks_json = json.dumps(source_chunks) if source_chunks else None

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO messages
                   (session_id, role, content, query_type, source_chunks, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, role, content, query_type, chunks_json, now),
            )
            conn.commit()

            # Also update session's last_active
            conn.execute(
                "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_history(
        self, session_id: str, limit: int = 50
    ) -> list[dict]:
        """
        Get conversation history for a session.

        Args:
            session_id: The session to retrieve history for.
            limit: Maximum number of messages to return (most recent).

        Returns:
            List of message dicts ordered chronologically.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT role, content, query_type, source_chunks, created_at
                   FROM messages
                   WHERE session_id = ?
                   ORDER BY id DESC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()

            messages = []
            for row in reversed(rows):  # Reverse to get chronological order
                msg = {
                    "role": row["role"],
                    "content": row["content"],
                }
                if row["query_type"]:
                    msg["query_type"] = row["query_type"]
                if row["source_chunks"]:
                    msg["source_chunks"] = json.loads(row["source_chunks"])
                msg["timestamp"] = row["created_at"]
                messages.append(msg)

            return messages
        finally:
            conn.close()

    def get_messages_for_llm(
        self, session_id: str, limit: int = 20
    ) -> list[dict]:
        """
        Get conversation history formatted for LLM context.
        Only includes role and content (no metadata).
        """
        history = self.get_history(session_id, limit)
        return [{"role": msg["role"], "content": msg["content"]} for msg in history]

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and their messages. Returns count deleted."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=self._timeout_hours)
        ).isoformat()

        conn = self._get_conn()
        try:
            # Get expired session IDs
            expired = conn.execute(
                "SELECT session_id FROM sessions WHERE last_active < ?",
                (cutoff,),
            ).fetchall()

            expired_ids = [row["session_id"] for row in expired]

            if expired_ids:
                placeholders = ",".join("?" * len(expired_ids))
                conn.execute(
                    f"DELETE FROM messages WHERE session_id IN ({placeholders})",
                    expired_ids,
                )
                conn.execute(
                    f"DELETE FROM sessions WHERE session_id IN ({placeholders})",
                    expired_ids,
                )
                conn.commit()

            logger.info(f"Cleaned up {len(expired_ids)} expired sessions")
            return len(expired_ids)
        finally:
            conn.close()

    def get_session_count(self) -> int:
        """Get total number of active sessions."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM sessions").fetchone()
            return row["cnt"]
        finally:
            conn.close()


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """Get or create the singleton SessionService instance."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
