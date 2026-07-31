"""Credentials — the single catalog of external accounts/keys the pipeline needs.

`CATALOG` is the source of truth for BOTH the runtime loader and the docs/CLI
`setup` command, so what the site documents can never drift from what the code
reads. Everything is optional: with nothing set the pipeline runs fully in
dry-run / fallback mode; add a component's env vars to make that piece live.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CredSpec:
    component: str          # human name
    key: str               # nested-creds key: platform id or provider id
    env: list[str]         # env vars that feed it
    required: list[str]    # which env vars are mandatory for this piece to go live
    account: str           # what account/setup is needed
    where: str             # where to generate the key
    gate: str              # what it unlocks / what happens without it


# One entry per external component. Order = suggested setup order.
CATALOG: list[CredSpec] = [
    CredSpec(
        "Claude (ideation, scripts, hooks)", "anthropic",
        ["ANTHROPIC_API_KEY"], ["ANTHROPIC_API_KEY"],
        "Anthropic account", "console.anthropic.com → API Keys",
        "LLM hooks/scripts; without it a deterministic template fallback is used.",
    ),
    CredSpec(
        "fal.ai (generative media aggregator)", "fal",
        ["FAL_KEY", "REELFORGE_FAL_VIDEO_MODEL", "REELFORGE_FAL_TTS_MODEL",
         "REELFORGE_FAL_MUSIC_MODEL"], ["FAL_KEY"],
        "fal.ai account (pay-per-use)", "fal.ai → Dashboard → Keys",
        "Real video/image/voice/music via one API; else dry-run placeholder media.",
    ),
    CredSpec(
        "MiniMax (TTS/music/video)", "minimax",
        ["MINIMAX_API_KEY", "MINIMAX_GROUP_ID"], ["MINIMAX_API_KEY"],
        "MiniMax platform account", "platform.minimax.io → API Keys",
        "Alt generative provider (Hailuo video, T2A voice, music-1.5).",
    ),
    CredSpec(
        "YouTube Data API (trend research)", "youtube_data",
        ["YOUTUBE_API_KEY"], ["YOUTUBE_API_KEY"],
        "Google Cloud project w/ YouTube Data API v3 enabled",
        "console.cloud.google.com → APIs & Services → Credentials → API key",
        "mostPopular trend signals; else that provider returns nothing (fallback).",
    ),
    CredSpec(
        "YouTube upload (publish)", "youtube_shorts",
        ["REELFORGE_YT_TOKEN_FILE", "REELFORGE_YT_CLIENT_ID",
         "REELFORGE_YT_CLIENT_SECRET", "REELFORGE_YT_TOKEN",
         "REELFORGE_YT_REFRESH_TOKEN"], ["REELFORGE_YT_TOKEN_FILE"],
        "Verified GCP project + OAuth client (scope youtube.upload); "
        "compliance audit (~2-4 wks) for public posting",
        "GCP → OAuth consent + OAuth client, run the OAuth flow to mint a token JSON",
        "Real uploads to YouTube Shorts; else publish stays dry-run.",
    ),
    CredSpec(
        "Instagram Reels (publish)", "instagram_reels",
        ["REELFORGE_IG_USER_ID", "REELFORGE_IG_ACCESS_TOKEN",
         "REELFORGE_IG_MEDIA_URL"], ["REELFORGE_IG_USER_ID", "REELFORGE_IG_ACCESS_TOKEN"],
        "Instagram BUSINESS account + Meta app w/ instagram_business_content_publish; "
        "draft must be hosted at a PUBLIC url",
        "developers.facebook.com → App → long-lived token; link IG business account",
        "Real Reels publishing; needs a public media_url; else dry-run.",
    ),
]


def _get(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def load_credentials(env: dict | None = None) -> dict:
    """Build the nested creds mapping the ops consume, from environment.

    Shape: { <platform_or_provider_key>: {..sub-keys..}, ... }. Only includes a
    key when at least one of its env vars is present.
    """
    e = env if env is not None else os.environ
    creds: dict[str, dict] = {}

    if e.get("ANTHROPIC_API_KEY"):
        creds["anthropic"] = {"api_key": e["ANTHROPIC_API_KEY"]}
    if e.get("FAL_KEY"):
        creds["fal"] = {k: v for k, v in {
            "api_key": e.get("FAL_KEY"),
            "video_model": e.get("REELFORGE_FAL_VIDEO_MODEL"),
            "tts_model": e.get("REELFORGE_FAL_TTS_MODEL"),
            "music_model": e.get("REELFORGE_FAL_MUSIC_MODEL"),
        }.items() if v}
    if e.get("MINIMAX_API_KEY"):
        creds["minimax"] = {k: v for k, v in {
            "api_key": e.get("MINIMAX_API_KEY"),
            "group_id": e.get("MINIMAX_GROUP_ID"),
        }.items() if v}
    if e.get("YOUTUBE_API_KEY"):
        creds["youtube_data"] = {"api_key": e["YOUTUBE_API_KEY"]}

    yt = {k: v for k, v in {
        "token_file": e.get("REELFORGE_YT_TOKEN_FILE"),
        "client_id": e.get("REELFORGE_YT_CLIENT_ID"),
        "client_secret": e.get("REELFORGE_YT_CLIENT_SECRET"),
        "token": e.get("REELFORGE_YT_TOKEN"),
        "refresh_token": e.get("REELFORGE_YT_REFRESH_TOKEN"),
    }.items() if v}
    if yt:
        creds["youtube_shorts"] = yt

    ig = {k: v for k, v in {
        "ig_user_id": e.get("REELFORGE_IG_USER_ID"),
        "access_token": e.get("REELFORGE_IG_ACCESS_TOKEN"),
        "media_url": e.get("REELFORGE_IG_MEDIA_URL"),
    }.items() if v}
    if ig:
        creds["instagram_reels"] = ig

    return creds


def env_status(env: dict | None = None) -> list[dict]:
    """Per-component readiness for the CLI `setup` command and docs."""
    e = env if env is not None else os.environ
    rows = []
    for spec in CATALOG:
        set_vars = [v for v in spec.env if e.get(v)]
        ready = all(e.get(v) for v in spec.required)
        rows.append({
            "component": spec.component, "key": spec.key, "ready": ready,
            "set": set_vars, "missing_required": [v for v in spec.required if not e.get(v)],
            "account": spec.account, "where": spec.where, "gate": spec.gate,
        })
    return rows
