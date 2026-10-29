"""
Core application module for Jarvis.

Contains the main Jarvis class that orchestrates startup and
coordinates all subsystems: wake word detection, speech input,
command processing, LLM brain, and voice output.

The Jarvis class provides an event system so UI layers (GUI, web, etc.)
can subscribe to events without modifying the core logic:
    jarvis.on("message", callback)
    jarvis.on("status", callback)
    jarvis.on("listening_state", callback)
"""

import threading
import time
from jarvis import __version__
from jarvis.brain import GroqBrain, GeminiBrain
from jarvis.commands import CommandProcessor
from jarvis.config import APP_NAME, WAKE_WORD, WAKE_WORD_ENABLED, BRAIN_PROVIDER, GEMINI_API_KEY, GROQ_API_KEY
from jarvis.logger import get_logger
from jarvis.memory import MemoryManager
from jarvis.permissions import PermissionManager, create_voice_confirm_fn
from jarvis.speech import GoogleSpeechListener
from jarvis.tts import Pyttsx3Speaker
from jarvis.utils import sanitize_ascii
from jarvis.wakeword import KeywordWakeWordDetector

logger = get_logger(__name__)


class Jarvis:
    """Main application class for the Jarvis assistant."""

    def __init__(self):
        """Initialize the Jarvis application."""
        self.name = APP_NAME
        self.version = __version__
        self.listener = None
        self.speaker = None
        self.brain = None
        self.processor = None
        self.wake_detector = None
        self.memory = None          # MemoryManager (all 5 tiers)
        self._running = False
        self._listening = True
        self._callbacks = {}
        logger.debug("Jarvis instance created.")

    # ------------------------------------------------------------------
    # Event system — allows UI layers to subscribe to events
    # ------------------------------------------------------------------

    def on(self, event: str, callback):
        """
        Register a callback for an event.

        Events:
            "message"         → callback(sender, text)
            "status"          → callback(subsystem, state)
            "listening_state" → callback(state)

        Args:
            event:    The event name.
            callback: The function to call when the event fires.
        """
        self._callbacks.setdefault(event, []).append(callback)

    def _emit(self, event: str, **kwargs):
        """Fire all callbacks registered for an event."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(**kwargs)
            except Exception as e:
                logger.error(f"Event callback error ({event}): {e}")

    # ------------------------------------------------------------------
    # Subsystem initialization
    # ------------------------------------------------------------------

    def _init_speech(self):
        """Initialize the speech recognition subsystem."""
        try:
            self.listener = GoogleSpeechListener()
            logger.info("Speech recognition:  ONLINE")
            self._emit("status", subsystem="speech", state="online")
        except RuntimeError as e:
            logger.error(f"Speech recognition:  FAILED -- {e}")
            logger.warning("Continuing without speech input.")
            self._emit("status", subsystem="speech", state="offline")

    def _init_tts(self):
        """Initialize the text-to-speech subsystem."""
        try:
            self.speaker = Pyttsx3Speaker()
            logger.info("Text-to-speech:      ONLINE")
            self._emit("status", subsystem="tts", state="online")
        except RuntimeError as e:
            logger.error(f"Text-to-speech:      FAILED -- {e}")
            logger.warning("Continuing without voice output.")
            self._emit("status", subsystem="tts", state="offline")

    def _init_memory(self):
        """Initialize the MemoryManager (all 5 memory tiers)."""
        try:
            self.memory = MemoryManager()
            self.memory.initialize()
            self.memory.start_session()
            self._emit("status", subsystem="memory", state="online")
            logger.info("Long-term memory:    ONLINE")
        except Exception as e:
            logger.error("Long-term memory:    FAILED -- %s", e)
            self.memory = None
            self._emit("status", subsystem="memory", state="offline")

    def _init_brain(self):
        """Initialize the LLM brain (supports Gemini and Groq with fallback)."""
        pref = BRAIN_PROVIDER.lower() if BRAIN_PROVIDER else ("gemini" if GEMINI_API_KEY else "groq")

        candidates = []
        if pref == "gemini":
            candidates = [("Gemini", GeminiBrain), ("Groq", GroqBrain)]
        else:
            candidates = [("Groq", GroqBrain), ("Gemini", GeminiBrain)]

        for name, brain_cls in candidates:
            try:
                self.brain = brain_cls(memory_manager=self.memory)
                logger.info("LLM brain (%s):     ONLINE", name)
                self._emit("status", subsystem="brain", state="online")
                return
            except Exception as e:
                logger.warning("LLM brain (%s) init failed: %s", name, e)

        logger.error("LLM brain:           FAILED")
        logger.warning(
            "Continuing without AI brain. "
            "Set GEMINI_API_KEY or GROQ_API_KEY in your .env file to enable."
        )
        self.brain = None
        self._emit("status", subsystem="brain", state="offline")

    def _init_commands(self):
        """Initialize the command processor with brain and permissions."""
        # Create voice confirmation if speaker + listener are available
        confirm_fn = None
        if self.speaker and self.listener:
            confirm_fn = create_voice_confirm_fn(
                self.speaker,
                self.listener,
                emit_fn=self._emit,
            )

        permission_manager = PermissionManager(confirm_fn=confirm_fn)
        self.processor = CommandProcessor(
            brain=self.brain,
            permission_manager=permission_manager,
        )
        logger.info("Command processor:   ONLINE")
        logger.info(
            f"Permissions:         ONLINE "
            f"({'voice confirmation' if confirm_fn else 'auto-mode'})"
        )
        self._emit("status", subsystem="commands", state="online")

    def _init_wake_word(self):
        """Initialize the wake word detector (reuses speech hardware)."""
        if not WAKE_WORD_ENABLED:
            logger.info("Wake word:           DISABLED")
            self._emit("status", subsystem="wake_word", state="disabled")
            return

        if not self.listener:
            logger.warning(
                "Wake word:           SKIPPED (no speech input available)"
            )
            self._emit("status", subsystem="wake_word", state="offline")
            return

        try:
            self.wake_detector = KeywordWakeWordDetector(
                recognizer=self.listener.recognizer,
                microphone=self.listener.microphone,
            )
            logger.info(
                f"Wake word:           ONLINE "
                f"(say \"{WAKE_WORD}\" to activate)"
            )
            self._emit("status", subsystem="wake_word", state="online")
        except Exception as e:
            logger.error(f"Wake word:           FAILED -- {e}")
            logger.warning("Continuing without wake word detection.")
            self._emit("status", subsystem="wake_word", state="offline")

    # ------------------------------------------------------------------
    # Conversation loop
    # ------------------------------------------------------------------

    def respond(self, text: str):
        """
        Respond to the user -- prints to terminal AND speaks aloud.

        This is the single output method for the entire app.
        All responses flow through here.

        Args:
            text: The response text.
        """
        # Sanitize for Windows console (cp1252 can't handle all Unicode)
        safe_text = sanitize_ascii(text)
        print(f"\n[{self.name}]: {safe_text}\n", flush=True)
        self._emit("message", sender="jarvis", text=text)
        if self.speaker:
            self.speaker.say(safe_text)

    def _on_speech(self, text: str):
        """
        Handle recognized speech -- the core conversation callback.

        Flow: listen -> process -> respond -> continue listening.

        Args:
            text: The recognized spoken text.
        """
        print(f"\n[You]: {text}", flush=True)
        self._emit("message", sender="user", text=text)
        self._emit("listening_state", state="processing")

        # Process the command through the command processor
        result = self.processor.process(text)

        # Speak the response
        self.respond(result.response)

        # Check if the user wants to quit
        if result.should_quit:
            self._running = False
            raise KeyboardInterrupt  # Triggers clean shutdown

    def _handle_conversational_follow_up(self, max_turns: int = 1):
        """
        Keep active listening open for a short follow-up window after responding.

        Allows natural multi-turn conversations without requiring the user
        to say "Hey Jarvis" repeatedly before each subsequent phrase.
        """
        turns = 0
        wait_elapsed = 0.0
        MAX_TTS_WAIT = 12.0  # Maximum seconds to wait for TTS to finish

        while turns < max_turns and self._running and self._listening:
            # Wait if TTS is still clearing, with a safety ceiling
            if self.speaker and getattr(self.speaker, "is_speaking", False):
                if wait_elapsed >= MAX_TTS_WAIT:
                    logger.warning("TTS wait exceeded max time in follow-up loop; proceeding.")
                else:
                    time.sleep(0.2)
                    wait_elapsed += 0.2
                    continue

            wait_elapsed = 0.0  # Reset wait timer once speaking is done
            self._emit("listening_state", state="listening")
            follow_up = self.listener.listen_once()
            if follow_up and self._listening:
                logger.info(f"Follow-up speech recognized: \"{follow_up}\"")
                self._on_speech(follow_up)
                turns += 1
            else:
                # User did not speak during follow-up window — gracefully return to wake standby
                break

    def _run_wake_word_loop(self):
        """
        Two-phase conversation loop with wake word detection and follow-up window.

        Phase 1: Listen for the wake word (short bursts, minimal API).
        Phase 2: Actively listen for a command (full recognition), followed by
                 an open follow-up window for natural conversation flow.
        """
        logger.info(
            f"Wake word mode active. Say \"{WAKE_WORD}\" to activate."
        )

        while self._running:
            if not self._listening:
                time.sleep(0.2)
                continue

            # Prevent listening to speaker playback
            if self.speaker and getattr(self.speaker, "is_speaking", False):
                time.sleep(0.2)
                continue

            # --- Phase 1: Wait for wake word ---
            self._emit("listening_state", state="wake_word")
            detected = self.wake_detector.listen_for_wake_word()

            if not detected:
                # Wake word not heard — discard whatever was said and
                # go back to listening. Do NOT process overheard speech.
                continue  # back to wake word standby

            if not self._listening:
                continue

            # --- Wake word detected! ---
            logger.info("Wake word detected -> listening for command...")

            self._emit("listening_state", state="activated")

            # Check if user spoke a command along with the wake word in one phrase
            inline_cmd = None
            if hasattr(self.wake_detector, "extract_trailing_command"):
                inline_cmd = self.wake_detector.extract_trailing_command()

            if inline_cmd:
                logger.info(f"Inline command detected after wake word: \"{inline_cmd}\"")
                self._on_speech(inline_cmd)
                self._handle_conversational_follow_up()
                continue

            print(f"\n[{self.name}]: Yes?", flush=True)
            self._emit("message", sender="jarvis", text="Yes?")
            if self.speaker:
                self.speaker.say("Yes?")

            # --- Phase 2: Listen for the actual command ---
            self._emit("listening_state", state="listening")
            text = self.listener.listen_once()

            if text:
                self._on_speech(text)
                self._handle_conversational_follow_up()
            else:
                # User said the wake word but then nothing
                logger.debug("No command received after wake word.")
                msg = "I'm listening, but I didn't catch that."
                print(f"\n[{self.name}]: {msg}\n", flush=True)
                self._emit("message", sender="jarvis", text=msg)
                if self.speaker:
                    self.speaker.say(msg)

    def _run_direct_loop(self):
        """
        Direct conversation loop without wake word (old behavior).

        Every recognized speech is processed as a command.
        Used when wake word is disabled.
        """
        logger.info("Direct mode: processing all speech.")
        while self._running:
            if not self._listening:
                time.sleep(0.2)
                continue

            self._emit("listening_state", state="listening")
            text = self.listener.listen_once()
            if text and self._listening:
                self._on_speech(text)

    def start_listening(self):
        """Enable speech/wake word listening."""
        self._listening = True
        logger.info("Listening enabled.")
        if self.wake_detector:
            self._emit("listening_state", state="wake_word")
        else:
            self._emit("listening_state", state="listening")

    def stop_listening(self):
        """Pause speech/wake word listening."""
        self._listening = False
        logger.info("Listening paused.")
        self._emit("listening_state", state="paused")

    @property
    def is_listening(self) -> bool:
        """Return True if microphone listening is currently enabled."""
        return self._listening

    def process_text(self, text: str) -> str:
        """
        Process a text command directly (e.g. from GUI text input or tests).

        Emits the user message, processes it via the command processor,
        and calls respond().

        Args:
            text: The text command.

        Returns:
            The response string.
        """
        text = text.strip()
        if not text:
            return ""

        print(f"\n[You]: {text}", flush=True)
        self._emit("message", sender="user", text=text)
        self._emit("listening_state", state="processing")

        if not self.processor:
            # Processor not yet initialized — initialize just the commands layer
            # (do NOT re-run full initialize() which would reinitialize mic and TTS)
            self._init_commands()


        result = self.processor.process(text)
        self.respond(result.response)

        if self._listening and self._running:
            self._emit(
                "listening_state",
                state="wake_word" if self.wake_detector else "listening",
            )
        else:
            self._emit("listening_state", state="paused" if not self._listening else "idle")

        return result.response

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self):
        """Initialize all subsystems without entering the conversation loop."""
        logger.info("=" * 50)
        logger.info("  %s v%s", self.name, self.version)
        logger.info("=" * 50)

        self._init_tts()
        self._init_speech()
        self._init_memory()          # memory before brain
        self._init_brain()
        self._init_commands()
        self._init_wake_word()

        logger.info("%s is ready.", self.name)
        self._emit("status", subsystem="jarvis", state="ready")

    def start(self):
        """Start the Jarvis assistant and enter the conversation loop."""
        self.initialize()
        self._running = True

        # Speak a greeting on startup
        if self.brain:
            greeting = f"{self.name} is online with AI brain active. "
        else:
            greeting = f"{self.name} is online in basic mode. "

        if self.wake_detector:
            greeting += f'Say "{WAKE_WORD}" to get my attention.'
        else:
            greeting += "How can I help you?"

        # Append pending task briefing if tasks exist
        if self.memory:
            task_brief = self.memory.startup_summary()
            if task_brief:
                greeting += " " + task_brief

        self.respond(greeting)

        if self.wake_detector:
            logger.info(
                f"Waiting for wake word \"{WAKE_WORD}\"... "
                "(say 'help' for commands, 'quit' to exit)"
            )
        else:
            logger.info("Listening... (say 'help' for commands, 'quit' to exit)")

        # Enter the conversation loop
        if self.listener:
            try:
                if self.wake_detector:
                    self._run_wake_word_loop()
                else:
                    self._run_direct_loop()
            except KeyboardInterrupt:
                pass  # Caught here so stop() always runs

        self.stop()

    def start_background(self):
        """Start Jarvis on a background thread (for GUI mode)."""
        thread = threading.Thread(target=self.start, daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Gracefully shut down the Jarvis assistant."""
        self._running = False
        self._emit("status", subsystem="jarvis", state="stopped")
        self._emit("listening_state", state="idle")
        logger.info(f"{self.name} is shutting down. Goodbye!")

