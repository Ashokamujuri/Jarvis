"""
Base class for all Jarvis tools.

A "tool" is an action Jarvis can perform — opening an app,
searching the web, getting system info, etc. Each tool is
self-describing: it declares its name, description, risk level,
and trigger keywords so the system can route requests to it
automatically.

To create a new tool:
    1. Subclass BaseTool
    2. Set name, description, risk_level, and keywords
    3. Implement execute()
    4. Register it in jarvis/tools/builtins/__init__.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Set

from jarvis.permissions import RiskLevel


@dataclass
class ToolResult:
    """
    The result of executing a tool.

    Attributes:
        success: Whether the tool executed successfully.
        message: A human-readable response to speak to the user.
        data:    Optional structured data (for use by other subsystems).
    """
    success: bool
    message: str
    data: Any = None


class BaseTool(ABC):
    """
    Abstract base class that all tools must implement.

    Attributes:
        name:        Unique identifier for this tool (e.g. "get_time").
        description: Brief explanation of what this tool does.
                     Used by the help system and (later) LLM tool selection.
        keywords:    Set of trigger phrases that activate this tool.
        risk_level:  How risky this tool's actions are.
                     SAFE = no confirmation, DANGEROUS = always asks.
    """

    name: str = ""
    description: str = ""
    keywords: Set[str] = set()
    risk_level: RiskLevel = RiskLevel.SAFE

    @abstractmethod
    def execute(self, raw_text: str) -> ToolResult:
        """
        Execute the tool's action.

        Args:
            raw_text: The full user input that triggered this tool.
                      The tool can parse arguments from this text.

        Returns:
            A ToolResult with success status and a spoken response.
        """

    def action_summary(self, raw_text: str) -> str:
        """
        Return a human-readable description of what this tool is
        about to do. Used in the confirmation prompt.

        Override this in subclasses for more specific descriptions.
        E.g., "delete the file report.txt" instead of "execute create_file".

        Args:
            raw_text: The full user input.

        Returns:
            A brief action description for the user.
        """
        return f"use the {self.name} tool"

    def get_risk_level(self, raw_text: str) -> RiskLevel:
        """
        Return the risk level for the specific action requested.

        Defaults to the tool's static `risk_level` attribute. Subclasses
        can override this if certain operations within the tool have
        different risk profiles (e.g. reading vs clearing data).

        Args:
            raw_text: The full user input text.

        Returns:
            The applicable RiskLevel.
        """
        return self.risk_level

    def matches(self, text: str) -> bool:
        """
        Check if the user's input should trigger this tool.

        Default implementation uses word-boundary matching against
        the tool's keywords. Subclasses can override for more
        sophisticated matching (e.g., regex, NLP).

        Args:
            text: The user's input (lowercased).

        Returns:
            True if this tool should handle the input.
        """
        from jarvis.utils import match_any_keyword
        return match_any_keyword(text, self.keywords)

