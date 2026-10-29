"""
Base class for speech listeners.

Any speech-to-text engine (Google, Whisper, Vosk, etc.) should
subclass BaseSpeechListener and implement the `listen_once` method.
This makes the engine swappable without touching the rest of Jarvis.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseSpeechListener(ABC):
    """Abstract base class that all speech listeners must implement."""

    @abstractmethod
    def listen_once(self) -> Optional[str]:
        """
        Listen to the microphone and return recognized text.

        Returns:
            The recognized text as a string, or None if nothing
            was understood or an error occurred.
        """

    def listen_loop(self, callback):
        """
        Continuously listen and pass recognized text to a callback.

        This default implementation runs an infinite loop calling
        listen_once(). Subclasses can override for more efficient
        streaming approaches.

        Args:
            callback: A callable that receives the recognized text (str).
        """
        while True:
            text = self.listen_once()
            if text is not None:
                callback(text)
