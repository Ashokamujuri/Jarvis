"""
Logging setup for Jarvis.

Provides a configured logger that outputs to both the console
and (optionally) a log file. Import and use throughout the project:

    from jarvis.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Hello from Jarvis!")
"""

import logging
import sys
from datetime import datetime

from jarvis.config import APP_NAME, LOG_DIR, LOG_LEVEL, LOG_TO_FILE


def get_logger(name: str) -> logging.Logger:
    """
    Create and return a configured logger.

    Args:
        name: The name for the logger, typically __name__.

    Returns:
        A logging.Logger instance with console (and optional file) handlers.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if get_logger is called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(LOG_LEVEL)

    # --- Formatter ---
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Console Handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # --- File Handler (optional) ---
    if LOG_TO_FILE:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_filename = datetime.now().strftime(f"{APP_NAME}_%Y-%m-%d.log")
        file_handler = logging.FileHandler(
            LOG_DIR / log_filename, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
