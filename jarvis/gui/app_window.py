"""
Jarvis Desktop GUI -- Dynamic Holographic Video Interface.

Plays the Jarvis UI.mp4 video directly as the futuristic animated interface,
with real-time assistant controls, voice/text interaction, and responsive scaling.
"""

import datetime
import math
import os
import queue
import signal
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont

try:
    import win32com.client
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False

try:
    import win32api
    HAS_WIN32API = True
except ImportError:
    HAS_WIN32API = False

from jarvis.app import Jarvis
from jarvis.config import APP_NAME, WAKE_WORD
from jarvis.logger import get_logger

logger = get_logger(__name__)

# Global reference to active GUI for console Ctrl+C handling
_ACTIVE_GUI_INSTANCE: Optional["JarvisGUI"] = None

# Aesthetic Color Palette
BG            = "#010812"
ACCENT        = "#00C8FF"
ACCENT_BRIGHT = "#40DFFF"
ACCENT_DIM    = "#004A6E"
SPEAK_COLOR   = "#00FFCC"
THINK_COLOR   = "#A78BFA"
ERR_COLOR     = "#EF4444"
TEXT_WHITE    = "#FFFFFF"
TEXT_BLUE     = "#7ECBEA"
TEXT_DIM      = "#527599"
GLASS_BG      = "#051326"
GLASS_BORDER  = "#00C8FF"

USER_NAME = "Ashok"

ASSETS_DIR = Path(__file__).parent / "assets"

def _register_custom_fonts():
    """Register custom TTF fonts (e.g. Orbitron) into Windows process memory."""
    font_file = ASSETS_DIR / "Orbitron.ttf"
    if font_file.is_file():
        try:
            import ctypes
            ctypes.windll.gdi32.AddFontResourceExW(str(font_file.resolve()), 0x10, 0)
        except Exception as e:
            logger.debug("Could not register custom font: %s", e)

def _load_glass_fonts() -> dict:
    """Load fonts for liquid glass HUD: Century Gothic and Brush Script MT."""
    # 1. Century Gothic for clock & date
    candidates = [
        ("C:/Windows/Fonts/GOTHICB.TTF", "C:/Windows/Fonts/GOTHIC.TTF"),
        ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf"),
        ("C:/Windows/Fonts/bahnschrift.ttf", "C:/Windows/Fonts/bahnschrift.ttf"),
    ]
    ft, fd = ImageFont.load_default(), ImageFont.load_default()
    for time_p, date_p in candidates:
        if os.path.isfile(time_p) and os.path.isfile(date_p):
            try:
                ft = ImageFont.truetype(time_p, 36)
                fd = ImageFont.truetype(date_p, 11)
                break
            except Exception:
                continue

    # 2. Brush Script MT for speech bubble text
    f_script = ImageFont.load_default()
    brush_paths = [
        "C:/Windows/Fonts/BRUSHSCI.TTF",
        "C:/Windows/Fonts/brushsci.ttf",
    ]
    for bp in brush_paths:
        if os.path.isfile(bp):
            try:
                f_script = ImageFont.truetype(bp, 26)
                break
            except Exception:
                continue

    # 3. Tag font for sender (GOTHICB / Segoe UI)
    f_tag = fd
    if os.path.isfile("C:/Windows/Fonts/GOTHICB.TTF"):
        try:
            f_tag = ImageFont.truetype("C:/Windows/Fonts/GOTHICB.TTF", 12)
        except Exception:
            pass

    return {
        "time": ft,
        "sub": fd,
        "script": f_script,
        "tag": f_tag,
    }

