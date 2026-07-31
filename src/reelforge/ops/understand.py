"""Understand ops — multi-signal highlight detection. Classical, NO LLM.

Each independent signal is one op returning a SignalTrack; `op_fuse_highlights`
normalizes, weights, peak-finds, and soft-NMS-dedupes them into ranked
Highlights. The math lives in pure helpers so it's unit-testable without media.
"""
from __future__ import annotations

import numpy as np

from ..core import media
from ..core.context import OpContext
from ..core.op import op
from ..core.types import Highlight, MediaInfo, OpResult, Segment, SignalTrack


# ---------------------------------------------------------------- pure helpers

def _normalize(values: np.ndarray) -> np.ndarray:
    """Min-max normalize to 0..1; all-constant -> zeros."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return v
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-12:
        return np.zeros_like(v)
    return (v - lo) / (hi - lo)


def _resample(track: SignalTrack, grid: np.ndarray) -> np.ndarray:
    """Interpolate a track onto a common time grid."""
    if not track.times:
        return np.zeros_like(grid)
    xs = np.asarray(track.times, dtype=float)
    ys = np.asarray(track.values, dtype=float)
    order = np.argsort(xs)
    return np.interp(grid, xs[order], ys[order])


def _soft_nms(items: list[Highlight], overlap_thresh: float = 0.2,
              score_floor: float = 1e-3) -> list[Highlight]:
    """Greedy soft non-max suppression over time windows.

    Keeps the highest-scoring window, suppresses any window overlapping it by
    more than `overlap_thresh`, and lightly decays mildly-overlapping ones.
    """
    remaining = sorted(items, key=lambda h: h.score, reverse=True)
    kept: list[Highlight] = []
    while remaining:
        best = remaining.pop(0)
        kept.append(best)
        survivors: list[Highlight] = []
        for h in remaining:
            inter = max(0.0, min(best.end_s, h.end_s) - max(best.start_s, h.start_s))
            denom = min(best.duration, h.duration) or 1.0
            frac = inter / denom
            if frac > overlap_thresh:
                continue  # suppressed by the higher-scoring window
            if inter > 0.0:
                h.score *= (1.0 - frac)  # soft touch for mild overlap
            if h.score >= score_floor:
                survivors.append(h)
        remaining = sorted(survivors, key=lambda h: h.score, reverse=True)
    return kept


def gforce_from_accel(accel_xyz: np.ndarray) -> list[float]:
    """Per-sample g-force magnitude sqrt(x^2+y^2+z^2). Pure/testable."""
    a = np.asarray(accel_xyz, dtype=float).reshape(-1, 3)
    return list(np.sqrt((a ** 2).sum(axis=1)))


# ------------------------------------------------------------------------ ops

@op("detect_scenes")
def op_detect_scenes(ctx: OpContext, video: str, hop_s: float = 0.5) -> OpResult:
    """Shot-boundary detection -> scenes + a scene_change SignalTrack."""
    from scenedetect import detect, ContentDetector

    info = media.probe(video)
    dur = info.duration_s or 0.0
    try:
        scene_list = detect(video, ContentDetector())
    except Exception:  # noqa: BLE001 - detection is best-effort
        scene_list = []

    if scene_list:
        scenes = [Segment(s.get_seconds(), e.get_seconds()) for s, e in scene_list]
        cuts = [s.start_s for s in scenes[1:]]
    else:
        scenes = [Segment(0.0, dur or 1.0)]
        cuts = []

    grid = np.arange(0.0, max(dur, hop_s), hop_s)
    vals = np.zeros_like(grid)
    for c in cuts:
        vals = np.maximum(vals, np.exp(-((grid - c) ** 2) / (2 * (hop_s ** 2))))
    track = SignalTrack("scene_change", list(grid), list(vals))
    return OpResult(outputs={"scenes": scenes, "track": track},
                    metrics={"n_scenes": float(len(scenes))},
                    message=f"{len(scenes)} scene(s), {len(cuts)} cut(s)")


@op("audio_energy")
def op_audio_energy(ctx: OpContext, video: str, hop_s: float = 0.5) -> OpResult:
    """Short-time RMS energy as a hype/impact signal."""
    info = media.probe(video)
    dur = info.duration_s or 0.0
    grid = np.arange(0.0, max(dur, hop_s), hop_s)
    if not info.has_audio:
        track = SignalTrack("audio_energy", list(grid), list(np.zeros_like(grid)))
        return OpResult(outputs={"track": track}, metrics={"peak_energy": 0.0},
                        message="no audio")
    wav = media.extract_audio_wav(video, ctx.storage.path("understand", "audio.wav"))
    data, sr = media.read_wav_mono(wav)
    win = max(1, int(hop_s * sr))
    vals = []
    for t in grid:
        i0 = int(t * sr)
        seg = data[i0:i0 + win]
        vals.append(float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0)
    track = SignalTrack("audio_energy", list(grid), vals)
    return OpResult(outputs={"track": track},
                    metrics={"peak_energy": max(vals) if vals else 0.0},
                    message=f"{len(vals)} bins")


@op("motion")
def op_motion(ctx: OpContext, video: str, target_fps: float = 4.0) -> OpResult:
    """Frame-difference magnitude as a motion-intensity signal."""
    times: list[float] = []
    vals: list[float] = []
    prev = None
    for ts, gray in media.iter_frames_gray(video, target_fps=target_fps, max_dim=256):
        g = gray.astype(np.float32)
        if prev is not None:
            times.append(ts)
            vals.append(float(np.mean(np.abs(g - prev))))
        prev = g
    if not vals:
        times, vals = [0.0], [0.0]
    track = SignalTrack("motion", times, vals)
    return OpResult(outputs={"track": track},
                    metrics={"peak_motion": max(vals) if vals else 0.0},
                    message=f"{len(vals)} frames")


@op("extract_telemetry")
def op_extract_telemetry(ctx: OpContext, video: str) -> OpResult:
    """Action-cam gyro/accel/GPS telemetry (Insta360/GoPro). Graceful if absent."""
    try:
        import telemetry_parser  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency / no telemetry present
        return OpResult(ok=True, outputs={"track": None, "available": False},
                        message="telemetry unavailable")
    try:
        tp = telemetry_parser.Parser(video)
        tele = tp.normalized_imu()  # list of samples with timestamp + accel
        times = [s.get("timestamp_ms", 0) / 1000.0 for s in tele]
        accel = np.array([s.get("accl", [0, 0, 0]) for s in tele], dtype=float)
        mags = gforce_from_accel(accel)
        track = SignalTrack("gforce", times, mags)
        return OpResult(outputs={"track": track, "available": True},
                        metrics={"peak_gforce": max(mags) if mags else 0.0},
                        message=f"{len(mags)} imu samples")
    except Exception as e:  # noqa: BLE001
        return OpResult(ok=True, outputs={"track": None, "available": False},
                        message=f"telemetry parse failed: {e}")


@op("fuse_highlights")
def op_fuse_highlights(ctx: OpContext, info: MediaInfo, tracks: list[SignalTrack], *,
                       min_len: float = 5.0, max_len: float = 45.0,
                       top_k: int = 5, hop_s: float = 0.5) -> OpResult:
    """Fuse signals -> ranked Highlights. Classical: normalize, weight, peaks, NMS."""
    from scipy.signal import find_peaks

    dur = info.duration_s or 0.0
    tracks = [t for t in tracks if t is not None]
    if dur <= 0 or not tracks:
        return OpResult(outputs={"highlights": []}, metrics={"n_highlights": 0.0},
                        message="no signal")
    grid = np.arange(0.0, max(dur, hop_s), hop_s)
    norms: dict[str, np.ndarray] = {}
    fused = np.zeros_like(grid)
    for t in tracks:
        n = _normalize(_resample(t, grid))
        norms[t.name] = n
        fused = fused + t.weight * n

    # peaks separated by ~min_len; fall back to global max if none
    distance = max(1, int(min_len / hop_s))
    peaks, _ = find_peaks(fused, distance=distance)
    if peaks.size == 0:
        peaks = np.array([int(np.argmax(fused))])

    win = min_len
    cands: list[Highlight] = []
    for pi in peaks:
        t = float(grid[pi])
        start = max(0.0, t - win / 2.0)
        end = min(dur, start + win)
        start = max(0.0, end - win)  # keep length if clamped at the tail
        reasons = {name: round(float(n[pi]), 4) for name, n in norms.items()}
        cands.append(Highlight(start, end, float(fused[pi]), reasons))

    kept = _soft_nms(cands)
    kept.sort(key=lambda h: h.score, reverse=True)
    kept = kept[:top_k]
    return OpResult(outputs={"highlights": kept},
                    metrics={"n_highlights": float(len(kept))},
                    message=f"{len(kept)} highlight(s) from {len(tracks)} signal(s)")
