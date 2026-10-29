"""
Built-in tools for Jarvis.

This module registers all built-in tools with a ToolRegistry.
To add a new tool, import it here and register it.

IMPORTANT: Registration order matters for tools with overlapping
keywords. The browser tool must be registered BEFORE open_application
so "open YouTube" routes to the browser (not the app launcher).
"""

from jarvis.tools.registry import ToolRegistry
from jarvis.tools.builtins.get_time import GetTimeTool
from jarvis.tools.builtins.system_info import SystemInfoTool
from jarvis.tools.builtins.memory import MemoryTool
from jarvis.tools.builtins.web_search import BrowserTool
from jarvis.tools.builtins.play_music import PlayMusicTool
from jarvis.tools.builtins.open_app import OpenApplicationTool
from jarvis.tools.builtins.close_app import CloseApplicationTool
from jarvis.tools.builtins.create_file import CreateFileTool


def register_all(registry: ToolRegistry) -> None:
    """
    Register all built-in tools with the given registry.

    Order matters: tools registered first get priority when
    multiple tools could match the same input.

    To add a new tool:
        1. Create the tool class in jarvis/tools/builtins/
        2. Import it here
        3. Add registry.register(YourTool()) below
    """
    registry.register(GetTimeTool())
    registry.register(SystemInfoTool())
    registry.register(MemoryTool())
    # PlayMusic BEFORE Browser (so "play Shape of You" -> music, not search)
    registry.register(PlayMusicTool())
    # Browser BEFORE open_app (so "open YouTube" -> browser, not app launcher)
    registry.register(BrowserTool())
    registry.register(OpenApplicationTool())
    registry.register(CloseApplicationTool())
    registry.register(CreateFileTool())

