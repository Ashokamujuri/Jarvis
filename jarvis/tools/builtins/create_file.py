"""
Create File tool for Jarvis.

Safely creates files with optional initial content inside the project's
data/files directory (or relative workspace path). Protects against path
traversal and system file overwrites.
"""

import os
import re
from pathlib import Path
from typing import Optional, Tuple

from jarvis.config import DATA_DIR
from jarvis.logger import get_logger
from jarvis.permissions import RiskLevel
from jarvis.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

# Sandboxed default folder for files created by Jarvis
SANDBOX_DIR = DATA_DIR / "files"


class CreateFileTool(BaseTool):
    """Creates a new text file safely with optional content."""

    name = "create_file"
    description = "Creates a new file on your computer."
    risk_level = RiskLevel.DANGEROUS
    keywords = {
        "create a file", "make a file", "new file",
        "create file", "write a file", "save a file",
    }

    def __init__(self):
        """Ensure the sandbox directory exists."""
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

    def _parse_command(self, raw_text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse the target filename and optional content from the command.

        Examples:
            "create a file named notes.txt with hello world"
            "create file test.txt"
            "make a file called todo.txt"
        """
        cleaned = raw_text.strip()

        # Regex pattern matching filename and optional content
        # e.g., create file (named|called)? <filename> (with|containing|saying)? <content>
        pattern = (
            r"(?:create|make|write|save)\s+(?:a\s+)?file\s+"
            r"(?:named|called)?\s*([a-zA-Z0-9_\-\.]+)"
            r"(?:\s+(?:with|containing|saying)\s+(.+))?"
        )
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            content = match.group(2).strip() if match.group(2) else ""
            return filename, content

        # Fallback: find any token ending with an extension like .txt, .md, .py, .json
        file_match = re.search(r"\b([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]{1,5})\b", cleaned)
        if file_match:
            filename = file_match.group(1).strip()
            return filename, ""

        return None, None

    def action_summary(self, raw_text: str) -> str:
        """Describe which file is about to be created for the confirmation prompt."""
        filename, _ = self._parse_command(raw_text)
        if filename:
            return f"create the file '{filename}'"
        return "create a new file"

    def execute(self, raw_text: str) -> ToolResult:
        """Parse input, validate file path, and write file."""
        filename, content = self._parse_command(raw_text)

        if not filename:
            return ToolResult(
                success=False,
                message="What would you like to name the file? Please specify a filename.",
            )

        # Default extension if none provided
        if "." not in filename:
            filename = f"{filename}.txt"

        # Prevent path traversal vulnerabilities
        safe_name = Path(filename).name
        target_path = (SANDBOX_DIR / safe_name).resolve()

        # Ensure target stays within sandbox
        try:
            target_path.relative_to(SANDBOX_DIR.resolve())
        except ValueError:
            return ToolResult(
                success=False,
                message="For safety, files can only be created in the Jarvis data directory.",
            )

        try:
            target_path.write_text(content or "", encoding="utf-8")
            logger.info(f"File created successfully: {target_path}")
            return ToolResult(
                success=True,
                message=f"Created the file '{safe_name}' successfully.",
                data={"filename": safe_name, "path": str(target_path)},
            )
        except Exception as e:
            logger.error(f"Failed to create file {target_path}: {e}")
            return ToolResult(
                success=False,
                message=f"I couldn't create the file '{safe_name}'. Error: {e}",
            )
