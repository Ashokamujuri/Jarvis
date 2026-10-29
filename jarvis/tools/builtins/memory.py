"""
Memory tool for Jarvis.

Allows the user to explicitly ask Jarvis to remember, recall,
or forget information. Only stores facts when the user says
something like "remember that..." or "don't forget...".

Supports four actions:
  - SAVE:    "Remember that my favorite language is Python"
  - RECALL:  "What do you remember?" / "What do you know about Python?"
  - FORGET:  "Forget about my favorite language"
  - CLEAR:   "Forget everything" / "Clear all memories"
"""

import re
from typing import Optional, Tuple

from jarvis.logger import get_logger
from jarvis.memory import MemoryStore
from jarvis.permissions import RiskLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils import match_any_keyword

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Intent patterns
# ------------------------------------------------------------------

# Phrases that indicate the user wants Jarvis to SAVE a memory
SAVE_TRIGGERS = [
    "remember that", "remember this", "don't forget that",
    "don't forget", "do not forget", "keep in mind that",
    "keep in mind", "note that", "make a note",
    "save this", "store this", "memorize",
    "remember my", "remember i",
]

# Phrases that indicate the user wants to RECALL memories
RECALL_TRIGGERS = [
    "what do you remember", "what do you know",
    "what have i told you", "do you remember",
    "recall", "show me my memories", "list memories",
    "what do you know about", "my memories",
]

# Phrases that indicate the user wants to FORGET something
FORGET_TRIGGERS = [
    "forget about", "forget that", "forget my",
    "delete memory", "remove memory", "erase memory",
    "forget everything", "clear all memories",
    "clear memory", "clear memories", "erase everything",
    "forget all", "delete all memories",
]

# All trigger patterns combined (for the matches() method)
ALL_TRIGGERS = SAVE_TRIGGERS + RECALL_TRIGGERS + FORGET_TRIGGERS


