"""Build ops: selection logic, ASS generation, and ffmpeg editing."""
from __future__ import annotations

from pathlib import Path

from reelforge.core.profile import ContentProfile
from reelforge.core import media
from reelforge.core.types import Caption, Highlight, Segment
from reelforge.ops import build


# ---- pure logic ----

def test_select_clips_hook_first(ctx):
    prof = ContentProfile(id="t", edit={"length_s": [2, 6], "clips_per_video": [1, 2],
                                        "hook_first": True})
    hi = [Highlight(10.0, 30.0, 0.9), Highlight(1.0, 3.0, 0.7), Highlight(40.0, 42.0, 0.3)]
    segs = build.op_select_clips(ctx, hi, prof).outputs["segments"]
    assert len(segs) == 2                     # capped at clips_per_video max
    assert segs[0].start_s == 10.0            # highest score first (hook_first)
    assert all(2.0 <= s.duration <= 6.0 + 1e-6 for s in segs)  # clamped to length_s


def test_select_clips_chronological(ctx):
    prof = ContentProfile(id="t", edit={"length_s": [2, 6], "clips_per_video": [1, 3],
                                        "hook_first": False})
    hi = [Highlight(10.0, 13.0, 0.9), Highlight(1.0, 3.0, 0.7)]
    segs = build.op_select_clips(ctx, hi, prof).outputs["segments"]
    assert [s.start_s for s in segs] == [1.0, 10.0]


def test_select_clips_max_total_cap(ctx):
    # two 6s clips = 12s, but the cap trims the total to 8s
    prof = ContentProfile(id="t", edit={"length_s": [6, 6], "clips_per_video": [1, 2],
                                        "hook_first": False, "max_total_s": 8.0})
    hi = [Highlight(0.0, 6.0, 0.9), Highlight(20.0, 26.0, 0.8)]
    segs = build.op_select_clips(ctx, hi, prof).outputs["segments"]
    total = sum(s.duration for s in segs)
    assert total <= 8.0 + 1e-6
    assert len(segs) >= 1


def test_build_ass():
    caps = [Caption(0.0, 1.5, "hello"), Caption(1.5, 3.0, "world")]
    ass = build.build_ass(caps, "karaoke_bold", 1080, 1920)
    assert "[Script Info]" in ass and "[V4+ Styles]" in ass and "[Events]" in ass
    assert ass.count("Dialogue:") == 2
    assert "hello" in ass and "world" in ass
    assert "0:00:00.00" in ass  # formatted start of first cue


# ---- ffmpeg editing (need ffmpeg) ----

def test_cut(ctx, sample_clip):
    res = build.op_cut(ctx, sample_clip, Segment(1.0, 4.0), name="c0")
    clip = res.outputs["clip"]
    assert Path(clip).exists()
    dur = media.probe(clip).duration_s
    assert 2.5 <= dur <= 3.6


def test_reframe_exact_dims(ctx, sample_clip):
    res = build.op_reframe(ctx, sample_clip, (216, 384))
    info = media.probe(res.outputs["path"])
    assert (info.width, info.height) == (216, 384)


def test_color_grade_valid(ctx, sample_clip):
    for look in ("teal_orange_punch", "vivid_action", "none", "unknown_look"):
        res = build.op_color_grade(ctx, sample_clip, look)
        assert media.probe(res.outputs["path"]).duration_s > 0


def test_captions_graceful_passthrough(ctx, sample_clip):
    res = build.op_captions(ctx, sample_clip)
    assert res.outputs["captioned"] is False       # no faster-whisper installed
    assert media.probe(res.outputs["path"]).duration_s > 0


def test_render_concat(ctx, sample_clip):
    a = build.op_cut(ctx, sample_clip, Segment(0.0, 2.0), name="a").outputs["clip"]
    b = build.op_cut(ctx, sample_clip, Segment(2.0, 4.0), name="b").outputs["clip"]
    draft = build.op_render(ctx, [a, b], name="d").outputs["draft"]
    assert Path(draft).exists()
    assert media.probe(draft).duration_s >= 3.0
