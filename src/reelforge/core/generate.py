"""Generative media core: produce video/voice/music from prompts.

Real providers (fal.ai, MiniMax, Stable Audio, Kokoro) live in reelforge.adapters
and are credential-gated + lazy-imported. The default DryRunGenerator produces
REAL placeholder media with ffmpeg (colored scene clips, silent narration track,
a sine music bed) so the whole generative pipeline assembles and is testable
with no API keys or GPU.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from . import media

# Soft pastel-ish palette (kid-friendly default); cycled per scene. 0xRRGGBB.
_PALETTE = [
    "0xF7C6D9", "0xC6E2F7", "0xD9F7C6", "0xF7E7C6",
    "0xE0C6F7", "0xC6F7EC", "0xF7D9C6", "0xCED9F7",
]
_MOOD_FREQ = {
    "soft_singalong": 330.0, "energetic_electronic": 220.0,
    "tension_underscore": 110.0, "warm": 294.0,
}


@dataclass
class GenResult:
    path: str
    duration: float
    kind: str
    provider: str
    dry_run: bool = True
    message: str = ""


class MediaGenerator(Protocol):
    provider: str

    def video(self, out: str, prompt: str, *, w: int, h: int, seconds: float,
              index: int = 0) -> GenResult: ...

    def voice(self, out: str, text: str, *, seconds: float) -> GenResult: ...

    def music(self, out: str, *, mood: str, seconds: float) -> GenResult: ...


class DryRunGenerator:
    """Deterministic, credential-free media via ffmpeg lavfi sources."""

    provider = "dryrun"

    def video(self, out: str, prompt: str, *, w: int, h: int, seconds: float,
              index: int = 0) -> GenResult:
        out = str(out)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        color = _PALETTE[index % len(_PALETTE)]
        media.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={seconds:.3f}:r=24",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", out,
        ])
        return GenResult(out, seconds, "video", self.provider,
                         message=f"placeholder scene {index}")

    def voice(self, out: str, text: str, *, seconds: float) -> GenResult:
        out = str(out)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        # No offline TTS available -> silent narration track sized to the script.
        media.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{seconds:.3f}", "-c:a", "aac", out,
        ])
        return GenResult(out, seconds, "voice", self.provider,
                         message="silent placeholder (no offline TTS)")

    def music(self, out: str, *, mood: str, seconds: float) -> GenResult:
        out = str(out)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        freq = _MOOD_FREQ.get(mood, 262.0)
        media.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={seconds:.3f}",
            "-c:a", "aac", out,
        ])
        return GenResult(out, seconds, "music", self.provider,
                         message=f"sine bed @ {freq:.0f}Hz")


def get_generator(provider: Optional[str], *, dry_run: bool = True,
                  creds: Optional[dict] = None) -> MediaGenerator:
    """Real adapter when a provider + creds are given and dry_run is off; else dry-run."""
    if dry_run or not provider or not creds:
        return DryRunGenerator()
    if provider == "fal":
        from ..adapters.fal import FalGenerator
        return FalGenerator(creds)
    if provider == "minimax":
        from ..adapters.minimax import MinimaxGenerator
        return MinimaxGenerator(creds)
    return DryRunGenerator()
