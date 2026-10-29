"""
Speech recognition post-processing corrections for Jarvis.

Google's free Speech-to-Text API is trained on general English and
frequently mishears tech product names that are not in its dictionary.

This module applies a lightweight correction pass after every recognition
call.  Each entry maps one or more "as-heard" variants to the canonical
spoken form that Jarvis's tool registry expects.

To add a new correction:
    Add an entry to CORRECTIONS below.
    Key   = what Google STT returns (lowercase, exact phrase as heard).
    Value = what it should have been (the canonical form Jarvis understands).
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Correction map
# ---------------------------------------------------------------------------
# Rules:
#   - Keys are LOWERCASE strings (as returned by Google STT).
#   - Values are the canonical replacement strings.
#   - Phrases are matched as whole-word boundaries when possible.
#   - Longer / more specific entries are applied before shorter ones.
# ---------------------------------------------------------------------------

CORRECTIONS: dict[str, str] = {
    # AI / Chat assistants
    "chat gpt":           "ChatGPT",
    "chat g p t":         "ChatGPT",
    "chat p t":           "ChatGPT",
    "chat ppt":           "ChatGPT",
    "chat pp t":          "ChatGPT",
    "chatppt":            "ChatGPT",
    "jet gpt":            "ChatGPT",
    "shat gpt":           "ChatGPT",
    "claude ai":          "Claude",
    "google gemini":      "Gemini",
    "bard":               "Gemini",
    "perplexity ai":      "Perplexity",
    "microsoft copilot":  "Copilot",
    "bing chat":          "Copilot",

    # Google services
    "gmail":              "Gmail",
    "g mail":             "Gmail",
    "google drive":       "Google Drive",
    "google docs":        "Google Docs",
    "google sheets":      "Google Sheets",
    "google calendar":    "Google Calendar",
    "google maps":        "Google Maps",
    "google translate":   "Google Translate",
    "you tube":           "YouTube",

    # Messaging
    "whatsapp web":       "WhatsApp",
    "whats app":          "WhatsApp",
    "what sapp":          "WhatsApp",
    "what's app":         "WhatsApp",
    "telegram web":       "Telegram",

    # Coding / Dev platforms
    "leet code":          "LeetCode",
    "lead code":          "LeetCode",
    "leak code":          "LeetCode",
    "lit code":           "LeetCode",
    "let code":           "LeetCode",
    "geeks for geeks":    "GeeksForGeeks",
    "geeks 4 geeks":      "GeeksForGeeks",
    "gfg":                "GeeksForGeeks",
    "stack overflow":     "Stack Overflow",
    "stack over flow":    "Stack Overflow",
    "git hub":            "GitHub",
    "code pen":           "CodePen",
    "repl it":            "Replit",
    "hacker rank":        "HackerRank",

    # Shopping / Entertainment
    "amazon prime":       "Prime Video",
    "prime video":        "Prime Video",
    "disney plus":        "Hotstar",
    "disney hotstar":     "Hotstar",
    "flip kart":          "Flipkart",

    # Productivity
    "vs code":            "VS Code",
    "visual studio code": "VS Code",
    "note pad":           "Notepad",

    # Music commands (common misheard patterns)
    "play me":            "play",
    "please play":        "play",
    "can you play":       "play",
    "could you play":     "play",
}

# Build a sorted list of (pattern, replacement) — longest patterns first
# so "chat gpt" is matched before "chat" etc.
_SORTED_CORRECTIONS = sorted(CORRECTIONS.items(), key=lambda x: len(x[0]), reverse=True)

# Pre-compile regex patterns for speed
_COMPILED = [
    (re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE), replacement)
    for phrase, replacement in _SORTED_CORRECTIONS
]


def correct(text: Optional[str]) -> Optional[str]:
    """
    Apply all corrections to the recognized speech text.

    Args:
        text: The raw recognized string from Google STT (or None).

    Returns:
        The corrected string, or None if input is None.

    Example:
        correct("open chat ppt")   -> "open ChatGPT"
        correct("open leet code")  -> "open LeetCode"
        correct("play me sahiba")  -> "play sahiba"
    """
    if not text:
        return text

    result = text
    for pattern, replacement in _COMPILED:
        result = pattern.sub(replacement, result)

    return result
