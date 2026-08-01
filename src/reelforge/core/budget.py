"""Budget guardrails: estimate per-op generative cost + cap spend per video/day.

Estimates are recorded to the ledger `spend` table (est vs actually-charged, the
latter only when not dry-run) so runs stay within `profile.budget.max_usd_per_video`
and the dashboard can report projected vs real cost. Prices are directional
(mid-2026) and live in one place to tune.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# USD per second of generated video, by provider (aggregator/model dependent).
VIDEO_USD_PER_S = {
    "fal": 0.05, "minimax": 0.05, "veo": 0.15, "kling": 0.10,
    "runway": 0.25, "luma": 0.08, "ltx": 0.04, "dryrun": 0.05,
}
TTS_USD_PER_1K_CHARS = 0.015     # OpenAI-class; Kokoro self-host ~0
MUSIC_USD_PER_TRACK = 0.20       # Stable Audio-class
IMAGE_USD = 0.04                 # Flux-class
_DEFAULT_VIDEO_PPS = 0.08


def estimate_cost(kind: str, provider: Optional[str] = None, *,
                  seconds: float = 0.0, chars: int = 0) -> float:
    """Estimate USD for one generative op. Pure/testable."""
    if kind == "video":
        pps = VIDEO_USD_PER_S.get(provider or "dryrun", _DEFAULT_VIDEO_PPS)
        return round(max(0.0, seconds) * pps, 4)
    if kind == "voice":
        return round((max(0, chars) / 1000.0) * TTS_USD_PER_1K_CHARS, 4)
    if kind == "music":
        return MUSIC_USD_PER_TRACK
    if kind == "image":
        return IMAGE_USD
    return 0.0


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class BudgetGuard:
    """Per-run budget accounting against profile.budget.max_usd_per_video."""

    def __init__(self, ledger, profile):
        self.ledger = ledger
        self.profile = profile
        self.max_per_video = float(profile.budget.max_usd_per_video)

    def run_est(self, run_id: str) -> float:
        return self.ledger.run_spend(run_id)["est_usd"]

    def allow(self, run_id: str, next_est: float) -> bool:
        """True if adding `next_est` keeps the run within its per-video budget."""
        return (self.run_est(run_id) + next_est) <= self.max_per_video + 1e-9

    def record(self, run_id: str, kind: str, provider: Optional[str], *,
               seconds: float = 0.0, chars: int = 0, dry_run: bool = True) -> float:
        est = estimate_cost(kind, provider, seconds=seconds, chars=chars)
        self.ledger.add_spend(run_id, _day(), kind, provider, est, dry_run)
        return est
