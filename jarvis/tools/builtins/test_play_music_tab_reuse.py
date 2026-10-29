"""
Regression tests for YouTube tab reuse in PlayMusicTool.

Tests prove that consecutive "play" commands navigate the SAME tab
instead of opening multiple new tabs.

Run with:
    python -m pytest jarvis/tools/builtins/test_play_music_tab_reuse.py -v
"""

import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call


# ---- helpers -----------------------------------------------------------------

def _make_search_response(videos):
    """Build a fake ytInitialData JSON embedded in YouTube HTML."""
    items = []
    for v in videos:
        items.append({
            "videoRenderer": {
                "videoId": v["id"],
                "title": {"runs": [{"text": v["title"]}]},
                "ownerText": {"runs": [{"text": v["channel"]}]},
                "lengthText": {"simpleText": v.get("duration", "3:30")},
            }
        })
    data = {
        "contents": {
            "twoColumnSearchResultsRenderer": {
                "primaryContents": {
                    "sectionListRenderer": {
                        "contents": [
                            {"itemSectionRenderer": {"contents": items}}
                        ]
                    }
                }
            }
        }
    }
    blob = json.dumps(data)
    return "var ytInitialData = %s; </script>" % blob


def _fake_yt_response(videos):
    """Return a mock requests.Response carrying fake YouTube HTML."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.text = _make_search_response(videos)
    return resp


# ---- ChromeCDP mock ----------------------------------------------------------

class FakeCDP:
    """
    Fake ChromeCDP that tracks tab navigation calls.

    Simulates one persistent YouTube tab being reused.
    """

    def __init__(self):
        self.is_running_returns = True
        self.youtube_tab_id = "tab-yt-001"
        self.navigate_calls = []       # list of (tab_id, url) tuples
        self.open_tab_calls = []
        self.activate_calls = []

    def is_running(self):
        return self.is_running_returns

    def find_youtube_tab(self):
        return self.youtube_tab_id

    def activate_tab(self, tab_id):
        self.activate_calls.append(tab_id)
        return True

    def navigate_tab(self, tab_id, url):
        self.navigate_calls.append((tab_id, url))
        return True

    def ensure_youtube_tab(self):
        return self.youtube_tab_id

    def play_video_in_youtube_tab(self, url):
        self.navigate_calls.append((self.youtube_tab_id, url))
        return True

    def open_tab(self, url):
        tab_id = "tab-new-%d" % len(self.open_tab_calls)
        self.open_tab_calls.append((tab_id, url))
        return tab_id


# ---- Tests -------------------------------------------------------------------

class TestPlayMusicTabReuse(unittest.TestCase):

    def _make_tool(self, fake_cdp):
        """Create a PlayMusicTool with a FakeCDP injected."""
        import sys
        sys.path.insert(0, ".")
        from jarvis.tools.builtins.play_music import PlayMusicTool

        tool = PlayMusicTool.__new__(PlayMusicTool)
        tool._cdp = fake_cdp
        return tool

    def _fake_search(self, videos):
        """Return a patch for requests.get that serves fake YouTube results."""
        return patch(
            "jarvis.tools.builtins.play_music.requests.get",
            return_value=_fake_yt_response(videos),
        )

    # ---- Tab reuse -----------------------------------------------------------

    def test_first_play_opens_youtube_tab(self):
        """First play command finds the YouTube tab and navigates it."""
        fake = FakeCDP()
        tool = self._make_tool(fake)

        videos = [{"id": "v001", "title": "Believer Imagine Dragons Official", "channel": "Imagine Dragons"}]
        with self._fake_search(videos):
            result = tool.execute("play Believer by Imagine Dragons")

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(fake.navigate_calls), 1)
        self.assertEqual(fake.navigate_calls[0][0], "tab-yt-001")
        self.assertIn("v001", fake.navigate_calls[0][1])

    def test_second_play_reuses_same_tab(self):
        """Second play command navigates the SAME tab (no new tab opened)."""
        fake = FakeCDP()
        tool = self._make_tool(fake)

        videos_a = [{"id": "v001", "title": "Believer Imagine Dragons Official", "channel": "Imagine Dragons"}]
        videos_b = [{"id": "v002", "title": "Shape of You Ed Sheeran Official", "channel": "Ed Sheeran"}]

        with self._fake_search(videos_a):
            r1 = tool.execute("play Believer by Imagine Dragons")
        with self._fake_search(videos_b):
            r2 = tool.execute("play Shape of You by Ed Sheeran")

        self.assertTrue(r1.success, r1.message)
        self.assertTrue(r2.success, r2.message)

        # Both commands should have used the same tab ID
        self.assertEqual(len(fake.navigate_calls), 2)
        self.assertEqual(fake.navigate_calls[0][0], "tab-yt-001")
        self.assertEqual(fake.navigate_calls[1][0], "tab-yt-001")

        # No new tabs should have been opened
        self.assertEqual(len(fake.open_tab_calls), 0)

    def test_three_consecutive_plays_reuse_same_tab(self):
        """Three consecutive play commands all reuse the same tab."""
        fake = FakeCDP()
        tool = self._make_tool(fake)

        songs = [
            ({"id": "v001", "title": "Believer Imagine Dragons Official", "channel": "Imagine Dragons"},
             "play Believer by Imagine Dragons"),
            ({"id": "v002", "title": "Shape of You Ed Sheeran Official", "channel": "Ed Sheeran"},
             "play Shape of You"),
            ({"id": "v003", "title": "Counting Stars OneRepublic Official", "channel": "OneRepublic"},
             "play Counting Stars by OneRepublic"),
        ]

        for video_info, phrase in songs:
            with self._fake_search([video_info]):
                result = tool.execute(phrase)
            self.assertTrue(result.success, result.message)

        # All 3 commands: same tab, different URLs
        self.assertEqual(len(fake.navigate_calls), 3)
        tab_ids = [c[0] for c in fake.navigate_calls]
        self.assertEqual(tab_ids, ["tab-yt-001", "tab-yt-001", "tab-yt-001"])

        video_ids = [c[1].split("v=")[1].split("&")[0] for c in fake.navigate_calls]
        self.assertEqual(video_ids, ["v001", "v002", "v003"])

        # Zero new tabs
        self.assertEqual(len(fake.open_tab_calls), 0)

    # ---- No YouTube tab existing ---------------------------------------------

    def test_play_when_no_youtube_tab_opens_and_navigates(self):
        """If no YouTube tab exists, a new tab is created and navigated."""
        fake = FakeCDP()
        fake.youtube_tab_id = None   # simulate: no YouTube tab open

        # After open_tab is called, pretend the tab now exists
        original_open = fake.open_tab

        def open_tab_side_effect(url):
            tab_id = original_open(url)
            fake.youtube_tab_id = tab_id   # now it exists
            return tab_id

        fake.open_tab = open_tab_side_effect

        # Redefine play_video_in_youtube_tab to reflect new tab creation
        def play_video(url):
            tab_id = "tab-new-0"
            fake.navigate_calls.append((tab_id, url))
            return True

        fake.play_video_in_youtube_tab = play_video

        tool = self._make_tool(fake)

        videos = [{"id": "v001", "title": "Believer Imagine Dragons Official", "channel": "Imagine Dragons"}]
        with self._fake_search(videos):
            result = tool.execute("play Believer by Imagine Dragons")

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(fake.navigate_calls), 1)

    # ---- CDP unavailable (fallback) -----------------------------------------

    def test_cdp_unavailable_falls_back_to_webbrowser(self):
        """If CDP is unavailable, falls back to webbrowser.open without crashing."""
        fake = FakeCDP()
        fake.is_running_returns = False
        fake.play_video_in_youtube_tab = MagicMock(return_value=False)

        # Also make navigate_tab fail
        fake.navigate_tab = MagicMock(return_value=False)
        fake.find_youtube_tab = MagicMock(return_value=None)
        fake.ensure_youtube_tab = MagicMock(return_value=None)

        tool = self._make_tool(fake)

        videos = [{"id": "v001", "title": "Believer Imagine Dragons Official", "channel": "Imagine Dragons"}]
        with self._fake_search(videos):
            with patch("jarvis.tools.builtins.play_music.webbrowser.open") as mock_wb:
                mock_wb.return_value = True
                result = tool.execute("play Believer by Imagine Dragons")

        self.assertTrue(result.success, result.message)
        mock_wb.assert_called_once()
        call_url = mock_wb.call_args[0][0]
        self.assertIn("v001", call_url)

    # ---- Request parsing -----------------------------------------------------

    def test_parse_song_and_artist(self):
        from jarvis.tools.builtins.play_music import PlayMusicTool
        p = PlayMusicTool._parse_request
        self.assertEqual(p("play Believer by Imagine Dragons"), ("believer", "imagine dragons"))
        self.assertEqual(p("play Shape of You"), ("shape of you", None))
        self.assertEqual(p("play Watermelon Sugar by Harry Styles"), ("watermelon sugar", "harry styles"))
        self.assertEqual(p("play me Counting Stars by OneRepublic"), ("counting stars", "onerepublic"))

    def test_matches_play_triggers(self):
        from jarvis.tools.builtins.play_music import PlayMusicTool
        tool = PlayMusicTool.__new__(PlayMusicTool)
        tool._cdp = MagicMock()

        self.assertTrue(tool.matches("play Believer"))
        self.assertTrue(tool.matches("play me Shape of You"))
        self.assertTrue(tool.matches("put on Blinding Lights"))
        self.assertTrue(tool.matches("play Counting Stars by OneRepublic"))

        self.assertFalse(tool.matches("open youtube"))
        self.assertFalse(tool.matches("play youtube"))
        self.assertFalse(tool.matches("play"))              # no song
        self.assertFalse(tool.matches("play again"))
        self.assertFalse(tool.matches("search for music"))

    # ---- Tab URL content -----------------------------------------------------

    def test_navigate_url_contains_autoplay(self):
        """The URL passed to navigate_tab must include autoplay=1."""
        fake = FakeCDP()
        tool = self._make_tool(fake)

        videos = [{"id": "abc123", "title": "Counting Stars OneRepublic Official", "channel": "OneRepublic"}]
        with self._fake_search(videos):
            tool.execute("play Counting Stars by OneRepublic")

        self.assertEqual(len(fake.navigate_calls), 1)
        nav_url = fake.navigate_calls[0][1]
        self.assertIn("watch?v=abc123", nav_url)
        self.assertIn("autoplay=1", nav_url)

    # ---- Low confidence gate -------------------------------------------------

    def test_low_confidence_does_not_navigate(self):
        """Low-confidence results must NOT cause navigation."""
        fake = FakeCDP()
        tool = self._make_tool(fake)

        # Title shares no tokens with the query
        videos = [{"id": "v999", "title": "Random Unrelated Content", "channel": "SomeChannel"}]
        with self._fake_search(videos):
            result = tool.execute("play Believer by Imagine Dragons")

        self.assertFalse(result.success)
        self.assertEqual(len(fake.navigate_calls), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
