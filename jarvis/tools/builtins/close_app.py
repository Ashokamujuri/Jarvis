"""
Close Application tool for Jarvis.

Security design: Reuses APPROVED_APPS and APP_REGISTRY from open_app.py.
Process matching by exact exe name only. File Explorer handled specially
(never kills explorer.exe shell process, only closes folder windows).

Close strategy:
  1. Graceful WM_CLOSE to all windows owned by the app process.
     Wait up to GRACEFUL_TIMEOUT_S for voluntary exit.
  2. If still alive: return a needs-confirmation ToolResult.
  3. Force-terminate: only on FORCE_CLOSE: prefixed re-invocation.
"""

import re
import time
from typing import Dict, List, Optional, Tuple

import psutil
import win32gui
import win32con
import win32process

from jarvis.logger import get_logger
from jarvis.permissions import RiskLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.builtins.open_app import (
    APPROVED_APPS,
    APP_REGISTRY,
    LaunchProfile,
)

logger = get_logger(__name__)

GRACEFUL_TIMEOUT_S: float = 3.0

_CLOSE_VERBS = {"close", "quit", "exit", "shut down", "shutdown", "end", "stop"}

_FALSE_POSITIVES = {
    "shut down windows", "shut down computer", "shut down pc",
    "close this", "close that", "end session",
    "stop running", "stop it", "stop that",
}


def _get_windows_for_pids(pids: set) -> List[int]:
    handles: List[int] = []
    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids:
                handles.append(hwnd)
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as exc:
        logger.debug("EnumWindows error: %s", exc)
    return handles


def _get_windows_by_class(class_names: List[str]) -> List[int]:
    handles: List[int] = []
    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            cls = win32gui.GetClassName(hwnd)
            if cls in class_names:
                handles.append(hwnd)
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as exc:
        logger.debug("EnumWindows error: %s", exc)
    return handles


