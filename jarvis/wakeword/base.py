"""
Base class for wake word detectors.

Any wake word engine (keyword matching, Picovoice Porcupine,
Snowboy, etc.) should subclass BaseWakeWordDetector and implement
the `listen_for_wake_word` method.

This makes the wake word system swappable without touching
the rest of Jarvis.
"""

from abc import ABC, abstractmethod


class BaseWakeWordDetector(ABC):
    """Abstract base class for all wake word detectors."""

    @abstractmethod
    def listen_for_wake_word(self) -> bool:
        """
        Listen for the wake word.

        This method should block until:
          - The wake word is detected (return True)
          - A timeout occurs with no speech (return False)
          - An error occurs (return False)

        The implementation should be lightweight and avoid
        unnecessary processing when no speech is detected.

        Returns:
            True if the wake word was detected, False otherwise.
        """

    @property
    @abstractmethod
    def wake_phrase(self) -> str:
        """The wake phrase this detector listens for."""
