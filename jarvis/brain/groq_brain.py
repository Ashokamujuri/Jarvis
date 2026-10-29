"""
Groq LLM brain for Jarvis.

Uses the Groq API (free tier) with fast inference on models like
Llama 3 and Mixtral. Requires a GROQ_API_KEY environment variable.

Get a free API key at: https://console.groq.com/keys
"""

from typing import Optional, TYPE_CHECKING

from groq import Groq, APIError, APIConnectionError, RateLimitError

from jarvis.config import GROQ_API_KEY, GROQ_MODEL, GROQ_MAX_TOKENS, MEMORY_INJECT_FACTS
from jarvis.logger import get_logger
from jarvis.brain.base import BaseBrain
from jarvis.personality import build_system_prompt

if TYPE_CHECKING:
    from jarvis.memory import MemoryManager

logger = get_logger(__name__)


class GroqBrain(BaseBrain):
    """LLM brain powered by the Groq API."""

    def __init__(self, memory_manager: Optional["MemoryManager"] = None):
        """
        Initialize the Groq client.

        Args:
            memory_manager: Optional MemoryManager instance. When provided,
                            conversation history is persisted to SQLite and
                            memory context is injected into every LLM call.

        Raises:
            RuntimeError: If the GROQ_API_KEY is not set.
        """
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY environment variable is not set. "
                "Get a free key at https://console.groq.com/keys "
                "and add it to your .env file."
            )

        try:
            self.client = Groq(api_key=GROQ_API_KEY)
            self.model = GROQ_MODEL
            self.max_tokens = GROQ_MAX_TOKENS
            self._memory = memory_manager
            self._session_id: Optional[str] = None

            # Conversation history for multi-turn context.
            # When a MemoryManager is available this list is seeded from the
            # DB so previous sessions are remembered.
            self._history = []

            if self._memory:
                self._session_id = self._memory.session_id
                if self._session_id:
                    self._history = self._memory.conversations.load_recent(
                        self._session_id
                    )
                    logger.info(
                        "GroqBrain: loaded %d turns from session %s.",
                        len(self._history), self._session_id[:8],
                    )

            # Always prepend the dynamic system prompt
            self._rebuild_system_message()

            logger.info("Groq brain initialized (model=%s).", self.model)

        except Exception as e:
            raise RuntimeError(f"Failed to initialize Groq client: {e}") from e

    def _rebuild_system_message(self) -> None:
        """
        Rebuild and inject the system message at position 0 of _history.
        Called on init and before every think() call so memory context
        is always up-to-date.
        """
        if self._memory and MEMORY_INJECT_FACTS:
            ctx = self._memory.build_context(self._session_id)
        else:
            ctx = ""

        system_content = build_system_prompt(ctx)

        if self._history and self._history[0].get("role") == "system":
            self._history[0]["content"] = system_content
        else:
            self._history.insert(0, {"role": "system", "content": system_content})

    def think(self, user_input: str) -> Optional[str]:
        """
        Send user input to Groq and return the LLM response.

        Maintains conversation history so the model has context
        from previous exchanges. When a MemoryManager is available,
        history is persisted to SQLite for cross-restart continuity.

        Args:
            user_input: The text the user said.

        Returns:
            The LLM's response string, or None on failure.
        """
        # Refresh the system message with the latest memory context
        self._rebuild_system_message()

        # Add the user message to history
        self._history.append({"role": "user", "content": user_input})

        # Persist user turn
        if self._memory and self._session_id:
            self._memory.conversations.save(self._session_id, "user", user_input)

        try:
            logger.debug("Sending to Groq (%s): \"%s\"", self.model, user_input)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._history,
                max_tokens=self.max_tokens,
                temperature=0.7,
            )

            reply = response.choices[0].message.content.strip()

            # Add the assistant's reply to history for context
            self._history.append({"role": "assistant", "content": reply})

            # Persist assistant turn
            if self._memory and self._session_id:
                self._memory.conversations.save(self._session_id, "assistant", reply)

            # Keep in-memory history manageable (system + last 20 exchanges)
            if len(self._history) > 41:
                self._history = [self._history[0]] + self._history[-40:]

            logger.debug("Groq response: \"%s\"", reply)
            return reply

        except RateLimitError:
            self._pop_last_user_message()
            logger.warning("Groq rate limit reached. Please wait a moment.")
            return "I'm being rate limited right now. Please try again in a moment."

        except APIConnectionError:
            self._pop_last_user_message()
            logger.error("Cannot connect to Groq API. Check your internet.")
            return "I'm having trouble connecting to my brain. Please check your internet connection."

        except APIError as e:
            err_str = str(e).lower()
            if any(term in err_str for term in ("model_not_found", "model_decommissioned", "does not exist", "decommissioned")) and self.model != "qwen/qwen3.8-27b":
                logger.warning("Groq model %s unavailable (%s). Trying fallback to qwen/qwen3.8-27b...", self.model, e)
                self.model = "qwen/qwen3.8-27b"
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=self._history,
                        max_tokens=self.max_tokens,
                        temperature=0.7,
                    )
                    reply = response.choices[0].message.content.strip()
                    self._history.append({"role": "assistant", "content": reply})
                    if self._memory and self._session_id:
                        self._memory.conversations.save(self._session_id, "assistant", reply)
                    return reply
                except Exception as fb_err:
                    logger.error("Groq fallback failed: %s", fb_err)

            self._pop_last_user_message()
            logger.error("Groq API error: %s", e)
            return "I encountered an error while thinking. Please try again."

        except Exception as e:
            self._pop_last_user_message()
            logger.error("Unexpected error in Groq brain: %s", e)
            return "Something went wrong on my end. Please try again."

    def _pop_last_user_message(self) -> None:
        """Remove the last user message from history on API failure."""
        if self._history and self._history[-1].get("role") == "user":
            self._history.pop()

    def reset_conversation(self) -> None:
        """Clear in-memory conversation history and start fresh."""
        self._history = []
        self._rebuild_system_message()
        logger.info("Conversation history cleared.")
