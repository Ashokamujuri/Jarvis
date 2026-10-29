"""
Play Music tool for Jarvis.

Handles requests like:
  "Play Believer by Imagine Dragons"
  "Play Shape of You"
  "Play Blinding Lights by The Weeknd"

How it works
------------
1. Parse the spoken text to extract song name and optional artist.
2. Build a focused YouTube search query (e.g. "believer imagine dragons
   official music video").
3. Send an HTTP request to YouTube search results and parse the embedded
   ytInitialData JSON to retrieve a ranked list of video IDs and titles.
   No API key is required. Only videos (not playlists or shorts) are
   returned because the search filter sp=EgIQAQ== is applied.
4. Score the top results against the original query to ensure confidence.
5. Navigate to the video in the user's DEFAULT Chrome browser using the
   unified ChromeCDP controller:
     - Case A: CDP available -> reuse YouTube tab, navigate via WebSocket.
     - Case B: Chrome running, YouTube tab visible -> Ctrl+L keyboard nav.
     - Case C: Chrome running, no YouTube tab -> open new tab in Chrome.
     - Case D: Chrome not running -> OS default browser opens the URL.

Tab reuse
---------
Every "play" command attempts to reuse the existing YouTube tab:
  - If Chrome was started with --remote-debugging-port (CDP mode), the
    exact YouTube tab is reused via WebSocket navigation.
  - Otherwise, the keyboard shortcut Ctrl+L is used to navigate the
    visible YouTube tab in the user's default Chrome browser.
No new tab is opened per song (except when no YouTube tab is open yet).

Fallback
--------
If no Chrome window control is possible, falls back to webbrowser.open()
(which opens a new tab in the running Chrome instance).

Confidence gating
-----------------
If the top result's title does not share enough tokens with the query,
Jarvis asks for clarification instead of playing an unrelated video.
The threshold is LOW_CONFIDENCE_THRESHOLD (default 0.25).

Separation from BrowserTool
----------------------------
matches() only fires on "play <something>" intents.  Phrases like
"open YouTube" or "search for videos" fall through to BrowserTool.
"""

import re
import json
import webbrowser
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import random
import time

import requests

from jarvis.logger import get_logger
from jarvis.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Full browser-like headers — reduces YouTube bot-detection / connection resets
_YT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Referer": "https://www.youtube.com/",
    "DNT": "1",
}

# YouTube search URL. sp=EgIQAQ== filters for videos only (not playlists/channels)
_YT_SEARCH_URL = "https://www.youtube.com/results"
_YT_VIDEO_FILTER = "EgIQAQ=="   # videos only

# Autoplay watch URL template
_YT_WATCH_URL = "https://www.youtube.com/watch?v={video_id}&autoplay=1"

# How many top results to fetch and score
_MAX_RESULTS = 5

# Minimum fraction of query tokens that must appear in the top video title
# for Jarvis to accept the result without asking for clarification.
LOW_CONFIDENCE_THRESHOLD = 0.25

# HTTP timeout per attempt (seconds)
_HTTP_TIMEOUT = 12

# Retry settings for YouTube search
_YT_MAX_RETRIES = 3
_YT_RETRY_BASE_DELAY = 1.2   # seconds — exponential back-off base

# Play trigger words
_PLAY_TRIGGERS = {
    "play", "play me", "please play", "can you play",
    "could you play", "put on", "start playing",
}

# Phrases that look like play intents but should not trigger this tool
_FALSE_POSITIVES = {
    "play youtube", "play a video", "open youtube",
    "play again", "play it again", "start over",
}

# Suffix appended to queries when no artist is supplied, to bias toward
# official uploads rather than covers or lyric videos.
_SEARCH_SUFFIX = "official music video"


# ---------------------------------------------------------------------------
# YouTube search helpers
# ---------------------------------------------------------------------------

