"""
Brain (LLM) package for Jarvis.

Provides AI-powered responses by sending user input to a large
language model. The architecture uses a base class (BaseBrain) so
the LLM provider can be swapped without changing the rest of Jarvis.
"""

from jarvis.brain.base import BaseBrain
from jarvis.brain.groq_brain import GroqBrain
from jarvis.brain.gemini_brain import GeminiBrain

__all__ = ["BaseBrain", "GroqBrain", "GeminiBrain"]
