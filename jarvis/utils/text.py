"""
Text processing and matching utilities for Jarvis.

Provides shared functions for keyword matching, phrase extraction,
and console text sanitization across tools, commands, and permissions.
"""

import re
from typing import Iterable, Optional


def match_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    """
    Check if the text matches any keyword using regex word boundaries (\\b).

    Ensures that multi-word phrases and single words are only matched as
    complete words, avoiding false positives like 'hi' in 'this' or 'ship'.

    Args:
        text: The target text to search (case-insensitive).
        keywords: A collection of trigger keywords or phrases.

    Returns:
        True if any keyword matches as a distinct word/phrase.
    """
    cleaned = text.lower().strip()
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        # Use regex word boundaries
        pattern = r"\b" + re.escape(kw_clean) + r"\b"
        if re.search(pattern, cleaned):
            return True
    return False


def extract_trailing_text(
    text: str,
    triggers: Iterable[str],
    fillers: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """
    Extract text that follows a matched trigger phrase, with optional filler stripping.

    Args:
        text: The user input text.
        triggers: List of phrases that precede the payload text.
        fillers: Optional list of trailing filler words to remove (e.g. 'please', 'for me').

    Returns:
        The extracted payload string, or None if empty or not matched.
    """
    cleaned = text.strip()
    sorted_triggers = sorted(triggers, key=len, reverse=True)

    for trigger in sorted_triggers:
        pattern = r"\b" + re.escape(trigger.strip()) + r"\b\s*"
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            payload = cleaned[match.end():].strip()
            if fillers:
                for filler in fillers:
                    f_pattern = r"\s*\b" + re.escape(filler.strip()) + r"\b\s*$"
                    payload = re.sub(f_pattern, "", payload, flags=re.IGNORECASE).strip()
            return payload if payload else None

    return None


def sanitize_ascii(text: str) -> str:
    """
    Convert arbitrary unicode text to ASCII-safe text for Windows console / SAPI5 TTS.

    Normalizes common typographic characters (curly quotes, dashes, ellipsis, etc.)
    to their clean ASCII equivalents before encoding, avoiding ugly '?' replacements.

    Args:
        text: The input text.

    Returns:
        Clean ASCII string.
    """
    if not text:
        return ""

    # Typographic normalization table
    replacements = {
        "\u2018": "'",  # Left single quotation mark
        "\u2019": "'",  # Right single quotation mark / apostrophe
        "\u201c": '"',  # Left double quotation mark
        "\u201d": '"',  # Right double quotation mark
        "\u2014": " - ", # Em dash
        "\u2013": "-",  # En dash
        "\u2026": "...", # Horizontal ellipsis
        "\u2022": "*",  # Bullet
        "\u00a0": " ",  # Non-breaking space
    }
    cleaned = text
    for char, repl in replacements.items():
        cleaned = cleaned.replace(char, repl)

    return cleaned.encode("ascii", errors="replace").decode("ascii")
