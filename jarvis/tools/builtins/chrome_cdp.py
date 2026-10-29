"""
Chrome DevTools Protocol (CDP) helper for Jarvis.

Manages Chrome for YouTube tab reuse and navigation with the user's
DEFAULT Chrome browser (no isolated JarvisChrome profile).

Strategy
--------
Priority 1 - CDP mode (full tab reuse):
    Chrome is already running with --remote-debugging-port=9222.
    Jarvis can see all open tabs, navigate any tab directly, and
    bring the Chrome window to the foreground.

Priority 2 - Keyboard navigation (partial reuse):
    Chrome is running WITHOUT the debug port (the normal case when
    the user launched Chrome themselves).  Jarvis:
      1. Brings the Chrome window to the foreground.
      2. If a YouTube tab is visible (Chrome title contains "YouTube"):
         a. Presses Ctrl+L to focus the address bar.
         b. Types the video URL and presses Enter.
         c. The current YouTube tab is REPLACED - no new tab is opened.
      3. Otherwise opens the URL via the OS default browser (new tab).

Priority 3 - OS default browser fallback:
    webbrowser.open() / chrome.exe <url> - Chrome opens the URL in a
    new tab in the running instance.

Window focus strategy
---------------------
Windows blocks SetForegroundWindow() from non-foreground processes.
We bypass this with the AttachThreadInput trick:
    1. Find the Chrome_WidgetWin_1 HWND for any chrome.exe process.
    2. AttachThreadInput(chrome_tid, jarvis_tid, True).
    3. ShowWindow(SW_RESTORE) + BringWindowToTop + SetForegroundWindow.
    4. AttachThreadInput detach.
Fallback: WScript.Shell.AppActivate("YouTube") via win32com.
"""

import asyncio
import ctypes
import json
import logging
import os
import subprocess
import time
from typing import Optional

import requests
import websockets

logger = logging.getLogger(__name__)

# ---- Configuration -----------------------------------------------------------

_CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
_CHROME_EXE_X86 = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

# The user s default Chrome profile directory (for CDP launch if needed)
_DEFAULT_CHROME_PROFILE = os.path.join(
    os.environ.get("LOCALAPPDATA", r"C:\Users\Public"),
    "Google", "Chrome", "User Data",
)

_CDP_PORT = 9222
_CDP_BASE = "http://localhost:%d" % _CDP_PORT

# How long to wait for Chrome to start (seconds)
_CHROME_STARTUP_WAIT = 8
_CDP_POLL_INTERVAL = 0.4

# Chrome launch flags - only used when Jarvis launches Chrome fresh
def _chrome_flags(profile: str) -> list:
    return [
        "--remote-debugging-port=%d" % _CDP_PORT,
        "--user-data-dir=" + profile,
        "--no-first-run",
        "--start-maximized",
    ]

# Windows class name for Chrome s main browser window
_CHROME_WINDOW_CLASS = "Chrome_WidgetWin_1"

# Seconds to wait after navigation before focusing
_FOCUS_DELAY = 1.0

# Win32 constants
_SW_RESTORE = 9
_SW_SHOW = 5
_SW_SHOWMAXIMIZED = 3

# Delay between keystrokes in keyboard-nav mode (seconds)
_KEY_DELAY = 0.08


# ---- Window focus helpers ----------------------------------------------------

def _get_chrome_exe() -> Optional[str]:
    """Return path to chrome.exe or None if not found."""
    for p in (_CHROME_EXE, _CHROME_EXE_X86):
        if os.path.exists(p):
            return p
    return None


def _find_any_chrome_pid() -> Optional[int]:
    """
    Return the PID of the main Chrome browser process (any instance).
    The main browser process has chrome in its name and does NOT
    have --type= in its command-line.
    """
    try:
        import psutil
        best_pid: Optional[int] = None
        best_len = 0
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "chrome" not in name:
                    continue
                cmdline = proc.info.get("cmdline") or []
                cmdline_str = " ".join(cmdline).lower()
                if "--type=" in cmdline_str:
                    continue
                if len(cmdline_str) > best_len:
                    best_len = len(cmdline_str)
                    best_pid = proc.info["pid"]
            except Exception:
                continue
        if best_pid:
            logger.info("[CDP] Found Chrome browser PID=%d", best_pid)
        return best_pid
    except ImportError:
        logger.warning("[CDP] psutil not available.")
    except Exception as exc:
        logger.warning("[CDP] PID search error: %s", exc)
    return None


