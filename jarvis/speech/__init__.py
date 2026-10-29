"""
Speech input package for Jarvis.

Provides microphone listening and speech-to-text conversion.
The architecture uses a base class (BaseSpeechListener) so the
underlying engine can be swapped without changing the rest of Jarvis.
"""

from jarvis.speech.base import BaseSpeechListener
from jarvis.speech.google_listener import GoogleSpeechListener

__all__ = ["BaseSpeechListener", "GoogleSpeechListener"]
