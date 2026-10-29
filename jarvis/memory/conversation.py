"""
Conversation history store - Tier 1 of Jarvis long-term memory.

Persists the LLM conversation history to SQLite so context survives
Jarvis restarts. The in-memory _history list in GroqBrain is loaded
from this store on startup and saved after each exchange.

Rolling window: only the last history_limit non-system messages are
kept per session.  Older turns are pruned automatically.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional
import sqlite3

from jarvis.config import DB_PATH
from jarvis.logger import get_logger

logger = get_logger(__name__)

DEFAULT_HISTORY_LIMIT = 40


class ConversationStore:
    """Persists LLM conversation turns to SQLite for cross-restart context."""

    def __init__(self, db_path=None, history_limit: int = DEFAULT_HISTORY_LIMIT):
        self.db_path = db_path or DB_PATH
        self.history_limit = history_limit
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("ConversationStore ready (limit=%d).", history_limit)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT    NOT NULL,
                    role        TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    token_est   INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_conv_session
                    ON conversation_history(session_id, id);
            """)
            conn.commit()

    @staticmethod
    def new_session() -> str:
        """Generate a new unique session ID."""
        return str(uuid.uuid4())

    def latest_session(self) -> Optional[str]:
        """Return the session_id of the most recently active session."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT session_id FROM conversation_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row["session_id"] if row else None

    def save(self, session_id: str, role: str, content: str) -> None:
        """Persist one conversation turn and prune the window if needed."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversation_history "
                "(session_id, role, content, timestamp, token_est) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, now, len(content.split())),
            )
            conn.commit()
        self._prune(session_id)

    def load_recent(self, session_id: str, limit: Optional[int] = None) -> List[dict]:
        """
        Return the most recent turns as [{role, content}] dicts,
        oldest-first, excluding system messages.
        """
        cap = limit or self.history_limit
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM conversation_history "
                "WHERE session_id = ? AND role != 'system' "
                "ORDER BY id DESC LIMIT ?",
                (session_id, cap),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def load_for_display(self, session_id: str, limit: int = 5) -> List[dict]:
        """Return recent turns with timestamps for memory context injection."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM conversation_history "
                "WHERE session_id = ? AND role != 'system' "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [
            {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
            for r in reversed(rows)
        ]

    def clear_session(self, session_id: str) -> int:
        """Delete all turns for the given session."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM conversation_history WHERE session_id = ?", (session_id,)
            )
            conn.commit()
        return cur.rowcount

    def count(self, session_id: str) -> int:
        """Return number of stored turns for the session."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS cnt FROM conversation_history WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]

    def _prune(self, session_id: str) -> None:
        """Remove oldest non-system turns to stay within history_limit."""
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM conversation_history "
                "WHERE session_id = ? AND role != 'system'",
                (session_id,),
            ).fetchone()["cnt"]
            if total > self.history_limit:
                excess = total - self.history_limit
                old_ids = conn.execute(
                    "SELECT id FROM conversation_history "
                    "WHERE session_id = ? AND role != 'system' ORDER BY id ASC LIMIT ?",
                    (session_id, excess),
                ).fetchall()
                ids = [r["id"] for r in old_ids]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"DELETE FROM conversation_history WHERE id IN ({placeholders})", ids
                )
                conn.commit()
                logger.debug("ConversationStore: pruned %d old turns.", len(ids))
