"""AI overlay captions + music bed (offline: fallback captions, dry music)."""
from __future__ import annotations

from pathlib import Path

import pytest

from reelforge.core import media
from reelforge.core.profile import ContentProfile
from reelforge.core.types import Segment
from reelforge.ops import caption, build
from reelforge.ops import generate as G
from reelforge.flows import run_footage


# ---- caption ops ----

def test_fallback_lines_count():
    assert len(caption._fallback_lines(["faith", "peace"], 4)) == 4
    assert len(caption._fallback_lines([], 10)) == 10   # cycles if count > list


def test_ai_captions_fallback_without_key(ctx, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = caption.op_ai_captions(ctx, frames=[], themes=["biker life", "faith"], count=3)
    assert res.outputs["source"] == "fallback"
    assert len(res.outputs["lines"]) == 3


def test_extract_keyframes(ctx, sample_clip):
    res = caption.op_extract_keyframes(ctx, sample_clip, n=3)
    frames = res.outputs["frames"]
    assert len(frames) == 3
    for f in frames:
        assert Path(f).exists() and Path(f).stat().st_size > 0


# ---- centered caption style ----

def test_build_ass_centered_vs_bottom():
    from reelforge.core.types import Caption
    caps = [Caption(0.0, 2.0, "ride on")]
    centered = build.build_ass(caps, "reflective_center", 1080, 1920)
    bottom = build.build_ass(caps, "karaoke_bold", 1080, 1920)
    assert "WrapStyle: 0" in centered          # word-wrap on (was 2 = overflow)
    assert ",5," in centered                   # ASS middle-center alignment
    assert ",2," in bottom                     # bottom-center alignment
    assert "ride on" in centered


# ---- music bed mixer ----

def test_add_music_bed_keeps_audio(ctx, sample_clip):
    clip = build.op_cut(ctx, sample_clip, Segment(0.0, 4.0), name="c").outputs["clip"]
    musicf = G.op_gen_music(ctx, "reflective", 4.0).outputs["audio"]  # dry-run sine
    res = build.op_add_music_bed(ctx, clip, musicf, music_gain=0.8, source_gain=0.25)
    info = media.probe(res.outputs["path"])
    assert info.has_audio and info.duration_s > 0


# ---- end to end (fallback captions + dry music) ----

def test_footage_flow_with_captions_and_music(tmp_path, sample_clip, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    prof = ContentProfile(
        id="bike_ai", niche="cycling POV",
        source={"proxy_transcode": False},
        edit={"length_s": [2, 5], "clips_per_video": [1, 1],
              "captions": {"enabled": True, "source": "ai", "count": 3,
                           "keyframes": 2, "style": "reflective_center",
                           "themes": ["biker life", "faith", "peace"]},
              "music": {"enabled": True, "source": "fal", "mood": "lofi"},
              "color_grade": {"look": "vivid_action"}},
        publish={"approval": "auto"},
    )
    res = run_footage(sample_clip, prof, work_root=tmp_path / "w", auto_approve=True)
    assert res["status"] == "approved"
    info = media.probe(res["draft"])
    assert info.has_audio                         # music bed mixed in
    assert (info.width, info.height) == (1080, 1920)
    assert Path(res["draft"]).exists()
