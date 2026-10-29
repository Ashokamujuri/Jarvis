"""
Command processing package for Jarvis.

Handles routing user input to the appropriate response.
Currently uses pattern-matched commands; later this will
be replaced by (or augmented with) an LLM brain.
"""

from jarvis.commands.processor import CommandProcessor

__all__ = ["CommandProcessor"]
