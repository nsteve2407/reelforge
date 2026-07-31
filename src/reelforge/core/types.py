"""Shared value types passed between atomic ops.

These are plain dataclasses (not pydantic) because ops traffic in numeric
signal arrays where pydantic validation adds cost without benefit. The
config layer (profile.py) uses pydantic; the runtime data plane uses these.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MediaInfo:
    """Result of probing a media file (see core.media.probe)."""
    path: str
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool
    v_codec: str = ""
    a_codec: str = ""

    @property
    def aspect(self) -> float:
        return (self.width / self.height) if self.height else 0.0

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width


@dataclass
class Segment:
    """A half-open time interval [start_s, end_s) within a source video."""
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError(f"Segment end {self.end_s} < start {self.start_s}")

    @property
    def duration(self) -> float:
        return self.end_s - self.start_s

    def overlaps(self, other: "Segment") -> bool:
        return self.start_s < other.end_s and other.start_s < self.end_s


@dataclass
class SignalTrack:
    """A per-signal interest curve sampled on a common time grid.

    `times` and `values` are equal-length sequences. `values` are raw
    (un-normalized); the fusion op normalizes per track before weighting.
    """
    name: str
    times: list[float]
    values: list[float]
    weight: float = 1.0

    def __post_init__(self) -> None:
        if len(self.times) != len(self.values):
            raise ValueError(
                f"SignalTrack '{self.name}': times({len(self.times)}) != "
                f"values({len(self.values)})"
            )


@dataclass
class Highlight:
    """A ranked interesting moment produced by signal fusion."""
    start_s: float
    end_s: float
    score: float
    reasons: dict[str, float] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end_s - self.start_s

    def as_segment(self) -> Segment:
        return Segment(self.start_s, self.end_s)


@dataclass
class Caption:
    """One caption cue with word-level timing preserved when available."""
    start_s: float
    end_s: float
    text: str


@dataclass
class OpResult:
    """Uniform return envelope so the runner can record artifacts/metrics."""
    ok: bool = True
    outputs: dict[str, object] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)  # name -> path
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""
