"""
Base class for LLM brain providers.

Any LLM provider (Groq, OpenAI, Google Gemini, local Ollama, etc.)
should subclass BaseBrain and implement the `think` method.
This makes the provider swappable without touching the rest of Jarvis.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseBrain(ABC):
    """Abstract base class that all LLM brain providers must implement."""

    @abstractmethod
    def think(self, user_input: str) -> Optional[str]:
        """
        Send user input to the LLM and return the response.

        Args:
            user_input: The text the user said.

        Returns:
            The LLM's response as a string, or None if the request failed.
        """

    @abstractmethod
    def reset_conversation(self) -> None:
        """Clear the conversation history and start fresh."""
