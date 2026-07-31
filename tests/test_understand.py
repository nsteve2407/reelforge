"""Understand ops: pure fusion helpers + real multi-signal detection."""
from __future__ import annotations

import numpy as np

from reelforge.core import media
from reelforge.core.types import Highlight, MediaInfo, SignalTrack
from reelforge.ops import understand as U


# ---- pure helpers (no media) ----

def test_normalize():
    out = U._normalize(np.array([0.0, 5.0, 10.0]))
    assert out.min() == 0.0 and out.max() == 1.0
    assert np.allclose(U._normalize(np.array([3.0, 3.0, 3.0])), 0.0)  # constant -> zeros


def test_gforce_from_accel():
    mags = U.gforce_from_accel(np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 2.0]]))
    assert mags[0] == 5.0 and mags[1] == 2.0


def test_soft_nms_removes_overlap():
    a = Highlight(0.0, 5.0, 1.0)      # winner
    b = Highlight(1.0, 6.0, 0.9)      # heavily overlaps a -> should be dropped
    c = Highlight(20.0, 25.0, 0.8)    # disjoint -> kept
    kept = U._soft_nms([a, b, c])
    spans = {(h.start_s, h.end_s) for h in kept}
    assert (0.0, 5.0) in spans and (20.0, 25.0) in spans
    assert (1.0, 6.0) not in spans


def test_resample_onto_grid():
    t = SignalTrack("x", [0.0, 10.0], [0.0, 10.0])
    grid = np.array([0.0, 5.0, 10.0])
    assert np.allclose(U._resample(t, grid), [0.0, 5.0, 10.0])


def test_fusion_finds_joint_peak(ctx):
    dur = 30.0
    # two signals both spiking around t=15s
    times = list(np.arange(0, dur, 0.5))
    def bump(center):
        return [float(np.exp(-((t - center) ** 2) / 8.0)) for t in times]
    tA = SignalTrack("motion", times, bump(15.0), weight=1.0)
    tB = SignalTrack("audio_energy", times, bump(15.0), weight=1.0)
    info = MediaInfo("x", dur, 1920, 1080, 30.0, True)
    hi = U.op_fuse_highlights(ctx, info, [tA, tB], min_len=4.0, max_len=10.0, top_k=3)
    hls = hi.outputs["highlights"]
    assert len(hls) >= 1
    top = hls[0]
    assert top.start_s <= 15.0 <= top.end_s        # window brackets the joint peak
    assert 4.0 - 1e-6 <= top.duration <= 10.0 + 1e-6


# ---- real signals on the synth clip ----

def test_signal_ops_on_clip(ctx, sample_clip):
    scenes = U.op_detect_scenes(ctx, sample_clip)
    assert len(scenes.outputs["scenes"]) >= 1
    assert isinstance(scenes.outputs["track"], SignalTrack)

    energy = U.op_audio_energy(ctx, sample_clip)
    et = energy.outputs["track"]
    assert et.times and max(et.values) > 0.0        # sample has a tone

    motion = U.op_motion(ctx, sample_clip)
    assert motion.outputs["track"].times            # testsrc has motion

    tele = U.op_extract_telemetry(ctx, sample_clip)
    assert tele.outputs["available"] is False       # graceful, no telemetry


def test_fuse_on_real_clip(ctx, sample_clip):
    info = media.probe(sample_clip)
    tracks = [
        U.op_detect_scenes(ctx, sample_clip).outputs["track"],
        U.op_audio_energy(ctx, sample_clip).outputs["track"],
        U.op_motion(ctx, sample_clip).outputs["track"],
    ]
    res = U.op_fuse_highlights(ctx, info, tracks, min_len=2.0, max_len=6.0, top_k=3)
    hls = res.outputs["highlights"]
    assert len(hls) >= 1
    for h in hls:
        assert 0.0 <= h.start_s < h.end_s <= info.duration_s + 1e-6
        assert 2.0 - 1e-6 <= h.duration <= 6.0 + 1e-6
        assert h.reasons  # per-signal contributions recorded
