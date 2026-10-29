"""
Projects store - Tier 4 of Jarvis long-term memory.

Tracks multi-session project context so Jarvis remembers what the
user is working on and can reference it intelligently.

Example:
    "I am building a Django app called BlogsAI"
    -> ProjectStore.create("BlogsAI", "A Django blogging platform")
"""

from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional
import sqlite3

from jarvis.config import DB_PATH
from jarvis.logger import get_logger

logger = get_logger(__name__)

PROJECT_STATUSES = {"active", "paused", "done"}


class Project:
    def __init__(self, pid, name, description, status, last_mentioned, notes, created_at):
        self.id = pid
        self.name = name
        self.description = description
        self.status = status
        self.last_mentioned = last_mentioned
        self.notes = notes
        self.created_at = created_at

    def __repr__(self):
        return f"Project(id={self.id}, name={self.name!r}, status={self.status!r})"


class ProjectStore:
    """Persistent project tracking backed by SQLite."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("ProjectStore ready.")

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
                CREATE TABLE IF NOT EXISTS projects (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    name           TEXT    NOT NULL UNIQUE,
                    description    TEXT    DEFAULT '',
                    status         TEXT    DEFAULT 'active',
                    last_mentioned TEXT,
                    notes          TEXT    DEFAULT '',
                    created_at     TEXT    NOT NULL
                )
            """)
            conn.commit()

    def _row_to_project(self, row) -> Project:
        return Project(
            row["id"], row["name"], row["description"],
            row["status"], row["last_mentioned"], row["notes"], row["created_at"],
        )

    def create(self, name: str, description: str = "", notes: str = "") -> Project:
        """Create a new project (or return existing one by name)."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (name, description, notes, created_at) "
                "VALUES (?, ?, ?, ?)",
                (name.strip(), description.strip(), notes.strip(), now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name.strip(),)
            ).fetchone()
        p = self._row_to_project(row)
        logger.info("Project created/found: %s", p.name)
        return p

    def update_mentioned(self, project_id: int) -> None:
        """Update last_mentioned timestamp for a project."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "UPDATE projects SET last_mentioned = ? WHERE id = ?", (now, project_id)
            )
            conn.commit()

    def set_status(self, project_id: int, status: str) -> bool:
        """Update project status. Returns True on success."""
        if status not in PROJECT_STATUSES:
            logger.warning("Invalid project status: %s", status)
            return False
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE projects SET status = ? WHERE id = ?", (status, project_id)
            )
            conn.commit()
        return cur.rowcount > 0

    def get_active(self) -> List[Project]:
        """Return all active projects."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE status = 'active' ORDER BY last_mentioned DESC, id DESC"
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def get_all(self) -> List[Project]:
        """Return all projects."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
        return [self._row_to_project(r) for r in rows]

    def search(self, query: str) -> List[Project]:
        """Search projects by name or description."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE name LIKE ? OR description LIKE ? ORDER BY id DESC",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def delete(self, project_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        return cur.rowcount > 0

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) AS cnt FROM projects").fetchone()["cnt"]
