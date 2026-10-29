"""
Jarvis Desktop GUI Package.

Provides a standalone desktop user interface for Jarvis.
Completely decoupled from the core assistant logic via the event system.
"""

from jarvis.gui.app_window import JarvisGUI, launch_gui

__all__ = ["JarvisGUI", "launch_gui"]
