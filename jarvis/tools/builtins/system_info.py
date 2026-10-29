"""
System Information tool.

Returns information about the computer: OS, CPU, memory, etc.
This is a fully working tool using only the Python standard library.
"""

import os
import platform

from jarvis.tools.base import BaseTool, ToolResult


class SystemInfoTool(BaseTool):
    """Returns system information about the computer."""

    name = "system_information"
    description = "Shows computer system info (OS, processor, memory)."
    keywords = {
        "system information", "system info", "computer info",
        "about this computer", "my computer", "system specs",
        "what system", "what computer",
    }

    def execute(self, raw_text: str) -> ToolResult:
        info = {
            "os": f"{platform.system()} {platform.release()}",
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor() or "Unknown",
            "hostname": platform.node(),
            "python": platform.python_version(),
        }

        # Try to get CPU count
        cpu_count = os.cpu_count()
        if cpu_count:
            info["cpu_cores"] = str(cpu_count)

        message = (
            f"You're running {info['os']} on a {info['machine']} machine "
            f"with {info.get('cpu_cores', 'unknown')} CPU cores. "
            f"Processor: {info['processor']}. "
            f"Computer name: {info['hostname']}."
        )

        return ToolResult(
            success=True,
            message=message,
            data=info,
        )
