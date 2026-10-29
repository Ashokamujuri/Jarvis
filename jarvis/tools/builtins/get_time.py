"""
Get Time tool.

Returns the current date and time. This is a fully working tool
that migrates the time functionality from the old inline handler.
"""

from datetime import datetime

from jarvis.tools.base import BaseTool, ToolResult


class GetTimeTool(BaseTool):
    """Returns the current date and time."""

    name = "get_time"
    description = "Tells the current date and time."
    keywords = {
        "what time is it", "what's the time", "tell me the time",
        "current time", "time please", "what time",
        "what is the date", "what's the date", "today's date",
    }

    def execute(self, raw_text: str) -> ToolResult:
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%A, %B %d, %Y")
        return ToolResult(
            success=True,
            message=f"It is currently {time_str} on {date_str}.",
            data={"time": time_str, "date": date_str},
        )
