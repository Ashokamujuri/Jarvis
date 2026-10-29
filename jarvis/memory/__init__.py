"""
Memory package for Jarvis.

Five-tier persistent local memory:
  Tier 1 - ConversationStore  (session conversation history)
  Tier 2 - MemoryStore        (explicit long-term user facts)
  Tier 3 - PreferenceStore    (user behavioral preferences)
  Tier 4 - ProjectStore       (ongoing project context)
  Tier 5 - TaskStore          (tasks and goals)

The MemoryManager class orchestrates all tiers through a single
access point and builds the memory context injected into the LLM.
"""

from jarvis.memory.store import MemoryStore
from jarvis.memory.conversation import ConversationStore
from jarvis.memory.preferences import PreferenceStore
from jarvis.memory.projects import ProjectStore
from jarvis.memory.tasks import TaskStore
from jarvis.memory.manager import MemoryManager

__all__ = [
    "MemoryManager",
    "MemoryStore",
    "ConversationStore",
    "PreferenceStore",
    "ProjectStore",
    "TaskStore",
]
