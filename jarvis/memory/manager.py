"""
MemoryManager - central orchestrator for all 5 memory tiers.

Provides a single access point for:
  Tier 1 - ConversationStore  (session history)
  Tier 2 - MemoryStore        (long-term user facts)
  Tier 3 - PreferenceStore    (user preferences)
  Tier 4 - ProjectStore       (project context)
  Tier 5 - TaskStore          (tasks and goals)

The most important public method is build_context() which assembles
a memory context block injected into the LLM system prompt on every
brain.think() call.
"""

from typing import Optional

from jarvis.config import DB_PATH
from jarvis.logger import get_logger
from jarvis.memory.conversation import ConversationStore
from jarvis.memory.store import MemoryStore
from jarvis.memory.preferences import PreferenceStore
from jarvis.memory.projects import ProjectStore
from jarvis.memory.tasks import TaskStore

logger = get_logger(__name__)

# Maximum number of facts to inject into the system prompt
_MAX_FACTS = 10
# Maximum number of recent conversation turns to inject
_MAX_DISPLAY_TURNS = 5


class MemoryManager:
    """
    Unified interface for all Jarvis memory tiers.

    Usage::

        mgr = MemoryManager()
        mgr.initialize()
        session = mgr.start_session()

        # Build context for the LLM
        ctx = mgr.build_context(session)

        # Save a conversation turn
        mgr.conversations.save(session, "user", "Hello")
        mgr.conversations.save(session, "assistant", "Hi there!")
    """

    def __init__(self, db_path=None):
        db = db_path or DB_PATH
        self.conversations  = ConversationStore(db_path=db)
        self.facts          = MemoryStore(db_path=db)
        self.preferences    = PreferenceStore(db_path=db)
        self.projects       = ProjectStore(db_path=db)
        self.tasks          = TaskStore(db_path=db)
        self._session_id: Optional[str] = None

    def initialize(self) -> None:
        """
        Ensure all DB tables exist and run any pending migrations.
        Safe to call on every startup.
        """
        # Stores init their own tables in __init__, so we just log counts.
        fact_count  = self.facts.count()
        pref_count  = self.preferences.count()
        proj_count  = self.projects.count()
        task_count  = self.tasks.count_pending()
        logger.info(
            "MemoryManager initialized: facts=%d prefs=%d projects=%d pending_tasks=%d",
            fact_count, pref_count, proj_count, task_count,
        )

    def start_session(self) -> str:
        """
        Create a new session ID for this Jarvis run.
        Stores it so callers can use mgr.session_id without passing it around.
        """
        self._session_id = ConversationStore.new_session()
        logger.info("MemoryManager: new session %s", self._session_id)
        return self._session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def build_context(self, session_id: Optional[str] = None) -> str:
        """
        Build a memory context block for injection into the LLM system prompt.

        Returns an empty string if there is nothing to inject (no facts,
        no active projects, no pending tasks, no recent conversation).

        Args:
            session_id: The current session (defaults to self._session_id).

        Returns:
            A formatted string to append to the system prompt.
        """
        sid = session_id or self._session_id
        blocks = []

        # ---- Facts -------------------------------------------------------
        all_facts = self.facts.get_all()
        if all_facts:
            # Prioritise recently accessed facts
            top_facts = all_facts[:_MAX_FACTS]
            lines = ["[FACTS I KNOW ABOUT YOU]"]
            for m in top_facts:
                lines.append(f"- {m.content}  ({m.category})")
            blocks.append("\n".join(lines))

        # ---- Active projects ---------------------------------------------
        active_projects = self.projects.get_active()
        if active_projects:
            lines = ["[ACTIVE PROJECTS]"]
            for p in active_projects[:5]:
                desc = f": {p.description}" if p.description else ""
                lines.append(f"- {p.name}{desc}")
            blocks.append("\n".join(lines))

        # ---- Pending tasks -----------------------------------------------
        pending = self.tasks.get_pending(limit=5)
        if pending:
            lines = ["[PENDING TASKS]"]
            for t in pending:
                priority_tag = f" [{t.priority}]" if t.priority != "normal" else ""
                lines.append(f"- {t.title}{priority_tag}")
            blocks.append("\n".join(lines))

        # ---- Recent conversation -----------------------------------------
        if sid:
            recent = self.conversations.load_for_display(sid, limit=_MAX_DISPLAY_TURNS)
            if recent:
                lines = [f"[RECENT CONVERSATION - last {len(recent)} turns]"]
                for turn in recent:
                    speaker = "User" if turn["role"] == "user" else "Jarvis"
                    lines.append(f"{speaker}: {turn['content']}")
                blocks.append("\n".join(lines))

        if not blocks:
            return ""

        return "\n\n".join(blocks)

    def startup_summary(self) -> Optional[str]:
        """
        Return a short spoken summary of pending tasks for the startup greeting.
        Returns None if there is nothing to announce.
        """
        pending = self.tasks.get_pending(limit=3)
        urgent = [t for t in pending if t.priority in ("high", "urgent")]
        total  = self.tasks.count_pending()

        if total == 0:
            return None

        if urgent:
            names = ", ".join(t.title for t in urgent[:2])
            suffix = f" and {total - len(urgent)} more" if total > len(urgent) else ""
            return f"You have {total} pending task{'s' if total != 1 else ''}. High priority: {names}{suffix}."

        return f"You have {total} pending task{'s' if total != 1 else ''}."
