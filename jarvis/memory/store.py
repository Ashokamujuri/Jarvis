"""
Memory store for Jarvis.

Provides persistent storage for facts and information the user
explicitly asks Jarvis to remember. Uses SQLite for simple,
local, zero-configuration storage.

The database file is stored in the project's data/ directory.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from jarvis.config import DATA_DIR, DB_PATH
from jarvis.logger import get_logger

logger = get_logger(__name__)

# Default database location from config
DEFAULT_DB_PATH = DB_PATH


class Memory:
    """A single memory entry."""

    def __init__(
        self,
        memory_id: int,
        content: str,
        category: str,
        created_at: str,
    ):
        self.id = memory_id
        self.content = content
        self.category = category
        self.created_at = created_at

    def __repr__(self):
        return f"Memory(id={self.id}, category='{self.category}', content='{self.content}')"


class MemoryStore:
    """
    SQLite-backed persistent memory for Jarvis.

    Provides CRUD operations for storing user-provided facts.
    Only stores information when the user explicitly asks.

    Usage:
        store = MemoryStore()
        store.save("My favorite color is blue", category="preferences")
        results = store.search("color")
        store.delete(results[0].id)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the memory store and create the table if needed.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to <project>/data/memory.db.
        """
        self.db_path = db_path or DEFAULT_DB_PATH

        # Ensure the data directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create the table if it doesn't exist
        self._init_db()
        logger.info(f"Memory store initialized ({self.db_path}).")

    @contextmanager
    def _get_connection(self):
        """Context manager yielding a SQLite connection and ensuring clean closure."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create the memories table and run safe column migrations."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    content      TEXT    NOT NULL,
                    category     TEXT    NOT NULL DEFAULT 'general',
                    created_at   TEXT    NOT NULL,
                    tags         TEXT    DEFAULT '',
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT   DEFAULT NULL
                )
            """)
            conn.commit()

        # Safe migrations — add new columns to existing databases
        self._safe_add_column("tags",          "TEXT",    "''")
        self._safe_add_column("access_count",  "INTEGER", "0")
        self._safe_add_column("last_accessed", "TEXT",    "NULL")

    def _safe_add_column(self, col: str, col_type: str, default: str) -> None:
        """Add a column to memories if it does not already exist."""
        with self._get_connection() as conn:
            existing = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if col not in existing:
                conn.execute(
                    f"ALTER TABLE memories ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                conn.commit()
                logger.info("MemoryStore: migrated — added column '%s'.", col)

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def save(self, content: str, category: str = "general", tags: str = "") -> "Memory":
        """
        Save a new memory.

        Args:
            content:  The fact or information to remember.
            category: Optional category (e.g., "preferences", "personal").
            tags:     Optional comma-separated tags for filtering.

        Returns:
            The created Memory object.
        """
        created_at = datetime.now().isoformat(timespec="seconds")

        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO memories (content, category, created_at, tags) "
                "VALUES (?, ?, ?, ?)",
                (content.strip(), category.strip().lower(), created_at, tags.strip()),
            )
            conn.commit()
            memory_id = cursor.lastrowid

        memory = Memory(memory_id, content.strip(), category.strip().lower(), created_at)
        logger.info("Memory saved: [%s] %s", category, content.strip())
        return memory

    def get_all(self) -> List["Memory"]:
        """
        Retrieve all memories, most recently accessed first.

        Returns:
            A list of all Memory objects.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, content, category, created_at "
                "FROM memories ORDER BY "
                "COALESCE(last_accessed, created_at) DESC"
            ).fetchall()

        return [
            Memory(row["id"], row["content"], row["category"], row["created_at"])
            for row in rows
        ]

    def search(self, query: str) -> List["Memory"]:
        """
        Search memories by content or category (case-insensitive).
        Also updates access tracking on matched rows.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, content, category, created_at "
                "FROM memories "
                "WHERE content LIKE ? OR category LIKE ? OR tags LIKE ? "
                "ORDER BY COALESCE(last_accessed, created_at) DESC",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()

        results = [
            Memory(row["id"], row["content"], row["category"], row["created_at"])
            for row in rows
        ]
        logger.debug("Memory search for '%s': %d results.", query, len(results))

        # Update access tracking for matched memories
        for m in results:
            self.update_access(m.id)

        return results

    def delete(self, memory_id: int) -> bool:
        """
        Delete a memory by its ID.

        Args:
            memory_id: The ID of the memory to delete.

        Returns:
            True if the memory was deleted, False if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Memory deleted: id={memory_id}")
        else:
            logger.warning(f"Memory not found for deletion: id={memory_id}")
        return deleted

    def delete_by_content(self, query: str) -> int:
        """
        Delete all memories matching a search query.

        Args:
            query: The search term — deletes all memories whose
                   content contains this text (case-insensitive).

        Returns:
            The number of memories deleted.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE content LIKE ?",
                (f"%{query}%",),
            )
            conn.commit()
            count = cursor.rowcount

        logger.info(f"Deleted {count} memories matching '{query}'.")
        return count

    def update_access(self, memory_id: int) -> None:
        """Increment access_count and update last_accessed for a memory."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE memories SET access_count = access_count + 1, "
                "last_accessed = ? WHERE id = ?",
                (now, memory_id),
            )
            conn.commit()

    def count(self) -> int:
        """Return the total number of stored memories."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()
        return row["cnt"]

    def clear_all(self) -> int:
        """
        Delete ALL memories. Use with caution.

        Returns:
            The number of memories deleted.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM memories")
            conn.commit()
            count = cursor.rowcount

        logger.warning(f"All memories cleared ({count} deleted).")
        return count
