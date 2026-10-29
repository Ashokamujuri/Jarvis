"""
Tools package for Jarvis.

Provides a plugin-like architecture for tools that Jarvis can
execute: opening apps, searching the web, getting system info, etc.

Key components:
    - BaseTool:      Abstract base class for all tools
    - ToolResult:    Structured result from tool execution
    - ToolRegistry:  Central registry for tool lookup
    - SafeExecutor:  Error-safe tool execution wrapper
"""

from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.executor import SafeExecutor

__all__ = ["BaseTool", "ToolResult", "ToolRegistry", "SafeExecutor"]
