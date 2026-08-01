"""ContentProfile — the generic contract that configures a pipeline run.

One YAML profile fully specifies a channel/niche: source mode, audience,
research signals, understand/build knobs, publish targets and compliance.
The engine reads this; no code changes to launch a new niche.

Models are permissive (extra fields ignored) so profiles can carry
forward-looking keys the current code doesn't consume yet.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class SourceMode(str, Enum):
    footage = "footage"
    generative = "generative"
    hybrid = "hybrid"


class Approval(str, Enum):
    required = "required"
    auto = "auto"


class _Base(BaseModel):
    model_config = {"extra": "ignore"}


class Channel(_Base):
    youtube: Optional[str] = None
    instagram: Optional[str] = None


class Audience(_Base):
    intent: list[str] = Field(default_factory=list)
    segment: Optional[str] = None
    relationship: Optional[str] = None
    age: Optional[str] = None
    tone: Optional[str] = None


class Source(_Base):
    mode: SourceMode = SourceMode.footage
    connectors: list[str] = Field(default_factory=list)
    watch: bool = False
    proxy_transcode: bool = True


class Research(_Base):
    enabled: bool = False
    signals: list[str] = Field(default_factory=list)
    ideas_per_run: int = 5


class Understand(_Base):
    scene_detect: str = "pyscenedetect"
    transcribe: Optional[str] = None
    highlight_scorer: Optional[str] = None
    score_for: list[str] = Field(default_factory=list)


class Captions(_Base):
    enabled: bool = False
    source: str = "transcribe"   # ai | transcribe | off — 'ai' = Claude-written overlay lines
    style: str = "karaoke_bold"
    lang: str = "en"
    count: int = 4               # how many AI overlay lines
    keyframes: int = 3           # frames sent to Claude vision to describe the scene
    themes: list[str] = Field(default_factory=list)


class ColorGrade(_Base):
    lut: Optional[str] = None
    look: str = "none"


class Music(_Base):
    enabled: bool = False
    source: Optional[str] = None   # fal | local | none
    mood: Optional[str] = None
    gain: float = 0.8              # music bed volume
    duck_original: float = 0.25    # original clip audio volume under the music


class Voiceover(_Base):
    enabled: bool = False
    provider: Optional[str] = None
    voice: Optional[str] = None


class Edit(_Base):
    aspect_ratio: str = "9:16"
    length_s: list[float] = Field(default_factory=lambda: [15.0, 45.0])
    clips_per_video: list[int] = Field(default_factory=lambda: [1, 3])
    hook_first: bool = True
    reframe: str = "center"
    captions: Captions = Field(default_factory=Captions)
    color_grade: ColorGrade = Field(default_factory=ColorGrade)
    music: Music = Field(default_factory=Music)
    voiceover: Voiceover = Field(default_factory=Voiceover)

    @field_validator("length_s")
    @classmethod
    def _len_ok(cls, v: list[float]) -> list[float]:
        if len(v) != 2 or v[0] <= 0 or v[1] < v[0]:
            raise ValueError("length_s must be [min,max] with 0 < min <= max")
        return v

    @property
    def target_w_h(self) -> tuple[int, int]:
        """Pixel target for the aspect_ratio at 1080 on the long/short edge."""
        ar = self.aspect_ratio.replace(" ", "")
        if ":" not in ar:
            return (1080, 1920)
        a, b = ar.split(":")
        aw, ah = float(a), float(b)
        if ah >= aw:  # vertical/square -> 1080 wide
            return (1080, int(round(1080 * ah / aw)))
        return (int(round(1080 * aw / ah)), 1080)


class Publish(_Base):
    platforms: list[str] = Field(default_factory=list)
    schedule: str = "best_time"
    daily_cap: int = 1
    approval: Approval = Approval.required
    ai_disclosure: bool = False
    made_for_kids: bool = False
    hashtags: list[str] = Field(default_factory=list)


class Budget(_Base):
    max_usd_per_video: float = 1.0


class Generate(_Base):
    """Generative-mode knobs (kids rhymes, TV b-roll). Optional."""
    script: Optional[str] = None
    music: Music = Field(default_factory=Music)
    voiceover: Voiceover = Field(default_factory=Voiceover)
    # animation / broll are free-form provider blocks; kept permissive
    animation: dict = Field(default_factory=dict)
    broll: dict = Field(default_factory=dict)


class ContentProfile(_Base):
    id: str
    niche: str = ""
    channel: Channel = Field(default_factory=Channel)
    audience: Audience = Field(default_factory=Audience)
    source: Source = Field(default_factory=Source)
    research: Research = Field(default_factory=Research)
    understand: Understand = Field(default_factory=Understand)
    edit: Edit = Field(default_factory=Edit)
    generate: Generate = Field(default_factory=Generate)
    publish: Publish = Field(default_factory=Publish)
    budget: Budget = Field(default_factory=Budget)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ContentProfile":
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.model_validate(data)


def load_profile(name_or_path: str | Path, profiles_dir: str | Path = "profiles") -> ContentProfile:
    """Load a profile by id (looks in profiles_dir) or by explicit path."""
    p = Path(name_or_path)
    if p.exists():
        return ContentProfile.from_yaml(p)
    cand = Path(profiles_dir) / f"{name_or_path}.yaml"
    if cand.exists():
        return ContentProfile.from_yaml(cand)
    raise FileNotFoundError(f"Profile not found: {name_or_path} (looked in {cand})")
