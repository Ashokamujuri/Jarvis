"""
Browser tool for Jarvis.

Handles three actions:
  1. OPEN_KNOWN_SITE  - "open YouTube", "go to GitHub"
     Exact match against WEBSITE_REGISTRY. Opens the canonical URL directly.

  2. OPEN_GENERIC     - "open LeetCode", "open WhatsApp Web"
     Target not in WEBSITE_REGISTRY but phrase has an open trigger.
     Smart URL inference (https://www.<slug>.com) attempted first.
     NEVER searches Google for a known/guessable website.

  3. SEARCH_WEB       - "search for Python decorators"
     Explicit search trigger. Opens a Google search results page.

Navigation:
  webbrowser.open() delegates to Windows ShellExecute.
  Chrome is the Windows default, so every URL opens in the existing
  Chrome session as a new tab -- cookies, sessions, and logins preserved.

To add a new website shortcut:
    Add an entry to WEBSITE_REGISTRY below.
"""

import re
import webbrowser
from typing import Dict, Optional
from urllib.parse import quote_plus

from jarvis.logger import get_logger
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils import match_any_keyword

logger = get_logger(__name__)


# ---- Website Registry --------------------------------------------------------
# Format:
#   "site_id": {
#       "names": [spoken aliases, lowercase],
#       "url":   canonical URL,
#       "display": human-readable name (optional),
#   }

WEBSITE_REGISTRY: Dict[str, dict] = {
    # AI / Chat
    "chatgpt": {
        "names": ["chatgpt", "chat gpt", "chat g p t"],
        "url": "https://chatgpt.com/",
        "display": "ChatGPT",
    },
    "claude": {
        "names": ["claude", "claude ai", "anthropic"],
        "url": "https://claude.ai/",
        "display": "Claude",
    },
    "gemini": {
        "names": ["gemini", "google gemini", "bard"],
        "url": "https://gemini.google.com/",
        "display": "Gemini",
    },
    "perplexity": {
        "names": ["perplexity", "perplexity ai"],
        "url": "https://www.perplexity.ai/",
        "display": "Perplexity",
    },
    "copilot": {
        "names": ["copilot", "microsoft copilot", "bing copilot"],
        "url": "https://copilot.microsoft.com/",
        "display": "Microsoft Copilot",
    },
    # Google Apps
    "google": {
        "names": ["google", "google.com"],
        "url": "https://www.google.com/",
        "display": "Google",
    },
    "gmail": {
        "names": ["gmail", "google mail", "my email", "my mail", "email"],
        "url": "https://mail.google.com/",
        "display": "Gmail",
    },
    "google_drive": {
        "names": ["google drive", "drive", "my drive"],
        "url": "https://drive.google.com/",
        "display": "Google Drive",
    },
    "google_docs": {
        "names": ["google docs", "docs"],
        "url": "https://docs.google.com/",
        "display": "Google Docs",
    },
    "google_sheets": {
        "names": ["google sheets", "sheets"],
        "url": "https://sheets.google.com/",
        "display": "Google Sheets",
    },
    "google_calendar": {
        "names": ["google calendar", "calendar"],
        "url": "https://calendar.google.com/",
        "display": "Google Calendar",
    },
    "google_maps": {
        "names": ["google maps", "maps"],
        "url": "https://maps.google.com/",
        "display": "Google Maps",
    },
    "google_translate": {
        "names": ["google translate", "translate"],
        "url": "https://translate.google.com/",
        "display": "Google Translate",
    },
    "youtube": {
        "names": ["youtube", "you tube"],
        "url": "https://www.youtube.com/",
        "display": "YouTube",
    },
    # Messaging
    "whatsapp": {
        "names": ["whatsapp", "whatsapp web", "whats app"],
        "url": "https://web.whatsapp.com/",
        "display": "WhatsApp Web",
    },
    "telegram": {
        "names": ["telegram", "telegram web"],
        "url": "https://web.telegram.org/",
        "display": "Telegram Web",
    },
    "discord": {
        "names": ["discord"],
        "url": "https://discord.com/app",
        "display": "Discord",
    },
    "slack": {
        "names": ["slack"],
        "url": "https://app.slack.com/",
        "display": "Slack",
    },
    # Social
    "instagram": {
        "names": ["instagram", "insta"],
        "url": "https://www.instagram.com/",
        "display": "Instagram",
    },
    "twitter": {
        "names": ["twitter", "x", "x.com"],
        "url": "https://x.com/",
        "display": "X / Twitter",
    },
    "facebook": {
        "names": ["facebook", "fb"],
        "url": "https://www.facebook.com/",
        "display": "Facebook",
    },
    "reddit": {
        "names": ["reddit"],
        "url": "https://www.reddit.com/",
        "display": "Reddit",
    },
    "linkedin": {
        "names": ["linkedin", "linked in"],
        "url": "https://www.linkedin.com/",
        "display": "LinkedIn",
    },
    # Coding / Dev
    "github": {
        "names": ["github", "git hub"],
        "url": "https://github.com/",
        "display": "GitHub",
    },
    "leetcode": {
        "names": ["leetcode", "leet code"],
        "url": "https://leetcode.com/",
        "display": "LeetCode",
    },
    "geeksforgeeks": {
        "names": ["geeksforgeeks", "geeks for geeks", "geeks 4 geeks", "gfg"],
        "url": "https://www.geeksforgeeks.org/",
        "display": "GeeksForGeeks",
    },
    "stackoverflow": {
        "names": ["stack overflow", "stackoverflow"],
        "url": "https://stackoverflow.com/",
        "display": "Stack Overflow",
    },
    "codepen": {
        "names": ["codepen", "code pen"],
        "url": "https://codepen.io/",
        "display": "CodePen",
    },
    "replit": {
        "names": ["replit", "repl it"],
        "url": "https://replit.com/",
        "display": "Replit",
    },
    "hackerrank": {
        "names": ["hackerrank", "hacker rank"],
        "url": "https://www.hackerrank.com/",
        "display": "HackerRank",
    },
    # Reference / Learning
    "wikipedia": {
        "names": ["wikipedia", "wiki"],
        "url": "https://www.wikipedia.org/",
        "display": "Wikipedia",
    },
    "w3schools": {
        "names": ["w3schools", "w3 schools"],
        "url": "https://www.w3schools.com/",
        "display": "W3Schools",
    },
    # Shopping
    "amazon": {
        "names": ["amazon"],
        "url": "https://www.amazon.in/",
        "display": "Amazon",
    },
    "flipkart": {
        "names": ["flipkart", "flip kart"],
        "url": "https://www.flipkart.com/",
        "display": "Flipkart",
    },
    # Entertainment
    "netflix": {
        "names": ["netflix"],
        "url": "https://www.netflix.com/",
        "display": "Netflix",
    },
    "primevideo": {
        "names": ["prime video", "amazon prime", "prime"],
        "url": "https://www.primevideo.com/",
        "display": "Prime Video",
    },
    "hotstar": {
        "names": ["hotstar", "disney hotstar", "disney plus"],
        "url": "https://www.hotstar.com/",
        "display": "Hotstar",
    },
    # News
    "bbc": {
        "names": ["bbc", "bbc news"],
        "url": "https://www.bbc.com/",
        "display": "BBC News",
    },
    "cnn": {
        "names": ["cnn"],
        "url": "https://www.cnn.com/",
        "display": "CNN",
    },
    # Productivity
    "notion": {
        "names": ["notion"],
        "url": "https://www.notion.so/",
        "display": "Notion",
    },
    "trello": {
        "names": ["trello"],
        "url": "https://trello.com/",
        "display": "Trello",
    },
    "figma": {
        "names": ["figma"],
        "url": "https://www.figma.com/",
        "display": "Figma",
    },
}

