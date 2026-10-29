"""
Pyttsx3 text-to-speech speaker.

Uses the `pyttsx3` library for fully offline, cross-platform TTS.
On Windows this uses the built-in SAPI5 voices — no internet required.

Uses a dedicated background worker thread and request queue to guarantee
thread safety and prevent SAPI5 COM apartment deadlocks across threads.
"""

import queue
import threading
from typing import Optional

import pyttsx3

from jarvis.config import TTS_RATE, TTS_VOLUME
from jarvis.logger import get_logger
from jarvis.tts.base import BaseSpeaker

logger = get_logger(__name__)


class Pyttsx3Speaker(BaseSpeaker):
    """Text-to-speech speaker powered by pyttsx3 (offline and thread-safe)."""

    def __init__(self):
        """Initialize the pyttsx3 TTS engine on a dedicated worker thread."""
        self._rate = TTS_RATE
        self._volume = TTS_VOLUME
        self._queue = queue.Queue()
        self._ready_event = threading.Event()
        self._init_error = None

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="TTSWorkerThread",
        )
        self._worker_thread.start()

        # Wait for worker thread to initialize pyttsx3
        if not self._ready_event.wait(timeout=5.0):
            logger.error("TTS worker thread initialization timed out.")
            raise RuntimeError("TTS engine initialization timed out")

        if self._init_error:
            logger.error(f"Failed to initialize TTS engine: {self._init_error}")
            raise RuntimeError(f"TTS engine not available: {self._init_error}")

        logger.info(
            f"TTS engine initialized (rate={self._rate}, volume={self._volume})."
        )

    def _worker_loop(self):
        """Dedicated worker thread handling all pyttsx3 COM interactions."""
        # Initialize COM on this worker thread if on Windows
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self._rate)
            self._engine.setProperty("volume", self._volume)
        except Exception as e:
            self._init_error = e
            self._ready_event.set()
            return

        self._is_speaking = False
        self._ready_event.set()  # Signal init complete


        while True:
            item = self._queue.get()
            if item is None:
                break

            action, payload, done_event = item
            try:
                if action == "say":
                    self._is_speaking = True
                    logger.debug(f'Speaking: "{payload}"')
                    self._engine.say(payload)
                    self._engine.runAndWait()
                elif action == "rate":
                    self._engine.setProperty("rate", payload)
                elif action == "volume":
                    self._engine.setProperty("volume", payload)
            except Exception as e:
                logger.error(f"TTS error while speaking: {e}")
            finally:
                self._is_speaking = False
                if done_event:
                    done_event.set()
                self._queue.task_done()

    @property
    def is_speaking(self) -> bool:
        """Return True if the TTS engine is currently speaking or has pending speech."""
        return self._is_speaking or not self._queue.empty()

    def say(self, text: str, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Speak the given text aloud.

        Thread-safe: pushes speech request to dedicated worker thread.
        Protected by a safety timeout scaled to text length so caller can never deadlock.

        Args:
            text: The text to speak.
            block: Whether to wait for speech to complete before returning.
            timeout: Maximum seconds to wait before unblocking caller (None = auto-calculated).

        Returns:
            True if spoken successfully or queued, False on error.
        """
        import time

        if not text or not text.strip():
            logger.warning("say() called with empty text — skipping.")
            return False

        # Auto-calculate timeout based on word count (approx 3 words per sec + grace period)
        if timeout is None or timeout <= 0:
            words = len(text.split())
            timeout = max(10.0, words * 0.6 + 6.0)

        done_event = threading.Event() if block else None
        self._queue.put(("say", text, done_event))

        if block and done_event:
            completed = done_event.wait(timeout=timeout)
            if not completed:
                logger.warning(f"TTS speech timed out after {timeout:.1f}s: '{text}'")
            else:
                # Small 200ms grace period so audio hardware buffer clears
                # before microphone starts listening again (prevents self-echo)
                time.sleep(0.2)
            return completed

        return True

    def set_rate(self, rate: int) -> None:
        """Set the speech rate (words per minute)."""
        self._rate = rate
        self._queue.put(("rate", rate, None))
        logger.debug(f"TTS rate set to {rate}.")

    def set_volume(self, volume: float) -> None:
        """Set the speech volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, volume))
        self._queue.put(("volume", self._volume, None))
        logger.debug(f"TTS volume set to {self._volume}.")