def _find_processes(exe_names: List[str]) -> List[psutil.Process]:
    targets = {n.lower() for n in exe_names}
    found: List[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() in targets:
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


def _still_alive(exe_names: List[str]) -> bool:
    return bool(_find_processes(exe_names))


def _build_close_lookup() -> Dict[str, Tuple[str, LaunchProfile]]:
    lookup: Dict[str, Tuple[str, LaunchProfile]] = {}
    for app_id, profile in APP_REGISTRY.items():
        if app_id not in APPROVED_APPS:
            continue
        aliases = profile.close_aliases if profile.close_aliases else profile.aliases
        for alias in aliases:
            lookup[alias.lower()] = (app_id, profile)
    return lookup


class CloseApplicationTool(BaseTool):
    name = "close_application"
    description = "Closes a running desktop application (close Chrome, quit Spotify, etc.)"
    risk_level = RiskLevel.MODERATE
    keywords = set()

    def __init__(self):
        self._close_lookup = _build_close_lookup()
        count = len({aid for aid, _ in self._close_lookup.values()})
        logger.info("CloseApplicationTool ready - %d apps can be closed.", count)

    def matches(self, text: str) -> bool:
        cleaned = text.lower().strip()
        for phrase in _FALSE_POSITIVES:
            if phrase in cleaned:
                return False
        for spoken_alias in self._close_lookup:
            alias_pat = r"\b" + re.escape(spoken_alias) + r"\b"
            for verb in _CLOSE_VERBS:
                verb_pat = r"\b" + re.escape(verb) + r"\b"
                if re.search(verb_pat, cleaned) and re.search(alias_pat, cleaned):
                    return True
        return False

    def get_risk_level(self, raw_text: str) -> RiskLevel:
        return RiskLevel.MODERATE

    def action_summary(self, raw_text: str) -> str:
        name = self._extract_app_name(raw_text)
        return ("close %s" % name) if name else "close an application"

    def execute(self, raw_text: str) -> ToolResult:
        force = False
        if raw_text.startswith("FORCE_CLOSE:"):
            force = True
            raw_text = raw_text[len("FORCE_CLOSE:"):]

        app_name = self._extract_app_name(raw_text)
        if not app_name:
            return ToolResult(
                success=False,
                message=(
                    "I did not catch which application to close. "
                    "I can close: %s." % self._available_list()
                ),
            )

        entry = self._close_lookup.get(app_name) or self._fuzzy_match(app_name)
        if not entry:
            logger.info("Close request for unknown alias: %r", app_name)
            return ToolResult(
                success=False,
                message=(
                    "I do not recognise %r as an app I can close. "
                    "I can close: %s." % (app_name, self._available_list())
                ),
            )

        app_id, profile = entry
        display = profile.display_name

        logger.info(
            "Close: %r -> %r force=%s pids=%s",
            app_name, app_id, force, profile.process_names,
        )

        if app_id == "file_explorer":
            return self._close_explorer_windows()

        procs = _find_processes(profile.process_names)
        if not procs:
            logger.info("  %s is not running.", display)
            return ToolResult(
                success=True,
                message="%s does not appear to be running." % display,
                data={"app_id": app_id, "action": "not_running"},
            )

        pids = {p.pid for p in procs}
        logger.info("  Found %d process(es) PIDs=%s", len(procs), pids)

        if force:
            return self._force_terminate(procs, display, app_id)

        windows = _get_windows_for_pids(pids)
        logger.info("  Sending WM_CLOSE to %d window(s).", len(windows))
        for hwnd in windows:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                logger.debug("    WM_CLOSE -> hwnd=0x%08x", hwnd)
            except Exception as exc:
                logger.debug("    WM_CLOSE failed hwnd=0x%08x: %s", hwnd, exc)

        deadline = time.monotonic() + GRACEFUL_TIMEOUT_S
        while time.monotonic() < deadline:
            if not _still_alive(profile.process_names):
                logger.info("  %s exited gracefully.", display)
                return ToolResult(
                    success=True,
                    message="%s has been closed." % display,
                    data={"app_id": app_id, "action": "graceful_close", "pids": list(pids)},
                )
            time.sleep(0.25)

        logger.warning(
            "  %s still running after %.1fs. Requesting confirmation.",
            display, GRACEFUL_TIMEOUT_S,
        )
        return ToolResult(
            success=False,
            message=(
                "%s is still running and did not close on its own. "
                "Should I force-close it? This may discard unsaved work." % display
            ),
            data={
                "app_id": app_id,
                "action": "needs_force_confirmation",
                "force_command": "FORCE_CLOSE:" + raw_text,
            },
        )

    @staticmethod
    def _close_explorer_windows() -> ToolResult:
        classes = ["CabinetWClass", "ExploreWClass"]
        windows = _get_windows_by_class(classes)
        if not windows:
            return ToolResult(
                success=True,
                message="No File Explorer windows are currently open.",
                data={"app_id": "file_explorer", "action": "not_running"},
            )
        closed = 0
        for hwnd in windows:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                closed += 1
                logger.debug("  WM_CLOSE -> Explorer hwnd=0x%08x", hwnd)
            except Exception as exc:
                logger.debug("  WM_CLOSE failed hwnd=0x%08x: %s", hwnd, exc)
        noun = "window" if closed == 1 else "windows"
        logger.info("  Closed %d File Explorer %s.", closed, noun)
        return ToolResult(
            success=True,
            message="Closed %d File Explorer %s." % (closed, noun),
            data={"app_id": "file_explorer", "action": "graceful_close", "windows": closed},
        )

    @staticmethod
    def _force_terminate(
        procs: List[psutil.Process], display: str, app_id: str
    ) -> ToolResult:
        killed: List[int] = []
        failed: List[int] = []
        for proc in procs:
            try:
                proc.terminate()
                killed.append(proc.pid)
                logger.warning("  FORCE_TERMINATED: %s PID=%d", display, proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                failed.append(proc.pid)
                logger.error("  Force-terminate failed PID=%d: %s", proc.pid, exc)
        if killed and not failed:
            return ToolResult(
                success=True,
                message="%s has been force-closed." % display,
                data={"app_id": app_id, "action": "force_terminated", "pids": killed},
            )
        if failed:
            return ToolResult(
                success=False,
                message=(
                    "I closed some %s processes but could not reach PID(s) %s. "
                    "You may need to close them manually." % (display, failed)
                ),
                data={"app_id": app_id, "action": "partial",
                      "killed": killed, "failed": failed},
            )
        return ToolResult(
            success=True,
            message="%s was already closed." % display,
            data={"app_id": app_id, "action": "already_gone"},
        )

    def _extract_app_name(self, raw_text: str) -> Optional[str]:
        cleaned = raw_text.lower().strip()
        for prefix in ["please ", "can you ", "could you "]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        for verb in sorted(_CLOSE_VERBS, key=len, reverse=True):
            if cleaned.startswith(verb + " "):
                cleaned = cleaned[len(verb):].strip()
                break
        for filler in ["please", "for me", "now", "app", "application"]:
            if cleaned.endswith(filler):
                cleaned = cleaned[: -len(filler)].strip()
        return cleaned if cleaned else None

    def _fuzzy_match(self, text: str) -> Optional[Tuple[str, LaunchProfile]]:
        from jarvis.utils import match_any_keyword
        for alias, entry in sorted(
            self._close_lookup.items(), key=lambda x: len(x[0]), reverse=True
        ):
            if match_any_keyword(text, [alias]):
                return entry
        return None

    def _available_list(self) -> str:
        seen: set = set()
        names: List[str] = []
        for app_id, profile in self._close_lookup.values():
            if app_id not in seen:
                seen.add(app_id)
                names.append(profile.display_name)
        return ", ".join(sorted(names)) if names else "none"