# ---- Constants ---------------------------------------------------------------

SEARCH_ENGINE_URL = "https://www.google.com/search?q={query}"

# Phrases that indicate an explicit web search request
SEARCH_TRIGGERS = [
    "search for", "search the web for", "search the internet for",
    "look up", "find online", "web search",
    "search about", "search",
]

# Phrases that indicate opening a website / web resource
OPEN_TRIGGERS = [
    "please open", "can you open", "could you open",
    "open up", "open", "go to", "navigate to",
    "take me to", "visit", "show me",
    # NOTE: "launch" intentionally omitted -- claimed by OpenApplicationTool
    # NOTE: "play" intentionally omitted -- claimed by PlayMusicTool
]

# Filler words stripped from open targets
TARGET_FILLERS = [
    "please", "for me", "now", "website", "web site",
    "site", "webpage", "web page", "page",
]


# ---- App alias guard ---------------------------------------------------------

def _build_app_alias_set() -> set:
    """
    Return a set of all spoken aliases registered in open_app.APP_REGISTRY.
    Prevents BrowserTool from grabbing "open Spotify", "open VS Code", etc.
    """
    try:
        from jarvis.tools.builtins.open_app import APP_REGISTRY
        aliases: set = set()
        for profile in APP_REGISTRY.values():
            for a in profile.aliases:
                aliases.add(a.lower())
        return aliases
    except Exception:
        return set()


_APP_ALIASES: set = _build_app_alias_set()


# ---- URL inference -----------------------------------------------------------

