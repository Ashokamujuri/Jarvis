"""
Tool registry for Jarvis.

Central place where all tools register themselves. The registry
provides tool lookup by name and input-matching so the command
processor can find the right tool for a given user request.
"""

from typing import Dict, List, Optional

from jarvis.logger import get_logger
from jarvis.tools.base import BaseTool

logger = get_logger(__name__)


class ToolRegistry:
    """
    Manages registration and lookup of all available tools.

    Usage:
        registry = ToolRegistry()
        registry.register(GetTimeTool())
        registry.register(SystemInfoTool())

        tool = registry.find_match("what time is it")
        if tool:
            result = tool.execute("what time is it")
    """

    def __init__(self):
        """Initialize an empty tool registry."""
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool with the registry.

        Args:
            tool: A BaseTool instance to register.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                "Each tool must have a unique name."
            )
        self._tools[tool.name] = tool
        logger.debug(f"Tool registered: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """
        Get a tool by its name.

        Args:
            name: The unique tool name.

        Returns:
            The tool instance, or None if not found.
        """
        return self._tools.get(name)

    def find_match(self, text: str) -> Optional[BaseTool]:
        """
        Find the first tool whose keywords match the user's input.

        Args:
            text: The user's input (will be lowercased internally).

        Returns:
            The matching tool, or None if no tool matches.
        """
        cleaned = text.lower().strip()
        for tool in self._tools.values():
            if tool.matches(cleaned):
                return tool
        return None

    def list_tools(self) -> List[BaseTool]:
        """Return a list of all registered tools."""
        return list(self._tools.values())

    @property
    def count(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def get_help_text(self) -> str:
        """
        Generate a human-readable help string listing all tools.

        Returns:
            A formatted string describing all available tools.
        """
        if not self._tools:
            return "No tools are currently available."

        lines = ["Available tools:"]
        for tool in self._tools.values():
            lines.append(f"  - {tool.name}: {tool.description}")
        return "\n".join(lines)
