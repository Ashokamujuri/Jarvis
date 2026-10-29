"""
Permission and confirmation system for Jarvis.

Provides a centralized way to classify tool risk levels and
request user confirmation before performing potentially dangerous
actions. This ensures all tools use the same confirmation logic
rather than each implementing their own.

Risk Levels:
    SAFE      - Read-only actions (get time, system info). No confirmation.
    MODERATE  - Actions with side effects (open app, create file). Confirmation optional.
    DANGEROUS - Destructive actions (delete file, run command). Always confirms.
    BLOCKED   - Never allowed (reserved for extremely dangerous operations).
"""

from enum import Enum, auto
from typing import Callable, Optional

from jarvis.logger import get_logger
from jarvis.utils import match_any_keyword, sanitize_ascii

logger = get_logger(__name__)


class RiskLevel(Enum):
    """
    Risk classification for tool actions.

    Tools declare their risk level, and the PermissionManager
    decides whether user confirmation is needed.
    """
    SAFE = auto()       # No confirmation needed (e.g., get time)
    MODERATE = auto()   # Confirmation recommended (e.g., open app)
    DANGEROUS = auto()  # Confirmation required (e.g., delete file)
    BLOCKED = auto()    # Never allowed (e.g., format disk)


# Type alias for the confirmation callback function.
# It takes a question string, asks the user, and returns True/False.
ConfirmFn = Callable[[str], bool]


class PermissionManager:
    """
    Centralized permission checking and confirmation for tools.

    Decides whether a tool action should proceed, be confirmed,
    or be blocked. Keeps confirmation logic out of individual tools.

    Usage:
        pm = PermissionManager(confirm_fn=my_confirm_function)
        allowed, message = pm.check(tool, raw_text)
        if allowed:
            result = tool.execute(raw_text)
    """

    def __init__(self, confirm_fn: Optional[ConfirmFn] = None):
        """
        Initialize the permission manager.

        Args:
            confirm_fn: A function that asks the user a yes/no question
                        and returns True (confirmed) or False (denied).
                        If None, MODERATE actions are auto-approved and
                        DANGEROUS actions are auto-denied.
        """
        self._confirm_fn = confirm_fn
        logger.info(
            f"Permission manager initialized "
            f"(confirmation: {'enabled' if confirm_fn else 'auto-mode'})."
        )

    def check(self, risk_level: "RiskLevel", action_description: str) -> tuple:
        """
        Check if an action should proceed.

        Args:
            risk_level:         The risk level of the action.
            action_description: A human-readable description of the action
                                (used in the confirmation prompt).

        Returns:
            A tuple of (allowed: bool, message: str).
            - allowed=True, message="" → proceed with execution
            - allowed=False, message="..." → deny with explanation
        """
        if risk_level == RiskLevel.SAFE:
            return True, ""

        if risk_level == RiskLevel.BLOCKED:
            logger.warning(f"BLOCKED action attempted: {action_description}")
            return False, (
                "I'm not allowed to perform that action. "
                "It has been marked as blocked for safety."
            )

        if risk_level == RiskLevel.DANGEROUS:
            return self._request_confirmation(
                action_description, required=True
            )

        if risk_level == RiskLevel.MODERATE:
            return self._request_confirmation(
                action_description, required=False
            )

        # Unknown risk level — deny by default
        logger.warning(f"Unknown risk level: {risk_level}")
        return False, "I'm not sure if this action is safe. Denying by default."

    def _request_confirmation(
        self, description: str, required: bool
    ) -> tuple:
        """
        Ask the user for confirmation.

        Args:
            description: What the action will do.
            required:    If True, no confirm_fn means auto-deny.
                         If False, no confirm_fn means auto-approve.

        Returns:
            (allowed, message) tuple.
        """
        if self._confirm_fn is None:
            if required:
                logger.warning(
                    f"DANGEROUS action auto-denied (no confirmation handler): "
                    f"{description}"
                )
                return False, (
                    f"This action requires confirmation, but I can't ask "
                    f"you right now. Action denied for safety."
                )
            else:
                # MODERATE with no confirm_fn → auto-approve
                logger.debug(
                    f"MODERATE action auto-approved: {description}"
                )
                return True, ""

        # Ask the user
        question = (
            f"I'm about to {description}. "
            f"Should I go ahead?"
        )

        logger.info(f"Requesting confirmation: {description}")

        try:
            confirmed = self._confirm_fn(question)
        except Exception as e:
            logger.error(f"Confirmation handler error: {e}")
            return False, "I had trouble getting your confirmation. Action cancelled."

        if confirmed:
            logger.info(f"User confirmed: {description}")
            return True, ""
        else:
            logger.info(f"User denied: {description}")
            return False, "Understood, I won't do that."


def create_voice_confirm_fn(
    speaker,
    listener,
    emit_fn: Optional[Callable] = None,
) -> ConfirmFn:
    """
    Create a confirmation function that uses voice I/O.

    The function will:
        1. Speak the confirmation question aloud and notify UI
        2. Listen for the user's response
        3. Return True if they say yes, False otherwise

    Args:
        speaker:  A Pyttsx3Speaker (or any speaker with a say() method).
        listener: A BaseSpeechListener (or any listener with listen_once()).
        emit_fn:  Optional event emitter callback for GUI synchronization.

    Returns:
        A confirmation callback function.
    """
    CONFIRM_WORDS = {"yes", "yeah", "yep", "sure", "go ahead", "do it",
                     "confirm", "approved", "affirmative", "okay", "ok",
                     "yes please", "please do", "go for it"}

    DENY_WORDS = {"no", "nope", "don't", "stop", "cancel", "deny",
                  "negative", "no way", "abort", "never mind"}

    def confirm(question: str) -> bool:
        """Ask a yes/no question via voice and return the answer."""
        # Print and speak the question
        safe_q = sanitize_ascii(question)
        print(f"\n[Jarvis]: {safe_q}", flush=True)
        if emit_fn:
            emit_fn("message", sender="jarvis", text=question)
            emit_fn("listening_state", state="listening")

        if speaker:
            speaker.say(question)

        # Listen for the response
        if listener:
            response = listener.listen_once()
            if response:
                cleaned = response.lower().strip()
                print(f"[You]: {cleaned}", flush=True)
                if emit_fn:
                    emit_fn("message", sender="user", text=cleaned)

                # Check for explicit yes
                if match_any_keyword(cleaned, CONFIRM_WORDS):
                    return True

                # Check for explicit no
                if match_any_keyword(cleaned, DENY_WORDS):
                    return False

                # Ambiguous response — treat as denial for safety
                logger.debug(f"Ambiguous confirmation response: '{cleaned}'")
                denial_msg = "I didn't get a clear yes or no. Cancelling for safety."
                print(f"[Jarvis]: {denial_msg}\n", flush=True)
                if emit_fn:
                    emit_fn("message", sender="jarvis", text=denial_msg)
                return False
            else:
                timeout_msg = "I didn't hear a response. Cancelling for safety."
                print(f"[Jarvis]: {timeout_msg}\n", flush=True)
                if emit_fn:
                    emit_fn("message", sender="jarvis", text=timeout_msg)
                return False
        else:
            # No listener available — can't confirm
            return False

    return confirm

