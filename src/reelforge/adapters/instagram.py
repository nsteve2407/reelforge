"""Instagram Reels publisher via the Meta Graph API (credential-gated).

Requires an Instagram BUSINESS account, a long-lived access token, and the
instagram_business_content_publish permission. The Graph API needs a PUBLIC
video URL (it fetches the media itself), so the draft must first be hosted at
a reachable URL (future: upload to the storage bucket and pass its public URL
via creds['media_url']). Flow: create REELS container -> poll status -> publish.
Not exercised by the test suite.

creds dict keys: ig_user_id, access_token, media_url (public URL of the draft).
"""
from __future__ import annotations

import time

from ..core.publish import PublishMeta, PublishResult

_GRAPH = "https://graph.facebook.com/v21.0"


class InstagramPublisher:
    platform = "instagram_reels"

    def __init__(self, creds: dict, cost: int = 1):
        self.creds = creds
        self.cost = cost

    def publish(self, video_path: str, meta: PublishMeta) -> PublishResult:
        import requests  # lazy

        media_url = self.creds.get("media_url")
        if not media_url:
            return PublishResult(
                ok=False, platform=self.platform, dry_run=False,
                message="Instagram requires a public media_url (host the draft first)",
            )
        ig_id = self.creds["ig_user_id"]
        token = self.creds["access_token"]
        caption = (meta.title + "\n\n" + " ".join(f"#{t}" for t in meta.tags)).strip()

        # 1) create container
        r = requests.post(f"{_GRAPH}/{ig_id}/media", data={
            "media_type": "REELS", "video_url": media_url,
            "caption": caption, "access_token": token,
        }, timeout=60)
        r.raise_for_status()
        creation_id = r.json()["id"]

        # 2) poll until the container is FINISHED
        for _ in range(30):
            s = requests.get(f"{_GRAPH}/{creation_id}", params={
                "fields": "status_code", "access_token": token,
            }, timeout=30).json()
            if s.get("status_code") == "FINISHED":
                break
            if s.get("status_code") == "ERROR":
                return PublishResult(ok=False, platform=self.platform,
                                     message="container processing error")
            time.sleep(5)

        # 3) publish
        p = requests.post(f"{_GRAPH}/{ig_id}/media_publish", data={
            "creation_id": creation_id, "access_token": token,
        }, timeout=60)
        p.raise_for_status()
        media_id = p.json()["id"]
        return PublishResult(
            ok=True, platform=self.platform, video_id=media_id,
            url=f"https://instagram.com/reel/{media_id}", dry_run=False,
            message="published Reel",
        )
