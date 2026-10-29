"""
Keyword-based wake word detector for Jarvis.

Uses the existing SpeechRecognition library with a SHORT phrase
limit (3 seconds) to listen for the wake phrase. The audio is
sent to Google's speech API only during these brief windows.

When no speech is detected (timeout), NO audio is sent externally —
only silence timeouts are processed locally.

How it minimizes API calls:
  - Short phrase limit (3s) means small audio clips
  - Timeouts (no speech) are handled locally — no API call
  - Only actual speech triggers a recognition request

This implementation can be replaced with a fully offline detector
(e.g., Picovoice Porcupine, Vosk) by subclassing BaseWakeWordDetector.
"""

import re
from typing import Optional

import speech_recognition as sr

from jarvis.config import SPEECH_LANGUAGE, WAKE_WORD, WAKE_WORD_TIMEOUT
from jarvis.logger import get_logger
from jarvis.speech.corrections import correct
from jarvis.wakeword.base import BaseWakeWordDetector

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Wake phrase configuration
# ---------------------------------------------------------------------------
# All phrases that will wake Jarvis up. Add new aliases here.
# Matching is case-insensitive. All phrases are checked as whole-word patterns.
#
# Common STT mishearings are included so the detector is robust.
# ---------------------------------------------------------------------------
WAKE_PHRASES = [
    "hey jarvis",       # primary wake phrase
    "okay jarvis",      # common alternative
    "ok jarvis",
    "jarvis",           # name alone (allowed — user explicitly requested it)
    "hey there",        # user-requested alias
    "hi jarvis",
    "yo jarvis",
    # STT mishearings of "hey jarvis"
    "hey travis",
    "hey harris",
    "a jarvis",
    "hey chavis",
]

# How long to capture audio for wake word detection.
# Must be long enough to capture the wake word + short inline command
# (e.g., "Hey Jarvis open Google Sheets") but short enough to feel
# responsive when just the wake word is said alone.
WAKE_PHRASE_LIMIT = 6  # seconds


class KeywordWakeWordDetector(BaseWakeWordDetector):
    """
    Detects the wake word using keyword matching on recognized speech.

    Listens in short bursts (3 seconds), recognizes speech via Google,
    and checks if the recognized text contains the wake phrase.
    """

    def __init__(self, recognizer: sr.Recognizer, microphone: sr.Microphone):
        """
        Initialize the wake word detector.

        Reuses the existing recognizer and microphone instances
        from the speech listener (avoids creating duplicate resources).

        Args:
            recognizer: An existing SpeechRecognition Recognizer.
            microphone: An existing SpeechRecognition Microphone.
        """
        self._recognizer = recognizer
        self._microphone = microphone
        self._wake_word = WAKE_WORD.lower()       # primary phrase from config
        self._wake_phrases = WAKE_PHRASES          # all accepted aliases
        self._timeout = WAKE_WORD_TIMEOUT
        self._last_detected_text = None
        self._matched_phrase: Optional[str] = None  # which phrase triggered

        logger.info(
            "Wake word detector initialized "
            "(primary: %r, aliases: %d, timeout: %ds).",
            self._wake_word, len(self._wake_phrases), self._timeout,
        )

    @property
    def wake_phrase(self) -> str:
        """The wake phrase this detector listens for."""
        return self._wake_word

    def extract_trailing_command(self) -> Optional[str]:
        """Extract and return any command spoken alongside the wake word in one phrase."""
        if self._last_detected_text:
            cmd = self.extract_command_after_wake_word(self._last_detected_text)
            self._last_detected_text = None
            return cmd
        return None

    def get_last_speech(self) -> Optional[str]:
        """Return any speech captured during the last listen attempt, then clear it."""
        val = getattr(self, "_last_speech", None)
        self._last_speech = None
        return val

    def listen_for_wake_word(self) -> bool:
        """
        Listen for the wake word in a short audio burst.

        Returns:
            True if one of the WAKE_PHRASES was detected, False on
            timeout or recognition failure.
        """
        self._last_detected_text = None
        self._matched_phrase = None
        try:
            with self._microphone as source:
                audio = self._recognizer.listen(
                    source,
                    timeout=self._timeout,
                    phrase_time_limit=WAKE_PHRASE_LIMIT,
                )

            # Only sends to API if we actually captured speech
            text = self._recognizer.recognize_google(
                audio, language=SPEECH_LANGUAGE
            )
            text = correct(text)  # Fix proper noun misrecognitions
            text_lower = text.lower().strip()
            logger.debug("Wake word check: heard %r", text_lower)

            # Check against all registered wake phrases
            matched = self._find_wake_phrase(text_lower)
            if matched:
                logger.info("Wake word detected! heard=%r matched=%r", text_lower, matched)
                self._last_detected_text = text
                self._matched_phrase = matched
                return True

            # Speech recognized but it wasn't a wake phrase —
            # store it so app.py can inspect it (but app.py will NOT
            # auto-route it — see the fix in app.py)
            logger.debug("Not a wake phrase: %r", text_lower)
            self._last_speech = text
            return False

        except sr.WaitTimeoutError:
            # No speech at all — no API call was made, just silence
            self._last_speech = None
            return False

        except sr.UnknownValueError:
            # Audio was captured but couldn't be understood
            return False

        except sr.RequestError as e:
            logger.error("Wake word recognition API error: %s", e)
            import time
            time.sleep(1.0)
            return False

        except OSError as e:
            logger.error("Microphone error during wake word detection: %s", e)
            return False

    def _find_wake_phrase(self, text: str) -> Optional[str]:
        """
        Check whether the text contains any registered wake phrase.

        Checks longest phrases first to prevent "jarvis" matching before
        "hey jarvis" has a chance to match.

        Args:
            text: Lowercased recognized speech (already stripped).

        Returns:
            The matched wake phrase string, or None if no match.
        """
        # Sort longest first so "hey jarvis" is checked before "jarvis"
        for phrase in sorted(self._wake_phrases, key=len, reverse=True):
            # Whole-word boundary match to prevent partial matches
            pattern = r'\b' + re.escape(phrase) + r'\b'
            if re.search(pattern, text):
                return phrase
        return None

    # Keep old name for compatibility with app.py
    def _contains_wake_word(self, text: str) -> bool:
        return self._find_wake_phrase(text) is not None

    def extract_command_after_wake_word(self, text: str) -> Optional[str]:
        """
        If the user says the wake word AND a command in one phrase,
        extract just the command portion.

        E.g., "Hey Jarvis open YouTube" -> "open YouTube"
             "Jarvis play Believer"     -> "play Believer"
             "Hey there set a timer"    -> "set a timer"

        Args:
            text: The full recognized text.

        Returns:
            The command portion (lowercased), or None if only the wake
            phrase was said.
        """
        text_lower = text.lower().strip()

        # Try each wake phrase from longest to shortest
        for phrase in sorted(self._wake_phrases, key=len, reverse=True):
            pattern = r'\b' + re.escape(phrase) + r'\b\s*'
            match = re.search(pattern, text_lower)
            if match:
                remainder = text_lower[match.end():].strip()
                return remainder if remainder else None

        return None
