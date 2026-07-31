"""Publishing core: quota accounting, scheduling, publish metadata, dry-run.

Platform adapters (YouTube/Instagram) live in reelforge.adapters and are only
used when real credentials are present. Everything here is credential-free and
unit-testable; the DryRunPublisher lets the whole publish path run and be tested
without any account.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from .profile import ContentProfile

# Per-platform limits/costs. YouTube: 10k units/day, upload=1600 (~6/day).
# Instagram: conservative 25 API posts/day, 1 unit each. quota_key groups
# platforms that share a project quota bucket.
PLATFORMS: dict[str, dict] = {
    "youtube_shorts": {"limit": 10000, "cost": 1600, "quota_key": "youtube"},
    "instagram_reels": {"limit": 25, "cost": 1, "quota_key": "instagram"},
}


@dataclass
class PublishMeta:
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy: str = "public"          # public | private | unlisted
    publish_at: Optional[str] = None  # ISO 8601; implies scheduled (private until then)
    made_for_kids: bool = False
    ai_disclosure: bool = False


@dataclass
class PublishResult:
    ok: bool
    platform: str
    video_id: Optional[str] = None
    url: Optional[str] = None
    dry_run: bool = False
    scheduled_at: Optional[str] = None
    message: str = ""


class Publisher(Protocol):
    platform: str
    cost: int

    def publish(self, video_path: str, meta: PublishMeta) -> PublishResult: ...


# ------------------------------------------------------------------- scheduling

# Rough "good hour" (local) by audience segment; deterministic + tunable.
_BEST_HOUR = {
    "toddlers_0_5": 7, "kids_6_12": 16, "gen_z_millennial": 19,
    "gen_z_13_24": 20, "millennials_25_40": 18, "parents": 20,
}


def next_best_time(now: datetime, profile: ContentProfile) -> Optional[datetime]:
    """Return the next scheduled publish datetime, or None for immediate posting."""
    sched = profile.publish.schedule
    if sched in ("asap_on_trigger", "now", "immediate"):
        return None
    hour = _BEST_HOUR.get((profile.audience.segment or "").lower(), 18)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def build_publish_meta(profile: ContentProfile, platform: str,
                       now: Optional[datetime] = None) -> PublishMeta:
    """Derive platform-ready metadata from the ContentProfile. Pure."""
    now = now or datetime.now(timezone.utc)
    tags = [h.lstrip("#") for h in profile.publish.hashtags]
    base_title = (profile.niche or profile.id).strip()
    hashtag_str = " ".join(profile.publish.hashtags)
    if platform == "youtube_shorts" and "#Shorts" not in profile.publish.hashtags:
        hashtag_str = ("#Shorts " + hashtag_str).strip()
    title = base_title[:90]
    if platform == "youtube_shorts" and "#Shorts" not in title:
        title = f"{title} #Shorts"[:100]
    desc_lines = [base_title, "", hashtag_str]
    if profile.publish.ai_disclosure:
        desc_lines += ["", "Contains AI-generated or AI-assisted content."]
    when = next_best_time(now, profile)
    scheduled = when is not None
    return PublishMeta(
        title=title,
        description="\n".join(desc_lines).strip(),
        tags=tags,
        privacy="private" if scheduled else "public",
        publish_at=when.isoformat() if scheduled else None,
        made_for_kids=profile.publish.made_for_kids,
        ai_disclosure=profile.publish.ai_disclosure,
    )


class QuotaGuard:
    """Tracks per-platform daily API cost in the ledger and blocks overruns."""

    def __init__(self, ledger, limits: Optional[dict] = None):
        self.ledger = ledger
        self.platforms = limits or PLATFORMS

    @staticmethod
    def _day() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def cost(self, platform: str) -> int:
        return int(self.platforms.get(platform, {}).get("cost", 1))

    def _key(self, platform: str) -> str:
        return self.platforms.get(platform, {}).get("quota_key", platform)

    def remaining(self, platform: str) -> int:
        spec = self.platforms.get(platform, {})
        limit = int(spec.get("limit", 0))
        used = self.ledger.quota_used(self._key(platform), self._day())
        return max(0, limit - used)

    def check(self, platform: str) -> tuple[bool, int]:
        """Return (allowed, remaining_after) without consuming."""
        rem = self.remaining(platform)
        cost = self.cost(platform)
        return (rem >= cost, rem - cost)

    def consume(self, platform: str) -> int:
        cost = self.cost(platform)
        return self.ledger.add_quota(self._key(platform), self._day(), cost)


class DryRunPublisher:
    """Simulates a publish without touching any API. Default when no creds."""

    def __init__(self, platform: str, cost: int = 0):
        self.platform = platform
        self.cost = cost

    def publish(self, video_path: str, meta: PublishMeta) -> PublishResult:
        import hashlib
        vid = "dry_" + hashlib.blake2b(video_path.encode(), digest_size=6).hexdigest()
        base = "https://youtube.com/shorts/" if self.platform == "youtube_shorts" \
            else "https://instagram.com/reel/"
        return PublishResult(
            ok=True, platform=self.platform, video_id=vid, url=f"{base}{vid}",
            dry_run=True, scheduled_at=meta.publish_at,
            message=f"DRY-RUN publish '{meta.title}' privacy={meta.privacy}",
        )


def get_publisher(platform: str, *, dry_run: bool = True,
                  creds: Optional[dict] = None) -> Publisher:
    """Choose a real adapter when creds are present and dry_run is off; else dry-run."""
    cost = PLATFORMS.get(platform, {}).get("cost", 1)
    if dry_run or not creds:
        return DryRunPublisher(platform, cost)
    if platform == "youtube_shorts":
        from ..adapters.youtube import YouTubePublisher
        return YouTubePublisher(creds, cost=cost)
    if platform == "instagram_reels":
        from ..adapters.instagram import InstagramPublisher
        return InstagramPublisher(creds, cost=cost)
    return DryRunPublisher(platform, cost)