def _infer_direct_url(target: str) -> Optional[str]:
    """
    Infer a direct canonical URL from an unknown target name.

    Examples:
      leetcode -> https://www.leetcode.com/
      chatgpt  -> https://www.chatgpt.com/
    """
    slug = target.lower().strip()
    # Already a domain-like string
    if re.match(r"^[a-z0-9\-]+\.[a-z]{2,}$", slug):
        return "https://" + slug + "/"
    # Convert target to a clean slug and build a .com URL
    slug_clean = re.sub(r"[^a-z0-9]", "", slug)
    if slug_clean:
        return "https://www." + slug_clean + ".com/"
    return None


# ---- BrowserTool ------------------------------------------------------------

class BrowserTool(BaseTool):
    """
    Routes browser/web intents to the correct handler.

    Priority (execute order):
      1. Explicit search intent  -> Google search results page
      2. Known site              -> direct canonical URL from WEBSITE_REGISTRY
      3. Generic open intent     -> inferred direct URL (www.<slug>.com)
                                   (never Google search for guessable domains)
    """

    name = "browser"
    description = "Opens websites and searches the web."
    keywords = set()

    def __init__(self):
        """Build the fast site-name lookup table."""
        self._site_lookup: Dict[str, dict] = {}
        for site_id, info in WEBSITE_REGISTRY.items():
            entry = {
                "site_id": site_id,
                "url": info["url"],
                "display": info.get("display", site_id.replace("_", " ").title()),
            }
            for spoken_name in info["names"]:
                self._site_lookup[spoken_name.lower()] = entry
        logger.info("BrowserTool: %d website shortcuts loaded.", len(WEBSITE_REGISTRY))

    # ---- Matching ------------------------------------------------------------

    def matches(self, text: str) -> bool:
        cleaned = text.lower().strip()
        if self._is_search_intent(cleaned):
            return True
        if self._find_known_site(cleaned) is not None:
            return True
        target = self._extract_open_target(cleaned)
        if target and not self._is_app_alias(target):
            return True
        return False

    # ---- Execution ----------------------------------------------------------

    def execute(self, raw_text: str) -> ToolResult:
        cleaned = raw_text.lower().strip()

        # 1. Explicit search
        if self._is_search_intent(cleaned):
            logger.info("[BROWSER] Intent=SEARCH_WEB | phrase=%r", raw_text)
            return self._do_search(cleaned)

        # 2. Known site -> direct URL
        site = self._find_known_site(cleaned)
        if site:
            logger.info(
                "[BROWSER] Intent=OPEN_KNOWN_SITE | site=%s | url=%s | phrase=%r",
                site["site_id"], site["url"], raw_text,
            )
            return self._do_open_known_site(site)

        # 3. Generic open -> direct URL inference
        target = self._extract_open_target(cleaned)
        if target and not self._is_app_alias(target):
            logger.info(
                "[BROWSER] Intent=OPEN_GENERIC | target=%r | phrase=%r",
                target, raw_text,
            )
            return self._do_open_generic(target)

        return ToolResult(
            success=False,
            message="I am not sure what website to open or what to search for.",
        )

    # ---- Search helpers -----------------------------------------------------

    def _is_search_intent(self, text: str) -> bool:
        """
        Return True for explicit search requests.
        "open google" is treated as a site-open intent, not a search.
        """
        cleaned = text.lower().strip()
        for trigger in OPEN_TRIGGERS:
            if cleaned == trigger + " google" or cleaned.startswith(trigger + " google "):
                return False
        return match_any_keyword(cleaned, SEARCH_TRIGGERS)

    def _do_search(self, text: str) -> ToolResult:
        """Extract the search query and open it in the browser."""
        query = self._extract_search_query(text)
        if not query:
            return ToolResult(
                success=False,
                message="What would you like me to search for?",
            )
        search_url = SEARCH_ENGINE_URL.format(query=quote_plus(query))
        try:
            webbrowser.open(search_url)
            logger.info(
                "[BROWSER] Action=web_search | query=%r | url=%s",
                query, search_url,
            )
            return ToolResult(
                success=True,
                message='Searching the web for "' + query + '".',
                data={"action": "search", "query": query, "url": search_url},
            )
        except Exception as exc:
            logger.error("Failed to open browser for search: %s", exc)
            return ToolResult(
                success=False,
                message="I could not open the browser to search. Please try again.",
            )

    @staticmethod
    def _extract_search_query(text: str) -> Optional[str]:
        """Strip trigger phrases and return the raw search query."""
        cleaned = text.lower().strip()
        for trigger in sorted(SEARCH_TRIGGERS, key=len, reverse=True):
            pattern = r"\b" + re.escape(trigger) + r"\b\s*"
            match = re.search(pattern, cleaned)
            if match:
                query = cleaned[match.end():].strip()
                for filler in ["please", "for me", "on the web", "on the internet", "online"]:
                    if query.endswith(filler):
                        query = query[: -len(filler)].strip()
                return query if query else None
        return None

    # ---- Known-site helpers -------------------------------------------------

    def _find_known_site(self, text: str) -> Optional[dict]:
        """Return site info dict if the text references a site in WEBSITE_REGISTRY."""
        cleaned = text.lower().strip()

        # Strip open triggers to isolate the site name
        site_name = cleaned
        for trigger in sorted(OPEN_TRIGGERS, key=len, reverse=True):
            if site_name.startswith(trigger + " ") or site_name == trigger:
                site_name = site_name[len(trigger):].strip()
                break

        # Remove trailing filler words
        for filler in TARGET_FILLERS:
            if site_name.endswith(filler):
                site_name = site_name[: -len(filler)].strip()

        # Direct lookup
        if site_name in self._site_lookup:
            return self._site_lookup[site_name]

        # Word-boundary scan (handles "open WhatsApp Web" -> "whatsapp")
        for spoken_name, info in self._site_lookup.items():
            if re.search(r"\b" + re.escape(spoken_name) + r"\b", cleaned):
                return info

        return None

    # Keep old name as alias for backward compatibility
    def _find_website(self, text: str) -> Optional[dict]:
        return self._find_known_site(text)

    def _do_open_known_site(self, site: dict) -> ToolResult:
        """Navigate directly to a known site's canonical URL."""
        site_id = site["site_id"]
        url = site["url"]
        display = site["display"]
        try:
            webbrowser.open(url)
            logger.info(
                "[BROWSER] Action=open_known_site | site=%s | url=%s | method=direct",
                site_id, url,
            )
            return ToolResult(
                success=True,
                message="Opening " + display + " for you.",
                data={
                    "action": "open_known_site",
                    "site_id": site_id,
                    "url": url,
                    "method": "direct",
                },
            )
        except Exception as exc:
            logger.error("Failed to open %s: %s", display, exc)
            return ToolResult(
                success=False,
                message="I could not open " + display + ". Please try again.",
            )

    # Keep old name as alias
    def _do_open_website(self, site: dict) -> ToolResult:
        return self._do_open_known_site(site)

    # ---- Generic open helpers -----------------------------------------------

    def _extract_open_target(self, text: str) -> Optional[str]:
        """
        Strip an open trigger and return the remaining target noun.

        Examples:
          "open ChatGPT"         -> "chatgpt"
          "go to LeetCode"       -> "leetcode"
          "take me to WhatsApp"  -> "whatsapp"
        """
        cleaned = text.lower().strip()
        for trigger in sorted(OPEN_TRIGGERS, key=len, reverse=True):
            if cleaned.startswith(trigger + " ") or cleaned == trigger:
                target = cleaned[len(trigger):].strip()
                for filler in TARGET_FILLERS:
                    if target.endswith(filler):
                        target = target[: -len(filler)].strip()
                return target if target else None
        return None

    @staticmethod
    def _is_app_alias(target: str) -> bool:
        """Return True if target is a registered desktop-app alias."""
        return target.lower() in _APP_ALIASES

    def _do_open_generic(self, target: str) -> ToolResult:
        """
        Open an unknown web target using direct URL inference.

        Strategy:
          1. Infer direct URL from target slug (https://www.<slug>.com/).
          2. Navigate directly -- NO Google search as intermediate step.
          3. Only fall back to Google search if URL inference itself fails.

        This ensures "open LeetCode" always lands on leetcode.com directly.
        """
        display = target.title()
        direct_url = _infer_direct_url(target)

        if direct_url:
            try:
                webbrowser.open(direct_url)
                logger.info(
                    "[BROWSER] Action=open_generic | target=%r | url=%s | method=url_inference",
                    target, direct_url,
                )
                return ToolResult(
                    success=True,
                    message="Opening " + display + " for you.",
                    data={
                        "action": "open_generic",
                        "target": target,
                        "url": direct_url,
                        "method": "url_inference",
                    },
                )
            except Exception as exc:
                logger.warning(
                    "URL inference navigation failed for %r: %s", target, exc
                )

        # Last resort: Google search (only reached if URL inference fails)
        search_url = SEARCH_ENGINE_URL.format(query=quote_plus(target))
        try:
            webbrowser.open(search_url)
            logger.info(
                "[BROWSER] Action=open_generic | target=%r | url=%s | method=search_fallback",
                target, search_url,
            )
            return ToolResult(
                success=True,
                message="Opening " + display + " for you.",
                data={
                    "action": "open_generic",
                    "target": target,
                    "url": search_url,
                    "method": "search_fallback",
                },
            )
        except Exception as exc:
            logger.error("Failed to open browser for %r: %s", target, exc)
            return ToolResult(
                success=False,
                message="I could not open " + display + " in the browser.",
            )