class MemoryTool(BaseTool):
    """Saves, recalls, and deletes user-provided memories."""

    name = "memory"
    description = "Remembers, recalls, and forgets facts you tell me."
    keywords = set()  # Not used — matches() is overridden

    def __init__(self):
        """Initialize with a MemoryStore instance."""
        self.store = MemoryStore()
        count = self.store.count()
        logger.info(f"MemoryTool: {count} memories in store.")

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def action_summary(self, raw_text: str) -> str:
        """Provide a specific summary for confirmation prompts."""
        cleaned = raw_text.lower().strip()
        if self._is_clear_all(cleaned):
            return "permanently erase all saved memories"
        action = self._classify_intent(cleaned)
        if action == "forget":
            query = self._extract_forget_query(cleaned)
            return f"delete memories regarding '{query}'" if query else "delete selected memories"
        return "modify memory storage"

    def get_risk_level(self, raw_text: str) -> RiskLevel:
        """Elevate risk to MODERATE when clearing all memories."""
        cleaned = raw_text.lower().strip()
        if self._is_clear_all(cleaned):
            return RiskLevel.MODERATE
        return RiskLevel.SAFE

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def matches(self, text: str) -> bool:
        """Check if the input is a memory-related command."""
        return match_any_keyword(text, ALL_TRIGGERS)

    # ------------------------------------------------------------------
    # Execution — route to save, recall, or forget
    # ------------------------------------------------------------------

    def execute(self, raw_text: str) -> ToolResult:
        """Route the user's memory command to the right action."""
        cleaned = raw_text.lower().strip()

        # Determine intent (order matters: forget before recall,
        # since "forget" is more destructive and should be explicit)
        action = self._classify_intent(cleaned)

        if action == "save":
            return self._do_save(cleaned)
        elif action == "forget":
            return self._do_forget(cleaned)
        elif action == "recall":
            return self._do_recall(cleaned)
        else:
            return ToolResult(
                success=False,
                message="I'm not sure what to do with that memory command.",
            )

    def _classify_intent(self, text: str) -> str:
        """Classify the user's intent: save, recall, or forget."""
        # Check forget first (more specific than recall)
        if match_any_keyword(text, FORGET_TRIGGERS):
            return "forget"

        # Check save
        if match_any_keyword(text, SAVE_TRIGGERS):
            return "save"

        # Check recall
        if match_any_keyword(text, RECALL_TRIGGERS):
            return "recall"

        return "unknown"

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _do_save(self, text: str) -> ToolResult:
        """Extract the fact from the text and save it."""
        fact = self._extract_fact(text)

        if not fact:
            return ToolResult(
                success=False,
                message="What would you like me to remember?",
            )

        # Try to detect a category from the content
        category = self._detect_category(fact)

        memory = self.store.save(fact, category=category)
        return ToolResult(
            success=True,
            message=f"Got it, I'll remember that. {fact}",
            data={"action": "save", "memory_id": memory.id},
        )

    @staticmethod
    def _extract_fact(text: str) -> Optional[str]:
        """
        Extract the fact to remember from the spoken text.

        Strips trigger phrases to isolate the actual information.
        E.g., "remember that my favorite color is blue"
              -> "my favorite color is blue"
        """
        cleaned = text.strip()

        # Try each trigger (longest first)
        sorted_triggers = sorted(SAVE_TRIGGERS, key=len, reverse=True)
        for trigger in sorted_triggers:
            pattern = r'\b' + re.escape(trigger) + r'\b\s*'
            match = re.search(pattern, cleaned)
            if match:
                fact = cleaned[match.end():].strip()
                # Remove trailing filler
                for filler in ["please", "for me", "okay"]:
                    if fact.endswith(filler):
                        fact = fact[: -len(filler)].strip()
                return fact if fact else None

        return None

    @staticmethod
    def _detect_category(fact: str) -> str:
        """
        Auto-detect a category based on the content.

        Simple keyword-based categorization. Falls back to "general".
        """
        fact_lower = fact.lower()

        categories = {
            "personal": [
                "my name", "my age", "my birthday", "i am", "i'm",
                "i live", "my address", "my phone",
            ],
            "preferences": [
                "favorite", "favourite", "prefer", "like", "love",
                "hate", "dislike",
            ],
            "work": [
                "project", "work", "job", "office", "meeting",
                "deadline", "colleague", "boss",
            ],
            "technical": [
                "programming", "language", "code", "python", "javascript",
                "api", "database", "server",
            ],
        }

        for category, keywords in categories.items():
            if any(kw in fact_lower for kw in keywords):
                return category

        return "general"

    # ------------------------------------------------------------------
    # Recall
    # ------------------------------------------------------------------

    def _do_recall(self, text: str) -> ToolResult:
        """Retrieve memories, optionally filtered by a search term."""
        query = self._extract_recall_query(text)

        if query:
            # Search for specific memories
            memories = self.store.search(query)
            if memories:
                lines = [f"Here's what I remember about \"{query}\":"]
                for m in memories:
                    lines.append(f"  {m.content}")
                return ToolResult(
                    success=True,
                    message=" ".join(lines),
                    data={"action": "recall", "count": len(memories)},
                )
            else:
                return ToolResult(
                    success=True,
                    message=f"I don't have any memories about \"{query}\".",
                )
        else:
            # List all memories
            memories = self.store.get_all()
            if memories:
                count = len(memories)
                # Speak up to 5 for brevity
                shown = memories[:5]
                lines = [f"I have {count} memories stored. Here are the most recent:"]
                for m in shown:
                    lines.append(f"{m.content}.")
                if count > 5:
                    lines.append(f"And {count - 5} more.")
                return ToolResult(
                    success=True,
                    message=" ".join(lines),
                    data={"action": "recall", "count": count},
                )
            else:
                return ToolResult(
                    success=True,
                    message=(
                        "I don't have any memories stored yet. "
                        "Tell me something to remember!"
                    ),
                )

    @staticmethod
    def _extract_recall_query(text: str) -> Optional[str]:
        """Extract an optional search query from a recall command."""
        cleaned = text.strip()

        # "what do you know about Python" -> "Python"
        about_pattern = r'\babout\b\s+(.+)'
        match = re.search(about_pattern, cleaned)
        if match:
            query = match.group(1).strip()
            for filler in ["please", "for me", "?"]:
                query = query.rstrip(filler).strip()
            return query if query else None

        return None

    # ------------------------------------------------------------------
    # Forget
    # ------------------------------------------------------------------

    def _do_forget(self, text: str) -> ToolResult:
        """Delete memories matching the user's description."""
        # Check for "forget everything" / "clear all"
        if self._is_clear_all(text):
            count = self.store.clear_all()
            if count > 0:
                return ToolResult(
                    success=True,
                    message=f"Done. I've cleared all {count} memories.",
                    data={"action": "clear_all", "count": count},
                )
            else:
                return ToolResult(
                    success=True,
                    message="There are no memories to clear.",
                )

        # Extract what to forget
        query = self._extract_forget_query(text)

        if not query:
            return ToolResult(
                success=False,
                message="What would you like me to forget?",
            )

        # Search for matching memories
        matches = self.store.search(query)
        if not matches:
            return ToolResult(
                success=True,
                message=f"I don't have any memories about \"{query}\".",
            )

        # Delete all matching memories
        count = self.store.delete_by_content(query)
        return ToolResult(
            success=True,
            message=f"Done. I've forgotten {count} memory about \"{query}\"."
            if count == 1
            else f"Done. I've forgotten {count} memories about \"{query}\".",
            data={"action": "forget", "count": count, "query": query},
        )

    @staticmethod
    def _is_clear_all(text: str) -> bool:
        """Check if the user wants to clear ALL memories."""
        clear_phrases = [
            "forget everything", "clear all memories", "erase everything",
            "clear memory", "clear memories", "forget all",
            "delete all memories",
        ]
        return any(phrase in text for phrase in clear_phrases)

    @staticmethod
    def _extract_forget_query(text: str) -> Optional[str]:
        """Extract what the user wants to forget."""
        cleaned = text.strip()

        # "forget about my favorite color" -> "my favorite color"
        sorted_triggers = sorted(FORGET_TRIGGERS, key=len, reverse=True)
        for trigger in sorted_triggers:
            pattern = r'\b' + re.escape(trigger) + r'\b\s*'
            match = re.search(pattern, cleaned)
            if match:
                query = cleaned[match.end():].strip()
                for filler in ["please", "for me"]:
                    if query.endswith(filler):
                        query = query[: -len(filler)].strip()
                return query if query else None

        return None
