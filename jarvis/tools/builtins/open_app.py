"""
Open Application tool for Jarvis.

Two-layer security model
─────────────────────────
Layer 1 — APPROVED_APPS (frozenset):
    The definitive list of applications Jarvis is allowed to launch.
    Removing an app_id from here immediately blocks it.

Layer 2 — APP_REGISTRY (dict):
    Per-app metadata: how to discover the executable and how to launch
    it.  The registry is filtered through the allowlist before any
    launch can occur.

Launch engine
─────────────
Each registry entry carries a ``launch_strategy`` that chooses the
right Windows mechanism:

  "shell_execute"   os.startfile() — lets the Windows shell pick the
                    correct verb.  Used for .exe, .cmd, .lnk, and URI
                    schemes.  Single-instance apps (Chrome, Edge, Code,
                    Spotify, Comet, Antigravity) bring their existing
                    window to the foreground automatically when launched
                    this way, because the OS delegates to the running
                    instance.

  "popen"           subprocess.Popen() — always spawns a new process.
                    Used for Command Prompt where a new window is the
                    correct behaviour.

  "uri"             Alias for "shell_execute".  Kept as a distinct tag
                    so log messages are readable.

Resolution pipeline (in order for each app):
  1. Windows URI scheme   — ms-settings:, etc.
  2. shutil.which()       — finds .exe / .cmd on the system PATH
  3. Explicit known paths — checked in the order listed in "paths"
  4. Start Menu .lnk      — searched in user + system Start Menu folders

To add a new approved application:
  1. Add its app_id to APPROVED_APPS.
  2. Add a matching LaunchProfile in APP_REGISTRY.
"""

import os
import re
import shutil
import subprocess
import glob
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal

from jarvis.logger import get_logger
from jarvis.permissions import RiskLevel
from jarvis.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# APPROVED_APPS  —  primary security boundary
# ──────────────────────────────────────────────────────────────────────────────
# Only app_ids listed here can be launched.  Everything else is refused.
# Edit ONLY this set to grant or revoke permissions.
# ──────────────────────────────────────────────────────────────────────────────

APPROVED_APPS: frozenset = frozenset({
    "file_explorer",    # File Manager / File Explorer
    "settings",         # Windows Settings
    "antigravity",      # Anti-Gravity IDE
    "vscode",           # Visual Studio Code
    "spotify",          # Spotify
    "chrome",           # Google Chrome
    "comet",            # Comet (Perplexity)
    "edge",             # Microsoft Edge
    "command_prompt",   # Command Prompt
    "instagram",        # Instagram (Edge PWA)
})


# ──────────────────────────────────────────────────────────────────────────────
# LaunchProfile dataclass
# ──────────────────────────────────────────────────────────────────────────────

LaunchStrategy = Literal["shell_execute", "popen", "uri"]


@dataclass
class LaunchProfile:
    """Complete description of how to discover and launch one application."""

    # Human-readable name used in spoken responses and log messages.
    display_name: str

    # Every phrase a user might say to refer to this app.
    aliases: List[str]

    # Primary command/binary name (searched via PATH).
    # For URI-only apps this can be left as "".
    command: str = ""

    # Additional filesystem paths to check in order (environment variables
    # are expanded at import time).
    paths: List[str] = field(default_factory=list)

    # A Windows URI scheme to launch instead of / in addition to the exe
    # (e.g. "ms-settings:", "shell:AppsFolder\...").
    uri: str = ""

    # Glob patterns for Start Menu .lnk shortcuts to try when PATH and
    # known paths fail.  Resolved at runtime.
    start_menu_globs: List[str] = field(default_factory=list)

    # How to actually start the process once the path is resolved.
    launch_strategy: LaunchStrategy = "shell_execute"

    # Window class names used for window-level graceful close.
    window_classes: List[str] = field(default_factory=list)

    # Exact process exe names (lowercase) as they appear in Task Manager.
    # Used by CloseApplicationTool for safe, targeted termination.
    # Must be exact — no wildcards, no partial names.
    process_names: List[str] = field(default_factory=list)

    # Extra spoken aliases specifically for close-intent detection.
    # Leave empty to reuse `aliases` for close matching too.
    close_aliases: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# APP_REGISTRY  —  per-application launch profiles
