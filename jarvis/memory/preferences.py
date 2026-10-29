"""
Preferences store - Tier 3 of Jarvis long-term memory.

Stores persistent key-value user preferences so Jarvis remembers
behavioral settings across restarts.

Examples:
    music.platform  = "youtube"
    voice.rate      = "fast"
    browser.default = "chrome"
    news.language   = "english"
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Optional
import sqlite3

from jarvis.config import DB_PATH
from jarvis.logger import get_logger

logger = get_logger(__name__)


class PreferenceStore:
    """Persistent key-value preference storage backed by SQLite."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("PreferenceStore ready.")

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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key         TEXT PRIMARY KEY,
                    value       TEXT    NOT NULL,
                    description TEXT    DEFAULT '',
                    updated_at  TEXT    NOT NULL
                )
            """)
            conn.commit()

    def set(self, key: str, value: str, description: str = "") -> None:
        """Set or update a preference."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO preferences (key, value, description, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "description=excluded.description, updated_at=excluded.updated_at",
                (key.lower().strip(), value.strip(), description, now),
            )
            conn.commit()
        logger.info("Preference set: %s = %s", key, value)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Return the value for key, or default if not set."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key.lower().strip(),)
            ).fetchone()
        return row["value"] if row else default

    def get_all(self) -> Dict[str, str]:
        """Return all preferences as a {key: value} dict."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM preferences ORDER BY key"
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def delete(self, key: str) -> bool:
        """Delete a preference. Returns True if it existed."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM preferences WHERE key = ?", (key.lower().strip(),)
            )
            conn.commit()
        return cur.rowcount > 0

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) AS cnt FROM preferences").fetchone()["cnt"]
