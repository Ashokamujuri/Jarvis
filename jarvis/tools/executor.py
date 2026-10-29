"""
Safe tool execution layer for Jarvis.

Wraps tool execution in permission checks AND error handling so:
  - Risky tools require user confirmation before running
  - Buggy or failing tools can never crash the conversation loop

All exceptions are caught, logged, and converted to user-friendly
error messages.
"""

from typing import Optional

from jarvis.logger import get_logger
from jarvis.permissions import PermissionManager, RiskLevel
from jarvis.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class SafeExecutor:
    """Safely executes tools with permission checks and error handling."""

    def __init__(self, permission_manager: Optional[PermissionManager] = None):
        """
        Initialize the executor.

        Args:
            permission_manager: Optional PermissionManager for confirmation.
                                If None, SAFE and MODERATE actions auto-approve,
                                DANGEROUS actions auto-deny.
        """
        self._permissions = permission_manager or PermissionManager()

    def run(self, tool: BaseTool, raw_text: str) -> ToolResult:
        """
        Execute a tool safely with permission checks.

        Flow:
            1. Check the tool's risk level
            2. If confirmation needed, ask the user
            3. If approved (or safe), execute with error handling
            4. If denied/blocked, return a denial message

        Args:
            tool:     The tool to execute.
            raw_text: The full user input to pass to the tool.

        Returns:
            A ToolResult — either the tool's real result, a denial
            message, or an error result if something went wrong.
        """
        # --- Permission check ---
        try:
            action_desc = tool.action_summary(raw_text)
        except Exception as e:
            logger.warning(f"Error determining action summary for '{tool.name}': {e}")
            action_desc = f"use the {tool.name} tool"

        try:
            risk_level = tool.get_risk_level(raw_text)
        except Exception as e:
            logger.warning(f"Error determining risk level for '{tool.name}': {e}")
            risk_level = tool.risk_level

        allowed, deny_message = self._permissions.check(risk_level, action_desc)

        if not allowed:
            logger.info(
                f"Tool '{tool.name}' denied "
                f"(risk={risk_level.name}): {deny_message}"
            )
            return ToolResult(success=False, message=deny_message)

        # --- Execute with error handling ---
        try:
            logger.info(f"Executing tool: {tool.name}")
            result = tool.execute(raw_text)
            logger.info(
                f"Tool '{tool.name}' completed "
                f"(success={result.success})"
            )
            return result

        except PermissionError as e:
            logger.error(f"Tool '{tool.name}' permission denied: {e}")
            return ToolResult(
                success=False,
                message=(
                    f"I don't have permission to do that. "
                    f"The {tool.name} tool needs elevated access."
                ),
            )

        except FileNotFoundError as e:
            logger.error(f"Tool '{tool.name}' file not found: {e}")
            return ToolResult(
                success=False,
                message=f"I couldn't find the file or program: {e}",
            )

        except TimeoutError as e:
            logger.error(f"Tool '{tool.name}' timed out: {e}")
            return ToolResult(
                success=False,
                message=f"The {tool.name} tool took too long and timed out.",
            )

        except Exception as e:
            logger.error(
                f"Tool '{tool.name}' unexpected error: {type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                message=(
                    f"Something went wrong with the {tool.name} tool. "
                    f"Error: {e}"
                ),
            )

