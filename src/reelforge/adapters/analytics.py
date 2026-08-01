"""Analytics adapters — pull post performance (credential-gated, lazy).

YouTube Analytics API and Instagram Insights. Return {} without creds so the
learning loop runs offline (metrics can also be supplied manually). Not run in
the test suite.
"""
from __future__ import annotations

from typing import Optional


def youtube_analytics(video_id: str, creds: dict, *, days: int = 7) -> dict:
    """Views / watch time / average view duration for a video."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception:  # noqa: BLE001
        return {}
    c = Credentials(
        token=creds.get("token"), refresh_token=creds.get("refresh_token"),
        client_id=creds.get("client_id"), client_secret=creds.get("client_secret"),
        token_uri=creds.get("token_uri", "https://oauth2.googleapis.com/token"),
        scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"],
    )
    ya = build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
    import datetime as _dt
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days)
    resp = ya.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
        filters=f"video=={video_id}",
    ).execute()
    rows = resp.get("rows") or [[0, 0, 0, 0]]
    v, mins, avd, avp = rows[0][:4]
    return {"views": v, "estimated_minutes_watched": mins,
            "avg_view_duration": avd, "retention3s": (avp or 0) / 100.0}


def instagram_insights(media_id: str, creds: dict) -> dict:
    """Plays / reach / engagement for a Reel."""
    import requests
    token = creds["access_token"]
    r = requests.get(
        f"https://graph.facebook.com/v21.0/{media_id}/insights",
        params={"metric": "plays,reach,likes,comments,shares,saved",
                "access_token": token}, timeout=30,
    )
    r.raise_for_status()
    out = {}
    for item in r.json().get("data", []):
        vals = item.get("values") or [{}]
        out[item["name"]] = vals[0].get("value", 0)
    out["views"] = out.get("plays", 0)
    return out
