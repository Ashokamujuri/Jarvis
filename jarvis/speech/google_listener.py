"""
Google Speech Recognition listener.

Uses the `SpeechRecognition` library with Google's free web API
to convert microphone audio into text. This is the default engine
and requires an internet connection.
"""

from typing import Optional

import speech_recognition as sr

from jarvis.config import SPEECH_LANGUAGE, SPEECH_TIMEOUT, SPEECH_PHRASE_LIMIT
from jarvis.logger import get_logger
from jarvis.speech.base import BaseSpeechListener
from jarvis.speech.corrections import correct

logger = get_logger(__name__)


class GoogleSpeechListener(BaseSpeechListener):
    """Speech listener powered by Google's free speech recognition API."""

    def __init__(self):
        """Initialize the recognizer and microphone."""
        self.recognizer = sr.Recognizer()

        # Try to access the microphone early so we fail fast with a clear message
        try:
            self.microphone = sr.Microphone()
            logger.info("Microphone initialized successfully.")
        except Exception as e:
            logger.error(
                "Could not access the microphone. "
                "Make sure a microphone is connected and not in use by another app."
            )
            raise RuntimeError("Microphone not available") from e

        # Calibrate for ambient noise on startup
        self._calibrate()

    def _calibrate(self):
        """Adjust the recognizer sensitivity to ambient noise."""
        logger.info("Calibrating microphone for ambient noise... (1 second)")
        # Pause threshold: how long of silence marks end of a phrase.
        # 1.2s allows natural inter-word pauses without cutting off sentences.
        self.recognizer.pause_threshold = 1.2
        # Non-speaking duration: silence buffer appended before phrase ends.
        self.recognizer.non_speaking_duration = 0.7
        self.recognizer.dynamic_energy_threshold = True

        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            # Ensure minimum threshold so low background hum doesn't trigger endless false speech captures
            self.recognizer.energy_threshold = max(self.recognizer.energy_threshold, 300)
            logger.info(
                f"Microphone calibration complete (energy_threshold={self.recognizer.energy_threshold:.0f})."
            )
        except OSError as e:
            logger.warning(f"Calibration failed: {e}. Continuing with defaults.")
            self.recognizer.energy_threshold = 300

    def listen_once(self) -> Optional[str]:
        """
        Listen to the microphone and return recognized text.

        Returns:
            Recognized text string, or None if nothing was understood.
        """
        try:
            with self.microphone as source:
                logger.debug("Listening...")
                audio = self.recognizer.listen(
                    source,
                    timeout=SPEECH_TIMEOUT,
                    phrase_time_limit=SPEECH_PHRASE_LIMIT,
                )

            logger.debug("Processing speech...")
            text = self.recognizer.recognize_google(
                audio, language=SPEECH_LANGUAGE
            )
            text = correct(text)
            logger.info(f"Recognized: \"{text}\"")
            return text

        except sr.WaitTimeoutError:
            logger.debug("No speech detected (timeout). Still listening...")
            return None

        except sr.UnknownValueError:
            logger.debug("Could not understand the audio. Try again.")
            return None

        except sr.RequestError as e:
            logger.error(
                f"Google Speech Recognition service error: {e}. "
                "Check your internet connection."
            )
            return None

        except OSError as e:
            logger.error(f"Microphone error: {e}")
            return None
