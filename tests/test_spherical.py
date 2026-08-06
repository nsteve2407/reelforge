"""360 routing: .insv detection + non-360 passthrough (ffmpeg-dependent bits skip)."""
from __future__ import annotations

from reelforge.ops import spherical as S


def test_is_360_by_extension():
    # extension check is pure — no ffprobe needed
    assert S.is_360("ride_VID_00_001.insv") is True
    assert S.is_360("/media/cam/CLIP.INSV") is True


def test_reframe_if_360_passthrough_for_flat(ctx, sample_clip):
    # a normal single-stream mp4 is not 360 -> returned unchanged, no reframe work
    out = S.reframe_if_360(ctx, sample_clip, w=1080, h=1920)
    assert out == str(sample_clip)


def test_flat_mp4_not_360(ctx, sample_clip):
    assert S.is_360(sample_clip) is False
    assert S.video_stream_count(sample_clip) == 1