def _find_chrome_hwnd(pid: Optional[int] = None) -> Optional[int]:
    """
    Find the main Chrome_WidgetWin_1 HWND.
    If pid is given, only considers windows owned by that PID.
    Otherwise returns the best Chrome window regardless of owner.
    """
    try:
        import win32gui
        import win32process

        found_hwnd = None
        best_title_len = 0

        def _cb(hwnd, _):
            nonlocal found_hwnd, best_title_len
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                return True
            if cls != _CHROME_WINDOW_CLASS:
                return True
            if pid is not None:
                try:
                    _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                except Exception:
                    return True
                if window_pid != pid:
                    return True
            title = win32gui.GetWindowText(hwnd)
            if len(title) > best_title_len:
                best_title_len = len(title)
                found_hwnd = hwnd
            return True

        win32gui.EnumWindows(_cb, None)

        if found_hwnd:
            logger.info("[CDP] Found Chrome HWND=0x%X (title_len=%d)", found_hwnd, best_title_len)
        return found_hwnd

    except ImportError:
        logger.warning("[CDP] pywin32 not available.")
        return None
    except Exception as exc:
        logger.warning("[CDP] HWND search error: %s", exc)
        return None


def _get_chrome_title(hwnd: int) -> str:
    """Return the window title for the given HWND."""
    try:
        import win32gui
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def _force_foreground(hwnd: int) -> bool:
    """
    Bring window HWND to the foreground using the AttachThreadInput trick.
    Bypasses Windows Focus Stealing Prevention.
    """
    try:
        user32 = ctypes.windll.user32

        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)

        if fg_tid and target_tid and fg_tid != target_tid:
            user32.AttachThreadInput(target_tid, fg_tid, True)

        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.ShowWindow(hwnd, _SW_SHOWMAXIMIZED)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        if fg_tid and target_tid and fg_tid != target_tid:
            user32.AttachThreadInput(target_tid, fg_tid, False)

        logger.info("[CDP] SetForegroundWindow(0x%X) succeeded.", hwnd)
        return True

    except Exception as exc:
        logger.warning("[CDP] _force_foreground failed: %s", exc)
        return False