def _yt_search(query: str, max_results: int = _MAX_RESULTS) -> Tuple[List[dict], Optional[str]]:
    """
    Search YouTube for ``query`` and return a list of video dicts.

    Each dict has keys: id, title, channel, duration.

    Retry strategy:
        Up to _YT_MAX_RETRIES attempts with exponential back-off + jitter.
        Connection resets (WinError 10054) are retried with a fresh TCP
        session automatically.

    Returns:
        (videos, error_message)  where error_message is None on success.
    """
    logger.debug("YT search: %r", query)

    last_error: Optional[str] = None
    resp = None

    for attempt in range(1, _YT_MAX_RETRIES + 1):
        try:
            resp = requests.get(
                _YT_SEARCH_URL,
                params={"search_query": query, "sp": _YT_VIDEO_FILTER},
                headers=_YT_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            last_error = None
            logger.debug("YT search succeeded on attempt %d.", attempt)
            break  # success

        except requests.exceptions.ConnectionError as exc:
            last_error = str(exc)
            logger.warning(
                "YT search connection error (attempt %d/%d): %s",
                attempt, _YT_MAX_RETRIES, exc,
            )
            if attempt < _YT_MAX_RETRIES:
                # Exponential back-off with ±30 % jitter to avoid burst retries
                delay = _YT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                delay *= 0.7 + random.random() * 0.6
                logger.info("[MUSIC] Retrying YouTube search in %.1fs...", delay)
                time.sleep(delay)
            continue

        except requests.RequestException as exc:
            last_error = str(exc)
            logger.error(
                "YT search HTTP error (attempt %d/%d): %s",
                attempt, _YT_MAX_RETRIES, exc,
            )
            if attempt < _YT_MAX_RETRIES:
                delay = _YT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.info("[MUSIC] Retrying YouTube search in %.1fs...", delay)
                time.sleep(delay)
            continue

    if last_error or resp is None:
        return [], (last_error or "No response from YouTube.")

    # YouTube embeds search results as a JSON blob in the page HTML.
    match = re.search(
        r"var ytInitialData\s*=\s*(\{.+?\});\s*(?:</script>|var )",
        resp.text,
        re.DOTALL,
    )
    if not match:
        logger.warning("ytInitialData not found in YouTube response.")
        return [], "Could not parse YouTube search results."

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        # The regex may have cut the JSON short — find the outermost balanced
        # brace to recover a valid JSON object.
        raw = match.group(1)
        depth = end = 0
        for i, ch in enumerate(raw):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            data = json.loads(raw[:end])
        except json.JSONDecodeError as exc:
            logger.error("JSON parse failed: %s", exc)
            return [], "Could not parse YouTube search results."

    # Navigate the nested structure to get video items.
    try:
        sections = (
            data["contents"]
            ["twoColumnSearchResultsRenderer"]
            ["primaryContents"]
            ["sectionListRenderer"]
            ["contents"]
        )
    except (KeyError, TypeError):
        logger.warning("Unexpected ytInitialData structure.")
        return [], "Unexpected YouTube page structure."

    videos: List[dict] = []
    for section in sections:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            vr = item.get("videoRenderer", {})
            if not vr:
                continue
            vid_id = vr.get("videoId", "")
            title_runs = vr.get("title", {}).get("runs", [])
            title = title_runs[0].get("text", "") if title_runs else ""
            owner_runs = vr.get("ownerText", {}).get("runs", [])
            channel = owner_runs[0].get("text", "") if owner_runs else ""
            duration = vr.get("lengthText", {}).get("simpleText", "")
            if vid_id and title:
                videos.append({
                    "id": vid_id,
                    "title": title,
                    "channel": channel,
                    "duration": duration,
                })
            if len(videos) >= max_results:
                break
        if len(videos) >= max_results:
            break

    logger.debug("YT search returned %d result(s).", len(videos))
    return videos, None


# ---------------------------------------------------------------------------
# Query / confidence helpers
# ---------------------------------------------------------------------------

def _build_query(song: str, artist: Optional[str]) -> str:
    """Build the YouTube search query from song + optional artist."""
    if artist:
        return "%s %s %s" % (song, artist, _SEARCH_SUFFIX)
    return "%s %s" % (song, _SEARCH_SUFFIX)


def _confidence_score(query_tokens: set, video_title: str) -> float:
    """
    Return the fraction of query tokens found in the video title.

    Excludes generic words that appear in every search suffix.
    """
    STOPWORDS = {"official", "music", "video", "audio", "lyrics", "the",
                 "a", "an", "of", "in", "on", "by", "for", "and", "ft",
                 "feat", "featuring", "version", "full", "hd", "4k"}
    title_lower = video_title.lower()
    meaningful = {t for t in query_tokens if t not in STOPWORDS and len(t) > 1}
    if not meaningful:
        return 1.0
    hits = sum(1 for t in meaningful if t in title_lower)
    return hits / len(meaningful)


# ---------------------------------------------------------------------------
# PlayMusicTool
# ---------------------------------------------------------------------------

class PlayMusicTool(BaseTool):
    """
    Searches YouTube for a song and plays it in a reused YouTube tab.

    Handles "play <song>" and "play <song> by <artist>" requests.
    Uses YouTube search scraping (no API key required).
    Uses Chrome DevTools Protocol to navigate the same YouTube tab
    across multiple consecutive play commands.
    """

    name = "play_music"
    description = "Plays a song on YouTube."
    keywords = set()

    def __init__(self):
        # Import lazily to avoid circular imports and keep startup fast
        from jarvis.tools.builtins.chrome_cdp import ChromeCDP
        self._cdp = ChromeCDP()

    def matches(self, text: str) -> bool:
        """
        Return True for "play <song>" intents only.

        Explicitly excluded: "open YouTube", search intents, and
        the false-positive phrases in _FALSE_POSITIVES.
        """
        cleaned = text.lower().strip()

        # Strip common conversational leading words: "yeah", "yes", "hey", "ok", "okay"
        for prefix in ("yeah ", "yes ", "hey ", "ok ", "okay "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        for phrase in _FALSE_POSITIVES:
            if phrase == cleaned or cleaned.startswith(phrase + " "):
                return False

        # Must start with a play trigger
        for trigger in sorted(_PLAY_TRIGGERS, key=len, reverse=True):
            if cleaned.startswith(trigger + " ") or cleaned == trigger:
                remainder = cleaned[len(trigger):].strip()
                if remainder:
                    return True
                break

        return False

    def action_summary(self, raw_text: str) -> str:
        song, artist = self._parse_request(raw_text)
        if artist:
            return "play %s by %s on YouTube" % (song, artist)
        return "play %s on YouTube" % song

    def execute(self, raw_text: str) -> ToolResult:
        """
        Parse the request, search YouTube, score results, navigate YouTube tab.
        """
        song, artist = self._parse_request(raw_text)

        if not song:
            return ToolResult(
                success=False,
                message="What song would you like me to play?",
            )

        if len(song.split()) < 1 or (len(song) < 3 and not artist):
            return ToolResult(
                success=False,
                message=(
                    "I am not sure which song you mean by %r. "
                    "Could you tell me the song name?" % song
                ),
            )

        query = _build_query(song, artist)
        logger.info(
            "[MUSIC] Request: song=%r artist=%r query=%r",
            song, artist, query,
        )

        # Search YouTube
        videos, err = _yt_search(query)
        if err or not videos:
            logger.error("[MUSIC] YT search failed: %s", err)
            return ToolResult(
                success=False,
                message=(
                    "I could not search YouTube right now. "
                    "Please check your internet connection and try again."
                ),
            )

        # Score top results
        query_tokens = set(re.sub(r"[^a-z0-9 ]", "", query).split())
        top = videos[0]
        score = _confidence_score(query_tokens, top["title"])

        logger.info(
            "[MUSIC] Top result: %r  channel=%r  duration=%s  score=%.2f",
            top["title"], top["channel"], top["duration"], score,
        )

        # Confidence gate
        if score < LOW_CONFIDENCE_THRESHOLD:
            logger.warning(
                "[MUSIC] Low confidence (%.2f) for query %r. Top result: %r",
                score, query, top["title"],
            )
            return ToolResult(
                success=False,
                message=(
                    "I am not confident I found the right song. "
                    "Could you give me the artist name as well? "
                    "For example: play %s by <artist name>." % song.title()
                ),
                data={"query": query, "top_title": top["title"], "score": score},
            )

        # Build autoplay URL
        watch_url = _YT_WATCH_URL.format(video_id=top["id"])
        logger.info(
            "[MUSIC] Target video: video_id=%s  title=%r  url=%s",
            top["id"], top["title"], watch_url,
        )

        # Navigate existing YouTube tab via CDP
        success = self._play_via_cdp(watch_url)

        if not success:
            # Fallback: open in browser (creates a new tab)
            logger.warning(
                "[MUSIC] CDP navigation failed — falling back to webbrowser.open()."
            )
            try:
                webbrowser.open(watch_url)
                logger.info("[MUSIC] Fallback: webbrowser.open() succeeded.")
                success = True
            except Exception as exc:
                logger.error("[MUSIC] Fallback webbrowser.open() failed: %s", exc)
                return ToolResult(
                    success=False,
                    message="I found the song but could not open the browser to play it.",
                    data={"url": watch_url, "error": str(exc)},
                )

        # Compose natural spoken response
        spoken_title = top["title"]
        spoken_channel = top["channel"]
        if artist:
            message = "Playing %s by %s for you." % (song.title(), artist.title())
        else:
            message = "Playing %s for you." % spoken_title

        return ToolResult(
            success=True,
            message=message,
            data={
                "video_id": top["id"],
                "title": spoken_title,
                "channel": spoken_channel,
                "duration": top["duration"],
                "url": watch_url,
                "query": query,
                "confidence": score,
                "cdp_used": success,
            },
        )

    # -----------------------------------------------------------------------
    # CDP playback helper
    # -----------------------------------------------------------------------

    def _play_via_cdp(self, watch_url: str) -> bool:
        """
        Navigate to watch_url using the unified ChromeCDP controller.

        Delegates entirely to ChromeCDP.play_video_in_youtube_tab() which
        implements the full 4-case decision tree:
          A) CDP available       -> reuse YouTube tab via WebSocket
          B) YouTube tab visible -> keyboard Ctrl+L navigation
          C) Chrome open, no YT -> open new tab in Chrome
          D) Chrome not open    -> OS default browser

        Returns True on success, False on any failure.
        """
        try:
            logger.info("[MUSIC] Delegating to ChromeCDP.play_video_in_youtube_tab: %s", watch_url[:80])
            ok = self._cdp.play_video_in_youtube_tab(watch_url)
            logger.info("[MUSIC] play_video_in_youtube_tab result: %s", ok)
            return ok
        except Exception as exc:
            logger.error("[MUSIC] CDP playback error: %s", exc, exc_info=True)
            return False

    # -----------------------------------------------------------------------
    # Request parsing
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_request(raw_text: str) -> Tuple[str, Optional[str]]:
        """
        Extract song name and optional artist from the spoken text.

        Patterns handled:
          "play Believer by Imagine Dragons"  -> ("believer", "imagine dragons")
          "play Shape of You"                 -> ("shape of you", None)
          "play Watermelon Sugar by Harry Styles" -> ("watermelon sugar", "harry styles")
        """
        cleaned = raw_text.lower().strip()

        # Strip leading polite / conversational phrases
        for prefix in ("yeah ", "yes ", "hey ", "ok ", "okay ", "please ", "can you ", "could you "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        # Strip play trigger (longest first)
        for trigger in sorted(_PLAY_TRIGGERS, key=len, reverse=True):
            if cleaned.startswith(trigger + " "):
                cleaned = cleaned[len(trigger):].strip()
                break
            elif cleaned == trigger:
                return "", None

        # Strip trailing filler
        for filler in (" please", " for me", " now"):
            if cleaned.endswith(filler):
                cleaned = cleaned[: -len(filler)].strip()

        # Split on ' by ' to detect artist
        if " by " in cleaned:
            parts = cleaned.split(" by ", 1)
            song = parts[0].strip()
            artist = parts[1].strip()
            # Ignore trailing noise after the artist
            for noise in (" please", " for me", " on youtube", " on spotify"):
                if artist.endswith(noise):
                    artist = artist[: -len(noise)].strip()
            return song, artist if artist else None

        return cleaned, None
