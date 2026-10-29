"""
Tasks store - Tier 5 of Jarvis long-term memory.

Persistent to-do list and goal tracker. Tasks can be linked to
projects (Tier 4) and have priority/status/due-date attributes.

Example:
    "Add task: write the README for BlogsAI, high priority"
    -> TaskStore.create("Write README for BlogsAI", priority="high")
"""

from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional
import sqlite3

from jarvis.config import DB_PATH
from jarvis.logger import get_logger

logger = get_logger(__name__)

TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
TASK_STATUSES   = {"pending", "in_progress", "done", "cancelled"}


class Task:
    def __init__(self, tid, title, description, priority, status,
                 due_date, project_id, created_at, updated_at):
        self.id = tid
        self.title = title
        self.description = description
        self.priority = priority
        self.status = status
        self.due_date = due_date
        self.project_id = project_id
        self.created_at = created_at
        self.updated_at = updated_at

    def __repr__(self):
        return f"Task(id={self.id}, title={self.title!r}, priority={self.priority!r}, status={self.status!r})"


class TaskStore:
    """Persistent task/goal tracking backed by SQLite."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("TaskStore ready.")

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
                CREATE TABLE IF NOT EXISTS tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT    NOT NULL,
                    description TEXT    DEFAULT '',
                    priority    TEXT    DEFAULT 'normal',
                    status      TEXT    DEFAULT 'pending',
                    due_date    TEXT    DEFAULT NULL,
                    project_id  INTEGER DEFAULT NULL,
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            """)
            conn.commit()

    def _row_to_task(self, row) -> Task:
        return Task(
            row["id"], row["title"], row["description"],
            row["priority"], row["status"], row["due_date"],
            row["project_id"], row["created_at"], row["updated_at"],
        )

    def create(
        self,
        title: str,
        description: str = "",
        priority: str = "normal",
        due_date: Optional[str] = None,
        project_id: Optional[int] = None,
    ) -> Task:
        """Create a new task."""
        if priority not in TASK_PRIORITIES:
            priority = "normal"
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (title, description, priority, status, "
                "due_date, project_id, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)",
                (title.strip(), description.strip(), priority, due_date, project_id, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        t = self._row_to_task(row)
        logger.info("Task created: [%s] %s", t.priority, t.title)
        return t

    def set_status(self, task_id: int, status: str) -> bool:
        """Update task status. Returns True on success."""
        if status not in TASK_STATUSES:
            return False
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, task_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def complete(self, task_id: int) -> bool:
        """Mark a task as done."""
        return self.set_status(task_id, "done")

    def get_pending(self, limit: int = 10) -> List[Task]:
        """Return pending tasks ordered by priority then created date."""
        priority_order = "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE status IN ('pending', 'in_progress') "
                f"ORDER BY {priority_order}, created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_all(self, include_done: bool = False) -> List[Task]:
        """Return all tasks."""
        where = "" if include_done else "WHERE status NOT IN ('done', 'cancelled')"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def search(self, query: str) -> List[Task]:
        """Search tasks by title or description."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE title LIKE ? OR description LIKE ? ORDER BY created_at DESC",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def delete(self, task_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        return cur.rowcount > 0

    def count_pending(self) -> int:
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE status IN ('pending', 'in_progress')"
            ).fetchone()["cnt"]
