"""
Configuration module for Jarvis.

Loads settings from environment variables with sensible defaults.
Safely parses and validates types so malformed environment variables
fall back gracefully rather than crashing application startup.

You can override any setting by creating a .env file in the project root
or by setting environment variables directly.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# --- Paths ---
# Root directory of the project (one level up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env file from project root (if it exists)
load_dotenv(PROJECT_ROOT / ".env")

# --- Helper functions for safe environment variable parsing ---


def _get_int(key: str, default: Optional[int], allow_none: bool = False) -> Optional[int]:
    """Safely parse an integer environment variable with fallback."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return None if allow_none else default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    """Safely parse a float environment variable with fallback."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    """Safely parse a boolean environment variable with fallback."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


# --- Core Directory Paths ---
LOG_DIR = Path(os.getenv("JARVIS_LOG_DIR", str(PROJECT_ROOT / "logs")))
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(PROJECT_ROOT / "data")))
DB_PATH = Path(os.getenv("JARVIS_DB_PATH", str(DATA_DIR / "memory.db")))

# --- Application Settings ---
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis").strip() or "Jarvis"

# Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL = os.getenv("JARVIS_LOG_LEVEL", "INFO").strip().upper() or "INFO"

# Whether to also log output to a file (in addition to console)
LOG_TO_FILE = _get_bool("JARVIS_LOG_TO_FILE", True)

# --- Speech Recognition Settings ---
# Language for speech recognition (BCP-47 language tag)
SPEECH_LANGUAGE = os.getenv("JARVIS_SPEECH_LANGUAGE", "en-US").strip() or "en-US"

# Max seconds to wait for speech before timing out (None = wait forever)
SPEECH_TIMEOUT = _get_int("JARVIS_SPEECH_TIMEOUT", 8, allow_none=True)

# Max seconds of speech to capture per phrase (None = no limit)
SPEECH_PHRASE_LIMIT = _get_int("JARVIS_SPEECH_PHRASE_LIMIT", 20, allow_none=True)

# --- Text-to-Speech Settings ---
# Speech rate in words per minute (default 175 — natural conversational speed)
TTS_RATE = _get_int("JARVIS_TTS_RATE", 175) or 175

# Speech volume from 0.0 (silent) to 1.0 (maximum)
TTS_VOLUME = max(0.0, min(1.0, _get_float("JARVIS_TTS_VOLUME", 1.0)))

# --- LLM Brain Provider Settings ---
# Provider: "gemini" or "groq" (auto-detected if blank)
BRAIN_PROVIDER = os.getenv("JARVIS_BRAIN_PROVIDER", "").strip().lower()

# --- LLM Brain Settings (Google Gemini) ---
# API key for Gemini (https://aistudio.google.com/apikey)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Model to use (e.g. gemini-2.5-flash)
GEMINI_MODEL = os.getenv("JARVIS_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

# Max tokens in the Gemini response
GEMINI_MAX_TOKENS = _get_int("JARVIS_GEMINI_MAX_TOKENS", 150) or 150

# --- LLM Brain Settings (Groq) ---
# API key for Groq (required for AI responses)
# Get a free key at: https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# Model to use (Groq-hosted models)
GROQ_MODEL = os.getenv("JARVIS_GROQ_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"

# Max tokens in the LLM response
GROQ_MAX_TOKENS = _get_int("JARVIS_GROQ_MAX_TOKENS", 150) or 150

# --- Wake Word Settings ---
# The phrase that activates Jarvis (e.g., "hey jarvis", "ok jarvis")
WAKE_WORD = os.getenv("JARVIS_WAKE_WORD", "hey jarvis").strip() or "hey jarvis"

# Max seconds to wait for speech during wake word detection
WAKE_WORD_TIMEOUT = _get_int("JARVIS_WAKE_WORD_TIMEOUT", 5) or 5

# Enable/disable wake word (set to "false" to process all speech directly)
WAKE_WORD_ENABLED = _get_bool("JARVIS_WAKE_WORD_ENABLED", True)

# --- Long-Term Memory Settings ---
# Number of recent conversation turns to restore from DB into the LLM context
MEMORY_HISTORY_LIMIT = _get_int("JARVIS_MEMORY_HISTORY_LIMIT", 40) or 40

# Number of recent conversation turns to inject into the LLM system prompt
MEMORY_INJECT_TURNS = _get_int("JARVIS_MEMORY_INJECT_TURNS", 10) or 10

# Whether to inject long-term facts/projects/tasks into the system prompt
MEMORY_INJECT_FACTS = _get_bool("JARVIS_MEMORY_INJECT_FACTS", True)