def _resolve_video_paths() -> dict:
    """
    Locates the 3 interface videos:
      - intro: Jarvis UA.mp4 / Jarvis ui.mp4 (startup intro, plays once)
      - mid:   mid_1080p_20261027221621.mp4 (plays in continuous loop after intro)
      - end:   end_1080p_20261027221814.mp4 (plays once on Ctrl+C / shutdown)
    """
    search_dirs = [
        Path.cwd(),
        Path(__file__).parent.parent.parent,
        ASSETS_DIR,
    ]

    def _find(names: List[str], patterns: List[str]) -> Optional[Path]:
        for d in search_dirs:
            if not d.is_dir():
                continue
            for n in names:
                p = d / n
                if p.is_file():
                    return p.resolve()
            for pat in patterns:
                matches = list(d.glob(pat))
                if matches and matches[0].is_file():
                    return matches[0].resolve()
        return None

    intro = _find(
        ["Jarvis ui.mp4", "Jarvis UA.mp4", "Jarvis UI.mp4", "jarvis_ui.mp4"],
        ["*jarvis*ui*.mp4", "*Jarvis*UA*.mp4", "*jarvis*ua*.mp4"],
    )
    mid = _find(
        ["mid_1080p_20261027221621.mp4", "mid_1080_20261027221621.mp4"],
        ["mid_1080*.mp4", "*mid*.mp4"],
    )
    end = _find(
        ["end_1080p_20261027221814.mp4", "end_1080_20261027221814.mp4"],
        ["end_1080*.mp4", "*end*.mp4"],
    )

    return {
        "intro": intro,
        "mid": mid,
        "end": end,
    }


VIDEO_PATHS = _resolve_video_paths()
VIDEO_PATH = VIDEO_PATHS.get("intro") or VIDEO_PATHS.get("mid")


def _make_state_styles():
    return {
        "idle":       (ACCENT_DIM,   "Standby"),
        "wake_word":  (ACCENT_DIM,   f'Say "{WAKE_WORD}"'),
        "activated":  (ACCENT_BRIGHT,"Activated -- Speak now"),
        "listening":  (ACCENT_BRIGHT,"Listening..."),
        "processing": (THINK_COLOR,  "Thinking..."),
        "thinking":   (THINK_COLOR,  "Thinking..."),
        "speaking":   (SPEAK_COLOR,  "Speaking..."),
        "paused":     (ACCENT_DIM,   "Microphone Paused"),
        "stopped":    (ACCENT_DIM,   "Offline"),
        "error":      (ERR_COLOR,    "Error"),
        "executing":  (ACCENT_BRIGHT,"Executing..."),
    }

STATE_STYLES = _make_state_styles()