def _focus_via_wscript(fragments=("YouTube", "Chrome", "Google Chrome")) -> bool:
    """Fallback: use WScript.Shell.AppActivate to focus a Chrome window."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        for fragment in fragments:
            if shell.AppActivate(fragment):
                logger.info("[CDP] AppActivate(%r) succeeded.", fragment)
                return True
        logger.warning("[CDP] AppActivate: no matching window found.")
        return False
    except Exception as exc:
        logger.warning("[CDP] WScript.Shell fallback failed: %s", exc)
        return False


def _keyboard_navigate(url: str, hwnd: Optional[int] = None) -> bool:
    """
    Navigate the currently active Chrome tab to url using keyboard shortcuts.
    Steps: Ctrl+L -> type URL -> Enter.
    Works with pywinauto (preferred) or pyautogui fallback.
    """
    if hwnd:
        _force_foreground(hwnd)
        time.sleep(_FOCUS_DELAY)

    # Try pywinauto keyboard first
    try:
        from pywinauto import keyboard
        keyboard.send_keys("^l", pause=_KEY_DELAY)
        time.sleep(0.15)
        keyboard.send_keys("^a", pause=_KEY_DELAY)
        keyboard.send_keys("{DELETE}", pause=_KEY_DELAY)
        escaped = (url
            .replace("{", "{{").replace("}", "}}")
            .replace("+", "{+}").replace("^", "{^}").replace("%", "{%}"))
        keyboard.send_keys(escaped, pause=0.01)
        time.sleep(0.1)
        keyboard.send_keys("{ENTER}", pause=_KEY_DELAY)
        logger.info("[CDP] Keyboard navigation via pywinauto: %s", url[:80])
        return True
    except Exception as exc:
        logger.warning("[CDP] pywinauto keyboard nav failed: %s - trying pyautogui.", exc)

    # Fallback: pyautogui
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")
        pyautogui.typewrite(url, interval=0.02)
        pyautogui.press("enter")
        logger.info("[CDP] Keyboard navigation via pyautogui: %s", url[:80])
        return True
    except Exception as exc:
        logger.warning("[CDP] pyautogui keyboard nav failed: %s", exc)

    return False


# ---- ChromeCDP / ChromeController -------------------------------------------

class ChromeCDP:
    """
    Unified Chrome controller for Jarvis.

    Provides tab reuse and YouTube navigation for the user s DEFAULT
    Chrome browser (no separate JarvisChrome profile).
    """

    def __init__(self):
        self._chrome_pid: Optional[int] = None
        self._direct_mode: bool = False

    # ---- Helpers -------------------------------------------------------------

    @staticmethod
    def _is_chrome_running() -> bool:
        """Return True if any chrome.exe process is running."""
        try:
            import psutil
            for proc in psutil.process_iter(["name"]):
                try:
                    if "chrome" in (proc.info.get("name") or "").lower():
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _get_chrome_hwnd(self) -> Optional[int]:
        """Return the best Chrome HWND, caching the PID."""
        if not self._chrome_pid:
            self._chrome_pid = _find_any_chrome_pid()
        hwnd = _find_chrome_hwnd(self._chrome_pid)
        if hwnd is None:
            hwnd = _find_chrome_hwnd(None)
        return hwnd

    def _chrome_has_youtube_tab(self) -> bool:
        """
        Return True if any visible Chrome window title contains YouTube.
        Used in keyboard-nav mode where we cannot inspect tabs via CDP.
        """
        hwnd = self._get_chrome_hwnd()
        if not hwnd:
            return False
        title = _get_chrome_title(hwnd)
        result = "youtube" in title.lower()
        logger.info("[CDP] Chrome title: %r - has YouTube tab: %s", title, result)
        return result

    # ---- Public: Window focus -----------------------------------------------

    def bring_chrome_to_front(self) -> bool:
        """
        Bring the Chrome window to the foreground.
        Tries AttachThreadInput trick (up to 3 attempts), then WScript fallback.
        """
        for attempt in range(3):
            hwnd = self._get_chrome_hwnd()
            if hwnd:
                ok = _force_foreground(hwnd)
                if ok:
                    logger.info("[CDP] Chrome focused (attempt=%d).", attempt + 1)
                    return True
            if attempt < 2:
                logger.info("[CDP] Chrome window not found yet (attempt %d), retrying...", attempt + 1)
                time.sleep(1.5)

        logger.warning("[CDP] HWND exhausted - using WScript fallback.")
        return _focus_via_wscript()

    # ---- Public: CDP interface -----------------------------------------------

    def is_running(self) -> bool:
        """Return True if CDP is reachable (Chrome running with debug port)."""
        try:
            r = requests.get(_CDP_BASE + "/json/version", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def list_tabs(self) -> list:
        """Return a list of open tab dicts (id, url, title, type)."""
        try:
            r = requests.get(_CDP_BASE + "/json", timeout=3)
            return r.json()
        except Exception as exc:
            logger.error("[CDP] Failed to list tabs: %s", exc)
            return []

    def find_youtube_tab(self) -> Optional[str]:
        """
        Return the tab ID of the first YouTube page tab, or None.
        Only page type tabs are considered.
        """
        tabs = self.list_tabs()
        logger.info(
            "[CDP] Open tabs: %s",
            [(t.get("url", "")[:50], t.get("type", "")) for t in tabs],
        )
        for tab in tabs:
            url = tab.get("url", "")
            tab_type = tab.get("type", "")
            if tab_type == "page" and "youtube.com" in url:
                logger.info("[CDP] Found YouTube tab: id=%s url=%s", tab["id"], url[:60])
                return tab["id"]
        logger.info("[CDP] No YouTube tab found.")
        return None

    def open_tab(self, url: str) -> Optional[str]:
        """Open a new tab with the given URL. Returns tab ID or None."""
        try:
            r = requests.put(
                _CDP_BASE + "/json/new",
                params={"url": url},
                timeout=5,
            )
            tab = r.json()
            tab_id = tab.get("id")
            logger.info("[CDP] Opened new tab: id=%s url=%s", tab_id, url[:60])
            return tab_id
        except Exception as exc:
            logger.error("[CDP] Failed to open tab: %s", exc)
            return None

    def activate_tab(self, tab_id: str) -> bool:
        """Activate tab within Chrome (foreground tab inside browser)."""
        try:
            r = requests.get(_CDP_BASE + "/json/activate/" + tab_id, timeout=3)
            return r.status_code == 200
        except Exception as exc:
            logger.error("[CDP] Failed to activate tab %s: %s", tab_id, exc)
            return False

    def navigate_tab(self, tab_id: str, url: str) -> bool:
        """
        Navigate an existing tab to the given URL via CDP Page.navigate.
        Automatically brings Chrome to the foreground after navigation.
        """
        tabs = self.list_tabs()
        ws_url = None
        for tab in tabs:
            if tab.get("id") == tab_id:
                ws_url = tab.get("webSocketDebuggerUrl")
                break

        if not ws_url:
            logger.error("[CDP] No WebSocket URL for tab %s.", tab_id)
            return False

        logger.info("[CDP] Navigating tab %s to %s", tab_id, url[:80])

        try:
            result = asyncio.run(self._ws_navigate(ws_url, url))
        except Exception as exc:
            logger.error("[CDP] WebSocket navigation failed: %s", exc)
            return False

        time.sleep(_FOCUS_DELAY)
        self.bring_chrome_to_front()

        return result

    def ensure_youtube_tab(self) -> Optional[str]:
        """
        Return a YouTube tab ID via CDP, creating one if it does not exist.
        Only call this when CDP is confirmed running.
        """
        tab_id = self.find_youtube_tab()
        if tab_id:
            logger.info("[CDP] Reusing existing YouTube tab: %s", tab_id)
            self.activate_tab(tab_id)
            return tab_id

        logger.info("[CDP] Opening a new YouTube tab.")
        tab_id = self.open_tab("https://www.youtube.com/")
        if tab_id:
            time.sleep(1.5)
            self.bring_chrome_to_front()
        return tab_id

    # ---- Public: Unified play flow -------------------------------------------

    def play_video_in_youtube_tab(self, video_url: str) -> bool:
        """
        Navigate to video_url in the user s default Chrome, reusing the
        current YouTube tab when possible.

        Decision tree:
          A) CDP running -> find/create YouTube tab -> navigate via CDP.
          B) Chrome running (no CDP) + has YouTube tab visible ->
             bring to front -> Ctrl+L -> type URL -> Enter.
          C) Chrome running (no CDP), no YouTube tab ->
             open_url_in_chrome() (opens new tab via chrome.exe <url>).
          D) Chrome not running -> webbrowser.open() -> Chrome starts.

        Returns True on success.
        """
        # Case A: CDP available - full tab control
        if self.is_running():
            logger.info("[CDP] Case A: CDP available - using full tab reuse.")
            tab_id = self.ensure_youtube_tab()
            if tab_id:
                ok = self.navigate_tab(tab_id, video_url)
                self.activate_tab(tab_id)
                logger.info("[CDP] Case A navigation result: %s", ok)
                return ok
            logger.warning("[CDP] Case A: ensure_youtube_tab failed, falling through.")

        # Case B: Chrome running, has visible YouTube tab - keyboard navigation
        if self._is_chrome_running():
            if self._chrome_has_youtube_tab():
                logger.info("[CDP] Case B: Chrome running with YouTube tab - keyboard nav.")
                hwnd = self._get_chrome_hwnd()
                ok = _keyboard_navigate(video_url, hwnd)
                if ok:
                    time.sleep(_FOCUS_DELAY)
                    self.bring_chrome_to_front()
                    return True
                logger.warning("[CDP] Case B: keyboard nav failed, falling through to Case C.")

            # Case C: Chrome running but no YouTube tab
            logger.info("[CDP] Case C: Chrome running, no YouTube tab - opening URL in Chrome.")
            return self.open_url_in_chrome(video_url)

        # Case D: Chrome not running at all
        logger.info("[CDP] Case D: Chrome not running - opening via default browser.")
        return self.open_url_in_chrome(video_url)

    def open_url_in_chrome(self, url: str) -> bool:
        """
        Open url in Chrome.
        If Chrome is running: pass URL to the running instance (new tab in existing window).
        If Chrome is not running: open via webbrowser.open() which triggers OS default browser.
        """
        chrome_exe = _get_chrome_exe()

        if chrome_exe and self._is_chrome_running():
            try:
                subprocess.Popen(
                    [chrome_exe, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("[CDP] Opened URL in existing Chrome via chrome.exe: %s", url[:80])
                time.sleep(1.5)
                self.bring_chrome_to_front()
                return True
            except Exception as exc:
                logger.warning("[CDP] chrome.exe direct open failed: %s", exc)

        # Fallback: OS default browser handler
        try:
            import webbrowser
            webbrowser.open(url)
            logger.info("[CDP] Opened URL via webbrowser.open(): %s", url[:80])
            time.sleep(1.5)
            self.bring_chrome_to_front()
            return True
        except Exception as exc:
            logger.error("[CDP] webbrowser.open() failed: %s", exc)
            return False

    def ensure_chrome(self) -> bool:
        """
        Legacy compatibility shim - ensures Chrome is available.
        Returns True if Chrome is running (with or without CDP).
        Sets self._direct_mode = True if CDP is not available.
        """
        if self.is_running():
            self._direct_mode = False
            logger.info("[CDP] CDP available on port %d.", _CDP_PORT)
            return True

        if self._is_chrome_running():
            self._direct_mode = True
            logger.info("[CDP] Chrome running without CDP - direct mode.")
            return True

        # Launch Chrome fresh with the user s default profile
        logger.info("[CDP] Launching Chrome with default profile + CDP...")
        chrome_exe = _get_chrome_exe()
        if not chrome_exe:
            logger.error("[CDP] Chrome executable not found.")
            return False

        profile = _DEFAULT_CHROME_PROFILE
        if not os.path.isdir(profile):
            os.makedirs(profile, exist_ok=True)

        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = _SW_SHOWMAXIMIZED

            proc = subprocess.Popen(
                [chrome_exe] + _chrome_flags(profile) + ["https://www.youtube.com/"],
                startupinfo=si,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            self._chrome_pid = proc.pid
            logger.info("[CDP] Chrome launched (PID=%d).", proc.pid)
        except Exception as exc:
            logger.error("[CDP] Failed to launch Chrome: %s", exc)
            return False

        deadline = time.monotonic() + _CHROME_STARTUP_WAIT
        while time.monotonic() < deadline:
            if self.is_running():
                logger.info("[CDP] Chrome CDP is now reachable.")
                self._direct_mode = False
                time.sleep(2.5)
                self.bring_chrome_to_front()
                return True
            time.sleep(_CDP_POLL_INTERVAL)

        logger.warning("[CDP] Chrome started but CDP not reachable - using direct mode.")
        self._direct_mode = True
        return self._is_chrome_running()

    # ---- Internal async helpers ---------------------------------------------

    @staticmethod
    async def _ws_navigate(ws_url: str, url: str) -> bool:
        """Send a Page.navigate command over the WebSocket connection."""
        try:
            async with websockets.connect(ws_url, open_timeout=5) as ws:
                cmd = json.dumps({
                    "id": 1,
                    "method": "Page.navigate",
                    "params": {"url": url},
                })
                await ws.send(cmd)
                resp_raw = await asyncio.wait_for(ws.recv(), timeout=10)
                resp = json.loads(resp_raw)
                logger.debug("[CDP] Page.navigate response: %s", resp_raw[:200])
                if resp.get("result", {}).get("frameId"):
                    return True
                if "error" in resp:
                    logger.error("[CDP] Page.navigate error: %s", resp["error"])
                    return False
                return True
        except asyncio.TimeoutError:
            logger.error("[CDP] WebSocket navigation timed out.")
            return False
        except Exception as exc:
            logger.error("[CDP] WebSocket error: %s", exc)
            return False


# Alias for any code that might still reference ChromeController
ChromeController = ChromeCDP
