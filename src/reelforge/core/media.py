"""Shared media primitives: ffprobe/ffmpeg wrappers and frame iteration.

Uses subprocess directly (robust across ffmpeg versions, incl. the 3.4 on
older Ubuntu) rather than depending on ffmpeg-python for control flow.
Higher-level editing (cut/reframe/grade/mux) lives in ops/build.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

from .types import MediaInfo


class FFmpegError(RuntimeError):
    pass


def which(tool: str) -> Optional[str]:
    return shutil.which(tool)


def have_ffmpeg() -> bool:
    return which("ffmpeg") is not None and which("ffprobe") is not None


def run(cmd: list[str], *, quiet: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raising FFmpegError with stderr tail on failure."""
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1500:]
        raise FFmpegError(f"command failed ({proc.returncode}): {' '.join(cmd[:3])}...\n{tail}")
    return proc


def probe(path: str | Path) -> MediaInfo:
    """Return MediaInfo for a media file using ffprobe JSON output."""
    path = str(path)
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    proc = run(cmd)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    def _duration() -> float:
        for src in (v or {}, fmt):
            d = src.get("duration")
            if d:
                try:
                    return float(d)
                except (TypeError, ValueError):
                    pass
        return 0.0

    def _fps() -> float:
        if not v:
            return 0.0
        for key in ("avg_frame_rate", "r_frame_rate"):
            r = v.get(key, "0/0")
            try:
                num, den = r.split("/")
                num, den = float(num), float(den)
                if den:
                    return num / den
            except (ValueError, ZeroDivisionError):
                continue
        return 0.0

    if v is None:
        raise FFmpegError(f"no video stream in {path}")

    return MediaInfo(
        path=path,
        duration_s=_duration(),
        width=int(v.get("width", 0)),
        height=int(v.get("height", 0)),
        fps=_fps(),
        has_audio=a is not None,
        v_codec=v.get("codec_name", ""),
        a_codec=(a or {}).get("codec_name", ""),
    )


def extract_audio_wav(src: str | Path, out: str | Path, sr: int = 16000, mono: bool = True) -> Path:
    """Decode audio to a PCM WAV (for RMS/energy analysis or transcription)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src), "-vn",
        "-ac", "1" if mono else "2", "-ar", str(sr),
        "-f", "wav", str(out),
    ]
    run(cmd)
    return out


def read_wav_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a PCM WAV into a float32 mono array in [-1, 1] with its samplerate."""
    import wave

    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sw, np.int16)
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    maxv = float(np.iinfo(dtype).max) if dtype != np.int8 else 127.0
    if maxv:
        data = data / maxv
    return data, sr


def iter_frames_gray(
    path: str | Path, target_fps: float = 4.0, max_dim: int = 256
) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (timestamp_s, grayscale_frame) sampled at ~target_fps, downscaled.

    Used by motion/optical-flow analysis. Downscaling keeps it cheap on CPU.
    """
    import cv2  # local import so core stays importable without opencv at rest

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FFmpegError(f"cannot open video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / max(0.1, target_fps))))
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                h, w = frame.shape[:2]
                scale = min(1.0, max_dim / float(max(h, w)))
                if scale < 1.0:
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                ts = idx / src_fps
                yield ts, gray
            idx += 1
    finally:
        cap.release()


def synth_test_clip(out: str | Path, duration: float = 12.0, fps: int = 30,
                    size: str = "640x360") -> Path:
    """Generate a synthetic test clip with motion + a tone burst.

    Deterministic input for smoke tests and demos when no footage is present.
    Uses only ffmpeg lavfi sources (works on ffmpeg 3.4).
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # video: test pattern; audio: a sine that changes freq (creates energy variation)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", str(out),
    ]
    run(cmd)
    return out