# ──────────────────────────────────────────────────────────────────────────────

def _e(path: str) -> str:
    """Expand environment variables in a path at import time."""
    return os.path.expandvars(path)


APP_REGISTRY: Dict[str, LaunchProfile] = {

    # ── Approved apps ─────────────────────────────────────────────────────────

    "file_explorer": LaunchProfile(
        display_name="File Explorer",
        aliases=[
            "file explorer", "explorer", "files", "my files",
            "file manager", "windows explorer", "finder",
        ],
        command="explorer.exe",
        launch_strategy="shell_execute",
        window_classes=["CabinetWClass", "ExploreWClass"],
        # NOTE: explorer.exe is the Windows shell — we close its windows
        # (CabinetWClass) gracefully rather than killing the process.
        process_names=[],  # empty = window-only close, never kill the process
        close_aliases=["file explorer", "explorer", "files", "my files",
                       "file manager", "windows explorer", "finder"],
    ),

    "settings": LaunchProfile(
        display_name="Windows Settings",
        aliases=[
            "settings", "windows settings", "system settings",
            "open settings", "preferences",
        ],
        uri="ms-settings:",
        launch_strategy="uri",
        window_classes=["ApplicationFrameWindow"],
        # Settings runs as SystemSettings.exe inside an ApplicationFrameWindow.
        # Closing the ApplicationFrameWindow is sufficient and graceful.
        process_names=["systemsettings.exe"],
        close_aliases=["settings", "windows settings", "system settings", "preferences"],
    ),

    "antigravity": LaunchProfile(
        display_name="Antigravity",
        aliases=[
            "antigravity", "anti gravity", "anti-gravity",
            "agy", "antigravity ide",
        ],
        # Installed via npm/pip — shows up as a .CMD shim on PATH.
        command="antigravity",
        paths=[
            _e(r"%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe"),
            _e(r"%LOCALAPPDATA%\antigravity\Antigravity.exe"),
            _e(r"%ProgramFiles%\Antigravity\Antigravity.exe"),
        ],
        start_menu_globs=[
            _e(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\Antigravity*.lnk"),
            _e(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\**\Antigravity*.lnk"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1"],
        process_names=["antigravity ide.exe", "antigravity.exe"],
        close_aliases=["antigravity", "anti gravity", "anti-gravity", "agy", "antigravity ide"],
    ),

    "vscode": LaunchProfile(
        display_name="Visual Studio Code",
        aliases=[
            "vs code", "visual studio code", "vscode", "code editor",
            "code", "vs-code",
        ],
        # `code` ships as a .CMD shim on PATH via the VS Code installer.
        command="code",
        paths=[
            _e(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            _e(r"%ProgramFiles%\Microsoft VS Code\Code.exe"),
        ],
        start_menu_globs=[
            _e(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\Visual Studio Code.lnk"),
            _e(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\**\Visual Studio Code.lnk"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1"],
        process_names=["code.exe"],
        close_aliases=["vs code", "visual studio code", "vscode", "code editor", "code", "vs-code"],
    ),

    "spotify": LaunchProfile(
        display_name="Spotify",
        aliases=[
            "spotify", "music player", "spotify music",
        ],
        # Spotify ships as both a classic installer and a Windows Store app.
        # The WindowsApps stub is the most reliable cross-install entry point.
        command="spotify",
        paths=[
            # Windows Store / WindowsApps stub (most common on Windows 11)
            _e(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
            # Classic installer location
            _e(r"%APPDATA%\Spotify\Spotify.exe"),
        ],
        start_menu_globs=[
            _e(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Spotify.lnk"),
            _e(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\Spotify.lnk"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1", "SpotifyMainWindow"],
        process_names=["spotify.exe"],
        close_aliases=["spotify", "music player", "spotify music"],
    ),

    "chrome": LaunchProfile(
        display_name="Google Chrome",
        aliases=[
            "chrome", "google chrome", "google browser",
        ],
        command="chrome",
        paths=[
            # System-wide install
            _e(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            _e(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            # Per-user install
            _e(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1"],
        process_names=["chrome.exe"],
        close_aliases=["chrome", "google chrome", "google browser"],
    ),

    "comet": LaunchProfile(
        display_name="Comet",
        aliases=[
            "comet", "comet browser", "comet app", "perplexity",
        ],
        # Comet is not on PATH, but has a Start Menu shortcut.
        # The shortcut resolves to the actual exe.
        command="",
        paths=[
            # Actual install location discovered from the shortcut
            _e(r"%LOCALAPPDATA%\Perplexity\Comet\Application\comet.exe"),
            _e(r"%LOCALAPPDATA%\Programs\Comet\Comet.exe"),
            _e(r"%ProgramFiles%\Comet\Comet.exe"),
        ],
        start_menu_globs=[
            _e(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Comet.lnk"),
            _e(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\Comet.lnk"),
            _e(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\**\Comet.lnk"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1"],
        process_names=["comet.exe"],
        close_aliases=["comet", "comet browser", "comet app", "perplexity"],
    ),

    "edge": LaunchProfile(
        display_name="Microsoft Edge",
        aliases=[
            "edge", "microsoft edge", "ms edge",
        ],
        command="msedge",
        paths=[
            _e(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            _e(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            _e(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1"],
        process_names=["msedge.exe"],
        close_aliases=["edge", "microsoft edge", "ms edge"],
    ),

    "command_prompt": LaunchProfile(
        display_name="Command Prompt",
        aliases=[
            "command prompt", "cmd", "terminal", "command line",
            "cmd prompt", "dos prompt",
        ],
        command="cmd.exe",
        launch_strategy="popen",
        window_classes=["ConsoleWindowClass"],
        process_names=["cmd.exe"],
        close_aliases=["command prompt", "cmd", "terminal", "command line",
                       "cmd prompt", "dos prompt"],
    ),

    "instagram": LaunchProfile(
        display_name="Instagram",
        aliases=[
            "instagram", "insta", "ig",
        ],
        # Installed as a Microsoft Edge PWA.
        # Launched via the Desktop shortcut which calls msedge_proxy.exe
        # with the PWA app-id, opening Instagram in its own app window.
        command="",
        paths=[
            # Desktop shortcut (OneDrive-synced Desktop)
            _e(r"%USERPROFILE%\OneDrive\Desktop\Instagram.lnk"),
            # Standard Desktop fallback
            _e(r"%USERPROFILE%\Desktop\Instagram.lnk"),
        ],
        start_menu_globs=[
            _e(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\Instagram.lnk"),
            _e(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\**\Instagram.lnk"),
        ],
        launch_strategy="shell_execute",
        window_classes=["Chrome_WidgetWin_1"],
        # msedge_proxy.exe hosts the PWA process
        process_names=["msedge_proxy.exe"],
        close_aliases=["instagram", "insta", "ig"],
    ),

    # ── Not approved — kept for helpful refusal messages ──────────────────────
    # Add the app_id to APPROVED_APPS above to re-enable.

    "notepad": LaunchProfile(
        display_name="Notepad",
        aliases=["notepad", "text editor", "note pad"],
        command="notepad.exe",
    ),
    "calculator": LaunchProfile(
        display_name="Calculator",
        aliases=["calculator", "calc", "the calculator"],
        command="calc.exe",
    ),
    "paint": LaunchProfile(
        display_name="MS Paint",
        aliases=["paint", "ms paint", "microsoft paint", "drawing"],
        command="mspaint.exe",
    ),
    "task_manager": LaunchProfile(
        display_name="Task Manager",
        aliases=["task manager", "taskmgr"],
        command="taskmgr.exe",
    ),
    "firefox": LaunchProfile(
        display_name="Firefox",
        aliases=["firefox", "mozilla firefox"],
        command="firefox.exe",
        paths=[_e(r"%ProgramFiles%\Mozilla Firefox\firefox.exe")],
    ),
    "powershell": LaunchProfile(
        display_name="PowerShell",
        aliases=["powershell", "power shell"],
        command="powershell.exe",
    ),
    "snipping_tool": LaunchProfile(
        display_name="Snipping Tool",
        aliases=["snipping tool", "screenshot", "snip"],
        command="snippingtool.exe",
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Resolution helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_lnk_target(lnk_path: str) -> Optional[str]:
    """
    Read a Windows .lnk shortcut and return the path it points to.

    Uses WScript.Shell via win32com when available, falls back to
    returning the .lnk path itself (os.startfile can open .lnk files
    directly, letting the shell resolve them).

    Returns:
        The resolved target path, the .lnk path itself as a fallback,
        or None if the file does not exist.
    """
    if not os.path.isfile(lnk_path):
        return None
    try:
        import win32com.client  # type: ignore
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(lnk_path)
        target = sc.Targetpath
        if target and os.path.isfile(target):
            logger.debug(f"  .lnk '{lnk_path}' -> target='{target}'")
            return target
        # Target path missing but shortcut exists — let the shell open it
        logger.debug(f"  .lnk target not found, will use shortcut directly: {lnk_path}")
        return lnk_path
    except Exception as exc:
        logger.debug(f"  win32com unavailable ({exc}), using .lnk directly: {lnk_path}")
        return lnk_path


def _resolve_profile(app_id: str, profile: LaunchProfile) -> Optional[str]:
    """
    Walk the resolution pipeline for one LaunchProfile.

    Resolution order:
      1. URI scheme  (if profile.uri is set)
      2. PATH        (shutil.which on profile.command)
      3. Known paths (profile.paths, in order)
      4. Start Menu  (first matching glob → .lnk → resolved target)

    Returns:
        The resolved path/URI string, or None if nothing was found.
    """
    logger.debug(f"[{app_id}] Resolving launch target …")

    # 1. URI scheme
    if profile.uri:
        logger.debug(f"[{app_id}] Using URI scheme: {profile.uri!r}")
        return profile.uri

    # 2. PATH lookup
    if profile.command:
        for variant in [profile.command, profile.command + ".exe", profile.command + ".cmd"]:
            found = shutil.which(variant)
            if found:
                logger.debug(f"[{app_id}] Found on PATH: {found!r}")
                return found

    # 3. Explicit known paths
    for path in profile.paths:
        if os.path.isfile(path):
            logger.debug(f"[{app_id}] Found at known path: {path!r}")
            return path
        else:
            logger.debug(f"[{app_id}] Known path not found: {path!r}")

    # 4. Start Menu shortcuts
    for pattern in profile.start_menu_globs:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            lnk = matches[0]
            logger.debug(f"[{app_id}] Found Start Menu shortcut: {lnk!r}")
            target = _resolve_lnk_target(lnk)
            if target:
                return target

    logger.debug(f"[{app_id}] Resolution failed — app not found.")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# OpenApplicationTool
# ──────────────────────────────────────────────────────────────────────────────

class OpenApplicationTool(BaseTool):
    """Opens a desktop application by name, enforcing the APPROVED_APPS allowlist."""

    name = "open_application"
    description = "Opens a desktop application (e.g., Chrome, VS Code, Spotify)."
    risk_level = RiskLevel.SAFE
    keywords = set()

    # ── Init ──────────────────────────────────────────────────────────────────

    def __init__(self):
        """
        Pre-resolve all approved apps and build alias lookup tables.

        Resolution is done once at startup so that execute() is fast.
        """
        # alias -> (app_id, profile, resolved_path_or_None)
        self._approved_lookup: Dict[str, tuple] = {}
        self._full_lookup: Dict[str, tuple] = {}

        installed_ids: set = set()
        blocked_ids = set(APP_REGISTRY) - APPROVED_APPS
        missing_ids = APPROVED_APPS - set(APP_REGISTRY)

        if missing_ids:
            logger.warning(
                f"APPROVED_APPS has entries with no registry profile (ignored): {missing_ids}"
            )

        for app_id, profile in APP_REGISTRY.items():
            resolved = _resolve_profile(app_id, profile)
            entry = (app_id, profile, resolved)

            for alias in profile.aliases:
                self._full_lookup[alias.lower()] = entry
                if app_id in APPROVED_APPS:
                    self._approved_lookup[alias.lower()] = entry

            if app_id in APPROVED_APPS and resolved:
                installed_ids.add(app_id)

        logger.info(
            f"OpenApplicationTool ready — "
            f"{len(APPROVED_APPS)} approved app(s), "
            f"{len(installed_ids)} resolved/installed, "
            f"{len(blocked_ids)} blocked registry entries."
        )

    # ── BaseTool interface ────────────────────────────────────────────────────

    def matches(self, text: str) -> bool:
        """
        Return True only if the text is an intent to open an *approved* app.

        Checks are performed against approved aliases only.  Blocked or
        unknown app names return False (falling through to the LLM brain).
        """
        cleaned = text.lower().strip()

        # Hard blocklist: common phrases that look like app launches but aren't
        FALSE_POSITIVE_PHRASES = {
            "start over", "reset conversation", "clear history",
            "run properly", "run again", "start again", "let's start",
            "how to run", "run the", "how do i run",
        }
        for phrase in FALSE_POSITIVE_PHRASES:
            if phrase in cleaned:
                return False

        for spoken_name in self._approved_lookup:
            pattern = r"\b" + re.escape(spoken_name) + r"\b"

            if any(t in cleaned for t in ["open ", "launch ", "open application"]):
                if re.search(pattern, cleaned):
                    return True

            elif any(t in cleaned for t in ["start ", "run "]):
                if re.search(r"\b(?:start|run)\s+" + re.escape(spoken_name) + r"\b", cleaned):
                    return True

            else:
                if re.search(pattern, cleaned):
                    return True

        return False

    def get_risk_level(self, raw_text: str) -> RiskLevel:
        """Command Prompt needs explicit confirmation; everything else is SAFE."""
        app_name = (self._extract_app_name(raw_text) or "").lower()
        if any(term in app_name for term in ["cmd", "command prompt", "terminal", "command line"]):
            return RiskLevel.MODERATE
        return RiskLevel.SAFE

    def action_summary(self, raw_text: str) -> str:
        """Describe which app is about to be launched."""
        app_name = self._extract_app_name(raw_text)
        return f"open {app_name}" if app_name else "open an application"

    # ── Execute ───────────────────────────────────────────────────────────────

    def execute(self, raw_text: str) -> ToolResult:
        """
        Parse the spoken text, enforce the allowlist, then launch.

        Returns:
            ToolResult with a spoken message and success/failure status.
        """
        app_name = self._extract_app_name(raw_text)

        if not app_name:
            return ToolResult(
                success=False,
                message=(
                    "I didn't catch which application to open. "
                    f"I can open: {self._available_list()}."
                ),
            )

        # ── Step 1: approved lookup ───────────────────────────────────
        entry = self._approved_lookup.get(app_name)
        if not entry:
            entry = self._fuzzy_match(app_name, approved_only=True)

        # ── Step 2: allowlist enforcement ────────────────────────────
        if not entry:
            full_entry = self._full_lookup.get(app_name) or self._fuzzy_match(
                app_name, approved_only=False
            )
            if full_entry:
                blocked_id, blocked_profile, _ = full_entry
                logger.warning(
                    f"BLOCKED launch: '{app_name}' -> '{blocked_id}' "
                    f"({blocked_profile.display_name}) is not in APPROVED_APPS."
                )
                return ToolResult(
                    success=False,
                    message=(
                        f"I'm not permitted to open {blocked_profile.display_name}. "
                        "It's not on my approved application list."
                    ),
                )

            logger.info(f"UNKNOWN launch request: '{app_name}' — not in registry.")
            return ToolResult(
                success=False,
                message=(
                    f"I don't recognise \"{app_name}\" as an application I can open. "
                    f"I can open: {self._available_list()}."
                ),
            )

        app_id, profile, resolved = entry

        # ── Step 3: check resolved path ──────────────────────────────
        if not resolved:
            logger.warning(
                f"ALLOWED but NOT INSTALLED: '{app_id}' ({profile.display_name}) — "
                f"no executable found."
            )
            return ToolResult(
                success=False,
                message=(
                    f"{profile.display_name} doesn't appear to be installed "
                    "on this computer."
                ),
            )

        logger.info(
            f"ALLOWED launch: '{app_name}' -> app_id='{app_id}' "
            f"strategy='{profile.launch_strategy}' path='{resolved}'"
        )

        return self._launch(profile, resolved)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_app_name(self, raw_text: str) -> Optional[str]:
        """Strip trigger words from the spoken text to isolate the app name."""
        cleaned = raw_text.lower().strip()
        triggers = [
            "please open", "can you open", "could you open",
            "open up", "open", "launch", "start", "run",
        ]
        for trigger in triggers:
            if cleaned.startswith(trigger):
                cleaned = cleaned[len(trigger):].strip()
                break
        fillers = ["please", "for me", "now", "app", "application"]
        for filler in fillers:
            if cleaned.endswith(filler):
                cleaned = cleaned[: -len(filler)].strip()
        return cleaned if cleaned else None

    def _fuzzy_match(self, text: str, *, approved_only: bool) -> Optional[tuple]:
        """Whole-word boundary match against the longest alias first."""
        from jarvis.utils import match_any_keyword
        source = self._approved_lookup if approved_only else self._full_lookup
        for spoken_name, entry in sorted(source.items(), key=lambda x: len(x[0]), reverse=True):
            if match_any_keyword(text, [spoken_name]):
                return entry
        return None

    def _available_list(self) -> str:
        """Comma-separated list of approved, installed apps for spoken responses."""
        seen: set = set()
        names: List[str] = []
        for app_id, profile, resolved in self._approved_lookup.values():
            if app_id not in seen and resolved:
                seen.add(app_id)
                names.append(profile.display_name)
        return ", ".join(sorted(names)) if names else "none currently detected"

    @staticmethod
    def _launch(profile: LaunchProfile, path: str) -> ToolResult:
        """
        Launch the application using the strategy declared in its profile.

        shell_execute / uri:
            Delegates to os.startfile() (Windows ShellExecuteW).
            - Single-instance apps (Chrome, Edge, Code, Spotify, Comet,
              Antigravity, File Explorer, Settings) will bring their
              existing window to the foreground automatically — the OS
              routes the ShellExecute call to the running instance.
            - Works for .exe, .cmd, .lnk, and URI schemes alike.

        popen:
            Uses subprocess.Popen with CREATE_NEW_CONSOLE to spawn a
            brand-new visible console window.  Used only for Command Prompt
            where opening a fresh window is the desired behaviour.

        Args:
            profile: The LaunchProfile for the app.
            path:    The resolved executable path or URI string.

        Returns:
            ToolResult indicating success or failure.
        """
        strategy = profile.launch_strategy
        display = profile.display_name

        try:
            if strategy in ("shell_execute", "uri"):
                logger.debug(f"  os.startfile({path!r})")
                os.startfile(path)  # type: ignore[attr-defined]

            elif strategy == "popen":
                # CREATE_NEW_CONSOLE (0x00000010) opens a visible new window
                logger.debug(f"  subprocess.Popen({path!r}, CREATE_NEW_CONSOLE)")
                subprocess.Popen(
                    path,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    close_fds=True,
                )

            else:
                # Unknown strategy — safe fallback
                logger.warning(f"  Unknown launch_strategy {strategy!r}, using os.startfile")
                os.startfile(path)  # type: ignore[attr-defined]

            logger.info(f"  Launched ({strategy}): {display} — '{path}'")
            return ToolResult(
                success=True,
                message=f"Opening {display} for you.",
                data={"app_id": profile.display_name, "path": path, "strategy": strategy},
            )

        except FileNotFoundError:
            logger.error(f"  Launch failed [{display}]: FileNotFoundError — '{path}'")
            return ToolResult(
                success=False,
                message=f"I couldn't find {display} at the expected location.",
            )

        except PermissionError:
            logger.error(f"  Launch failed [{display}]: PermissionError — '{path}'")
            return ToolResult(
                success=False,
                message=f"I don't have permission to open {display}.",
            )

        except OSError as exc:
            logger.error(f"  Launch failed [{display}]: OSError — {exc}")
            return ToolResult(
                success=False,
                message=f"Something went wrong trying to open {display}.",
            )

