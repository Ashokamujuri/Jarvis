"""
Google Gemini LLM brain for Jarvis.

Uses the google-genai SDK (v1+) with streaming enabled for
minimum perceived latency.

Speed optimizations & Memory integration:
-----------------------------------------
1. Streaming (generate_content_stream):
   Tokens arrive as soon as the model starts generating, joined seamlessly.
2. Dict-based conversation history:
   Plain Python dicts (role/parts format) work reliably with generate_content_stream.
3. Multi-tier memory integration:
   Loads and persists conversation turns to SQLite via MemoryManager,
   injecting dynamic user facts, projects, and tasks into the system prompt.
4. Trimmed history window:
   Only the last _MAX_HISTORY_TURNS exchanges are kept in context.

Get a free API key at: https://aistudio.google.com/apikey
"""

from typing import Dict, List, Optional, TYPE_CHECKING

import google.genai as genai
from google.genai import types as genai_types

from jarvis.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_MAX_TOKENS,
    MEMORY_INJECT_FACTS,
)
from jarvis.logger import get_logger
from jarvis.brain.base import BaseBrain
from jarvis.personality import build_system_prompt

if TYPE_CHECKING:
    from jarvis.memory import MemoryManager

logger = get_logger(__name__)

# Keep this many user+model turn pairs in history
_MAX_HISTORY_TURNS = 10


class GeminiBrain(BaseBrain):
    """LLM brain powered by the Google Gemini API with streaming and memory."""

    def __init__(self, memory_manager: Optional["MemoryManager"] = None):
        """
        Initialize the Gemini client.

        Args:
            memory_manager: Optional MemoryManager instance for conversation
                            persistence and dynamic context injection.

        Raises:
            RuntimeError: If GEMINI_API_KEY is not set.
        """
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is not set. "
                "Get a free key at https://aistudio.google.com/apikey "
                "and add it to your .env file."
            )

        try:
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            self._model = GEMINI_MODEL
            self._max_tokens = GEMINI_MAX_TOKENS
            self._memory = memory_manager
            self._session_id: Optional[str] = None

            # Conversation history as plain dicts:
            # [{"role": "user", "parts": [{"text": "..."}]}, ...]
            self._history: List[Dict] = []

            if self._memory:
                self._session_id = self._memory.session_id
                if self._session_id:
                    recent_turns = self._memory.conversations.load_recent(
                        self._session_id
                    )
                    for turn in recent_turns:
                        role = "user" if turn.get("role") == "user" else "model"
                        content = turn.get("content", "")
                        if content:
                            self._history.append(self._make_turn(role, content))
                    logger.info(
                        "GeminiBrain: loaded %d turns from session %s.",
                        len(self._history),
                        self._session_id[:8],
                    )

            logger.info(
                "Gemini brain initialized (model=%s, streaming=True, max_tokens=%d).",
                self._model,
                self._max_tokens,
            )

        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Gemini client: {exc}") from exc

    def _make_turn(self, role: str, text: str) -> Dict:
        """Build a history dict entry for Gemini API."""
        return {"role": role, "parts": [{"text": text}]}

    def _build_gen_config(self) -> genai_types.GenerateContentConfig:
        """Assemble GenerationConfig with dynamic memory context."""
        if self._memory and MEMORY_INJECT_FACTS:
            ctx = self._memory.build_context(self._session_id)
        else:
            ctx = ""
        system_content = build_system_prompt(ctx)

        return genai_types.GenerateContentConfig(
            system_instruction=system_content,
            max_output_tokens=self._max_tokens,
            temperature=0.7,
        )

    def think(self, user_input: str) -> Optional[str]:
        """
        Send user_input to Gemini and return the full streamed response.

        Maintains conversation history so the model has context
        from previous exchanges. When a MemoryManager is available,
        history is persisted to SQLite for cross-restart continuity.

        Args:
            user_input: The text the user said.

        Returns:
            The LLM response string, or None on failure.
        """
        # Append the new user turn to history
        user_turn = self._make_turn("user", user_input)
        contents = self._history + [user_turn]

        # Persist user turn
        if self._memory and self._session_id:
            self._memory.conversations.save(self._session_id, "user", user_input)

        try:
            logger.debug("Sending to Gemini (%s) [stream]: %r", self._model, user_input)

            gen_config = self._build_gen_config()
            chunks = []
            for chunk in self._client.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=gen_config,
            ):
                if chunk.text:
                    chunks.append(chunk.text)

            reply = "".join(chunks).strip()

            if not reply:
                logger.warning("Gemini returned an empty response.")
                return "I didn't get a clear response. Could you try again?"

            logger.debug("Gemini response: %r", reply)

            # Persist both turns to in-memory history
            self._history.append(user_turn)
            self._history.append(self._make_turn("model", reply))

            # Persist assistant turn
            if self._memory and self._session_id:
                self._memory.conversations.save(self._session_id, "assistant", reply)

            # Trim to keep only the last N turns (2 dicts per turn)
            max_items = _MAX_HISTORY_TURNS * 2
            if len(self._history) > max_items:
                self._history = self._history[-max_items:]

            return reply

        except Exception as exc:
            err = str(exc).lower()

            if "quota" in err or "rate" in err or "429" in err:
                logger.warning("Gemini quota/rate limit: %s", exc)
                return "I'm being rate limited right now. Please try again in a moment."

            if "api_key" in err or "invalid" in err or "401" in err or "403" in err:
                logger.error("Gemini API key error: %s", exc)
                return "There's an issue with my API key. Please check the GEMINI_API_KEY in your .env file."

            if "network" in err or "connect" in err or "timeout" in err:
                logger.error("Gemini connection error: %s", exc)
                return "I'm having trouble connecting to Gemini. Please check your internet connection."

            logger.error("Gemini unexpected error: %s", exc, exc_info=True)
            return "Something went wrong while thinking. Please try again."

    def reset_conversation(self) -> None:
        """Clear all conversation history and start fresh."""
        self._history = []
        logger.info("Gemini conversation history cleared.")
