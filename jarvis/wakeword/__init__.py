"""
Wake word detection package for Jarvis.

Provides wake-word detection so Jarvis only actively listens
for commands after the user says the wake phrase (e.g., "Hey Jarvis").
"""

from jarvis.wakeword.base import BaseWakeWordDetector
from jarvis.wakeword.keyword_detector import KeywordWakeWordDetector

__all__ = ["BaseWakeWordDetector", "KeywordWakeWordDetector"]
