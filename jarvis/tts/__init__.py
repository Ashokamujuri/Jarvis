"""
Text-to-speech package for Jarvis.

Provides voice output so Jarvis can speak responses aloud.
The architecture mirrors the speech-recognition package: a base class
(BaseSpeaker) defines the interface, and concrete implementations
can be swapped without changing the rest of Jarvis.
"""

from jarvis.tts.base import BaseSpeaker
from jarvis.tts.pyttsx_speaker import Pyttsx3Speaker

__all__ = ["BaseSpeaker", "Pyttsx3Speaker"]
