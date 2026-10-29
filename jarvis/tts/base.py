"""
Base class for text-to-speech speakers.

Any TTS engine (pyttsx3, gTTS, Coqui, Azure, etc.) should
subclass BaseSpeaker and implement the `say` method.
This makes the engine swappable without touching the rest of Jarvis.
"""

from abc import ABC, abstractmethod


class BaseSpeaker(ABC):
    """Abstract base class that all TTS speakers must implement."""

    @abstractmethod
    def say(self, text: str) -> bool:
        """
        Speak the given text aloud.

        Args:
            text: The text to speak.

        Returns:
            True if the text was spoken successfully, False otherwise.
        """

    @abstractmethod
    def set_rate(self, rate: int) -> None:
        """
        Set the speech rate (words per minute).

        Args:
            rate: Speaking speed in words per minute.
        """

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        """
        Set the speech volume.

        Args:
            volume: Volume level from 0.0 (silent) to 1.0 (max).
        """
