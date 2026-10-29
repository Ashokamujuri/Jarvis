"""
Command processor for Jarvis.

Routes spoken input through three layers:
  1. System commands (fast, offline keyword matching — greetings, quit, etc.)
  2. Tool execution (registered tools via ToolRegistry + SafeExecutor)
  3. LLM brain (open-ended conversation, if connected)

Design:
    - System commands are conversational shortcuts (hello, goodbye, help).
    - Tools are actions that DO something (get time, system info, open app).
    - The LLM brain handles everything else as natural conversation.
    - Each layer is independent and can be extended without touching the others.
"""

import random
import re
from typing import Optional

from jarvis.config import APP_NAME
from jarvis.logger import get_logger
from jarvis.permissions import PermissionManager
from jarvis.tools import ToolRegistry, SafeExecutor
from jarvis.tools.builtins import register_all
from jarvis.utils import match_any_keyword

logger = get_logger(__name__)


class CommandResult:
    """The result of processing a command."""

    def __init__(self, response: str, should_quit: bool = False):
        self.response = response
        self.should_quit = should_quit


class CommandProcessor:
    """
    Processes spoken text and produces responses.

    Three-layer routing:
        1. System commands  → instant conversational responses
        2. Tool registry    → execute an action, return the result
        3. LLM brain        → open-ended AI conversation
    """

    def __init__(self, brain=None, permission_manager=None):
        """
        Initialize the command processor.

        Args:
            brain:              An optional BaseBrain instance for LLM responses.
            permission_manager: An optional PermissionManager for tool confirmations.
        """
        self.name = APP_NAME
        self.brain = brain

        # --- Tool registry ---
        self.tool_registry = ToolRegistry()
        register_all(self.tool_registry)

        # --- Safe executor with permission checks ---
        self.executor = SafeExecutor(
            permission_manager=permission_manager or PermissionManager()
        )

        # --- System commands (conversational, no tool execution) ---
        # Each entry: (set of trigger keywords, handler function)
        # Order matters — first match wins.
        self._commands = [
            (
                {"hello", "hi", "hey", "greetings", "good morning",
                 "good afternoon", "good evening"},
                self._handle_greeting,
            ),
            (
                {"how are you", "how do you do", "how's it going",
                 "what's up", "how are you doing"},
                self._handle_how_are_you,
            ),
            (
                {"what is your name", "what's your name", "who are you",
                 "tell me your name"},
                self._handle_name,
            ),
            (
                {"what can you do", "help", "what do you do",
                 "what are your commands"},
                self._handle_help,
            ),
            (
                {"thank you", "thanks", "thank you very much"},
                self._handle_thanks,
            ),
            (
                {"reset conversation", "clear history", "start over",
                 "new conversation"},
                self._handle_reset,
            ),
            (
                {"goodbye", "bye", "quit", "exit", "stop",
                 "shut down", "shutdown", "see you"},
                self._handle_goodbye,
            ),
        ]

        brain_status = "connected" if brain else "not connected"
        logger.info(
            f"Command processor loaded: "
            f"{len(self._commands)} system commands, "
            f"{self.tool_registry.count} tools "
            f"(brain: {brain_status})."
        )

    def process(self, text: str) -> CommandResult:
        """
        Process spoken text and return a response.

        Flow: compound-play extraction -> system commands -> tools -> LLM brain -> fallback.

        Compound command handling:
            Phrases like "open YouTube and play Sahi" are decomposed.
            The "play <song>" part is extracted and routed to play_music
            directly, so the user does not need to issue two separate
            commands.

        Args:
            text: The recognized speech text.

        Returns:
            A CommandResult with the response and quit flag.
        """
        cleaned = text.lower().strip()
        logger.info("[ROUTING] input=%r", cleaned)

        # Layer 0: Compound command extraction
        # Detect "open/do X and play <song>" — extract play sub-command
        play_sub = self._extract_play_subcommand(cleaned)
        if play_sub:
            logger.info(
                "[ROUTING] Compound command detected — extracted play sub-command: %r",
                play_sub,
            )
            play_tool = self.tool_registry.find_match(play_sub)
            if play_tool and play_tool.name == "play_music":
                logger.info("[ROUTING] -> TOOL | tool=play_music (via compound extract)")
                result = self.executor.run(play_tool, play_sub)
                return CommandResult(result.message)

        # Layer 1: System commands (conversational, fast)
        for keywords, handler in self._commands:
            if self._matches(cleaned, keywords):
                logger.info("[ROUTING] -> SYSTEM_COMMAND | matched keywords")
                return handler(cleaned)

        # Layer 2: Tool execution (with permission checks)
        tool = self.tool_registry.find_match(cleaned)
        if tool:
            logger.info("[ROUTING] -> TOOL | tool=%s", tool.name)
            result = self.executor.run(tool, text)
            return CommandResult(result.message)

        # Layer 3: LLM brain (open conversation)
        if self.brain:
            logger.info("[ROUTING] -> LLM_BRAIN")
            return self._ask_brain(text)

        # Layer 4: No brain — fallback
        logger.info("[ROUTING] -> FALLBACK (no match, no brain)")
        return self._handle_unknown(text)

    # ------------------------------------------------------------------
    # Matching logic
    # ------------------------------------------------------------------

    @staticmethod
    def _matches(text: str, keywords: set) -> bool:
        """
        Check if the text matches any keyword using word boundaries.

        Delegates to jarvis.utils.match_any_keyword.
        """
        return match_any_keyword(text, keywords)

    @staticmethod
    def _extract_play_subcommand(text: str) -> str:
        """
        Detect compound phrases that contain a play sub-command and extract it.

        Patterns handled:
          "open youtube and play Believer"       -> "play Believer"
          "open youtube and play Sahi"           -> "play Sahi"
          "yeah open youtube and play sahi"      -> "play sahi"
          "search the web and play counting stars" -> "play counting stars"

        Returns the extracted "play <song>" phrase, or empty string if none found.
        """
        import re as _re
        cleaned = text.lower().strip()

        # Match leading prefixes: "yeah play ...", "please play ...", "can you play ..."
        m_prefix = _re.search(
            r"^(?:yeah|yes|yep|hey|ok|okay|please|can you|could you|would you)\s+(play(?:\s+me)?\s+.+)$",
            cleaned,
        )
        if m_prefix:
            candidate = m_prefix.group(1).strip()
            play_content = _re.sub(r"^play(?:\s+me)?\s*", "", candidate).strip()
            if play_content and len(play_content) >= 2:
                return candidate

        # Match " and play <something>" or " then play <something>"
        m = _re.search(
            r"\b(?:and|then)\s+(play(?:\s+me)?\s+.+)$",
            cleaned,
        )
        if m:
            candidate = m.group(1).strip()
            # Make sure there is actual content after 'play'
            play_content = _re.sub(r"^play(?:\s+me)?\s*", "", candidate).strip()
            if play_content and len(play_content) >= 2:
                return candidate
        return ""

    def is_known_intent(self, text: str) -> bool:
        """
        Check if the given text matches a registered tool or system command.

        Used to detect direct spoken commands without requiring a separate
        wake word prefix.
        """
        cleaned = text.lower().strip()
        for keywords, _ in self._commands:
            if self._matches(cleaned, keywords):
                return True
        return self.tool_registry.find_match(cleaned) is not None

    # ------------------------------------------------------------------
    # LLM brain integration
    # ------------------------------------------------------------------

    def _ask_brain(self, text: str) -> CommandResult:
        """Send unmatched input to the LLM brain."""
        logger.info(f'Asking LLM brain: "{text}"')
        response = self.brain.think(text)

        if response:
            return CommandResult(response)
        else:
            return CommandResult(
                "I'm sorry, I had trouble thinking about that. "
                "Could you try again?"
            )

    # ------------------------------------------------------------------
    # System command handlers — conversational responses
    # ------------------------------------------------------------------

    def _handle_greeting(self, text: str) -> CommandResult:
        responses = [
            f"Hello! I'm {self.name}, your personal assistant. How can I help you?",
            f"Hi there! {self.name} at your service.",
            f"Hey! Good to hear from you. What can I do for you?",
            f"Greetings! {self.name} here, ready to assist.",
        ]
        return CommandResult(random.choice(responses))

    def _handle_how_are_you(self, text: str) -> CommandResult:
        responses = [
            "I'm doing great, thank you for asking! All systems are running smoothly.",
            "I'm functioning perfectly! Ready to help with whatever you need.",
            "All systems operational and running at full capacity. How about you?",
            "I'm excellent! My circuits are humming and I'm ready to go.",
        ]
        return CommandResult(random.choice(responses))

    def _handle_name(self, text: str) -> CommandResult:
        responses = [
            f"I am {self.name}, your personal AI assistant.",
            f"My name is {self.name}. I'm here to help you.",
            f"You can call me {self.name}. Just A Rather Very Intelligent System.",
        ]
        return CommandResult(random.choice(responses))

    def _handle_help(self, text: str) -> CommandResult:
        # List available tools
        tools = self.tool_registry.list_tools()
        tool_names = [t.name for t in tools]
        tool_list = ", ".join(tool_names) if tool_names else "none yet"

        brain_info = (
            " For anything else, just ask me naturally."
            if self.brain
            else ""
        )

        return CommandResult(
            f"I'm {self.name}, your personal assistant. "
            f"My available tools are: {tool_list}. "
            f"I also respond to greetings and basic conversation."
            + brain_info
        )

    def _handle_thanks(self, text: str) -> CommandResult:
        responses = [
            "You're welcome! Happy to help.",
            "Anytime! That's what I'm here for.",
            "My pleasure! Let me know if you need anything else.",
        ]
        return CommandResult(random.choice(responses))

    def _handle_reset(self, text: str) -> CommandResult:
        """Reset the LLM conversation history."""
        if self.brain:
            self.brain.reset_conversation()
            return CommandResult("Conversation reset. Let's start fresh!")
        return CommandResult("No conversation history to clear.")

    def _handle_goodbye(self, text: str) -> CommandResult:
        responses = [
            "Goodbye! It was nice talking to you.",
            "See you later! Have a great day.",
            "Farewell! I'll be here when you need me.",
        ]
        return CommandResult(random.choice(responses), should_quit=True)

    def _handle_unknown(self, original_text: str) -> CommandResult:
        """Fallback when no command matches and no brain is connected."""
        responses = [
            f'I heard you say: "{original_text}". '
            "I don't have a specific response for that yet.",
            f'You said: "{original_text}". '
            "I'm not sure how to help with that right now.",
        ]
        return CommandResult(random.choice(responses))