class VideoBackgroundEngine:
    """
    Decodes and streams the Jarvis 3-phase video interface in a high-priority background thread:
      1. Intro Phase: Plays Jarvis UI.mp4 (or Jarvis UA.mp4) once from beginning to end.
      2. Mid Phase: Automatically switches to mid_1080p_20261027221621.mp4 and loops seamlessly as the ambient interface.
      3. End Phase: When Ctrl+C / shutdown is triggered, switches to end_1080p_20261027221814.mp4 and plays once to completion.
    Synchronizes audio via WMP across all three phases.
    """
    PHASE_INTRO = "intro"
    PHASE_MID   = "mid"
    PHASE_END   = "end"

    def __init__(
        self,
        intro_path: Optional[Path] = None,
        mid_path: Optional[Path] = None,
        end_path: Optional[Path] = None,
    ):
        self.intro_path = Path(intro_path) if intro_path else None
        self.mid_path   = Path(mid_path) if mid_path else None
        self.end_path   = Path(end_path) if end_path else None

        self.running           = False
        self._thread           = None
        self._lock             = threading.Lock()

        self._latest_pil       = None
        self._frame_id         = 0
        self._target_size      = (1200, 750)

        # Video phase state
        self.current_phase     = self.PHASE_INTRO if (self.intro_path and self.intro_path.is_file()) else self.PHASE_MID
        self._switch_requested = None
        self._is_completed     = False
        self._on_end_callback  = None

        # Audio controller
        self._wmp              = None
        self._is_muted         = False
        self._volume           = 25  # pleasant ambient volume

        # Thread-safe audio request queue:
        # Worker thread posts (path, loop) here; main thread flushes via flush_pending_audio().
        self._audio_queue      = queue.Queue()

    def set_target_size(self, width: int, height: int):
        if width > 50 and height > 50:
            with self._lock:
                self._target_size = (width, height)

    def set_on_end_callback(self, callback):
        """Set callback to be executed when the end video finishes playback."""
        with self._lock:
            self._on_end_callback = callback

    def has_end_video(self) -> bool:
        return self.end_path is not None and self.end_path.is_file()

    @property
    def is_completed(self) -> bool:
        with self._lock:
            return self._is_completed

    def play_end(self):
        """Request immediate transition to the ending shutdown video."""
        with self._lock:
            self._switch_requested = self.PHASE_END

    def start(self):
        if self.running:
            return
        self.running = True
        self._is_completed = False
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        initial_path = self.intro_path if (self.intro_path and self.intro_path.is_file()) else self.mid_path
        if initial_path:
            self._play_audio(initial_path, loop=(initial_path != self.intro_path))

    def _play_audio(self, video_path: Optional[Path], loop: bool = False):
        if not HAS_WIN32COM or not video_path or not video_path.is_file():
            return
        try:
            if not self._wmp:
                self._wmp = win32com.client.Dispatch("WMPlayer.OCX")
            self._wmp.settings.autoStart = True
            self._wmp.settings.setMode("loop", loop)
            self._wmp.settings.volume = self._volume
            self._wmp.settings.mute = self._is_muted
            self._wmp.URL = str(video_path.resolve())
        except Exception as e:
            logger.warning("Could not initialize WMP audio for %s: %s", video_path, e)
            self._wmp = None

    def toggle_mute(self) -> bool:
        """Toggle audio mute. Returns True if now muted, False if unmuted."""
        self._is_muted = not self._is_muted
        if self._wmp:
            try:
                self._wmp.settings.mute = self._is_muted
            except Exception:
                pass
        return self._is_muted

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    def flush_pending_audio(self):
        """Drain the audio request queue and apply changes.

        MUST be called from the main (tkinter) thread so that WMP COM object
        is always driven from the thread that created it (COM STA requirement).
        """
        try:
            while True:
                video_path, loop = self._audio_queue.get_nowait()
                self._play_audio(video_path, loop)
        except queue.Empty:
            pass

    def _worker(self):
        active_path = self.intro_path if (self.intro_path and self.intro_path.is_file()) else self.mid_path
        if not active_path or not active_path.is_file():
            logger.warning("No valid interface video file found.")
            return

        current_phase = self.PHASE_INTRO if active_path == self.intro_path else self.PHASE_MID
        cap = cv2.VideoCapture(str(active_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_interval = 1.0 / fps

        logger.info("Video engine started: playing %s (%s) at %.1f FPS", current_phase, active_path.name, fps)

        while self.running:
            # Check for phase switch requests (e.g. switch to END on Ctrl+C)
            with self._lock:
                req = self._switch_requested
                self._switch_requested = None

            if req == self.PHASE_END and self.end_path and self.end_path.is_file():
                if current_phase != self.PHASE_END:
                    logger.info("Switching to END video: %s", self.end_path.name)
                    cap.release()
                    current_phase = self.PHASE_END
                    active_path = self.end_path
                    cap = cv2.VideoCapture(str(active_path))
                    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                    frame_interval = 1.0 / fps
                    # Signal main thread to switch audio (COM STA: WMP must be driven from main thread)
                    self._audio_queue.put((active_path, False))

            t_start = time.perf_counter()
            ret, frame = cap.read()

            if not ret:
                if current_phase == self.PHASE_INTRO:
                    # Intro video finished! Transition to mid video:
                    if self.mid_path and self.mid_path.is_file():
                        logger.info(
                            "Intro video (%s) finished. Transitioning to mid video (%s)",
                            active_path.name, self.mid_path.name
                        )
                        cap.release()
                        current_phase = self.PHASE_MID
                        active_path = self.mid_path
                        cap = cv2.VideoCapture(str(active_path))
                        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                        frame_interval = 1.0 / fps
                        # Signal main thread to switch audio (COM STA safety)
                        self._audio_queue.put((active_path, True))
                        ret, frame = cap.read()
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()

                elif current_phase == self.PHASE_MID:
                    # Re-open the cap for a seamless loop.
                    # cap.set(POS_FRAMES, 0) is unreliable with H.264 and can stall the decoder.
                    cap.release()
                    cap = cv2.VideoCapture(str(active_path))
                    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                    frame_interval = 1.0 / fps
                    ret, frame = cap.read()

                elif current_phase == self.PHASE_END:
                    # End video finished!
                    logger.info("End video (%s) completed playback.", active_path.name)
                    with self._lock:
                        self._is_completed = True
                    break

            if not ret or frame is None:
                time.sleep(0.015)
                continue

            with self._lock:
                tw, th = self._target_size

            # Fast hardware-accelerated bilinear resize
            resized = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            with self._lock:
                self._latest_pil = pil_img
                self._frame_id += 1
                self.current_phase = current_phase

            elapsed = time.perf_counter() - t_start
            delay = frame_interval - elapsed
            if delay > 0:
                time.sleep(delay)

        cap.release()
        with self._lock:
            self._is_completed = True
        logger.info("Video engine worker terminated.")

        if self._on_end_callback:
            try:
                self._on_end_callback()
            except Exception as e:
                logger.error("Error executing on_end_callback: %s", e)

    def get_latest_frame(self) -> Tuple[int, Optional[Image.Image]]:
        with self._lock:
            return self._frame_id, self._latest_pil

    def stop(self):
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        if self._wmp:
            try:
                self._wmp.controls.stop()
                self._wmp.close()
            except Exception:
                pass
            self._wmp = None


class JarvisGUI:
    """
    Jarvis Desktop GUI with Jarvis UI.mp4 video interface and interactive assistant overlay.
    """
    POLL_MS       = 50
    FRAME_POLL_MS = 15  # ~60 Hz check for 30 FPS video frames

    def __init__(self, assistant=None, root=None):
        self.assistant = assistant or Jarvis()
        self.root      = root or tk.Tk()

        self._event_queue   = queue.Queue()
        self._bg_thread     = None

        self._listening_state = "idle"
        self._ring_color    = ACCENT_DIM
        self._state_text    = "Standby"
        self._messages: List[Tuple[str, str]] = []

        # Video Engine & HUD State
        self._video_engine   = None
        self._displayed_fid  = -1
        self._current_photo  = None
        self._canvas_img_id  = None
        self._last_render_time = 0.0
        self._glass_fonts    = _load_glass_fonts()

        # Liquid Glass Speech bubble state
        self._active_speech    = ("JARVIS", f'Jarvis is online with AI brain active. Say "{WAKE_WORD}" to get my attention.')
        self._speech_hide_time = time.time() + 10.0

        self._fullscreen     = False
        self._shutting_down  = False

        self._setup_window()
        self._setup_fonts()
        self._build_canvas()
        self._build_hud_overlay()
        self._bind_events()
        self._init_video_engine()
        self._sync_initial_states()
        self._setup_ctrl_handlers()

        self.root.after(self.POLL_MS, self._poll_events)
        self.root.after(self.FRAME_POLL_MS, self._render_video_frame)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_window(self):
        self.root.title(APP_NAME + " -- Personal AI Assistant")
        self.root.configure(bg=BG)
        self.root.geometry("1200x750")
        self.root.minsize(900, 560)
        self.root.bind("<F11>",    self._toggle_fullscreen)
        self.root.bind("<Escape>", self._exit_fullscreen)
        self.root.bind("<space>",  lambda _: self._toggle_listening())

    def _setup_fonts(self):
        _register_custom_fonts()
        self.f_btn = tkfont.Font(family="Segoe UI", size=12)

    def _build_canvas(self):
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

    def _init_video_engine(self):
        video_paths = _resolve_video_paths()
        intro = video_paths.get("intro")
        mid = video_paths.get("mid")
        end = video_paths.get("end")

        logger.info(
            "Initializing Jarvis Video Engine: intro=%s, mid=%s, end=%s",
            intro.name if intro else None,
            mid.name if mid else None,
            end.name if end else None,
        )

        if intro or mid:
            self._video_engine = VideoBackgroundEngine(intro, mid, end)
            self._video_engine.set_target_size(1200, 750)
            self._video_engine.set_on_end_callback(self._on_end_video_finished)
            self._video_engine.start()
        else:
            logger.warning("Jarvis UI video not found, falling back to static background.")

    def _build_hud_overlay(self):
        """Top right minimal window controls (Mute, Fullscreen)."""
        self._ctrl_frame = tk.Frame(self.root, bg=BG)
        self._ctrl_frame.place(relx=1.0, x=-20, y=14, anchor="ne")

        self._btn_mute = tk.Button(
            self._ctrl_frame, text="\U0001F50A",
            font=self.f_btn, bg=BG, fg=TEXT_BLUE,
            activebackground=BG, activeforeground=ACCENT_BRIGHT,
            relief="flat", bd=0, highlightthickness=0, cursor="hand2",
            command=self._toggle_audio_mute
        )
        self._btn_mute.pack(side=tk.LEFT, padx=5)

        self._btn_fs = tk.Button(
            self._ctrl_frame, text="\u26F6",
            font=self.f_btn, bg=BG, fg=TEXT_BLUE,
            activebackground=BG, activeforeground=ACCENT_BRIGHT,
            relief="flat", bd=0, highlightthickness=0, cursor="hand2",
            command=self._toggle_fullscreen
        )
        self._btn_fs.pack(side=tk.LEFT, padx=5)

    def _draw_liquid_glass_badge(
        self, w: int, h: int, time_str: str, date_str: str, status_str: str, phase: float
    ) -> Image.Image:
        """Renders an authentic liquid glassmorphic HUD card with dynamic shimmer and glow."""
        badge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)
        radius = 20

        # 1. Translucent frosted obsidian glass base
        draw.rounded_rectangle([0, 0, w, h], radius=radius, fill=(4, 15, 32, 145))

        # 2. Breathing liquid cyan glow border
        pulse = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
        border_alpha = int(140 + 80 * pulse)
        border_color = (0, 210, 255, border_alpha)
        draw.rounded_rectangle([0, 0, w, h], radius=radius, outline=border_color, width=2)

        # 3. Specular curved glass gloss reflection on top half
        draw.rounded_rectangle([2, 2, w - 2, int(h * 0.46)], radius=radius - 2, fill=(255, 255, 255, 18))

        # 4. Animated liquid shimmer light sweep
        shimmer_mask = Image.new("L", (w, h), 0)
        sdraw = ImageDraw.Draw(shimmer_mask)
        sweep_x = int((w + 240) * (phase % 1.0) - 120)
        for offset in range(-28, 29):
            alpha_val = int(85 * (1.0 - abs(offset) / 28.0))
            sdraw.line([(sweep_x + offset, 0), (sweep_x + offset - 40, h)], fill=alpha_val, width=2)

        shimmer = Image.new("RGBA", (w, h), (140, 235, 255, 0))
        shimmer.putalpha(shimmer_mask)
        badge = Image.alpha_composite(badge, shimmer)
        draw = ImageDraw.Draw(badge)

        # 5. Crisp Century Gothic typography
        font_time = self._glass_fonts["time"]
        font_sub = self._glass_fonts["sub"]

        # Time text (Centered)
        bbox_t = draw.textbbox((0, 0), time_str, font=font_time)
        tw = bbox_t[2] - bbox_t[0]
        tx = (w - tw) // 2
        ty = 12

        # Glowing sapphire shadow for depth
        draw.text((tx + 1, ty + 1), time_str, font=font_time, fill=(0, 60, 100, 140))
        draw.text((tx, ty), time_str, font=font_time, fill=(255, 255, 255, 250))

        # Sub line: DATE  ●  STATUS
        sub_text = f"{date_str}   \u25cf   {status_str.upper()}"
        bbox_s = draw.textbbox((0, 0), sub_text, font=font_sub)
        sw = bbox_s[2] - bbox_s[0]
        sx = (w - sw) // 2
        sy = ty + (bbox_t[3] - bbox_t[1]) + 13

        draw.text((sx, sy), sub_text, font=font_sub, fill=(126, 203, 234, 235))
        return badge

    def _draw_liquid_glass_speech(
        self, sender: str, text: str, phase: float, max_w: int = 740
    ) -> Image.Image:
        """Renders an authentic liquid glass conversation bubble using the requested Brush Script MT font."""
        font_tag = self._glass_fonts.get("tag", self._glass_fonts["sub"])
        font_txt = self._glass_fonts.get("script", self._glass_fonts["time"])

        # Word wrap text to fit comfortably within max_w
        words = text.split(" ")
        lines = []
        cur_line = []
        dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        for w in words:
            test_line = " ".join(cur_line + [w])
            bbox = dummy.textbbox((0, 0), test_line, font=font_txt)
            if bbox[2] - bbox[0] > (max_w - 70):
                if cur_line:
                    lines.append(" ".join(cur_line))
                    cur_line = [w]
                else:
                    lines.append(w)
                    cur_line = []
            else:
                cur_line.append(w)
        if cur_line:
            lines.append(" ".join(cur_line))

        line_h = 32
        text_total_h = max(line_h, len(lines) * line_h)
        longest_line_w = max((dummy.textbbox((0, 0), l, font=font_txt)[2] - dummy.textbbox((0, 0), l, font=font_txt)[0]) for l in lines) if lines else 200
        card_w = min(max_w, max(380, longest_line_w + 70))
        card_h = 34 + text_total_h + 16

        badge = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)
        radius = 20

        # 1. Translucent frosted obsidian glass base
        draw.rounded_rectangle([0, 0, card_w, card_h], radius=radius, fill=(4, 15, 32, 150))

        # 2. Breathing liquid cyan glow border
        pulse = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
        border_alpha = int(140 + 80 * pulse)
        border_color = (0, 210, 255, border_alpha)
        draw.rounded_rectangle([0, 0, card_w, card_h], radius=radius, outline=border_color, width=2)

        # 3. Specular curved glass gloss reflection on top
        draw.rounded_rectangle([2, 2, card_w - 2, int(card_h * 0.44)], radius=radius - 2, fill=(255, 255, 255, 16))

        # 4. Animated liquid shimmer light sweep
        shimmer_mask = Image.new("L", (card_w, card_h), 0)
        sdraw = ImageDraw.Draw(shimmer_mask)
        sweep_x = int((card_w + 240) * (phase % 1.0) - 120)
        for offset in range(-28, 29):
            alpha_val = int(75 * (1.0 - abs(offset) / 28.0))
            sdraw.line([(sweep_x + offset, 0), (sweep_x + offset - 40, card_h)], fill=alpha_val, width=2)

        shimmer = Image.new("RGBA", (card_w, card_h), (140, 235, 255, 0))
        shimmer.putalpha(shimmer_mask)
        badge = Image.alpha_composite(badge, shimmer)
        draw = ImageDraw.Draw(badge)

        # Sender tag (Cyan)
        draw.text((28, 12), sender.upper(), font=font_tag, fill=(0, 210, 255, 240))

        # Message text in Brush Script MT (White with soft drop shadow)
        curr_y = 36
        for l in lines:
            draw.text((29, curr_y + 1), l, font=font_txt, fill=(0, 50, 90, 160))
            draw.text((28, curr_y), l, font=font_txt, fill=(255, 255, 255, 255))
            curr_y += line_h

        return badge

    def _apply_liquid_glass_hud(self, frame_pil: Image.Image, phase: float) -> Image.Image:
        """Places the liquid glass date and time HUD on the right side and speech bubble at bottom."""
        w, h = frame_pil.size

        # 1. Date & Time liquid glass badge on right side
        badge_w = min(310, max(240, int(w * 0.26)))
        badge_h = min(95, max(75, int(h * 0.13)))
        badge_x = int(w * 0.66)
        badge_y = max(18, int(h * 0.08))
        if badge_x + badge_w > w - 15:
            badge_x = w - badge_w - 20

        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%a, %d %b").upper()

        time_badge = self._draw_liquid_glass_badge(badge_w, badge_h, time_str, date_str, self._state_text, phase)
        frame_pil.paste(time_badge, (badge_x, badge_y), time_badge)

        # 2. Speech bubble liquid glass card with Brush Script MT
        if self._active_speech and time.time() < self._speech_hide_time:
            sender, text = self._active_speech
            if text:
                max_bubble_w = min(740, int(w * 0.75))
                speech_badge = self._draw_liquid_glass_speech(sender, text, phase, max_bubble_w)
                bx = (w - speech_badge.size[0]) // 2
                by = max(int(h * 0.74), h - speech_badge.size[1] - 25)
                frame_pil.paste(speech_badge, (bx, by), speech_badge)

        return frame_pil

    def _render_single_frame(self):
        """Pulls the latest frame from the video engine, composites liquid glass HUD, and displays."""
        if not self.root.winfo_exists() or not self._video_engine:
            return

        fid, pil_img = self._video_engine.get_latest_frame()
        if pil_img is not None:
            anim_phase = (time.perf_counter() * 0.32) % 1.0
            now = time.perf_counter()
            if fid != self._displayed_fid or (now - self._last_render_time) >= 0.033:
                self._displayed_fid = fid
                self._last_render_time = now
                try:
                    frame_with_hud = self._apply_liquid_glass_hud(pil_img.copy(), anim_phase)
                    self._current_photo = ImageTk.PhotoImage(frame_with_hud)
                    if self._canvas_img_id is None:
                        self._canvas_img_id = self.canvas.create_image(
                            0, 0, image=self._current_photo, anchor="nw", tags="video"
                        )
                    else:
                        self.canvas.itemconfig(self._canvas_img_id, image=self._current_photo)
                except Exception as e:
                    logger.debug("Frame render error: %s", e)

    def _render_video_frame(self):
        """Periodic timer polling frames from VideoBackgroundEngine and rendering them to canvas."""
        self._render_single_frame()
        # Keep scheduling as long as the window exists — even during shutdown so the
        # end video keeps playing.  The loop stops naturally when force_exit() destroys
        # the window or the callback raises an exception.
        if self.root.winfo_exists():
            self.root.after(self.FRAME_POLL_MS, self._render_video_frame)

    def _on_resize(self, event):
        w, h = event.width, event.height
        if w < 50 or h < 50:
            return

        if self._video_engine:
            self._video_engine.set_target_size(w, h)

    def _toggle_audio_mute(self):
        if self._video_engine:
            is_muted = self._video_engine.toggle_mute()
            self._btn_mute.configure(text="\U0001F507" if is_muted else "\U0001F50A")

    def _toggle_fullscreen(self, _=None):
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)

    def _exit_fullscreen(self, _=None):
        self._fullscreen = False
        self.root.attributes("-fullscreen", False)

    def _bind_events(self):
        self.assistant.on("message",         self._q_message)
        self.assistant.on("status",          self._q_status)
        self.assistant.on("listening_state", self._q_listening)

    def _q_message(self, sender, text):
        self._event_queue.put(("message", (sender, text)))

    def _q_status(self, subsystem, state):
        self._event_queue.put(("status", (subsystem, state)))

    def _q_listening(self, state):
        self._event_queue.put(("listening", (state,)))

    def _poll_events(self):
        try:
            while not self._event_queue.empty():
                kind, args = self._event_queue.get_nowait()
                if   kind == "message":   self._on_message(*args)
                elif kind == "status":    self._on_status(*args)
                elif kind == "listening": self._on_listening(*args)
        except Exception as e:
            logger.error("GUI poll error: %s", e)
        finally:
            # Always keep polling — even during shutdown — so that pending audio
            # requests from the worker thread (mid-loop, end-video switch) are
            # flushed promptly from the main thread (COM STA requirement).
            if self.root.winfo_exists():
                if self._video_engine:
                    self._video_engine.flush_pending_audio()
                self.root.after(self.POLL_MS, self._poll_events)

    def _on_listening(self, state):
        self._listening_state = state
        style = STATE_STYLES.get(state.lower(), STATE_STYLES["idle"])
        self._ring_color  = style[0]
        self._state_text  = style[1]

    def _on_status(self, subsystem, state):
        logger.debug("Status: %s -> %s", subsystem, state)

    def _on_message(self, sender, text):
        sender_lower = sender.lower()
        self._messages.append((sender_lower, text))
        is_user = (sender_lower == "user")
        tag = "YOU" if is_user else APP_NAME.upper()

        self._active_speech = (tag, text)
        self._speech_hide_time = time.time() + 10.0

        if not is_user:
            self._on_listening("speaking")

    def _hide_bubble(self):
        self._active_speech = None

    def _toggle_listening(self):
        if self.assistant.is_listening:
            self.assistant.stop_listening()
            self._on_listening("paused")
        else:
            self.assistant.start_listening()
            self._on_listening("activated")

    def _sync_initial_states(self):
        if not getattr(self.assistant, "_listening", True):
            self._on_listening("paused")
        elif getattr(self.assistant, "wake_detector", None):
            self._on_listening("wake_word")
        else:
            self._on_listening("idle")

    def _setup_ctrl_handlers(self):
        """Register console control handler and Python signal handler to catch Ctrl+C in terminal."""
        global _ACTIVE_GUI_INSTANCE
        _ACTIVE_GUI_INSTANCE = self

        if HAS_WIN32API:
            def _console_ctrl_handler(ctrl_type):
                # 0 = CTRL_C_EVENT, 1 = CTRL_BREAK_EVENT, 2 = CTRL_CLOSE_EVENT
                if ctrl_type in (0, 1, 2):
                    print("\n[Ctrl+C received in terminal - Playing shutdown sequence...]", flush=True)
                    logger.info("Console Ctrl+C received (type=%s). Initiating shutdown.", ctrl_type)
                    if self._shutting_down:
                        print("[Immediate exit requested]", flush=True)
                        os._exit(0)
                    else:
                        try:
                            self.root.after(0, self.trigger_shutdown)
                        except Exception:
                            self.trigger_shutdown()
                    return True
            try:
                win32api.SetConsoleCtrlHandler(_console_ctrl_handler, True)
                self._win32_ctrl_handler = _console_ctrl_handler
            except Exception as e:
                logger.debug("Could not set win32 console ctrl handler: %s", e)

        try:
            def _sigint_handler(sig, frame):
                print("\n[SIGINT / Ctrl+C detected - Playing shutdown sequence...]", flush=True)
                if self._shutting_down:
                    print("[Immediate exit requested]", flush=True)
                    os._exit(0)
                else:
                    try:
                        self.root.after(0, self.trigger_shutdown)
                    except Exception:
                        self.trigger_shutdown()
            signal.signal(signal.SIGINT, _sigint_handler)
        except Exception as e:
            logger.debug("Could not set SIGINT signal handler: %s", e)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def trigger_shutdown(self, force: bool = False):
        """Initiate graceful shutdown: play end video, update HUD, then cleanly exit."""
        if self._shutting_down:
            if force:
                self.force_exit()
            return

        self._shutting_down = True
        logger.info("Initiating graceful shutdown sequence with end video...")

        # 1. Stop assistant listening and microphone immediately
        try:
            self.assistant.stop_listening()
            self.assistant.stop()
        except Exception as e:
            logger.debug("Error stopping assistant during shutdown: %s", e)

        # 2. Update HUD display to shutdown state
        self._state_text = "Shutting Down"
        self._ring_color = ERR_COLOR
        self._active_speech = ("JARVIS", "Shutting down systems. Goodbye, Ashok.")
        self._speech_hide_time = time.time() + 60.0

        # 3. Transition video engine to the end video
        if self._video_engine and self._video_engine.has_end_video():
            self._video_engine.play_end()
        else:
            self.root.after(200, self.force_exit)

    def _on_end_video_finished(self):
        """Callback invoked when end_1080p_20261027221814.mp4 completes playback."""
        logger.info("End video completed. Closing GUI window.")
        try:
            self.root.after(100, self.force_exit)
        except Exception:
            self.force_exit()

    def force_exit(self):
        """Clean up all resources and close the application."""
        logger.info("Closing Jarvis GUI and terminating.")
        if self._video_engine:
            try:
                self._video_engine.stop()
            except Exception:
                pass
        try:
            self.assistant.stop()
        except Exception:
            pass
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def wait_for_shutdown(self, timeout: float = 15.0):
        """Pump GUI updates until the shutdown video finishes playing if mainloop was interrupted."""
        start_t = time.time()
        while self._shutting_down and (time.time() - start_t < timeout):
            if not self.root.winfo_exists():
                break
            if self._video_engine and self._video_engine.is_completed:
                break
            try:
                self._render_single_frame()
                self.root.update_idletasks()
                self.root.update()
            except Exception:
                break
            time.sleep(0.015)
        self.force_exit()

    def start_assistant(self):
        self._bg_thread = self.assistant.start_background()

    def run(self):
        self.start_assistant()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            print("\n[Ctrl+C caught in mainloop - Playing shutdown sequence...]", flush=True)
            self.trigger_shutdown()
            self.wait_for_shutdown()

    def on_close(self):
        if not self._shutting_down:
            print("\n[Window close requested - Playing shutdown sequence...]", flush=True)
            self.trigger_shutdown()
        else:
            self.force_exit()


def launch_gui(assistant=None):
    app = JarvisGUI(assistant=assistant)
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n[Ctrl+C caught in launch_gui - Playing shutdown sequence...]", flush=True)
        app.trigger_shutdown()
        app.wait_for_shutdown()

