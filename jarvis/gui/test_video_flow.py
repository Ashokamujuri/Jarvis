import pytest
from pathlib import Path
from jarvis.gui.app_window import _resolve_video_paths, VideoBackgroundEngine

def test_resolve_video_paths():
    paths = _resolve_video_paths()
    assert "intro" in paths
    assert "mid" in paths
    assert "end" in paths

    intro = paths["intro"]
    mid = paths["mid"]
    end = paths["end"]

    assert intro is not None and intro.is_file(), f"Intro video not found: {intro}"
    assert mid is not None and mid.is_file(), f"Mid video not found: {mid}"
    assert end is not None and end.is_file(), f"End video not found: {end}"

    assert "ui" in intro.name.lower() or "ua" in intro.name.lower()
    assert "mid" in mid.name.lower()
    assert "end" in end.name.lower()

def test_video_engine_phases():
    paths = _resolve_video_paths()
    engine = VideoBackgroundEngine(paths["intro"], paths["mid"], paths["end"])

    assert engine.current_phase == VideoBackgroundEngine.PHASE_INTRO
    assert engine.has_end_video() is True
    assert engine.is_completed is False

    engine.play_end()
    assert engine._switch_requested == VideoBackgroundEngine.PHASE_END
